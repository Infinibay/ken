use ken_models::{EncoderSpec, LegacyRuntimeIdentity, RetrievalProfile};
use ken_retrieval::encoder::EncoderLoader;
use ken_retrieval::{
    DocumentEncoder, LexicalCounter, Passage, PassagePolicy, Result, TokenCounter,
    embedding_store::{load_vectors, reclaim_retired, retrieval_snapshot},
    projections::{ProjectionIndexer, View, index_embeddings},
    storage::{generation, load_passage_map, replace_file_passages},
};
use ken_store::ProjectDatabase;
use ken_syntax::ParsedSymbol;
use rusqlite::{Connection, params, types::ValueRef};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    cell::{Cell, RefCell},
    rc::Rc,
};
#[derive(Deserialize)]
struct Fixture {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Input,
    result: Expected,
}
#[derive(Deserialize)]
struct Input {
    profile: Value,
    passages: Vec<Passage>,
    symbols: Vec<ParsedSymbol>,
    path: String,
    language: Option<String>,
    source_hash: String,
    counter: String,
}
#[derive(Deserialize)]
struct Expected {
    ids: Vec<i64>,
    views: Value,
    tables: Value,
    calls: Vec<Vec<String>>,
    policy: (usize, String, usize),
    fingerprint: String,
    stored_profile: String,
}
fn fixture() -> Fixture {
    serde_json::from_str(include_str!("fixtures/projection-reference.json")).unwrap()
}
fn runtime() -> LegacyRuntimeIdentity {
    let value: Value = serde_json::from_str(include_str!(
        "../../ken-models/tests/fixtures/profile-identity/macos.json"
    ))
    .unwrap();
    LegacyRuntimeIdentity::from_json(&value["legacy_runtime"].to_string()).unwrap()
}
struct Encoder {
    calls: RefCell<Vec<Vec<String>>>,
    characters: bool,
    fail: Cell<bool>,
    action: RefCell<Option<Box<dyn Fn()>>>,
}
impl DocumentEncoder for Encoder {
    fn dim(&self) -> Result<usize> {
        Ok(3)
    }
    fn token_count(&self, text: &str) -> Result<usize> {
        if self.characters {
            Ok(text.chars().count())
        } else {
            LexicalCounter.count(text)
        }
    }
    fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        if self.fail.get() {
            return Err(ken_retrieval::RetrievalError::Invalid(
                "encoding unavailable".into(),
            ));
        }
        self.calls
            .borrow_mut()
            .push(texts.iter().map(|s| s.to_string()).collect());
        if let Some(action) = self.action.borrow_mut().take() {
            action();
        }
        Ok(texts
            .iter()
            .map(|s| {
                let b = s.as_bytes();
                let mut v = vec![
                    (b.iter().map(|&n| n as u64).sum::<u64>() % 31 + 1) as f32,
                    (b.len() % 23 + 1) as f32,
                    (b.iter()
                        .enumerate()
                        .map(|(i, &n)| (i + 1) as u64 * n as u64)
                        .sum::<u64>()
                        % 19
                        + 1) as f32,
                ];
                let norm = v.iter().map(|n| n * n).sum::<f32>().sqrt();
                for n in &mut v {
                    *n /= norm
                }
                v
            })
            .collect())
    }
}
struct Loader {
    encoder: Rc<Encoder>,
    loads: Cell<usize>,
}
impl EncoderLoader for Loader {
    fn load(&self, _: &EncoderSpec) -> Result<Rc<dyn DocumentEncoder>> {
        self.loads.set(self.loads.get() + 1);
        Ok(self.encoder.clone())
    }
}
fn loader(characters: bool) -> Rc<Loader> {
    Rc::new(Loader {
        encoder: Rc::new(Encoder {
            calls: RefCell::new(vec![]),
            characters,
            fail: Cell::new(false),
            action: RefCell::new(None),
        }),
        loads: Cell::new(0),
    })
}
fn database(c: &Case) -> (tempfile::TempDir, ProjectDatabase) {
    let dir = tempfile::tempdir().unwrap();
    let mut db = ProjectDatabase::open(&dir.path().join("index.db")).unwrap();
    db.initialize().unwrap();
    let conn = db.connection();
    conn.execute(
        "INSERT INTO ci_files(path,language,content_hash,mtime,indexed_at)VALUES(?1,?2,x'00',0,0)",
        params![c.input.path, c.input.language],
    )
    .unwrap();
    for s in &c.input.symbols {
        conn.execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end,docstring)VALUES(1,?1,?2,?3,?4,?5,?6)",params![s.kind,s.name,s.qualname,s.line_start as i64,s.line_end as i64,s.docstring]).unwrap();
    }
    db.set_meta("retrieval_profile", &c.result.stored_profile)
        .unwrap();
    db.set_meta("retrieval_profile_fingerprint", &c.result.fingerprint)
        .unwrap();
    (dir, db)
}
fn tables(conn: &Connection) -> Value {
    let mut out = serde_json::Map::new();
    for (table, order) in [
        ("ci_retrieval_embeddings", "id"),
        ("ci_passage_vectors", "passage_id,view"),
    ] {
        let mut query = conn
            .prepare(&format!("SELECT * FROM {table} ORDER BY {order}"))
            .unwrap();
        let rows=query.query_map([],|r|(0..r.as_ref().column_count()).map(|i|Ok(match r.get_ref(i)?{ValueRef::Null=>Value::Null,ValueRef::Integer(v)=>json!(v),ValueRef::Real(v)=>json!(v),ValueRef::Text(v)=>json!(std::str::from_utf8(v).unwrap()),ValueRef::Blob(v)=>json!({"blob_hex":v.iter().map(|b|format!("{b:02x}")).collect::<String>()})})).collect::<rusqlite::Result<Vec<_>>>()).unwrap().collect::<rusqlite::Result<Vec<_>>>().unwrap();
        out.insert(table.into(), json!(rows));
    }
    Value::Object(out)
}
#[test]
fn two_views_match_original() {
    let f = fixture();
    assert_eq!(f.cases.len(), 93);
    for c in f.cases {
        let (_dir, mut db) = database(&c);
        let load = loader(c.input.counter == "characters");
        let profile = RetrievalProfile::from_json(&c.input.profile.to_string()).unwrap();
        let indexer =
            ProjectionIndexer::new(db.connection(), profile, runtime(), load.clone()).unwrap();
        let policy = indexer.policy().unwrap();
        assert_eq!(
            (8, policy.tokenizer_version.clone(), policy.max_tokens),
            c.result.policy
        );
        assert_eq!(load.loads.get(), 0);
        let prepared = indexer
            .prepare(db.connection(), &[&c.input.passages, &c.input.passages])
            .unwrap();
        assert_eq!(prepared.len(), 2);
        for view in [View::Identity, View::Behavior] {
            let p = &prepared[0].views[&view];
            let e = &c.result.views[view.as_str()];
            assert_eq!(
                json!(p.texts),
                e["texts"],
                "{} {} texts",
                c.id,
                view.as_str()
            );
            let expected_vectors: Vec<Vec<f32>> =
                serde_json::from_value(e["vectors"].clone()).unwrap();
            assert_eq!(
                p.vectors,
                expected_vectors,
                "{} {} vectors",
                c.id,
                view.as_str()
            );
            assert_eq!(p.revision, e["revision"].as_str().unwrap());
        }
        let tx = db.immediate().unwrap();
        let ids = replace_file_passages(
            &tx,
            1,
            &c.input.passages,
            Some(&c.input.source_hash),
            &PassagePolicy::default(),
        )
        .unwrap();
        assert_eq!(ids, c.result.ids);
        prepared[0].publish(&tx, &ids).unwrap();
        tx.commit().unwrap();
        indexer
            .prepare(db.connection(), &[&c.input.passages])
            .unwrap();
        assert_eq!(
            *load.encoder.calls.borrow(),
            c.result.calls,
            "{} encode calls",
            c.id
        );
        assert_artifacts(tables(db.connection()), c.result.tables, &c.id);
    }
}
fn first() -> Case {
    fixture()
        .cases
        .into_iter()
        .find(|c| !c.input.passages.is_empty() && c.input.counter == "lexical")
        .unwrap()
}
fn populate(db: &mut ProjectDatabase, c: &Case, load: Rc<Loader>) -> ProjectionIndexer {
    let indexer = ProjectionIndexer::new(
        db.connection(),
        RetrievalProfile::from_json(&c.input.profile.to_string()).unwrap(),
        runtime(),
        load,
    )
    .unwrap();
    let p = indexer
        .prepare(db.connection(), &[&c.input.passages])
        .unwrap();
    let tx = db.immediate().unwrap();
    let ids = replace_file_passages(
        &tx,
        1,
        &c.input.passages,
        Some(&c.input.source_hash),
        &PassagePolicy::default(),
    )
    .unwrap();
    p[0].publish(&tx, &ids).unwrap();
    tx.commit().unwrap();
    indexer
}
#[test]
fn unchanged_texts_are_not_encoded_again() {
    let c = first();
    let (_dir, mut db) = database(&c);
    let load = loader(false);
    let indexer = populate(&mut db, &c, load.clone());
    let calls = load.encoder.calls.borrow().len();
    indexer
        .prepare(db.connection(), &[&c.input.passages])
        .unwrap();
    assert_eq!(load.encoder.calls.borrow().len(), calls);
    let current_generation = generation(db.connection()).unwrap();
    index_embeddings(&mut db, indexer.profile.clone(), runtime(), load.clone()).unwrap();
    assert_eq!(generation(db.connection()).unwrap(), current_generation);
    assert_eq!(load.encoder.calls.borrow().len(), calls);
    let mut changed = c.input.passages.clone();
    changed[0].fields.body = "changed body cookie".into();
    let prepared = indexer.prepare(db.connection(), &[&changed]).unwrap();
    let retired: Vec<i64> = db
        .connection()
        .prepare("SELECT id FROM ci_retrieval_embeddings")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .map(|r| r.unwrap())
        .collect();
    db.connection().execute("INSERT INTO ci_retrieval_embeddings(view,model_revision,text_hash,dimension,embedding)VALUES('identity','unrelated','unused',1,x'0000803f')",[]).unwrap();
    let tx = db.immediate().unwrap();
    let ids = replace_file_passages(
        &tx,
        1,
        &changed,
        Some(&c.input.source_hash),
        &PassagePolicy::default(),
    )
    .unwrap();
    prepared[0].publish(&tx, &ids).unwrap();
    assert!(reclaim_retired(&tx, Some(&retired)).unwrap() > 0);
    tx.commit().unwrap();
    assert_eq!(
        db.connection()
            .query_row(
                "SELECT count(*) FROM ci_retrieval_embeddings WHERE model_revision='unrelated'",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        1
    );
}
#[test]
fn nonfinite_second_view_rolls_back() {
    let c = first();
    let (_dir, mut db) = database(&c);
    let load = loader(false);
    let indexer = populate(&mut db, &c, load);
    let before = tables(db.connection());
    let old_passages = load_passage_map(db.connection(), None).unwrap();
    let epoch = generation(db.connection()).unwrap();
    let mut prepared = indexer
        .prepare(db.connection(), &[&c.input.passages])
        .unwrap();
    prepared[0].views.get_mut(&View::Behavior).unwrap().vectors[0][0] = f32::NAN;
    let tx = db.immediate().unwrap();
    let ids = replace_file_passages(
        &tx,
        1,
        &c.input.passages,
        Some(&c.input.source_hash),
        &PassagePolicy::default(),
    )
    .unwrap();
    assert!(prepared[0].publish(&tx, &ids).is_err());
    drop(tx);
    assert_eq!(tables(db.connection()), before);
    assert_eq!(
        load_passage_map(db.connection(), None).unwrap(),
        old_passages
    );
    assert_eq!(generation(db.connection()).unwrap(), epoch);
}
#[test]
fn source_and_profile_races_reject() {
    let c = first();
    let (_dir, mut db) = database(&c);
    let load = loader(false);
    let indexer = populate(&mut db, &c, load.clone());
    let prepared = indexer
        .prepare(db.connection(), &[&c.input.passages])
        .unwrap();
    let before = tables(db.connection());
    db.set_meta("retrieval_profile_fingerprint", "concurrent")
        .unwrap();
    let tx = db.immediate().unwrap();
    assert!(prepared[0].publish(&tx, &c.result.ids).is_err());
    drop(tx);
    assert_eq!(tables(db.connection()), before);
    assert!(ProjectionIndexer::for_active(db.connection(), runtime(), load.clone()).is_err());
    db.set_meta("retrieval_profile_fingerprint", &c.result.fingerprint)
        .unwrap();
    load.encoder.fail.set(true);
    let mut changed = c.input.passages.clone();
    changed[0].fields.body = "new uncached cookie body".into();
    assert!(indexer.prepare(db.connection(), &[&changed]).is_err());
    assert_eq!(tables(db.connection()), before);
}
#[test]
fn old_reader_observes_complete_generation() {
    let c = first();
    let (dir, mut db) = database(&c);
    let load = loader(false);
    let indexer = populate(&mut db, &c, load);
    let reader = ProjectDatabase::open(&dir.path().join("index.db")).unwrap();
    let snapshot = retrieval_snapshot(reader.connection()).unwrap();
    let old = load_passage_map(reader.connection(), None).unwrap();
    let old_vectors = load_vectors(
        reader.connection(),
        "behavior",
        c.result.views["behavior"]["revision"].as_str().unwrap(),
    )
    .unwrap();
    let mut changed = c.input.passages.clone();
    changed[0].fields.body = "new source cookie".into();
    let prepared = indexer.prepare(db.connection(), &[&changed]).unwrap();
    let tx = db.immediate().unwrap();
    let ids = replace_file_passages(
        &tx,
        1,
        &changed,
        Some(&c.input.source_hash),
        &PassagePolicy::default(),
    )
    .unwrap();
    prepared[0].publish(&tx, &ids).unwrap();
    reclaim_retired(&tx, None).unwrap();
    tx.commit().unwrap();
    assert_eq!(load_passage_map(reader.connection(), None).unwrap(), old);
    assert_eq!(
        load_vectors(
            reader.connection(),
            "behavior",
            c.result.views["behavior"]["revision"].as_str().unwrap()
        )
        .unwrap(),
        old_vectors
    );
    snapshot.finish().unwrap();
    assert_ne!(load_passage_map(reader.connection(), None).unwrap(), old);
}

#[test]
fn source_generation_race_rejects_bulk_projection_publication() {
    let c = first();
    let (dir, mut db) = database(&c);
    let load = loader(false);
    let indexer = populate(&mut db, &c, load.clone());
    db.connection()
        .execute("DELETE FROM ci_passage_vectors WHERE view='behavior'", [])
        .unwrap();
    db.connection()
        .execute(
            "DELETE FROM ci_retrieval_embeddings WHERE view='behavior'",
            [],
        )
        .unwrap();
    let before = tables(db.connection());
    let path = dir.path().join("index.db");
    *load.encoder.action.borrow_mut() = Some(Box::new(move || {
        let db = ProjectDatabase::open(&path).unwrap();
        db.connection()
            .execute(
                "UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='retrieval_generation'",
                [],
            )
            .unwrap();
    }));
    let error = index_embeddings(&mut db, indexer.profile.clone(), runtime(), load).unwrap_err();
    assert!(error.to_string().contains("source changed"));
    assert_eq!(tables(db.connection()), before);
}

fn assert_artifacts(actual: Value, expected: Value, id: &str) {
    let mut actual = actual;
    let mut expected = expected;
    let a = actual["ci_retrieval_embeddings"].as_array_mut().unwrap();
    let e = expected["ci_retrieval_embeddings"].as_array_mut().unwrap();
    assert_eq!(a.len(), e.len(), "{id} artifacts");
    for (a, e) in a.iter_mut().zip(e.iter_mut()) {
        let parse = |v: &Value| {
            let h = v[5]["blob_hex"].as_str().unwrap();
            let b: Vec<u8> = (0..h.len())
                .step_by(2)
                .map(|i| u8::from_str_radix(&h[i..i + 2], 16).unwrap())
                .collect();
            assert_eq!(b.len() % 4, 0);
            b.chunks_exact(4)
                .map(|b| f32::from_le_bytes(b.try_into().unwrap()))
                .collect::<Vec<_>>()
        };
        let av = parse(a);
        let ev = parse(e);
        assert_eq!(av.len(), ev.len());
        for (a, e) in av.iter().zip(&ev) {
            assert!(
                a.is_finite() && e.is_finite() && (*a - *e).abs() <= 1e-6 + 1e-6 * e.abs(),
                "{id} normalized F32 {a} != {e}"
            );
        }
        a[5] = Value::Null;
        e[5] = Value::Null;
    }
    assert_eq!(
        actual, expected,
        "{id} exact artifact metadata/order/link rows"
    );
}
#[test]
fn malformed_cached_vectors_and_dimension_changes_reject() {
    use ken_retrieval::embedding_store::{EmbeddingInput, put_embeddings};
    let c = first();
    let (_dir, mut db) = database(&c);
    let load = loader(false);
    let indexer = populate(&mut db, &c, load);
    let before = tables(db.connection());
    for mutation in [
        "UPDATE ci_retrieval_embeddings SET dimension=dimension+1",
        "UPDATE ci_retrieval_embeddings SET embedding=x'0000c07f'",
        "UPDATE ci_retrieval_embeddings SET embedding=zeroblob(dimension*4)",
    ] {
        let tx = db.immediate().unwrap();
        tx.connection().execute(mutation, []).unwrap();
        assert!(
            indexer
                .prepare(tx.connection(), &[&c.input.passages])
                .is_err()
        );
        drop(tx);
        assert_eq!(tables(db.connection()), before);
    }
    let revision = c.result.views["behavior"]["revision"].as_str().unwrap();
    for vector in [
        vec![],
        vec![0., 0., 0.],
        vec![f32::NAN, 1., 0.],
        vec![1., 0.],
        vec![f32::MAX, 0., 0.],
    ] {
        let tx = db.immediate().unwrap();
        let entries = [EmbeddingInput {
            passage_id: c.result.ids[0],
            text: "changed vector".into(),
            vector,
        }];
        assert!(put_embeddings(&tx, "behavior", revision, &entries).is_err());
        drop(tx);
        assert_eq!(tables(db.connection()), before);
    }
    assert!(load_vectors(db.connection(), "behavior", "different-revision").is_err());
}
