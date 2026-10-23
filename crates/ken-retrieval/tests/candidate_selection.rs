use ken_models::{EncoderSpec, LegacyRuntimeIdentity, RetrievalProfile};
use ken_retrieval::{
    DocumentEncoder, Passage, PassagePolicy, Result,
    dense::DenseView,
    embedding_store::load_vectors,
    encoder::EncoderLoader,
    projections::index_embeddings,
    storage::{load_passage_map, replace_file_passages},
};
use ken_store::ProjectDatabase;
use rusqlite::params;
use serde::Deserialize;
use serde_json::Value;
use std::{
    collections::{BTreeMap, HashSet},
    rc::Rc,
};
#[derive(Deserialize, Clone)]
struct Input {
    passages: Vec<Passage>,
    document_vectors: Vec<(String, Vec<f32>)>,
    fallback_vector: Vec<f32>,
    query_vector: Vec<Value>,
    request: Value,
    #[serde(default = "shared")]
    shared: bool,
    #[serde(default = "shared")]
    prepare: bool,
    #[serde(default = "limit")]
    candidate_limit: usize,
    #[serde(default)]
    sql: Vec<String>,
}
fn shared() -> bool {
    true
}
fn limit() -> usize {
    100
}
fn fixture() -> Value {
    #[derive(Deserialize)]
    struct Header {
        families: BTreeMap<String, Box<serde_json::value::RawValue>>,
    }
    #[cfg(target_os = "macos")]
    let raw = include_str!("fixtures/search-selection-reference.json");
    #[cfg(target_os = "linux")]
    let raw = include_str!("fixtures/search-selection-reference-linux.json");
    let h: Header = serde_json::from_str(raw).unwrap();
    serde_json::from_str(h.families["selection"].get()).unwrap()
}
fn input(value: &Value) -> Input {
    serde_json::from_value(value.clone()).unwrap()
}
fn vector(values: &[Value]) -> Vec<f32> {
    values
        .iter()
        .map(|v| match v.as_str() {
            Some("nan") => f32::NAN,
            Some("inf") => f32::INFINITY,
            _ => v.as_f64().unwrap() as f32,
        })
        .collect()
}
struct Documents(Input);
impl DocumentEncoder for Documents {
    fn dim(&self) -> Result<usize> {
        Ok(self.0.fallback_vector.len())
    }
    fn token_count(&self, text: &str) -> Result<usize> {
        Ok(ken_retrieval::vocabulary::code_tokens(text).len())
    }
    fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        Ok(texts
            .iter()
            .map(|text| {
                self.0
                    .document_vectors
                    .iter()
                    .find(|(word, _)| {
                        text.to_ascii_lowercase()
                            .contains(&word.to_ascii_lowercase())
                    })
                    .map(|(_, v)| v)
                    .unwrap_or(&self.0.fallback_vector)
                    .clone()
            })
            .collect())
    }
}
struct Loader(Rc<dyn DocumentEncoder>);
impl EncoderLoader for Loader {
    fn load(&self, _: &EncoderSpec) -> Result<Rc<dyn DocumentEncoder>> {
        Ok(self.0.clone())
    }
}
fn setup(
    i: &Input,
    legacy: &LegacyRuntimeIdentity,
) -> (tempfile::TempDir, ProjectDatabase, RetrievalProfile) {
    let temp = tempfile::tempdir().unwrap();
    let mut db = ProjectDatabase::open(&temp.path().join("index.db")).unwrap();
    db.initialize().unwrap();
    db.connection().execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at,language)VALUES('client.py',x'00',0,0,'python')",[]).unwrap();
    let mut symbols = HashSet::new();
    for p in &i.passages {
        let token = (
            p.entity.kind.clone(),
            p.entity.qualname.clone(),
            p.entity_span.start_line,
            p.entity_span.end_line,
        );
        if symbols.insert(token) {
            let name = p.entity.qualname.as_ref().unwrap();
            db.connection().execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end)VALUES(1,?1,?2,?3,?4,?5)",params![p.entity.kind,name.rsplit('.').next().unwrap(),name,p.entity_span.start_line as i64,p.entity_span.end_line as i64]).unwrap();
        }
    }
    let tx = db.immediate().unwrap();
    replace_file_passages(
        &tx,
        1,
        &i.passages,
        Some(&"a".repeat(64)),
        &PassagePolicy::default(),
    )
    .unwrap();
    tx.commit().unwrap();
    let spec = serde_json::json!({"model_id":"test/selection","revision":"a".repeat(40),"backend":"provided"});
    let profile = RetrievalProfile::from_json(
        &serde_json::json!({"identity":spec,"behavior":spec,"candidate_limit":i.candidate_limit})
            .to_string(),
    )
    .unwrap();
    if i.prepare && !i.passages.is_empty() {
        index_embeddings(
            &mut db,
            profile.clone(),
            legacy.clone(),
            Rc::new(Loader(Rc::new(Documents(i.clone())))),
        )
        .unwrap();
    }
    for sql in &i.sql {
        db.connection().execute_batch(sql).unwrap();
    }
    (temp, db, profile)
}
#[test]
fn stored_vector_normalization_retains_the_original_owner_cutoff() {
    let family = fixture();
    let legacy = LegacyRuntimeIdentity::from_json(&family["legacy_runtime"].to_string()).unwrap();
    let case = family["cases"].as_array().unwrap().last().unwrap();
    let i = input(&case["input"]);
    let (_temp, db, profile) = setup(&i, &legacy);
    let revision = profile.vector_revision("identity", &legacy).unwrap();
    let dense = DenseView::new(
        load_passage_map(db.connection(), None).unwrap(),
        load_vectors(db.connection(), "identity", &revision).unwrap(),
    )
    .unwrap();
    let actual = dense
        .search(&vector(&i.query_vector), "identity", 1)
        .unwrap();
    let expected = case["result"]["candidates"][0]["entity"]["qualname"]
        .as_str()
        .unwrap();
    assert_eq!(actual[0].entity.qualname.as_deref(), Some(expected));
}
#[derive(Clone, Debug, PartialEq, serde::Serialize, Deserialize)]
struct QueryCall {
    encoder: String,
    query: ken_text::PythonText,
}
struct Queries {
    name: String,
    vector: Vec<f32>,
    calls: Rc<std::cell::RefCell<Vec<QueryCall>>>,
}
impl ken_retrieval::query_encoder::QueryEncoder for Queries {
    fn embed_query(&self, query: &ken_text::PythonText) -> Result<Vec<f32>> {
        self.calls.borrow_mut().push(QueryCall {
            encoder: self.name.clone(),
            query: query.clone(),
        });
        Ok(self.vector.clone())
    }
}
fn compare_candidates(
    mut actual: Vec<ken_retrieval::query::Candidate>,
    mut expected: Vec<ken_retrieval::query::Candidate>,
) {
    assert_eq!(actual.len(), expected.len());
    for (a, e) in actual.iter_mut().zip(&mut expected) {
        assert_eq!(
            a.signals.keys().collect::<Vec<_>>(),
            e.signals.keys().collect::<Vec<_>>()
        );
        for (key, value) in &a.signals {
            let bound = if key.starts_with("cosine_") {
                1e-6
            } else {
                1e-12
            };
            assert!(
                (value - e.signals[key]).abs() <= bound + bound * e.signals[key].abs(),
                "{key}"
            );
        }
        a.signals.clear();
        e.signals.clear();
        assert_eq!(a.passages.len(), e.passages.len());
        for (p, q) in a.passages.iter_mut().zip(&mut e.passages) {
            assert_eq!(
                p.signals.keys().collect::<Vec<_>>(),
                q.signals.keys().collect::<Vec<_>>()
            );
            for (key, value) in &p.signals {
                let bound = if key.starts_with("cosine_") {
                    1e-6
                } else {
                    1e-12
                };
                assert!(
                    (value - q.signals[key]).abs() <= bound + bound * q.signals[key].abs(),
                    "{key}"
                );
            }
            p.signals.clear();
            q.signals.clear();
        }
        assert_eq!(a, e, "complete ordered owners/evidence");
    }
}
#[test]
fn snapshot_candidate_union_and_query_calls_match_every_original_sql_case() {
    let family = fixture();
    let legacy = LegacyRuntimeIdentity::from_json(&family["legacy_runtime"].to_string()).unwrap();
    for case in family["cases"].as_array().unwrap() {
        let i = input(&case["input"]);
        let (_temp, db, profile) = setup(&i, &legacy);
        let calls = Rc::new(std::cell::RefCell::new(Vec::new()));
        let identity: Rc<dyn ken_retrieval::query_encoder::QueryEncoder> = Rc::new(Queries {
            name: if i.shared { "shared" } else { "identity" }.into(),
            vector: vector(&i.query_vector),
            calls: calls.clone(),
        });
        let behavior = if i.shared {
            identity.clone()
        } else {
            Rc::new(Queries {
                name: "behavior".into(),
                vector: vector(&i.query_vector),
                calls: calls.clone(),
            })
        };
        let encoders = ken_retrieval::query_encoder::QueryEncoders { identity, behavior };
        let request = serde_json::from_value(i.request).unwrap();
        let actual = ken_retrieval::candidates::retrieve(
            db.connection(),
            &request,
            &profile,
            &legacy,
            &encoders,
        );
        let expected_calls: Vec<QueryCall> =
            serde_json::from_value(if case.get("error").is_some() {
                case["query_calls"].clone()
            } else {
                case["result"]["query_calls"].clone()
            })
            .unwrap();
        assert_eq!(
            *calls.borrow(),
            expected_calls,
            "{} query call order",
            case["id"]
        );
        if let Some(error) = case.get("error") {
            assert!(
                actual
                    .unwrap_err()
                    .to_string()
                    .contains(error["message"].as_str().unwrap()),
                "{}",
                case["id"]
            );
        } else {
            compare_candidates(
                actual.unwrap(),
                serde_json::from_value(case["result"]["candidates"].clone()).unwrap(),
            );
        }
    }
}
#[test]
fn complete_owner_descriptions_reject_stale_proposals_after_own_writes_and_rollback() {
    let family = fixture();
    let legacy = LegacyRuntimeIdentity::from_json(&family["legacy_runtime"].to_string()).unwrap();
    let i = input(&family["cases"][0]["input"]);
    let (_temp, db, _profile) = setup(&i, &legacy);
    let owners = ken_retrieval::candidates::owner_passages(db.connection()).unwrap();
    assert_eq!(owners.len(), 3);
    assert!(owners.iter().all(|(_, p)| p.len() == 1));
    let request = ken_retrieval::query::SearchRequest::new("persist_state").unwrap();
    let mut proposed =
        ken_retrieval::candidates::exact_candidates(db.connection(), &request).unwrap();
    let describe = |c: &[ken_retrieval::query::Candidate]| {
        ken_retrieval::candidates::owner_descriptions(db.connection(), c)
    };
    assert_eq!(describe(&proposed).unwrap()[0].1.entity, proposed[0].entity);
    db.connection()
        .execute_batch(
            "SAVEPOINT changed;UPDATE ci_retrieval_files SET source_hash='different-version';",
        )
        .unwrap();
    assert!(
        describe(&proposed)
            .unwrap_err()
            .to_string()
            .contains("source changed before owner ranking")
    );
    db.connection()
        .execute_batch("ROLLBACK TO changed;RELEASE changed;")
        .unwrap();
    assert!(describe(&proposed).is_ok());
    let evidence = proposed[0].passages.clone();
    proposed[0].passages.clear();
    assert!(
        describe(&proposed)
            .unwrap_err()
            .to_string()
            .contains("owner changed before ranking")
    );
    proposed[0].passages = evidence;
    db.connection().execute_batch("SAVEPOINT renamed;UPDATE ci_symbols SET name='renamed',qualname='renamed'WHERE name='persist_state';").unwrap();
    assert!(
        describe(&proposed)
            .unwrap_err()
            .to_string()
            .contains("owner changed before ranking")
    );
    db.connection()
        .execute_batch("ROLLBACK TO renamed;RELEASE renamed;")
        .unwrap();
    assert!(describe(&proposed).is_ok());
}
