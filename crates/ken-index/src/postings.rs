//! Name postings share the same vocabulary as query consumers.
use crate::Result;
use ken_retrieval::vocabulary::{NAME_TOKEN_VERSION, name_tokens};
use rusqlite::{Connection, params};
use std::collections::BTreeSet;
pub(crate) fn write_file(
    conn: &Connection,
    id: i64,
    path: &str,
    stops: &BTreeSet<String>,
) -> Result<()> {
    conn.execute(
        "DELETE FROM ci_name_tokens WHERE kind=0 AND row_id=?1",
        [id],
    )?;
    insert(conn, 0, id, &name_tokens(path, stops))
}
pub(crate) fn write_symbol(
    conn: &Connection,
    id: i64,
    kind: &str,
    qualname: Option<&str>,
    name: &str,
    stops: &BTreeSet<String>,
) -> Result<()> {
    insert(
        conn,
        1,
        id,
        &name_tokens(&format!("{kind} {} {name}", qualname.unwrap_or("")), stops),
    )
}
fn insert(conn: &Connection, kind: i64, id: i64, tokens: &BTreeSet<String>) -> Result<()> {
    let mut statement =
        conn.prepare("INSERT OR IGNORE INTO ci_name_tokens(token,kind,row_id)VALUES(?1,?2,?3)")?;
    for token in tokens {
        statement.execute(params![token, kind, id])?;
    }
    Ok(())
}
pub fn rebuild_name_tokens(conn: &Connection, stops: &BTreeSet<String>) -> Result<usize> {
    conn.execute_batch("SAVEPOINT index_name_rebuild")?;
    let work = || -> Result<usize> {
        conn.execute("DELETE FROM ci_name_tokens", [])?;
        conn.execute_batch("CREATE TEMP TABLE IF NOT EXISTS _tok_stage(token TEXT,kind INTEGER,row_id INTEGER); DELETE FROM _tok_stage")?;
        let mut insert =
            conn.prepare("INSERT INTO _tok_stage(token,kind,row_id)VALUES(?1,?2,?3)")?;
        let mut written = 0;
        let mut query = conn.prepare("SELECT id,path FROM ci_files")?;
        for row in query.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))? {
            let (id, path) = row?;
            for token in name_tokens(&path, stops) {
                insert.execute(params![token, 0, id])?;
            }
            written += 1;
        }
        let mut query = conn.prepare("SELECT id,kind,qualname,name FROM ci_symbols")?;
        for row in query.query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, Option<String>>(2)?,
                r.get::<_, String>(3)?,
            ))
        })? {
            let (id, kind, qualname, name) = row?;
            for token in name_tokens(
                &format!(
                    "{} {} {name}",
                    kind.unwrap_or_default(),
                    qualname.unwrap_or_default()
                ),
                stops,
            ) {
                insert.execute(params![token, 1, id])?;
            }
            written += 1;
        }
        drop(insert);
        conn.execute("INSERT OR IGNORE INTO ci_name_tokens(token,kind,row_id)SELECT token,kind,row_id FROM _tok_stage ORDER BY kind,token,row_id",[])?;
        conn.execute("DROP TABLE _tok_stage", [])?;
        conn.execute("INSERT INTO meta(key,value)VALUES('name_token_version',?1)ON CONFLICT(key)DO UPDATE SET value=excluded.value",[NAME_TOKEN_VERSION.to_string()])?;
        Ok(written)
    };
    match work() {
        Ok(n) => {
            conn.execute_batch("RELEASE SAVEPOINT index_name_rebuild")?;
            Ok(n)
        }
        Err(e) => {
            conn.execute_batch(
                "ROLLBACK TO SAVEPOINT index_name_rebuild; RELEASE SAVEPOINT index_name_rebuild",
            )?;
            Err(e)
        }
    }
}
