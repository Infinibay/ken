#[path = "common/selection_scenario.rs"]
mod scenario;
use ken_models::{ContextualRetrieval, EncoderSpec, LegacyRuntimeIdentity};
use ken_retrieval::{
    Result,
    candidates::{owner_passages, retrieve_contextual},
    contextual::{ContextualRetriever, OwnerVectorSnapshot},
    query_encoder::{QueryEncoder, QueryEncoders},
    source_views::SourceViewSnapshot,
};
use ken_text::PythonText;
use serde::{Deserialize, Serialize};
use serde_json::{Value, value::RawValue};
use std::{cell::RefCell, collections::BTreeMap, rc::Rc};
#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
struct Call {
    encoder: String,
    query: PythonText,
}
struct Encoder {
    name: String,
    vector: Vec<f32>,
    original: Option<PythonText>,
    calls: Rc<RefCell<Vec<Call>>>,
}
impl QueryEncoder for Encoder {
    fn embed_query(&self, query: &PythonText) -> Result<Vec<f32>> {
        self.calls.borrow_mut().push(Call {
            encoder: self.name.clone(),
            query: query.clone(),
        });
        Ok(
            if self.original.as_ref().is_some_and(|text| text != query) {
                vec![0., 3.]
            } else {
                self.vector.clone()
            },
        )
    }
}
#[derive(Deserialize)]
struct Root {
    families: BTreeMap<String, Box<RawValue>>,
}
#[test]
fn contextual_union_retains_original_exact_authority_and_complete_measurements() {
    #[cfg(target_os = "macos")]
    let raw = include_str!("fixtures/search-selection-reference.json");
    #[cfg(target_os = "linux")]
    let raw = include_str!("fixtures/search-selection-reference-linux.json");
    let root: Root = serde_json::from_str(raw).unwrap();
    let family: Value = serde_json::from_str(root.families["context_selection"].get()).unwrap();
    let legacy = LegacyRuntimeIdentity::from_json(&family["legacy_runtime"].to_string()).unwrap();
    for case in family["cases"].as_array().unwrap() {
        let value = &case["input"];
        let input: scenario::Input = serde_json::from_value(value.clone()).unwrap();
        let (_temp, db, mut profile) = scenario::setup(&input, &legacy);
        let calls = Rc::new(RefCell::new(Vec::new()));
        let identity: Rc<dyn QueryEncoder> = Rc::new(Encoder {
            name: if input.shared { "shared" } else { "identity" }.into(),
            vector: scenario::vector(&input.query_vector),
            original: None,
            calls: calls.clone(),
        });
        let behavior = if input.shared {
            identity.clone()
        } else {
            Rc::new(Encoder {
                name: "behavior".into(),
                vector: scenario::vector(&input.query_vector),
                original: None,
                calls: calls.clone(),
            })
        };
        let encoders = QueryEncoders { identity, behavior };
        let context_spec: EncoderSpec = serde_json::from_value(serde_json::json!({"model_id":"test/context","revision":"b".repeat(64),"backend":"provided","batch_size":1})).unwrap();
        let view_spec: EncoderSpec = serde_json::from_value(serde_json::json!({"model_id":"test/views","revision":"c".repeat(64),"backend":"provided","batch_size":1})).unwrap();
        let request = serde_json::from_value(input.request).unwrap();
        let owners = owner_passages(db.connection()).unwrap();
        let keys = owners.iter().map(|(e, _)| e.clone()).collect::<Vec<_>>();
        let hashes = owners
            .iter()
            .map(|(_, ps)| ps[0].source_hash.clone())
            .collect::<Vec<_>>();
        let matrix: Vec<Vec<f32>> =
            serde_json::from_value(value["context_matrix"].clone()).unwrap();
        let generation = ken_retrieval::storage::generation(db.connection()).unwrap();
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
        )
        .unwrap();
        let views = if value["views"] == true {
            Some(
                SourceViewSnapshot::new(
                    view_spec.clone(),
                    generation,
                    keys.clone(),
                    hashes,
                    matrix,
                    BTreeMap::from([
                        ("contract".into(), (0..keys.len() as i64).rev().collect()),
                        ("implementation".into(), (0..keys.len() as i64).collect()),
                    ]),
                    context_spec.clone(),
                )
                .unwrap(),
            )
        } else {
            None
        };
        let runtime = if value["runtime"] != false {
            Some(
                ContextualRetriever::new(
                    Rc::new(Encoder {
                        name: "context".into(),
                        vector: vec![2., 0.],
                        original: Some(
                            ken_retrieval::query::SearchRequest::query(&request).clone(),
                        ),
                        calls: calls.clone(),
                    }),
                    context_spec.clone(),
                    vectors,
                    views,
                )
                .unwrap(),
            )
        } else {
            None
        };
        if value["contextual"] != false {
            profile.contextual = Some(ContextualRetrieval {
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
            profile.evidence = Some(serde_json::from_value(serde_json::json!({"model_revision":"d".repeat(64),"word_model":profile.identity,"feature_version":2,"evidence_version":2})).unwrap());
        }
        let expand = |query: &PythonText| {
            calls.borrow_mut().push(Call {
                encoder: "expansion".into(),
                query: query.clone(),
            });
            Ok(PythonText::from(value["expanded"].as_str().unwrap()))
        };
        let actual = retrieve_contextual(
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
        );
        let expected_calls: Vec<Call> = serde_json::from_value(if case.get("error").is_some() {
            case["query_calls"].clone()
        } else {
            case["result"]["query_calls"].clone()
        })
        .unwrap();
        assert_eq!(*calls.borrow(), expected_calls, "{} calls", case["id"]);
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
            let (candidates, expanded) = actual.unwrap();
            assert_eq!(
                expanded.to_utf8().unwrap(),
                case["result"]["expanded"].as_str().unwrap()
            );
            scenario::compare_candidates(
                candidates,
                serde_json::from_value(case["result"]["candidates"].clone()).unwrap(),
            );
        }
    }
}
