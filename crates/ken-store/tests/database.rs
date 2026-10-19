use ken_store::ProjectDatabase;
use rusqlite::{Connection, types::ValueRef};
use serde_json::{Map, Value, json};

fn fixture() -> (tempfile::TempDir, ProjectDatabase) {
    let root = tempfile::tempdir().unwrap();
    let mut db = ProjectDatabase::open(&root.path().join("ken.db")).unwrap();
    db.initialize().unwrap();
    (root, db)
}

fn file(conn: &Connection, name: &str, embedding: Option<&[u8]>, slot: Option<i64>) -> i64 {
    conn.execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at,embedding,vec_slot) VALUES(?1,x'00',0,0,?2,?3)",
        rusqlite::params![name, embedding, slot]).unwrap();
    conn.last_insert_rowid()
}

fn rows(conn: &Connection, sql: &str) -> Vec<Vec<Value>> {
    let mut statement = conn.prepare(sql).unwrap();
    statement
        .query_map([], |row| {
            (0..row.as_ref().column_count())
                .map(|i| {
                    Ok(match row.get_ref(i)? {
                        ValueRef::Null => Value::Null,
                        ValueRef::Integer(v) => json!(v),
                        ValueRef::Real(v) => json!(v),
                        ValueRef::Text(v) => json!(std::str::from_utf8(v).unwrap()),
                        ValueRef::Blob(_) => panic!("unexpected binary schema attribute"),
                    })
                })
                .collect::<rusqlite::Result<Vec<_>>>()
        })
        .unwrap()
        .collect::<rusqlite::Result<Vec<_>>>()
        .unwrap()
}

fn schema_snapshot(conn: &Connection) -> Value {
    let objects = rows(
        conn,
        "SELECT type,name,tbl_name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name",
    );
    let mut tables = Map::new();
    for object in &objects {
        if object[0] != "table" {
            continue;
        }
        let name = object[1].as_str().unwrap();
        let quoted = serde_json::to_string(name).unwrap();
        let mut indexes = Vec::new();
        for index in rows(conn, &format!("PRAGMA index_list({quoted})")) {
            let label = index[1].as_str().unwrap();
            indexes.push(json!({"name": label,"unique":index[2],"origin":index[3],"partial":index[4],
                "columns":rows(conn,&format!("PRAGMA index_xinfo({})",serde_json::to_string(label).unwrap()))}));
        }
        indexes.sort_by(|a, b| a["name"].as_str().cmp(&b["name"].as_str()));
        tables.insert(name.into(), json!({"columns":rows(conn,&format!("PRAGMA table_info({quoted})")),
            "indexes":indexes,"foreign_keys":rows(conn,&format!("PRAGMA foreign_key_list({quoted})"))}));
    }
    json!({"objects":objects,"tables":tables})
}

fn original_schema(case_id: &str) -> Value {
    let document: Value = serde_json::from_str(include_str!(
        "../../../docs/validation/rust-migration-2026-10-19/m2-storage/reference.json"
    ))
    .unwrap();
    document["oracles"][0]["results"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["id"] == case_id)
        .unwrap()["output"]["schema"]
        .clone()
}

