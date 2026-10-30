//! Disposable native byte memo. Transactions publish a whole authenticated entry.
use ken_query::execution::{ExecutionError, Result};
use rusqlite::{Connection, OptionalExtension, params};
use sha2::{Digest, Sha256};
use std::{
    io::Write,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};
fn error(e: impl std::fmt::Display) -> ExecutionError {
    ExecutionError::Storage(e.to_string())
}
pub(super) fn digest(bytes: &[u8], check: &mut dyn FnMut() -> Result<()>) -> Result<String> {
    let mut hash = Sha256::new();
    for bytes in bytes.chunks(8192) {
        check()?;
        hash.update(bytes);
    }
    check()?;
    Ok(format!("{:x}", hash.finalize()))
}
pub(super) struct CheckedWriter<'a> {
    pub bytes: Vec<u8>,
    pub check: &'a mut dyn FnMut() -> Result<()>,
    pub stopped: Option<ExecutionError>,
}
impl Write for CheckedWriter<'_> {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if let Err(e) = (self.check)() {
            self.stopped = Some(e);
            return Err(std::io::Error::other("memo serialization interrupted"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
pub(super) fn encode<T: serde::Serialize>(
    value: &T,
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<Vec<u8>> {
    let mut writer = CheckedWriter {
        bytes: vec![],
        check,
        stopped: None,
    };
    let result = serde_json::to_writer(&mut writer, value);
    if let Some(e) = writer.stopped {
        return Err(e);
    }
    result.map_err(error)?;
    Ok(writer.bytes)
}

pub(super) fn decode<T: serde::de::DeserializeOwned>(
    bytes: &[u8],
    check: &mut dyn FnMut() -> Result<()>,
) -> Result<T> {
    struct Reader<'a> {
        bytes: &'a [u8],
        position: usize,
        check: &'a mut dyn FnMut() -> Result<()>,
        stopped: Option<ExecutionError>,
    }
    impl std::io::Read for Reader<'_> {
        fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
            if let Err(e) = (self.check)() {
                self.stopped = Some(e);
                return Err(std::io::Error::other("memo decode interrupted"));
            }
            let n = out.len().min(8192).min(self.bytes.len() - self.position);
            out[..n].copy_from_slice(&self.bytes[self.position..self.position + n]);
            self.position += n;
            Ok(n)
        }
    }
    let mut reader = Reader {
        bytes,
        position: 0,
        check,
        stopped: None,
    };
    let result = serde_json::from_reader(std::io::BufReader::new(&mut reader));
    if let Some(e) = reader.stopped {
        return Err(e);
    }
    result.map_err(error)
}
pub(super) struct Memo {
    db: Option<Connection>,
    limit: u64,
    pub evictions: u64,
    pub error: Option<String>,
}
impl Memo {
    pub fn new(
        path: Option<&Path>,
        limit: u64,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<Self> {
        check()?;
        let mut memo = Self {
            db: None,
            limit,
            evictions: 0,
            error: None,
        };
        let Some(path) = path.filter(|_| limit > 0) else {
            return Ok(memo);
        };
        let open = (|| -> std::result::Result<Connection, Box<dyn std::error::Error>> {
            if std::fs::symlink_metadata(path).is_ok_and(|m| !m.is_file()) {
                return Err("memo path is not a regular file".into());
            }
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            let db = Connection::open(path)?;
            db.busy_timeout(std::time::Duration::ZERO)?;
            let names=db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")?.query_map([],|r|r.get::<_,String>(0))?.collect::<std::result::Result<Vec<_>,_>>()?;
            if names.iter().any(|n| n != "buckets" && n != "memo_format") {
                return Err("foreign memo schema".into());
            }
            db.execute_batch("PRAGMA journal_mode=DELETE;CREATE TABLE IF NOT EXISTS memo_format(format TEXT NOT NULL);CREATE TABLE IF NOT EXISTS buckets(key TEXT PRIMARY KEY,revision TEXT NOT NULL,digest TEXT NOT NULL,payload BLOB NOT NULL,bytes INTEGER NOT NULL,touched INTEGER NOT NULL);")?;
            let format: Option<String> = db
                .query_row("SELECT format FROM memo_format", [], |r| r.get(0))
                .optional()?;
            match format {
                None => {
                    db.execute(
                        "INSERT INTO memo_format VALUES('ken-native-exploration-memo/1')",
                        [],
                    )?;
                }
                Some(s) if s == "ken-native-exploration-memo/1" => {}
                _ => return Err("foreign memo format".into()),
            };
            Ok(db)
        })();
        check()?;
        match open {
            Ok(db) => memo.db = Some(db),
            Err(e) => memo.error = Some(e.to_string()),
        };
        while memo.allocated() > limit {
            check()?;
            let result=memo.db.as_ref().unwrap().execute("DELETE FROM buckets WHERE key=(SELECT key FROM buckets ORDER BY touched,key LIMIT 1)",[]);
            match result {
                Ok(0) => break,
                Ok(_) => memo.evictions += 1,
                Err(e) => {
                    memo.error = Some(e.to_string());
                    break;
                }
            }
        }
        Ok(memo)
    }
    pub fn enabled(&self) -> bool {
        self.db.is_some()
    }
    pub fn allocated(&self) -> u64 {
        self.db
            .as_ref()
            .and_then(|db| {
                db.query_row("SELECT coalesce(sum(bytes),0) FROM buckets", [], |r| {
                    r.get::<_, i64>(0)
                })
                .ok()
            })
            .and_then(|bytes| u64::try_from(bytes).ok())
            .unwrap_or(0)
    }
    pub fn get(
        &mut self,
        key: &str,
        revision: &str,
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<Option<Vec<u8>>> {
        check()?;
        let Some(db) = &self.db else { return Ok(None) };
        let row = db
            .query_row(
                "SELECT digest,payload FROM buckets WHERE key=?1 AND revision=?2",
                params![key, revision],
                |r| Ok((r.get::<_, String>(0)?, r.get::<_, Vec<u8>>(1)?)),
            )
            .optional();
        let (expected, bytes) = match row {
            Ok(Some(row)) => row,
            Ok(None) => return Ok(None),
            Err(e) => {
                self.error = Some(e.to_string());
                return Ok(None);
            }
        };
        if digest(&bytes, check)? != expected {
            self.error = Some("memo checksum mismatch; rebuilding".into());
            return Ok(None);
        }
        check()?;
        let _ = db.execute(
            "UPDATE buckets SET touched=?1 WHERE key=?2",
            params![now(), key],
        );
        Ok(Some(bytes))
    }
    pub fn put(
        &mut self,
        key: &str,
        revision: &str,
        bytes: &[u8],
        check: &mut dyn FnMut() -> Result<()>,
    ) -> Result<()> {
        check()?;
        let Some(db) = &self.db else { return Ok(()) };
        if bytes.len() as u64 > self.limit {
            self.evictions += 1;
            return Ok(());
        }
        let digest = digest(bytes, check)?;
        loop {
            check()?;
            match db.execute_batch("BEGIN IMMEDIATE") {
                Ok(()) => break,
                Err(rusqlite::Error::SqliteFailure(e, _))
                    if matches!(
                        e.code,
                        rusqlite::ErrorCode::DatabaseBusy | rusqlite::ErrorCode::DatabaseLocked
                    ) =>
                {
                    std::thread::sleep(std::time::Duration::from_millis(2))
                }
                Err(e) => {
                    self.error = Some(e.to_string());
                    return Ok(());
                }
            }
        }
        let result = (|| -> Result<()> {
            db.execute("DELETE FROM buckets WHERE key=?1", [key])
                .map_err(error)?;
            loop {
                check()?;
                let total: i64 = db
                    .query_row("SELECT coalesce(sum(bytes),0) FROM buckets", [], |r| {
                        r.get(0)
                    })
                    .map_err(error)?;
                let total =
                    u64::try_from(total).map_err(|_| error("negative retained memo byte count"))?;
                if total.saturating_add(bytes.len() as u64) <= self.limit {
                    break;
                }
                db.execute("DELETE FROM buckets WHERE key=(SELECT key FROM buckets ORDER BY touched,key LIMIT 1)",[]).map_err(error)?;
                self.evictions += 1;
            }
            db.execute(
                "INSERT INTO buckets VALUES(?1,?2,?3,?4,?5,?6)",
                params![key, revision, digest, bytes, bytes.len() as i64, now()],
            )
            .map_err(error)?;
            // Final interruption check while the write lock still hides all changes.
            check()?;
            db.execute_batch("COMMIT").map_err(error)?;
            Ok(())
        })();
        if let Err(e) = result {
            let _ = db.execute_batch("ROLLBACK");
            match e {
                ExecutionError::Exhausted(_) => return Err(e),
                _ => self.error = Some(e.to_string()),
            }
        }
        Ok(())
    }
}
fn now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_micros()
        .min(i64::MAX as u128) as i64
}
