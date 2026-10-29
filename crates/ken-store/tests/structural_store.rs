use base64::{Engine, engine::general_purpose::STANDARD};
use flate2::read::GzDecoder;
use ken_program::StructuralIr;
use ken_store::structural::{
    NodeFilter, Scalar, StructuralError, StructuralStore, migrate, validate,
};
use rusqlite::{Connection, params};
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::Read,
    sync::{Arc, Barrier},
    thread,
};
fn fixture() -> String {
    let bytes = include_bytes!("fixtures/structural-store-reference.json.gz");
    assert_eq!(bytes.len(), 34619);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "e7d887858d27db2395fc141011ff7a52baa33001499250b2bdf31e916ab36751"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    text
}
fn reference() -> Value {
    serde_json::from_str(&fixture()).unwrap()
}
fn inputs() -> Vec<StructuralIr> {
    #[derive(Deserialize)]
    struct Input {
        input: Vec<Box<RawValue>>,
    }
    let v: Input = serde_json::from_str(&fixture()).unwrap();
    v.input
        .iter()
        .map(|raw| StructuralIr::from_json(raw.get()).unwrap())
        .collect()
}
fn nodes(
    store: &StructuralStore,
    snapshot: i64,
    filter: NodeFilter,
) -> Vec<ken_store::structural::StoredNode> {
    store
        .prepare_scan(snapshot, filter)
        .unwrap()
        .rows()
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap()
}
fn ddl(db: &Connection) -> Value {
    let rows=db.prepare("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").unwrap().query_map([],|r|Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,Option<String>>(2)?))).unwrap().collect::<rusqlite::Result<Vec<_>>>().unwrap();
    serde_json::to_value(rows).unwrap()
}
#[test]
fn exact_schema_history_up_down_rejects_foreign_modified_and_rolls_back_partial_ddl() {
    let reference = reference();
    let mut db = Connection::open_in_memory().unwrap();
    db.pragma_update(None, "foreign_keys", true).unwrap();
    for row in reference["versions"].as_array().unwrap() {
        let version = row["version"].as_i64().unwrap();
        migrate(&mut db, version).unwrap();
        assert_eq!(validate(&db, false).unwrap(), version);
        assert_eq!(ddl(&db), row["ddl"]);
    }
    for version in (0..15).rev() {
        migrate(&mut db, version).unwrap();
        assert_eq!(validate(&db, true).unwrap(), version);
    }
    migrate(&mut db, 15).unwrap();
    assert_eq!(validate(&db, false).unwrap(), 15);
    let mut failed = Connection::open_in_memory().unwrap();
    failed
        .authorizer(Some(|ctx: rusqlite::hooks::AuthContext<'_>| {
            if matches!(
                ctx.action,
                rusqlite::hooks::AuthAction::CreateTable {
                    table_name: "k2_nodes",
                    ..
                }
            ) {
                rusqlite::hooks::Authorization::Deny
            } else {
                rusqlite::hooks::Authorization::Allow
            }
        }))
        .unwrap();
    assert!(migrate(&mut failed, 15).is_err());
    failed
        .authorizer(None::<fn(rusqlite::hooks::AuthContext<'_>) -> rusqlite::hooks::Authorization>)
        .unwrap();
    assert_eq!(ddl(&failed), json!([]));
    assert_eq!(validate(&failed, true).unwrap(), 0);
    for mutation in [
        "PRAGMA user_version=99",
        "PRAGMA application_id=0",
        "UPDATE k2_migrations SET checksum='wrong'",
        "DROP INDEX k2_nodes_kind_name",
        "CREATE TABLE alien(x)",
    ] {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("s.sqlite");
        StructuralStore::open(Some(&path), None)
            .unwrap()
            .close()
            .unwrap();
        let db = Connection::open(&path).unwrap();
        db.execute_batch(mutation).unwrap();
        drop(db);
        let before = fs::read(&path).unwrap();
        assert!(
            StructuralStore::open(Some(&path), None).is_err(),
            "{mutation}"
        );
        assert_eq!(fs::read(&path).unwrap(), before, "{mutation}");
    }
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("ken.db");
    let db = Connection::open(&path).unwrap();
    db.execute_batch("CREATE TABLE cr_findings(content);INSERT INTO cr_findings VALUES('keep')")
        .unwrap();
    drop(db);
    let before = fs::read(&path).unwrap();
    assert!(StructuralStore::open(Some(&path), None).is_err());
    assert_eq!(fs::read(path).unwrap(), before);
    let path = temp.path().join("views-only.sqlite");
    let db = Connection::open(&path).unwrap();
    db.execute_batch("CREATE VIEW alien AS SELECT 1").unwrap();
    drop(db);
    let before = fs::read(&path).unwrap();
    assert!(StructuralStore::open(Some(&path), None).is_err());
    assert_eq!(fs::read(path).unwrap(), before);
}
#[test]
fn original_units_programs_operations_snapshots_and_cross_runtime_database_match() {
    let reference = reference();
    let inputs = inputs();
    let mut store = StructuralStore::open(None, None).unwrap();
    let mut units = Vec::new();
    for (i, ir) in inputs.iter().enumerate() {
        let unit = store
            .put_unit(
                &format!("key{i}"),
                ir,
                &format!("hash{i}"),
                "frontend",
                true,
            )
            .unwrap();
        assert_eq!(
            store
                .put_unit(&format!("key{i}"), ir, "ignored", "ignored", true)
                .unwrap(),
            unit
        );
        units.push(unit);
        compare_unit(&mut store, unit, &reference["units"][i]);
    }
    let first = store
        .publish(&[units[0]], None, "legacy-source/1", true)
        .unwrap();
    let second = store
        .publish(&[units[1], units[2]], Some(first), "legacy-source/1", true)
        .unwrap();
    let repeated = store
        .publish(&[units[2], units[1]], Some(second), "legacy-source/1", true)
        .unwrap();
    assert_eq!(repeated, second);
    let empty = store
        .publish(&[], Some(repeated), "legacy-source/1", true)
        .unwrap();
    assert_eq!(store.current().unwrap(), Some(empty));
    for row in reference["scans"].as_array().unwrap() {
        let found = nodes(
            &store,
            row["snapshot"].as_i64().unwrap(),
            NodeFilter::default(),
        );
        assert_eq!(serde_json::to_value(&found).unwrap(), row["nodes"]);
        let props = found
            .iter()
            .map(|n| serde_json::to_value(store.properties(n).unwrap()).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(serde_json::to_value(props).unwrap(), row["properties"]);
    }
    for row in reference["queries"].as_array().unwrap() {
        let args = &row["args"];
        let filter = NodeFilter {
            kind: args["kind"].as_str().map(Into::into),
            name: args["name"].as_str().map(Into::into),
            reference: args["reference"].as_bool().unwrap_or(false),
            ..Default::default()
        };
        assert_eq!(
            serde_json::to_value(nodes(&store, first, filter)).unwrap(),
            row["nodes"]
        );
    }
    let snapshots = store
        .connection()
        .prepare(
            "SELECT snapshot_id,manifest,profile,coverage FROM k2_snapshots ORDER BY snapshot_id",
        )
        .unwrap()
        .query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, i64>(3)?,
            ))
        })
        .unwrap()
        .collect::<rusqlite::Result<Vec<_>>>()
        .unwrap();
    assert_eq!(
        serde_json::to_value(snapshots).unwrap(),
        reference["snapshots"]
    );
    let function = nodes(
        &store,
        first,
        NodeFilter {
            kind: Some("CALLABLE".into()),
            ..Default::default()
        },
    )
    .pop()
    .unwrap();
    let props = store.properties(&function).unwrap();
    assert_eq!(
        props["big"],
        Scalar::Int("1208925819614629174706176".into())
    );
    assert!(matches!(props["negative_zero"],Scalar::Float(v)if v==0.&&v.is_sign_negative()));
    assert_eq!(props["enabled"], Scalar::Bool(true));
    assert_eq!(props["nothing"], Scalar::Null);
    assert!(!props.contains_key("nested"));
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("python.sqlite");
    fs::write(
        &path,
        STANDARD
            .decode(reference["database_b64"].as_str().unwrap())
            .unwrap(),
    )
    .unwrap();
    let mut old = StructuralStore::open(Some(&path), None).unwrap();
    for row in reference["units"].as_array().unwrap() {
        compare_unit(&mut old, row["unit"].as_i64().unwrap(), row);
    }
    old.close().unwrap();
}
fn compare_unit(store: &mut StructuralStore, unit: i64, row: &Value) {
    let loaded = store.load_unit(unit).unwrap();
    assert_eq!(
        loaded
            .entities
            .iter()
            .find(|(k, _)| k == "fn")
            .unwrap()
            .1
            .attrs["big"]
            .get(),
        "1208925819614629174706176"
    );
    assert_eq!(serde_json::to_value(&loaded).unwrap(), row["loaded"]);
    assert_eq!(
        serde_json::to_value(store.program(unit).unwrap()).unwrap(),
        row["program"]
    );
    assert_eq!(
        serde_json::to_value(store.operations(unit, None).unwrap()).unwrap(),
        row["operations"]
    );
    assert_eq!(
        serde_json::to_value(store.operations(unit, Some("fn")).unwrap()).unwrap(),
        row["owned_operations"]
    );
}
#[test]
fn publication_conflicts_retention_and_invalid_projection_never_publish_partial_state() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("s.sqlite");
    let ir = inputs();
    let mut writer = StructuralStore::open(Some(&path), None).unwrap();
    let a = writer.put_unit("a", &ir[0], "h", "v", true).unwrap();
    let first = writer.publish(&[a], None, "base", true).unwrap();
    let b = writer.put_unit("b", &ir[1], "h2", "v", true).unwrap();
    assert!(writer.publish(&[a, b], Some(first), "base", true).is_err());
    assert_eq!(writer.current().unwrap(), Some(first));
    assert!(writer.publish(&[a, a], Some(first), "base", true).is_err());
    assert!(writer.publish(&[99999], Some(first), "base", true).is_err());
    assert_eq!(writer.current().unwrap(), Some(first));
    writer.limit_bytes = Some(writer.allocated_bytes().unwrap() - 1);
    assert!(matches!(
        writer.put_unit("budget", &ir[2], "h", "v", true),
        Err(StructuralError::Retention)
    ));
    assert_eq!(writer.find_unit("budget").unwrap(), None);
    writer.limit_bytes = None;
    let mut bad = ir[0].clone();
    bad.operations[0].parent = Some(bad.operations[0].id.clone());
    assert!(
        writer
            .put_unit("invalid-forest", &bad, "h", "v", true)
            .is_err()
    );
    assert_eq!(writer.find_unit("invalid-forest").unwrap(), None);
    let gate = Arc::new(Barrier::new(2));
    let mut tasks = Vec::new();
    for profile in ["left", "right"] {
        let path = path.clone();
        let gate = gate.clone();
        tasks.push(thread::spawn(move || {
            let mut store = StructuralStore::open(Some(&path), None).unwrap();
            gate.wait();
            store.publish(&[a], Some(first), profile, true)
        }));
    }
    let results = tasks
        .into_iter()
        .map(|t| t.join().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(results.iter().filter(|r| r.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|r| matches!(
                r,
                Err(StructuralError::Invalid("snapshot publication conflict"))
            ))
            .count(),
        1
    );
    for budget in [-1., f64::NAN, f64::INFINITY] {
        let p = temp.path().join("never/s.sqlite");
        assert!(StructuralStore::open(Some(&p), Some(budget)).is_err());
        assert!(!p.parent().unwrap().exists());
    }
    let p = temp.path().join("ephemeral/s.sqlite");
    let mut ephemeral = StructuralStore::open(Some(&p), Some(0.)).unwrap();
    assert!(ephemeral.path().is_none());
    ephemeral.put_unit("work", &ir[0], "h", "v", true).unwrap();
    assert!(!p.parent().unwrap().exists());
}
#[test]
fn active_snapshots_and_acquisitions_are_protected_until_lease_expiry() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("s.sqlite");
    let ir = inputs();
    let mut writer = StructuralStore::open(Some(&path), None).unwrap();
    let a = writer.put_unit("a", &ir[0], "h", "v", true).unwrap();
    let first = writer.publish(&[a], None, "p", true).unwrap();
    let mut reader = StructuralStore::open(Some(&path), None).unwrap();
    let b = writer.put_unit("b", &ir[1], "h", "v", true).unwrap();
    let second = writer.publish(&[b], Some(first), "p", true).unwrap();
    let c = writer.put_unit("c", &ir[2], "h", "v", true).unwrap();
    let third = writer.publish(&[c], Some(second), "p", true).unwrap();
    assert!(writer.collect(1, &[]).unwrap().deferred);
    reader.pin_snapshot(first).unwrap();
    {
        let mut scan = reader.prepare_scan(first, NodeFilter::default()).unwrap();
        let mut rows = scan.rows().unwrap();
        assert!(rows.next().unwrap().is_ok());
        reader.renew(true).unwrap();
        assert_eq!(rows.collect::<Result<Vec<_>, _>>().unwrap().len(), 5);
    }
    let result = writer.collect(1, &[]).unwrap();
    assert!(!result.deferred);
    assert_eq!(result.snapshots, 1);
    assert_eq!(nodes(&reader, first, NodeFilter::default()).len(), 6);
    writer.close().unwrap();
    let mut collector = StructuralStore::open(Some(&path), None).unwrap();
    collector.pin_snapshot(third).unwrap();
    assert!(!collector.collect(1, &[]).unwrap().deferred);
    assert_eq!(nodes(&reader, first, NodeFilter::default()).len(), 6);
    reader
        .connection()
        .execute(
            "UPDATE k2_leases SET expires_ns=0 WHERE lease_id=?1",
            [reader.lease_id().unwrap()],
        )
        .unwrap();
    assert!(matches!(reader.renew(true), Err(StructuralError::Expired)));
    let collected = collector.collect(1, &[]).unwrap();
    assert_eq!(collected.snapshots, 1);
    assert!(matches!(
        reader.prepare_scan(first, NodeFilter::default()),
        Err(StructuralError::Missing(_))
    ));
    assert_eq!(nodes(&collector, third, NodeFilter::default()).len(), 6);
}
#[test]
fn lazy_ast_and_operations_fallback_preserve_data_and_scans_remain_snapshot_bound() {
    let mut store = StructuralStore::open(None, None).unwrap();
    let ir = inputs();
    let unit = store.put_unit("lazy", &ir[0], "h", "v", false).unwrap();
    let snapshot = store.publish(&[unit], None, "p", true).unwrap();
    store.limit_bytes = Some(store.allocated_bytes().unwrap() - 1);
    assert_eq!(
        serde_json::to_value(store.program(unit).unwrap()).unwrap(),
        reference()["units"][0]["program"]
    );
    let projected: i64 = store
        .connection()
        .query_row("SELECT count(*) FROM k2_ast_units", [], |r| r.get(0))
        .unwrap();
    assert_eq!(projected, 0);
    store
        .connection()
        .execute("DELETE FROM k2_operation_units WHERE unit_id=?1", [unit])
        .unwrap();
    let fallback = store.operations(unit, Some("fn")).unwrap();
    assert!(fallback.facts.is_empty());
    assert_eq!(fallback.operations.len(), 2);
    assert!(
        fallback
            .entities
            .iter()
            .all(|(_, e)| ["CALL", "VALUE"].contains(&e.kind.as_str()))
    );
    let projected: i64 = store
        .connection()
        .query_row("SELECT count(*) FROM k2_operation_units", [], |r| r.get(0))
        .unwrap();
    assert_eq!(projected, 0);
    store.limit_bytes = None;
    compare_unit(&mut store, unit, &reference()["units"][0]);
    store
        .connection()
        .execute(
            "UPDATE k2_nodes SET name=NULL WHERE unit_id=?1 AND local_id='module'",
            [unit],
        )
        .unwrap();
    let filter = NodeFilter {
        name: Some("compute".into()),
        ..Default::default()
    };
    store.reset_scanned();
    let fast = nodes(&store, snapshot, filter.clone());
    assert_eq!(store.scanned(), 2);
    store.reset_scanned();
    let slow = nodes(
        &store,
        snapshot,
        NodeFilter {
            reference: true,
            ..filter
        },
    );
    assert_eq!(store.scanned(), 6);
    assert_eq!(
        fast.iter()
            .map(|n| n.id)
            .collect::<std::collections::BTreeSet<_>>(),
        slow.iter().map(|n| n.id).collect()
    );
    assert_eq!(fast.len(), 2);
    let owner = nodes(
        &store,
        snapshot,
        NodeFilter {
            kind: Some("CALLABLE".into()),
            ..Default::default()
        },
    )
    .pop()
    .unwrap();
    let owned = nodes(
        &store,
        snapshot,
        NodeFilter {
            owner: Some((owner.unit, owner.local_id)),
            ..Default::default()
        },
    );
    assert_eq!(owned.len(), 3);
    assert!(matches!(
        store.prepare_scan(99999, NodeFilter::default()),
        Err(StructuralError::Missing(_))
    ));
    let table: &str = "k2_nodes";
    let plan=store.connection().prepare(&format!("EXPLAIN QUERY PLAN SELECT n.node_id FROM {table} n JOIN k2_snapshot_units m ON m.unit_id=n.unit_id WHERE m.snapshot_id=?1 AND n.kind=?2")).unwrap().query_map(params![snapshot,"CALL"],|r|r.get::<_,String>(3)).unwrap().collect::<rusqlite::Result<Vec<_>>>().unwrap();
    assert!(!plan.is_empty());
    let mut bulk = ir[0].clone();
    bulk.path = "bulk.py".into();
    bulk.entities.clear();
    bulk.operations.clear();
    bulk.facts.clear();
    for i in 0..7500 {
        let id = format!("entity{i}");
        let mut attrs = ken_program::Attributes::new();
        for (key, value) in [
            ("start_byte", (i * 2).to_string()),
            ("end_byte", (i * 2 + 1).to_string()),
            ("native_kind", "\"call\"".into()),
        ] {
            attrs.insert(key.into(), RawValue::from_string(value).unwrap());
        }
        bulk.entities.push((
            id.clone(),
            ken_program::Entity {
                id,
                kind: "CALL".into(),
                name: String::new(),
                path: bulk.path.clone(),
                line: i + 1,
                end_line: i + 1,
                attrs,
            },
        ));
        bulk.operations.push(ken_program::Operation {
            id: format!("op{i}"),
            kind: "CALL".into(),
            native_kind: "call".into(),
            parent: None,
            role: "body".into(),
            start: i * 2,
            end: i * 2 + 1,
            line: i + 1,
            owner: "fn".into(),
            attrs: Default::default(),
        });
    }
    let mut repeated = bulk.operations[0].clone();
    repeated.id = "z-duplicate".into();
    repeated.line = 99999;
    repeated.owner = "replacement".into();
    bulk.operations.push(repeated);
    let unit = store.put_unit("bulk", &bulk, "h", "v", false).unwrap();
    let loaded = store.load_unit(unit).unwrap();
    assert_eq!(loaded.entities.len(), 7500);
    assert_eq!(loaded.entities[7499].0, "entity7499");
    let loaded = store.operations(unit, None).unwrap();
    assert_eq!(loaded.entities.len(), 7500);
    assert_eq!(loaded.entities[0].0, "entity0");
    assert_eq!(loaded.entities[0].1.line, 99999);
    assert_eq!(loaded.entities[7499].0, "entity7499");
}
