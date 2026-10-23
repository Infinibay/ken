use super::{Calls, raw};
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
struct Input {
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
    let temp = tempfile::tempdir_in(".").unwrap();
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
use ken_retrieval::{
    contextual::{ContextualRetriever, OwnerVectorSnapshot},
    query::{Candidate, SearchRequest},
    query_encoder::{QueryEncoder, QueryEncoders},
    source_views::SourceViewSnapshot,
};
use ken_text::PythonText;
use serde::Serialize;
use serde_json::value::RawValue;
#[derive(Clone)]
struct Queries {
    name: String,
    vector: Vec<f32>,
    original: Option<PythonText>,
    calls: Calls,
}
impl QueryEncoder for Queries {
    fn embed_query(&self, query: &PythonText) -> Result<Vec<f32>> {
        #[derive(Serialize)]
        struct Call<'a> {
            encoder: &'a str,
            query: &'a PythonText,
        }
        self.calls.push(&Call {
            encoder: &self.name,
            query,
        })?;
        Ok(if self.original.as_ref().is_some_and(|q| q != query) {
            vec![0., 3.]
        } else {
            self.vector.clone()
        })
    }
}
#[derive(Serialize)]
struct Selection {
    candidates: Vec<Candidate>,
    query_calls: Vec<Box<RawValue>>,
}
#[derive(Serialize)]
struct ContextSelection {
    candidates: Vec<Candidate>,
    expanded: PythonText,
    query_calls: Vec<Box<RawValue>>,
}
pub(super) fn run(input: &str, kind: &str, legacy: &Value, calls: &Calls) -> Result<Box<RawValue>> {
    let input_value: Value = serde_json::from_str(input)?;
    let input: Input = serde_json::from_str(input)?;
    let legacy = LegacyRuntimeIdentity::from_json(&legacy.to_string())?;
    let (_temporary, db, mut profile) = setup(&input, &legacy);
    let identity: Rc<dyn QueryEncoder> = Rc::new(Queries {
        name: if input.shared { "shared" } else { "identity" }.into(),
        vector: vector(&input.query_vector),
        original: None,
        calls: calls.clone(),
    });
    let behavior = if input.shared {
        identity.clone()
    } else {
        Rc::new(Queries {
            name: "behavior".into(),
            vector: vector(&input.query_vector),
            original: None,
            calls: calls.clone(),
        })
    };
    let encoders = QueryEncoders { identity, behavior };
    let request: SearchRequest = serde_json::from_value(input.request)?;
    if kind == "selection" {
        let candidates = ken_retrieval::candidates::retrieve(
            db.connection(),
            &request,
            &profile,
            &legacy,
            &encoders,
        )?;
        return raw(&Selection {
            candidates,
            query_calls: calls.values(),
        });
    }
    let value = input_value;
    let context_spec: EncoderSpec = serde_json::from_value(
        serde_json::json!({"model_id":"test/context","revision":"b".repeat(64),"backend":"provided","batch_size":1}),
    )?;
    let view_spec: EncoderSpec = serde_json::from_value(
        serde_json::json!({"model_id":"test/views","revision":"c".repeat(64),"backend":"provided","batch_size":1}),
    )?;
    let owners = ken_retrieval::candidates::owner_passages(db.connection())?;
    let keys = owners.iter().map(|(e, _)| e.clone()).collect::<Vec<_>>();
    let hashes = owners
        .iter()
        .map(|(_, p)| p[0].source_hash.clone())
        .collect::<Vec<_>>();
    let matrix: Vec<Vec<f32>> = serde_json::from_value(value["context_matrix"].clone())?;
    let generation = ken_retrieval::storage::generation(db.connection())?;
    let vectors = OwnerVectorSnapshot::new(
        context_spec.clone(),
        generation + value["generation_offset"].as_i64().unwrap_or(0),
        keys.clone(),
        if value["stale_source"] == true {
            vec!["changed".into(); keys.len()]
        } else {
            hashes.clone()
        },
        matrix.clone(),
        1,
    )?;
    let views = if value["views"] == true {
        Some(SourceViewSnapshot::new(
            view_spec.clone(),
            generation,
            keys.clone(),
            hashes,
            matrix,
            std::collections::BTreeMap::from([
                ("contract".into(), (0..keys.len() as i64).rev().collect()),
                ("implementation".into(), (0..keys.len() as i64).collect()),
            ]),
            context_spec.clone(),
        )?)
    } else {
        None
    };
    let runtime = if value["runtime"] != false {
        Some(ContextualRetriever::new(
            Rc::new(Queries {
                name: "context".into(),
                vector: vec![2., 0.],
                original: Some(request.query().clone()),
                calls: calls.clone(),
            }),
            context_spec.clone(),
            vectors,
            views,
        )?)
    } else {
        None
    };
    if value["contextual"] != false {
        profile.contextual = Some(ken_models::ContextualRetrieval {
            model: context_spec,
            channel_limit: value["channel_limit"].as_u64().unwrap_or(1) as usize,
            broad_limit: value["broad_limit"].as_u64().unwrap_or(3) as usize,
            projection_version: 1,
            view_model: if value["views"] == true {
                Some(view_spec)
            } else {
                None
            },
        });
        profile.evidence = Some(serde_json::from_value(
            serde_json::json!({"model_revision":"d".repeat(64),"word_model":profile.identity,"feature_version":2,"evidence_version":2}),
        )?);
    }
    let expand = |query: &PythonText| {
        #[derive(Serialize)]
        struct Call<'a> {
            encoder: &'a str,
            query: &'a PythonText,
        }
        calls.push(&Call {
            encoder: "expansion",
            query,
        })?;
        Ok(PythonText::from(
            value["expanded"].as_str().expect("provided expansion text"),
        ))
    };
    let (candidates, expanded) = ken_retrieval::candidates::retrieve_contextual(
        db.connection(),
        &request,
        &profile,
        &legacy,
        &encoders,
        runtime.as_ref(),
        if value["expander"] != false {
            Some(&expand)
        } else {
            None
        },
    )?;
    raw(&ContextSelection {
        candidates,
        expanded,
        query_calls: calls.values(),
    })
}
