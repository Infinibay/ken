use super::ProbeResult;
use rusqlite::{Connection, types::ValueRef};
use serde_json::{Value, json};
use std::collections::BTreeMap;

pub fn rows(conn: &Connection, sql: &str) -> ProbeResult<Vec<Value>> {
    let mut stmt = conn.prepare(sql)?;
    let columns = stmt.column_count();
    let result = stmt
        .query_map([], |row| {
            (0..columns)
                .map(|col| {
                    Ok(match row.get_ref(col)? {
                        ValueRef::Null => Value::Null,
                        ValueRef::Integer(n) => json!(n),
                        ValueRef::Real(n) => json!(n),
                        ValueRef::Text(text) => json!(String::from_utf8_lossy(text)),
                        ValueRef::Blob(raw) => json!(super::history::hex(raw)),
                    })
                })
                .collect::<rusqlite::Result<Vec<_>>>()
                .map(Value::Array)
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(result)
}
pub fn snapshot(conn: &Connection) -> ProbeResult<Value> {
    let objects = rows(
        conn,
        "SELECT type,name,tbl_name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name",
    )?;
    let mut tables = BTreeMap::new();
    for object in &objects {
        if object[0] != "table" {
            continue;
        }
        let name = object[1].as_str().ok_or("nontext schema name")?;
        let quoted = serde_json::to_string(name)?;
        let mut indexes = Vec::new();
        for row in rows(conn, &format!("PRAGMA index_list({quoted})"))? {
            let index_name = row[1].as_str().ok_or("nontext index name")?;
            indexes.push(json!({"name":index_name,"unique":row[2],"origin":row[3],"partial":row[4],"columns":rows(conn,&format!("PRAGMA index_xinfo({})",serde_json::to_string(index_name)?))?}));
        }
        indexes.sort_by(|a, b| a["name"].as_str().cmp(&b["name"].as_str()));
        tables.insert(name.to_owned(),json!({"columns":rows(conn,&format!("PRAGMA table_info({quoted})"))?,"indexes":indexes,"foreign_keys":rows(conn,&format!("PRAGMA foreign_key_list({quoted})"))?}));
    }
    Ok(json!({"objects":objects,"tables":tables}))
}
