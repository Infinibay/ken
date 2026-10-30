use crate::Result;
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
const KINDS: [&str; 4] = ["file", "symbol", "tool", "error"];
fn resolve(db: &Connection, kind: &str, key: &str) -> (Option<i64>, Option<i64>, i64) {
    let result = (|| -> Result<(Option<i64>, Option<i64>, i64)> {
        match kind {
            "file" => {
                let mut stmt =
                    db.prepare("SELECT id FROM ci_files WHERE path=? OR path LIKE ? LIMIT 2")?;
                let ids = stmt
                    .query_map(
                        params![key, format!("%/{}", key.trim_start_matches('/'))],
                        |r| r.get::<_, i64>(0),
                    )?
                    .collect::<std::result::Result<Vec<_>, _>>()?;
                if ids.len() == 1 {
                    return Ok((Some(ids[0]), None, 1));
                }
            }
            "symbol" => {
                let mut stmt = db.prepare("SELECT id FROM ci_symbols WHERE qualname=? LIMIT 2")?;
                let ids = stmt
                    .query_map([key], |r| r.get::<_, i64>(0))?
                    .collect::<std::result::Result<Vec<_>, _>>()?;
                if ids.len() == 1 {
                    return Ok((None, Some(ids[0]), 1));
                }
            }
            _ => {}
        }
        Ok((None, None, 0))
    })();
    result.unwrap_or((None, None, 0))
}
pub fn set_anchors(db: &Connection, id: i64, anchors: &Value, now: i64) -> Result<usize> {
    db.execute(
        "DELETE FROM cr_finding_refs WHERE finding_id=? AND method='anchor'",
        [id],
    )?;
    let mut count = 0;
    for kind in KINDS {
        let key = anchors[kind].as_str().unwrap_or("").trim();
        if key.is_empty() {
            continue;
        }
        let (file, symbol, resolved) = resolve(db, kind, key);
        db.execute("INSERT OR REPLACE INTO cr_finding_refs(finding_id,ref_kind,ref_key,file_id,symbol_id,method,resolved,updated_at) VALUES(?,?,?,?,?,'anchor',?,?)",params![id,kind,key,file,symbol,resolved,now])?;
        count += 1;
    }
    Ok(count)
}
pub fn anchors_for(db: &Connection, id: i64) -> Result<Value> {
    let mut stmt = match db.prepare(
        "SELECT ref_kind,ref_key FROM cr_finding_refs WHERE finding_id=? AND method='anchor'",
    ) {
        Ok(s) => s,
        Err(_) => return Ok(json!({})),
    };
    let rows = stmt
        .query_map([id], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        })?
        .collect::<std::result::Result<BTreeMap<_, _>, _>>()?;
    Ok(json!(rows))
}
pub fn by_anchor(db: &Connection, anchors: &Value, limit: usize) -> Result<Vec<Value>> {
    let mut clauses = Vec::new();
    let mut values = vec!["anchor".to_owned()];
    for kind in KINDS {
        let key = anchors[kind].as_str().unwrap_or("").trim();
        if key.is_empty() {
            continue;
        }
        match kind {
            "file" => {
                let norm = key.replace('\\', "/");
                let base = norm.trim_end_matches('/').rsplit('/').next().unwrap_or("");
                clauses.push("(r.ref_kind='file' AND (r.ref_key=? OR ? LIKE '%/' || r.ref_key OR r.ref_key LIKE '%/' || ?))");
                values.extend([key.to_owned(), key.to_owned(), base.to_owned()]);
            }
            "error" => {
                clauses.push("(r.ref_kind='error' AND ? LIKE '%' || r.ref_key || '%')");
                values.push(key.to_owned());
            }
            _ => {
                clauses.push("(r.ref_kind=? AND r.ref_key=?)");
                values.extend([kind.to_owned(), key.to_owned()]);
            }
        }
    }
    if clauses.is_empty() {
        return Ok(Vec::new());
    }
    let sql = format!(
        "SELECT f.id,f.topic,f.content,f.tags,f.updated_at,r.ref_kind,r.ref_key FROM cr_finding_refs r JOIN cr_findings f ON f.id=r.finding_id WHERE r.method=? AND ({}) ORDER BY f.updated_at DESC LIMIT ?",
        clauses.join(" OR ")
    );
    let mut stmt = match db.prepare(&sql) {
        Ok(s) => s,
        Err(_) => return Ok(Vec::new()),
    };
    let mut params = values
        .into_iter()
        .map(rusqlite::types::Value::Text)
        .collect::<Vec<_>>();
    params.push((limit.max(1) as i64).into());
    let rows = stmt.query_map(rusqlite::params_from_iter(params), |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, String>(3)?,
            r.get::<_, i64>(4)?,
            r.get::<_, String>(5)?,
            r.get::<_, String>(6)?,
        ))
    })?;
    let mut seen = BTreeSet::new();
    let mut out = Vec::new();
    for row in rows {
        let (id, topic, content, tags, updated, kind, key) = row?;
        if seen.insert(id) {
            out.push(json!({"topic":topic,"content":content,"tags":serde_json::from_str::<Value>(&tags)?,"anchor":{"kind":kind,"key":key},"updated_at":updated}));
        }
    }
    Ok(out)
}
