use super::{Result, StructuralError, schema};
use ken_program::{Program, StructuralIr};
use rusqlite::{Connection, params, types::Value as Sql};
use serde::Serialize;
use serde_json::{Map, Value};
use std::collections::BTreeMap;
fn column<'a>(family: &str, name: &'a str) -> &'a str {
    match name {
        "id" => match family {
            "nodes" => "node_id",
            "scopes" => "scope_id",
            "symbols" => "symbol_id",
            _ => name,
        },
        "start" => "start_byte",
        "end" => "end_byte",
        "node" => "node_id",
        _ => name,
    }
}
fn number(v: &Value) -> Result<Sql> {
    Ok(match v {
        Value::Null => Sql::Null,
        Value::Bool(v) => Sql::Integer(i64::from(*v)),
        Value::Number(n) => Sql::Integer(
            n.as_i64()
                .ok_or(StructuralError::Invalid("AST integer outside SQLite range"))?,
        ),
        _ => return Err(StructuralError::Invalid("invalid AST scalar")),
    })
}
fn intern(strings: &mut BTreeMap<String, i64>, value: &str) -> i64 {
    let next = strings.len() as i64;
    *strings.entry(value.into()).or_insert(next)
}
fn records<'a, T: Serialize + 'a>(records: &'a [T]) -> impl Iterator<Item = Result<Value>> + 'a {
    records.iter().map(|r| Ok(serde_json::to_value(r)?))
}
pub(super) fn project(db: &Connection, unit: i64, program: &Program) -> Result<()> {
    program.validate()?;
    db.execute(
        "INSERT INTO k2_ast_units VALUES(?1,?2)",
        params![unit, program.version],
    )?;
    let mut strings = BTreeMap::new();
    for (family, layout) in schema::manifest().layouts.families() {
        let columns = layout[0]
            .split_whitespace()
            .filter(|n| !layout[2].split_whitespace().any(|t| t == *n))
            .map(|n| column(family, n))
            .collect::<Vec<_>>();
        let placeholders = std::iter::repeat_n("?", columns.len() + 1)
            .collect::<Vec<_>>()
            .join(",");
        let mut insert = db.prepare(&format!(
            "INSERT INTO k2_ast_{family} VALUES({placeholders})"
        ))?;
        let rows: Box<dyn Iterator<Item = Result<Value>> + '_> = match family {
            "nodes" => Box::new(records(&program.nodes)),
            "scopes" => Box::new(records(&program.scopes)),
            "symbols" => Box::new(records(&program.symbols)),
            "references" => Box::new(records(&program.references)),
            _ => unreachable!(),
        };
        for record in rows {
            let record = record?;
            let identity = record
                .get("id")
                .or_else(|| record.get("node"))
                .and_then(Value::as_i64)
                .ok_or(StructuralError::Invalid("missing AST identity"))?;
            let mut values = vec![Sql::Integer(unit)];
            for field in layout[0].split_whitespace() {
                let value = &record[field];
                if layout[2].split_whitespace().any(|t| t == field) {
                    for (i, item) in value
                        .as_array()
                        .ok_or(StructuralError::Invalid("invalid AST members"))?
                        .iter()
                        .enumerate()
                    {
                        let string = intern(
                            &mut strings,
                            item.as_str()
                                .ok_or(StructuralError::Invalid("invalid AST member string"))?,
                        );
                        db.execute(
                            "INSERT INTO k2_ast_members VALUES(?1,?2,?3,?4,?5,?6)",
                            params![unit, family, identity, field, i as i64, string],
                        )?;
                    }
                } else if layout[1].split_whitespace().any(|s| s == field) {
                    values.push(Sql::Integer(intern(
                        &mut strings,
                        value
                            .as_str()
                            .ok_or(StructuralError::Invalid("invalid AST string"))?,
                    )));
                } else {
                    values.push(number(value)?);
                }
            }
            insert.execute(rusqlite::params_from_iter(&values))?;
        }
    }
    for link in &program.links {
        db.execute(
            "INSERT INTO k2_ast_links VALUES(?1,?2,?3,?4,?5)",
            params![
                unit,
                link.source as i64,
                link.relation,
                link.target as i64,
                link.ordinal
            ],
        )?;
    }
    for (value, id) in strings {
        db.execute(
            "INSERT INTO k2_ast_strings VALUES(?1,?2,?3)",
            params![unit, id, value],
        )?;
    }
    for (i, message) in program.diagnostics.iter().enumerate() {
        db.execute(
            "INSERT INTO k2_ast_diagnostics VALUES(?1,?2,?3)",
            params![unit, i as i64, message],
        )?;
    }
    for body in ken_program::body_ranges(program) {
        db.execute(
            "INSERT INTO k2_ast_bodies VALUES(?1,?2,?3,?4,?5,?6)",
            params![
                unit,
                body.owner as i64,
                body.relation,
                body.root as i64,
                body.subtree_end as i64,
                body.final_node() as i64
            ],
        )?;
    }
    Ok(())
}
pub(super) fn ensure(db: &Connection, unit: i64, ir: &StructuralIr) -> Result<()> {
    let exists: bool = db.query_row(
        "SELECT EXISTS(SELECT 1 FROM k2_ast_units WHERE unit_id=?1 AND version=?2)",
        params![unit, ken_program::AST_VERSION],
        |r| r.get(0),
    )?;
    if !exists {
        db.execute("DELETE FROM k2_ast_units WHERE unit_id=?1", [unit])?;
        project(db, unit, &ken_program::normalize(ir)?)?;
    }
    Ok(())
}
pub(super) fn load(db: &Connection, unit: i64) -> Result<Program> {
    let (path, language): (String, String) = db.query_row(
        "SELECT path,language FROM k2_units WHERE unit_id=?1",
        [unit],
        |r| Ok((r.get(0)?, r.get(1)?)),
    )?;
    let strings = db
        .prepare("SELECT string_id,value FROM k2_ast_strings WHERE unit_id=?1")?
        .query_map([unit], |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
        })?
        .collect::<rusqlite::Result<BTreeMap<_, _>>>()?;
    let mut members = BTreeMap::<(String, i64, String), Vec<Value>>::new();
    let mut q=db.prepare("SELECT family,record_id,field,value FROM k2_ast_members WHERE unit_id=?1 ORDER BY family,record_id,field,ordinal")?;
    for row in q.query_map([unit], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, i64>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, i64>(3)?,
        ))
    })? {
        let (family, id, field, string) = row?;
        let value = strings
            .get(&string)
            .ok_or(StructuralError::Invalid("missing AST interned string"))?
            .clone();
        members
            .entry((family, id, field))
            .or_default()
            .push(value.into());
    }
    let mut result = Map::new();
    result.insert("path".into(), path.into());
    result.insert("language".into(), language.into());
    result.insert("version".into(), ken_program::AST_VERSION.into());
    for (family, layout) in schema::manifest().layouts.families() {
        let names = layout[0]
            .split_whitespace()
            .filter(|n| !layout[2].split_whitespace().any(|t| t == *n))
            .collect::<Vec<_>>();
        let selection = names
            .iter()
            .map(|n| format!("\"{}\"", column(family, n)))
            .collect::<Vec<_>>()
            .join(",");
        let identity = &schema::manifest().identities[family];
        let mut query = db.prepare(&format!(
            "SELECT {selection} FROM k2_ast_{family} WHERE unit_id=?1 ORDER BY {identity}"
        ))?;
        let mut rows = query.query([unit])?;
        let mut family_rows = Vec::new();
        while let Some(row) = rows.next()? {
            let id: i64 = row.get(
                names
                    .iter()
                    .position(|n| *n == "id" || *n == "node")
                    .unwrap(),
            )?;
            let mut record = Map::new();
            for (i, name) in names.iter().enumerate() {
                let raw: Option<i64> = row.get(i)?;
                let value = if layout[1].split_whitespace().any(|s| s == *name) {
                    let key = raw.ok_or(StructuralError::Invalid("null AST string"))?;
                    strings
                        .get(&key)
                        .ok_or(StructuralError::Invalid("missing AST interned string"))?
                        .clone()
                        .into()
                } else if family == "symbols" && *name == "mutable" {
                    raw.map_or(Value::Null, |n| Value::Bool(n != 0))
                } else {
                    raw.map_or(Value::Null, Value::from)
                };
                record.insert((*name).into(), value);
            }
            for field in layout[2].split_whitespace() {
                record.insert(
                    field.into(),
                    Value::Array(
                        members
                            .get(&(family.into(), id, field.into()))
                            .cloned()
                            .unwrap_or_default(),
                    ),
                );
            }
            family_rows.push(Value::Object(record));
        }
        result.insert(family.into(), Value::Array(family_rows));
    }
    let links=db.prepare("SELECT source,relation,target,ordinal FROM k2_ast_links WHERE unit_id=?1 ORDER BY source,relation,ordinal,target")?.query_map([unit],|r|Ok(ken_program::Link{source:r.get::<_,i64>(0)?as usize,relation:r.get(1)?,target:r.get::<_,i64>(2)?as usize,ordinal:r.get(3)?}))?.collect::<rusqlite::Result<Vec<_>>>()?;
    result.insert("links".into(), serde_json::to_value(links)?);
    let diagnostics = db
        .prepare("SELECT message FROM k2_ast_diagnostics WHERE unit_id=?1 ORDER BY ordinal")?
        .query_map([unit], |r| r.get::<_, String>(0))?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    result.insert("diagnostics".into(), serde_json::to_value(diagnostics)?);
    let program: Program = serde_json::from_value(Value::Object(result))?;
    program.validate()?;
    Ok(program)
}
