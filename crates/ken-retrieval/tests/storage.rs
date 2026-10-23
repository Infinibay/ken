use ken_retrieval::{
    Passage, PassagePolicy,
    storage::{load_passage_map, replace_file_passages, source_extractor_current},
};
use ken_store::ProjectDatabase;
use ken_syntax::ParsedSymbol;
use rusqlite::{Connection, params, types::ValueRef};
use serde::Deserialize;
use serde_json::{Value, json};
#[derive(Deserialize)]
struct Fixture {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Input,
    steps: Vec<Step>,
}
#[derive(Deserialize)]
struct Input {
    path: String,
    language: String,
    symbols: Vec<ParsedSymbol>,
    passages: Vec<Passage>,
    source_hash: String,
    max_tokens: usize,
    tokenizer_version: String,
}
#[derive(Deserialize)]
struct Step {
    action: String,
    ids: Option<Vec<i64>>,
    error: Option<Value>,
    tables: Value,
    loaded: Vec<(i64, Passage)>,
}
fn fixture() -> Fixture {
    serde_json::from_str(include_str!("fixtures/storage-reference.json")).unwrap()
}
fn database(input: &Input) -> (tempfile::TempDir, ProjectDatabase) {
    let dir = tempfile::tempdir().unwrap();
    let mut db = ProjectDatabase::open(&dir.path().join("index.db")).unwrap();
    db.initialize().unwrap();
    db.connection().execute("INSERT INTO ci_files(path,language,content_hash,mtime,indexed_at)VALUES(?1,?2,x'00',0,0)",params![input.path,input.language]).unwrap();
    for s in &input.symbols {
        db.connection().execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end,docstring)VALUES(1,?1,?2,?3,?4,?5,?6)",params![s.kind,s.name,s.qualname,s.line_start as i64,s.line_end as i64,s.docstring]).unwrap();
    }
    (dir, db)
}
fn snapshot(conn: &Connection) -> Value {
    let mut map = serde_json::Map::new();
    for (table, order) in [
        ("ci_passages", "id"),
        ("ci_passage_terms", "passage_id,field,term"),
        ("ci_passage_lengths", "passage_id,field"),
        ("ci_retrieval_files", "file_id"),
    ] {
        let mut statement = conn
            .prepare(&format!("SELECT * FROM {table} ORDER BY {order}"))
            .unwrap();
        let rows = statement
            .query_map([], |row| {
                (0..row.as_ref().column_count())
                    .map(|i| {
                        Ok(match row.get_ref(i)? {
                            ValueRef::Null => Value::Null,
                            ValueRef::Integer(v) => json!(v),
                            ValueRef::Real(v) => json!(v),
                            ValueRef::Text(v) => json!(std::str::from_utf8(v).unwrap()),
                            ValueRef::Blob(_) => panic!("unexpected blob"),
                        })
                    })
                    .collect::<rusqlite::Result<Vec<_>>>()
            })
            .unwrap()
            .collect::<rusqlite::Result<Vec<_>>>()
            .unwrap();
        map.insert(table.into(), json!(rows));
    }
    Value::Object(map)
}
#[test]
fn replace_edit_delete_matches_original() {
    let reference = fixture();
    assert_eq!(reference.cases.len(), 26);
    for c in reference.cases {
        let (_dir, mut db) = database(&c.input);
        let policy = PassagePolicy::new(c.input.max_tokens, c.input.tokenizer_version).unwrap();
        for step in c.steps {
            let tx = db.immediate().unwrap();
            let result = if step.action == "delete" {
                tx.connection()
                    .execute("DELETE FROM ci_files WHERE id=1", [])
                    .unwrap();
                Ok(vec![])
            } else {
                replace_file_passages(
                    &tx,
                    1,
                    &c.input.passages,
                    Some(&c.input.source_hash),
                    &policy,
                )
            };
            if step.error.is_some() {
                assert!(result.is_err(), "{} {}", c.id, step.action);
                drop(tx)
            } else {
                assert_eq!(
                    result.unwrap(),
                    step.ids.unwrap(),
                    "{} {}",
                    c.id,
                    step.action
                );
                tx.commit().unwrap();
            }
            assert_eq!(
                snapshot(db.connection()),
                step.tables,
                "{} {} rows",
                c.id,
                step.action
            );
            assert_eq!(
                load_passage_map(db.connection(), None).unwrap(),
                step.loaded,
                "{} {} loaded",
                c.id,
                step.action
            );
        }
    }
}
#[test]
fn missing_symbol_and_non_scalar_docs_roll_back() {
    let c = fixture()
        .cases
        .into_iter()
        .find(|c| !c.input.symbols.is_empty() && c.steps[0].error.is_none())
        .unwrap();
    let (_dir, mut db) = database(&c.input);
    let policy = PassagePolicy::default();
    let tx = db.immediate().unwrap();
    replace_file_passages(
        &tx,
        1,
        &c.input.passages,
        Some(&c.input.source_hash),
        &policy,
    )
    .unwrap();
    tx.commit().unwrap();
    let before = snapshot(db.connection());
    for mode in 0..3 {
        let mut invalid = c.input.passages.clone();
        if mode == 0 {
            invalid[0].entity.qualname = Some("nonexistent".into());
        } else if mode == 1 {
            invalid[0].fields.documentation =
                ken_text::PythonText::from_codepoints(vec![0xd800]).unwrap();
        } else {
            invalid[0].source_hash = "mixed-generation".into();
        }
        let tx = db.immediate().unwrap();
        assert!(
            replace_file_passages(&tx, 1, &invalid, Some(&c.input.source_hash), &policy).is_err()
        );
        drop(tx);
        assert_eq!(snapshot(db.connection()), before);
    }
}
#[test]
fn stale_policy_blocks_load() {
    let c = fixture()
        .cases
        .into_iter()
        .find(|c| c.steps[0].error.is_none())
        .unwrap();
    let (_dir, mut db) = database(&c.input);
    let tx = db.immediate().unwrap();
    replace_file_passages(
        &tx,
        1,
        &c.input.passages,
        Some(&c.input.source_hash),
        &PassagePolicy::default(),
    )
    .unwrap();
    tx.commit().unwrap();
    assert!(source_extractor_current(db.connection()).unwrap());
    db.connection()
        .execute("UPDATE ci_retrieval_files SET extractor_version=0", [])
        .unwrap();
    assert!(!source_extractor_current(db.connection()).unwrap());
    assert!(load_passage_map(db.connection(), None).is_err());
    assert!(
        load_passage_map(db.connection(), Some(&[]))
            .unwrap()
            .is_empty()
    );
}
