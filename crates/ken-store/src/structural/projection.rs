use super::{Result, Scalar, scalar};
use ken_program::{Attributes, StructuralIr};
use rusqlite::{Connection, params};
use std::collections::{BTreeMap, BTreeSet};
fn integer(attrs: &Attributes, key: &str) -> Option<i64> {
    attrs.get(key)?.get().parse().ok()
}
fn text(attrs: &Attributes, key: &str) -> Option<String> {
    serde_json::from_str(attrs.get(key)?.get()).ok()
}
pub(super) fn project(db: &Connection, unit: i64, ir: &StructuralIr) -> Result<()> {
    let mut owners = BTreeMap::new();
    let mut fields = BTreeSet::new();
    let mut parameters = BTreeMap::new();
    for fact in &ir.facts {
        if [
            "HAS_METHOD",
            "HAS_FIELD",
            "HAS_PARAMETER",
            "HAS_CALL",
            "DECLARES",
        ]
        .contains(&fact.relation.as_str())
        {
            owners.insert(&fact.object, &fact.subject);
        }
        if fact.relation == "HAS_FIELD" {
            fields.insert(&fact.object);
        }
        if fact.relation == "HAS_PARAMETER" {
            parameters.insert(&fact.object, &fact.attrs);
        }
    }
    for (_, entity) in &ir.entities {
        let kind = if entity.kind == "STORAGE" && fields.contains(&entity.id) {
            "FIELD"
        } else {
            &entity.kind
        };
        db.execute("INSERT INTO k2_nodes(unit_id,local_id,kind,name,owner,line,end_line)VALUES(?1,?2,?3,?4,?5,?6,?7)",params![unit,entity.id,kind,entity.name,owners.get(&entity.id).copied(),entity.line,entity.end_line])?;
        let id = db.last_insert_rowid();
        let mut attrs = entity.attrs.clone();
        if let Some(value) = attrs.remove("async_") {
            attrs.insert("async".into(), value);
        }
        if entity.kind == "PARAMETER" {
            let native = attrs.get("position").map_or_else(
                || serde_json::value::RawValue::from_string("null".into()).unwrap(),
                Clone::clone,
            );
            attrs.insert("native_position".into(), native);
            if let Some(facts) = parameters.get(&entity.id) {
                for key in ["position", "receiver"] {
                    if let Some(value) = facts.get(key) {
                        attrs.insert(key.into(), value.clone());
                    }
                }
            }
            if attrs.get("receiver").is_some_and(|r| scalar::truthy(r)) {
                attrs.remove("position");
            }
        }
        for (key, raw) in &attrs {
            if let Some(value) = Scalar::from_raw(raw)? {
                let (tag, value) = value.database();
                db.execute(
                    "INSERT INTO k2_properties VALUES(?1,?2,?3,?4)",
                    params![id, key, tag, value],
                )?;
            }
        }
    }
    for (i, fact) in ir.facts.iter().enumerate() {
        db.execute(
            "INSERT INTO k2_facts VALUES(?1,?2,?3,?4,?5,?6,?7)",
            params![
                unit,
                i as i64,
                fact.subject,
                fact.relation,
                fact.object,
                serde_json::to_string(&fact.attrs)?,
                serde_json::to_string(&fact.evidence)?
            ],
        )?;
    }
    project_operations(db, unit, ir)
}
pub(super) fn project_operations(db: &Connection, unit: i64, ir: &StructuralIr) -> Result<()> {
    let exists: bool = db.query_row(
        "SELECT EXISTS(SELECT 1 FROM k2_operation_units WHERE unit_id=?1)",
        [unit],
        |r| r.get(0),
    )?;
    if exists {
        return Ok(());
    }
    let mut entities = BTreeMap::new();
    for (_, e) in &ir.entities {
        if ["CALL", "VALUE"].contains(&e.kind.as_str())
            && let (Some(start), Some(end), Some(native)) = (
                integer(&e.attrs, "start_byte"),
                integer(&e.attrs, "end_byte"),
                text(&e.attrs, "native_kind"),
            )
        {
            entities.insert((start, end, native), &e.id);
        }
    }
    db.execute("INSERT INTO k2_operation_units VALUES(?1)", [unit])?;
    for op in &ir.operations {
        db.execute(
            "INSERT INTO k2_operations VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12)",
            params![
                unit,
                op.id,
                op.owner,
                op.parent,
                op.kind,
                op.native_kind,
                op.role,
                op.start,
                op.end,
                op.line,
                serde_json::to_string(&op.attrs)?,
                entities
                    .get(&(op.start, op.end, op.native_kind.clone()))
                    .copied()
            ],
        )?;
    }
    Ok(())
}
