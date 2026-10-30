//! Durable productivity stores raw volume and one strongest turn per file.
use crate::{
    Result,
    channels::{historical_file_scores, pattern_multiplier},
};
use rusqlite::{Connection, OptionalExtension, params};
use std::collections::BTreeMap;
pub fn snapshot_session_scores(
    conn: &Connection,
    agent: &str,
    _iteration: i64,
    now_ms: i64,
) -> Result<usize> {
    let session: Option<i64> = conn
        .query_row(
            "SELECT id FROM cr_sessions WHERE agent_id=? ORDER BY id DESC LIMIT 1",
            [agent],
            |r| r.get(0),
        )
        .optional()?;
    let Some(session) = session else { return Ok(0) };
    let events = crate::channels::behavioral::events(conn, session, None)?;
    let mut groups = Vec::<Vec<crate::channels::behavioral::Event>>::new();
    let mut indices = BTreeMap::new();
    for event in events {
        let index = *indices.entry(event.context).or_insert_with(|| {
            groups.push(Vec::new());
            groups.len() - 1
        });
        groups[index].push(event);
    }
    let mut best = Vec::<(String, f64, String)>::new();
    let mut positions = BTreeMap::new();
    for turn in groups {
        for (path, raw, pattern) in historical_file_scores(&turn) {
            let index = *positions.entry(path.clone()).or_insert_with(|| {
                best.push((path, 0., "neutral".into()));
                best.len() - 1
            });
            if raw * pattern_multiplier(&pattern)
                > best[index].1 * pattern_multiplier(&best[index].2)
            {
                best[index].1 = raw;
                best[index].2 = pattern;
            }
        }
    }
    conn.execute_batch("SAVEPOINT ken_session_snapshot")?;
    let write = (|| -> Result<()> {
        conn.execute(
            "DELETE FROM cr_session_scores WHERE session_id=?",
            [session],
        )?;
        let mut statement=conn.prepare("INSERT INTO cr_session_scores(session_id,target_kind,target_id,target_path,score,pattern,created_at) VALUES(?,'file',NULL,?,?,?,?)")?;
        for (path, raw, pattern) in &best {
            statement.execute(params![session, path, raw, pattern, now_ms])?;
        }
        Ok(())
    })();
    if let Err(error) = write {
        let rollback =
            conn.execute_batch("ROLLBACK TO ken_session_snapshot;RELEASE ken_session_snapshot");
        rollback?;
        return Err(error);
    }
    conn.execute_batch("RELEASE ken_session_snapshot")?;
    Ok(best.len())
}
