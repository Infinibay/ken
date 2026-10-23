use ken_models::{EncoderSpec, LegacyRuntimeIdentity, RetrievalProfile};
use ken_retrieval::{
    DocumentEncoder, Passage, PassagePolicy, Result, encoder::EncoderLoader,
    projections::index_embeddings, storage::replace_file_passages,
};
use ken_store::ProjectDatabase;
use rusqlite::params;
use serde::Deserialize;
use serde_json::Value;
use std::{collections::HashSet, rc::Rc};
#[derive(Deserialize, Clone)]
pub struct Input {
    pub passages: Vec<Passage>,
    pub document_vectors: Vec<(String, Vec<f32>)>,
    pub fallback_vector: Vec<f32>,
    pub query_vector: Vec<Value>,
    pub request: Value,
    #[serde(default = "shared")]
    pub shared: bool,
    #[serde(default = "shared")]
    pub prepare: bool,
    #[serde(default = "limit")]
    pub candidate_limit: usize,
    #[serde(default)]
    pub sql: Vec<String>,
}
fn shared() -> bool {
    true
}
fn limit() -> usize {
    100
}
pub fn vector(values: &[Value]) -> Vec<f32> {
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
pub fn setup(
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
pub fn compare_candidates(
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
