//! Live literal search and the incremental SQLite FTS mirror, without models.
use crate::Result;
use ken_core::{project::ProjectPaths, source_reader::SourceFileReader, tool_output::Document};
use ken_index::changes::content_hash;
use ken_retrieval::source_snapshot::SourceError;
use ken_text::unicode::{splitlines, whitespace, word};
use rusqlite::{Connection, OpenFlags, params};
use std::{collections::BTreeMap, path::Path, time::Duration};

macro_rules! doc {
    ($($key:literal : $value:expr),* $(,)?) => {
        Document::object(vec![$(($key, Document::from($value))),*])
    };
}

/// Each request reads current indexed paths and source handles. Only BM25 writes
/// the derived mirror; it never changes source index records or loads models.
pub struct WorktreeTextSearch {
    paths: ProjectPaths,
}
impl WorktreeTextSearch {
    pub fn new(paths: ProjectPaths) -> Self {
        Self { paths }
    }

    pub fn find(&self, query: &str, literal: bool, language: &str, limit: i64) -> Result<Document> {
        if query.is_empty() {
            return Ok(doc!("ok": false, "error": "empty query"));
        }
        let flags = if literal {
            OpenFlags::SQLITE_OPEN_READ_ONLY
        } else {
            OpenFlags::SQLITE_OPEN_READ_WRITE
        };
        let mut conn =
            Connection::open_with_flags(self.paths.db(), flags | OpenFlags::SQLITE_OPEN_NO_MUTEX)?;
        conn.busy_timeout(Duration::from_secs(5))?;
        let reader = SourceFileReader::new(&self.paths).map_err(SourceError::from)?;
        let tx = conn.transaction()?;
        let files = tx
            .prepare("SELECT path,language FROM ci_files ORDER BY path")?
            .query_map([], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, Option<String>>(1)?))
            })?
            .collect::<rusqlite::Result<BTreeMap<_, _>>>()?;
        let limit = limit.max(1) as usize;
        let hits = if literal {
            literal_hits(&reader, &files, query, language, limit)
        } else {
            sync_mirror(&tx, &reader, &files)?;
            match bm25_hits(&tx, &files, query, language, limit) {
                Ok(hits) => hits,
                Err(error) => {
                    tx.commit()?;
                    return Ok(doc!("ok": false, "error": format!("fts query failed: {error}")));
                }
            }
        };
        tx.commit()?;
        Ok(
            doc!("ok": true, "mode": if literal { "literal" } else { "bm25" }, "query": query, "results": hits),
        )
    }
}

type Files = BTreeMap<String, Option<String>>;
fn language_matches(files: &Files, path: &str, language: &str) -> bool {
    language.is_empty() || files.get(path).and_then(Option::as_deref) == Some(language)
}
fn literal_hits(
    reader: &SourceFileReader,
    files: &Files,
    query: &str,
    language: &str,
    limit: usize,
) -> Vec<Document> {
    let mut hits = Vec::new();
    for path in files.keys() {
        if !language_matches(files, path, language) {
            continue;
        }
        let Ok(bytes) = reader
            .open(Path::new(path))
            .and_then(|source| source.read())
        else {
            continue;
        };
        // Python read_text applies universal newline conversion before matching.
        let text = String::from_utf8_lossy(&bytes)
            .replace("\r\n", "\n")
            .replace('\r', "\n");
        let count = text.matches(query).count();
        if count == 0 {
            continue;
        }
        let snippets = splitlines(&text).into_iter().enumerate()
            .filter(|(_, line)| line.contains(query)).take(5)
            .map(|(line, text)| doc!("line": line + 1, "text": text.trim_matches(whitespace).chars().take(200).collect::<String>()))
            .collect::<Vec<_>>();
        hits.push(doc!("path": path.as_str(), "count": count, "snippets": snippets));
        // The original selects paths before sorting this bounded result by count.
        if hits.len() >= limit {
            break;
        }
    }
    hits.sort_by_key(|hit| std::cmp::Reverse(hit.get("count").integer().unwrap()));
    hits
}

fn sync_mirror(
    conn: &Connection,
    reader: &SourceFileReader,
    files: &Files,
) -> rusqlite::Result<()> {
    let state = conn
        .prepare("SELECT path,content_hash FROM ci_fts_state")?
        .query_map([], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, Vec<u8>>(1)?))
        })?
        .collect::<rusqlite::Result<BTreeMap<_, _>>>()?;
    for path in state.keys().filter(|path| !files.contains_key(*path)) {
        conn.execute("DELETE FROM fts_files WHERE path=?1", [path])?;
        conn.execute("DELETE FROM ci_fts_state WHERE path=?1", [path])?;
    }
    for path in files.keys() {
        let Ok(source) = reader.open(Path::new(path)) else {
            continue;
        };
        let Ok(meta) = source.metadata() else {
            continue;
        };
        if meta.len() > 1024 * 1024 {
            continue;
        }
        let Ok(bytes) = source.read() else {
            continue;
        };
        // Recheck after the read in case a writer grew the same source handle.
        if bytes.len() > 1024 * 1024 {
            continue;
        }
        let hash = content_hash(&bytes);
        if state.get(path).is_some_and(|old| old.as_slice() == hash) {
            continue;
        }
        conn.execute("DELETE FROM fts_files WHERE path=?1", [path])?;
        conn.execute(
            "INSERT INTO fts_files(path,body)VALUES(?1,?2)",
            params![path, String::from_utf8_lossy(&bytes)],
        )?;
        conn.execute("INSERT INTO ci_fts_state(path,content_hash)VALUES(?1,?2) ON CONFLICT(path) DO UPDATE SET content_hash=excluded.content_hash", params![path, hash.as_slice()])?;
    }
    Ok(())
}

fn bm25_hits(
    conn: &Connection,
    files: &Files,
    query: &str,
    language: &str,
    limit: usize,
) -> rusqlite::Result<Vec<Document>> {
    let terms = query
        .split(whitespace)
        .filter(|s| s.chars().any(|c| c != '_' && word(c)))
        .map(|s| format!("\"{}\"", s.replace('"', "\"\"")))
        .collect::<Vec<_>>();
    if terms.is_empty() {
        return Ok(Vec::new());
    }
    let mut statement = conn.prepare("SELECT path,snippet(fts_files,1,'[',']',' … ',12),bm25(fts_files) AS score FROM fts_files WHERE fts_files MATCH ?1 ORDER BY score LIMIT ?2")?;
    let rows = statement.query_map(
        params![
            terms.join(" OR "),
            limit.saturating_mul(3).min(i64::MAX as usize) as i64
        ],
        |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, f64>(2)?,
            ))
        },
    )?;
    let mut hits = Vec::new();
    for row in rows {
        let (path, snippet, score) = row?;
        if !language_matches(files, &path, language) {
            continue;
        }
        let score = format!("{score:.3}")
            .parse::<f64>()
            .expect("rounded finite SQLite score");
        hits.push(doc!("path": path, "score": score, "snippet": snippet));
        if hits.len() >= limit {
            break;
        }
    }
    Ok(hits)
}
