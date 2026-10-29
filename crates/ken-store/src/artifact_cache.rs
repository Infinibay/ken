//! Disposable compressed JSON artifacts, compatible with Python's structural cache.
use flate2::{Compression, read::ZlibDecoder, write::ZlibEncoder};
use ken_program::StructuralIr;
use rusqlite::{Connection, OpenFlags, OptionalExtension, params};
use serde::Serialize;
use serde_json::value::RawValue;
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
#[derive(Debug, thiserror::Error)]
#[error("cache max_mb must be finite and nonnegative and fit the native byte range")]
pub struct InvalidCacheBudget;
#[derive(Clone, Debug, Serialize)]
pub struct CacheStats {
    pub hits: u64,
    pub misses: u64,
    pub evictions: u64,
    pub max_bytes: u64,
    pub bytes: u64,
    pub enabled: bool,
    pub error: Option<String>,
}
/// Errors in this optional memo never turn a source result into an empty graph.
/// Unknown/foreign schemas are rejected before opening the file for writes.
pub struct ArtifactCache {
    path: PathBuf,
    db: Option<Connection>,
    limit: u64,
    hits: u64,
    misses: u64,
    evictions: u64,
    error: Option<String>,
}
impl ArtifactCache {
    pub fn open(path: &Path, max_mb: f64) -> Result<Self, InvalidCacheBudget> {
        let bytes = max_mb * 1_000_000.;
        if !max_mb.is_finite() || max_mb < 0. || !bytes.is_finite() || bytes > u64::MAX as f64 {
            return Err(InvalidCacheBudget);
        }
        let mut cache = Self {
            path: path.into(),
            db: None,
            limit: bytes as u64,
            hits: 0,
            misses: 0,
            evictions: 0,
            error: None,
        };
        if cache.limit < 32768 {
            return Ok(cache);
        }
        if let Err(error) = cache.initialize() {
            cache.error = Some(error);
            cache.db = None;
        }
        Ok(cache)
    }
    fn initialize(&mut self) -> Result<(), String> {
        if let Ok(metadata) = fs::symlink_metadata(&self.path) {
            if !metadata.is_file() {
                return Err("cache path is not a regular file".into());
            }
            let db = Connection::open_with_flags(&self.path, OpenFlags::SQLITE_OPEN_READ_ONLY)
                .map_err(|e| e.to_string())?;
            validate(&db)?;
        }
        if let Some(parent) = self.path.parent().filter(|p| !p.as_os_str().is_empty()) {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let db = Connection::open(&self.path).map_err(|e| e.to_string())?;
        db.busy_timeout(Duration::from_secs(5))
            .map_err(|e| e.to_string())?;
        // Revalidate after acquisition; another process may have installed the file.
        validate(&db)?;
        db.execute_batch("PRAGMA auto_vacuum=FULL; PRAGMA journal_mode=DELETE; CREATE TABLE IF NOT EXISTS entries(key TEXT PRIMARY KEY,value BLOB NOT NULL,size INTEGER NOT NULL,touched INTEGER NOT NULL); CREATE INDEX IF NOT EXISTS cache_lru ON entries(touched);").map_err(|e|e.to_string())?;
        self.db = Some(db);
        let db = self.db.as_ref().unwrap();
        db.execute_batch("BEGIN IMMEDIATE")
            .map_err(|e| e.to_string())?;
        let result = evict(db, self.limit, 0);
        match result {
            Ok(n) => {
                db.execute_batch("COMMIT").map_err(|e| e.to_string())?;
                self.evictions += n;
            }
            Err(e) => {
                let _ = db.execute_batch("ROLLBACK");
                return Err(e.to_string());
            }
        }
        let page_size: u64 = read_pragma(db, "PRAGMA page_size").map_err(|e| e.to_string())?;
        db.pragma_update(
            None,
            "max_page_count",
            (self.limit / page_size).max(8) as i64,
        )
        .map_err(|e| e.to_string())?;
        Ok(())
    }
    /// SHA256 over eight-byte big-endian lengths followed by each exact byte string.
    pub fn key<'a>(parts: impl IntoIterator<Item = &'a [u8]>) -> String {
        let mut hash = Sha256::new();
        for part in parts {
            hash.update((part.len() as u64).to_be_bytes());
            hash.update(part);
        }
        format!("{:x}", hash.finalize())
    }
    pub fn stats(&self) -> CacheStats {
        CacheStats {
            hits: self.hits,
            misses: self.misses,
            evictions: self.evictions,
            max_bytes: self.limit,
            bytes: fs::metadata(&self.path).map_or(0, |m| m.len()),
            enabled: self.db.is_some(),
            error: self.error.clone(),
        }
    }
    /// Build reports use per-request counters; an unavailable cache retains its error.
    pub fn reset_stats(&mut self) {
        self.hits = 0;
        self.misses = 0;
        self.evictions = 0;
        if self.db.is_some() {
            self.error = None;
        }
    }
    pub fn get_json(&mut self, key: &str) -> Option<Box<RawValue>> {
        let result = (|| -> Result<Option<Box<RawValue>>, Box<dyn std::error::Error>> {
            let Some(db) = &self.db else {
                return Ok(None);
            };
            let row: Option<Vec<u8>> = db
                .query_row("SELECT value FROM entries WHERE key=?1", [key], |r| {
                    r.get(0)
                })
                .optional()?;
            let Some(bytes) = row else {
                return Ok(None);
            };
            let mut text = String::new();
            ZlibDecoder::new(&bytes[..]).read_to_string(&mut text)?;
            let value = RawValue::from_string(text)?;
            db.execute(
                "UPDATE entries SET touched=?1 WHERE key=?2",
                params![now(), key],
            )?;
            Ok(Some(value))
        })();
        match result {
            Ok(Some(v)) => {
                self.hits += 1;
                Some(v)
            }
            Ok(None) => {
                self.misses += 1;
                None
            }
            Err(e) => {
                self.error = Some(e.to_string());
                self.misses += 1;
                None
            }
        }
    }
    pub fn get_ir(&mut self, key: &str) -> Option<StructuralIr> {
        let raw = self.get_json(key)?;
        match StructuralIr::from_json(raw.get()) {
            Ok(ir) => Some(ir),
            Err(_) => {
                self.hits -= 1;
                self.misses += 1;
                self.error = Some("invalid cached IR; rebuilding".into());
                None
            }
        }
    }
    /// Reject a well-formed artifact that does not describe the requested input.
    /// Validation belongs to the consumer; rejected hits count as misses.
    pub fn get_ir_checked(
        &mut self,
        key: &str,
        valid: impl FnOnce(&StructuralIr) -> bool,
    ) -> Option<StructuralIr> {
        let ir = self.get_ir(key)?;
        if valid(&ir) {
            Some(ir)
        } else {
            self.hits -= 1;
            self.misses += 1;
            self.error = Some("invalid cached IR; rebuilding".into());
            None
        }
    }
    pub fn put_json(&mut self, key: &str, value: &RawValue) {
        if self.db.is_none() {
            return;
        }
        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        let result = encoder
            .write_all(value.get().as_bytes())
            .and_then(|()| encoder.finish());
        match result {
            Ok(bytes) => self.put_payload(key, &bytes),
            Err(e) => self.error = Some(e.to_string()),
        }
    }
    pub fn put_ir(&mut self, key: &str, ir: &StructuralIr) {
        if self.db.is_none() {
            return;
        }
        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        if let Err(e) = serde_json::to_writer(&mut encoder, ir) {
            self.error = Some(e.to_string());
            return;
        }
        match encoder.finish() {
            Ok(bytes) => self.put_payload(key, &bytes),
            Err(e) => self.error = Some(e.to_string()),
        }
    }
    fn put_payload(&mut self, key: &str, payload: &[u8]) {
        let Some(db) = &self.db else {
            return;
        };
        let result = (|| -> rusqlite::Result<u64> {
            let page_size: u64 = read_pragma(db, "PRAGMA page_size")?;
            let pages = (payload.len() as u64 + page_size - 5) / (page_size - 4);
            let reserve = pages * page_size + 16384;
            if reserve.saturating_add(32768) > self.limit {
                return Ok(0);
            }
            db.execute_batch("BEGIN IMMEDIATE")?;
            let written = (|| {
                db.execute("DELETE FROM entries WHERE key=?1", [key])?;
                let removed = evict(db, self.limit, reserve)?;
                db.execute(
                    "INSERT INTO entries VALUES(?1,?2,?3,?4)",
                    params![key, payload, payload.len() as i64, now()],
                )?;
                db.execute_batch("COMMIT")?;
                Ok(removed)
            })();
            if written.is_err() {
                let _ = db.execute_batch("ROLLBACK");
            }
            written
        })();
        match result {
            Ok(n) => self.evictions += n,
            Err(e) => self.error = Some(e.to_string()),
        }
    }
}
fn now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos().min(i64::MAX as u128) as i64)
}
fn evict(db: &Connection, limit: u64, reserve: u64) -> rusqlite::Result<u64> {
    let mut count = 0;
    loop {
        let pages: u64 = read_pragma(db, "PRAGMA page_count")?;
        let free: u64 = read_pragma(db, "PRAGMA freelist_count")?;
        let size: u64 = read_pragma(db, "PRAGMA page_size")?;
        if (pages - free) * size + reserve <= limit {
            return Ok(count);
        }
        let victim: Option<String> = db
            .query_row(
                "SELECT key FROM entries ORDER BY touched,key LIMIT 1",
                [],
                |r| r.get(0),
            )
            .optional()?;
        let Some(key) = victim else {
            return Ok(count);
        };
        db.execute("DELETE FROM entries WHERE key=?1", [key])?;
        count += 1;
    }
}
fn validate(db: &Connection) -> Result<(), String> {
    let mut stmt = db
        .prepare("SELECT type,name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'")
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
        .map_err(|e| e.to_string())?
        .collect::<rusqlite::Result<Vec<_>>>()
        .map_err(|e| e.to_string())?;
    if rows.iter().any(|(kind, name)| {
        !((kind == "table" && name == "entries") || (kind == "index" && name == "cache_lru"))
    }) {
        return Err("cache database has foreign objects".into());
    }
    if rows.iter().any(|(_, name)| name == "entries") {
        // Assigning FULL after schema creation does not convert a NONE database.
        // A disabled untouched memo is safer than claiming a quota it cannot keep.
        if read_pragma(db, "PRAGMA auto_vacuum").map_err(|e| e.to_string())? != 1 {
            return Err("cache requires FULL auto-vacuum".into());
        }
        let mut stmt = db
            .prepare("PRAGMA table_info(entries)")
            .map_err(|e| e.to_string())?;
        let cols = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, i64>(3)?,
                    r.get::<_, i64>(5)?,
                ))
            })
            .map_err(|e| e.to_string())?
            .collect::<rusqlite::Result<Vec<_>>>()
            .map_err(|e| e.to_string())?;
        let expected = vec![
            ("key".into(), "TEXT".into(), 0, 1),
            ("value".into(), "BLOB".into(), 1, 0),
            ("size".into(), "INTEGER".into(), 1, 0),
            ("touched".into(), "INTEGER".into(), 1, 0),
        ];
        if cols != expected {
            return Err("cache entries schema differs".into());
        }
        if rows.iter().any(|(_, n)| n == "cache_lru") {
            let mut stmt = db
                .prepare("PRAGMA index_info(cache_lru)")
                .map_err(|e| e.to_string())?;
            let cols = stmt
                .query_map([], |r| r.get::<_, String>(2))
                .map_err(|e| e.to_string())?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(|e| e.to_string())?;
            if cols != ["touched"] {
                return Err("cache LRU schema differs".into());
            }
        }
    }
    let page_size: u64 = read_pragma(db, "PRAGMA page_size").map_err(|e| e.to_string())?;
    if page_size != 4096 {
        return Err("cache page size differs".into());
    }
    Ok(())
}

fn read_pragma(db: &Connection, sql: &str) -> rusqlite::Result<u64> {
    let value: i64 = db.query_row(sql, [], |r| r.get(0))?;
    u64::try_from(value).map_err(|_| rusqlite::Error::InvalidQuery)
}