#[test]
fn fresh_and_legacy_schema_preserve_objects_rows_and_cascade_slot_reclamation() {
    for legacy in [false, true] {
        let (_root, mut db) = fixture();
        let fid = file(db.connection(), "é\0fixture.py", None, None);
        db.set_meta("keep", "value").unwrap();
        if legacy {
            for name in [
                "idx_ci_imports_resolution",
                "idx_ci_files_vec_slot",
                "idx_ci_symbols_vec_slot",
                "idx_ci_intent_sources_vec_slot",
            ] {
                db.connection()
                    .execute_batch(&format!("DROP INDEX {name}"))
                    .unwrap();
            }
            for name in [
                "trg_ci_files_free_slot",
                "trg_ci_symbols_free_slot",
                "trg_ci_intent_free_slot",
            ] {
                db.connection()
                    .execute_batch(&format!("DROP TRIGGER {name}"))
                    .unwrap();
            }
            for (table, column) in [
                ("ci_imports", "resolution"),
                ("ci_files", "vec_slot"),
                ("ci_symbols", "vec_slot"),
                ("ci_intent_sources", "vec_slot"),
                ("ci_passages", "implementation_start_line"),
            ] {
                db.connection()
                    .execute_batch(&format!("ALTER TABLE {table} DROP COLUMN {column}"))
                    .unwrap();
            }
        }
        db.initialize().unwrap();
        let snapshot = schema_snapshot(db.connection());
        assert_eq!(
            snapshot,
            original_schema(if legacy {
                "schema-legacy"
            } else {
                "schema-fresh"
            })
        );
        db.initialize().unwrap();
        assert_eq!(snapshot, schema_snapshot(db.connection()));
        assert_eq!(db.get_meta("keep").unwrap().as_deref(), Some("value"));
        assert_eq!(
            db.connection()
                .query_row("SELECT path FROM ci_files WHERE id=?1", [fid], |r| r
                    .get::<_, String>(0))
                .unwrap(),
            "é\0fixture.py"
        );
        for (key, want) in [
            ("synchronous", 1),
            ("foreign_keys", 1),
            ("busy_timeout", 5000),
        ] {
            assert_eq!(
                db.connection()
                    .query_row(&format!("PRAGMA {key}"), [], |r| r.get::<_, i64>(0))
                    .unwrap(),
                want
            );
        }
        assert_eq!(
            db.connection()
                .query_row("PRAGMA journal_mode", [], |r| r.get::<_, String>(0))
                .unwrap(),
            "wal"
        );
        db.connection()
            .execute("UPDATE ci_files SET vec_slot=3 WHERE id=?1", [fid])
            .unwrap();
        for (name, slot) in [("f", 10), ("g", 11)] {
            db.connection().execute("INSERT INTO ci_symbols(file_id,kind,name,line_start,line_end,vec_slot) VALUES(?1,'function',?2,1,2,?3)",
                rusqlite::params![fid,name,slot]).unwrap();
        }
        db.connection().execute("INSERT INTO ci_intent_sources(file_id,source_kind,text,updated_at,vec_slot) VALUES(?1,'module_docstring','text',0,7)",[fid]).unwrap();
        db.connection()
            .execute("DELETE FROM ci_files WHERE id=?1", [fid])
            .unwrap();
        let free = db
            .connection()
            .prepare("SELECT space,slot FROM ci_vec_free ORDER BY space,slot")
            .unwrap()
            .query_map([], |r| {
                Ok(json!([r.get::<_, String>(0)?, r.get::<_, i64>(1)?]))
            })
            .unwrap()
            .collect::<rusqlite::Result<Vec<_>>>()
            .unwrap();
        assert_eq!(
            free,
            vec![
                json!(["ci_files", 3]),
                json!(["ci_intent_sources", 7]),
                json!(["ci_symbols", 10]),
                json!(["ci_symbols", 11])
            ]
        );
        assert_eq!(
            db.connection()
                .query_row("SELECT count(*) FROM ci_symbols", [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            0
        );
    }
}

#[test]
fn unique_slots_allow_multiple_nulls_and_metadata_preserves_raw_strings() {
    let (_root, db) = fixture();
    file(db.connection(), "a.py", None, Some(7));
    assert!(db.connection().execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at,vec_slot) VALUES('b.py',x'00',0,0,7)",[]).is_err());
    file(db.connection(), "n1.py", None, None);
    file(db.connection(), "n2.py", None, None);
    assert_eq!(db.get_meta("absent").unwrap(), None);
    for value in ["", "é/設定", "\0middle\0", "17"] {
        db.set_meta("key", value).unwrap();
        assert_eq!(db.get_meta("key").unwrap().as_deref(), Some(value));
    }
}

#[test]
fn initialization_reports_sql_errors_and_rolls_back_partial_schema() {
    for query_only in [false, true] {
        let root = tempfile::tempdir().unwrap();
        let mut db = ProjectDatabase::open(&root.path().join("bad.db")).unwrap();
        if query_only {
            db.connection()
                .execute_batch("PRAGMA query_only=ON")
                .unwrap();
        } else {
            db.connection()
                .execute_batch("CREATE TABLE ci_files(id INTEGER PRIMARY KEY,path TEXT)")
                .unwrap();
        }
        assert!(db.initialize().is_err());
        assert_eq!(
            db.connection()
                .query_row(
                    "SELECT count(*) FROM sqlite_master WHERE name='meta'",
                    [],
                    |r| r.get::<_, i64>(0)
                )
                .unwrap(),
            0
        );
        assert!(db.connection().is_autocommit());
    }
}
