use crate::feature_support as f;
use ken_models::EvidenceRanking;
use ken_retrieval::{
    Result, RetrievalError,
    matrix::Matrix,
    numeric_ranker::NumericRanker,
    owner_ranking::{EvidenceReranker, ExpansionConfig},
    query::CodeMatch,
    ranking_trace::{MODEL_ORDER_POLICY, RankingTrace, TraceObservation},
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use std::{cell::RefCell, collections::BTreeMap, rc::Rc, sync::Arc};
#[derive(Deserialize)]
pub struct Case {
    pub id: String,
    pub kind: String,
    pub input: Input,
    pub result: Option<Value>,
    pub error: Option<Value>,
    pub encoder_calls: Vec<f::Call>,
    pub stemmer_calls: Vec<Vec<PythonText>>,
    pub expansion_calls: Vec<PythonText>,
}
pub struct Input {
    pub base: f::Input,
    fields: Fields,
}
impl std::ops::Deref for Input {
    type Target = Fields;
    fn deref(&self) -> &Fields {
        &self.fields
    }
}
impl<'de> Deserialize<'de> for Input {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        let raw = Box::<RawValue>::deserialize(deserializer)?;
        Ok(Self {
            base: serde_json::from_str(raw.get()).map_err(serde::de::Error::custom)?,
            fields: serde_json::from_str(raw.get()).map_err(serde::de::Error::custom)?,
        })
    }
}
#[derive(Deserialize)]
pub struct Fields {
    pub model: Box<RawValue>,
    #[serde(default)]
    pub expand: bool,
    pub expansion_revision: Option<String>,
    pub expansion_result: Option<Box<RawValue>>,
    #[serde(default)]
    pub profile: BTreeMap<String, Value>,
    pub evidence_version: Option<usize>,
    pub request_id: Option<String>,
    pub second_query: Option<PythonText>,
    #[serde(default)]
    pub values: Vec<Vec<f64>>,
    pub tamper: Option<String>,
    pub piece_kind: Option<String>,
    #[serde(default)]
    pub compare_empty: bool,
}
pub fn cases() -> Vec<Case> {
    #[derive(Deserialize)]
    struct Root {
        cases: Vec<Case>,
    }
    #[cfg(target_os = "macos")]
    let raw = include_str!("../fixtures/numeric-reference-owner-ranking.json");
    #[cfg(target_os = "linux")]
    let raw = include_str!("../fixtures/numeric-reference-owner-ranking-linux.json");
    let root: Root =
        serde_json::from_str(&ken_retrieval::json_transport::python_strings(raw).unwrap()).unwrap();
    assert_eq!(root.cases.len(), 70);
    root.cases
}
pub fn observe(case: Case) {
    let encoder = Rc::new(f::Encoder::new(&case.input.base));
    let stems = Arc::new(f::Stems::new(&case.input.base));
    let calls = Rc::new(RefCell::new(Vec::new()));
    let got = (|| -> Result<Value> {
        let model = Arc::new(
            NumericRanker::from_json(case.input.model.get())
                .map_err(|e| RetrievalError::Invalid(e.to_string()))?,
        );
        if case.kind == "trace_ids" {
            let a = RankingTrace::new(case.input.request_id.clone())?;
            let b = RankingTrace::new(case.input.request_id.clone())?;
            return Ok(
                json!({"first_valid":uuid4(a.request_id()),"second_valid":uuid4(b.request_id()),"different":a.request_id()!=b.request_id()}),
            );
        }
        let candidates: Vec<_> = case
            .input
            .base
            .candidates
            .iter()
            .map(|c| c.materialize())
            .collect();
        if case.kind.starts_with("trace_") {
            let mut trace = RankingTrace::new(Some(
                case.input
                    .request_id
                    .clone()
                    .unwrap_or("fixed-trace".into()),
            ))?;
            if case.kind == "trace_empty" {
                return if case.input.compare_empty {
                    trace.compare(&key("missing.py", "missing"), &key("other.py", "other"))
                } else {
                    Ok(serde_json::from_str(&trace.to_json(false)?).unwrap())
                };
            }
            let mut values = Matrix::new(
                candidates.len(),
                model.features().len(),
                case.input.values.iter().flatten().copied().collect(),
            )?;
            let scores = model
                .predict(&values)
                .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
            let mut order: Vec<_> = (0..candidates.len()).collect();
            order.sort_by(|a, b| {
                candidates[*b]
                    .signals
                    .get("exact")
                    .unwrap_or(&0.)
                    .partial_cmp(candidates[*a].signals.get("exact").unwrap_or(&0.))
                    .unwrap()
                    .then_with(|| scores[*b].partial_cmp(&scores[*a]).unwrap())
            });
            let matches: Vec<_> = order
                .iter()
                .map(|i| CodeMatch {
                    entity: candidates[*i].entity.clone(),
                    score: scores[*i],
                    evidence: candidates[*i].passages.clone(),
                    source_hash: candidates[*i].passages[0].source_hash.clone(),
                    signals: candidates[*i].signals.clone(),
                    owned_regions: candidates[*i].owned_regions.clone(),
                })
                .collect();
            let query = case.input.base.query.as_ref().unwrap();
            let expanded = case.input.base.expanded.as_ref().unwrap_or(query);
            trace.record(TraceObservation {
                model: &model,
                query,
                expanded,
                candidates: &candidates,
                matches: &matches,
                values: Some(&values),
                feature_version: 1,
                evidence_version: 1,
                policy: MODEL_ORDER_POLICY,
                piece_kind: case.input.piece_kind.as_deref(),
            })?;
            if case.kind == "trace_restore" {
                let mut altered: Value = serde_json::from_str(&trace.to_json(true)?).unwrap();
                tamper(&mut altered, case.input.tamper.as_deref());
                trace = RankingTrace::from_json(&serde_json::to_string(&altered).unwrap(), &model)?;
            }
            let mut detached: Value = serde_json::from_str(&trace.to_json(true)?).unwrap();
            detached["owners"][0]["signals"]["rrf"] = json!(999.);
            values = Matrix::new(
                values.rows(),
                values.columns(),
                vec![999.; values.values().len()],
            )?;
            assert_eq!(values.values()[0], 999.);
            let plain: Value = serde_json::from_str(&trace.to_json(false)?).unwrap();
            let with_query: Value = serde_json::from_str(&trace.to_json(true)?).unwrap();
            let pair = trace.compare(&matches[0].entity, &matches[1].entity)?;
            return Ok(
                json!({"detached":plain["owners"][0]["signals"]["rrf"]!=json!(999.),"trace":plain,"with_query":with_query,"pair":pair}),
            );
        }
        let callback = if case.input.expand {
            let log = calls.clone();
            let response = case
                .input
                .expansion_result
                .as_ref()
                .map(|v| v.get().to_string());
            Some(Rc::new(move |q: &PythonText| {
                log.borrow_mut().push(q.clone());
                match &response {
                    Some(raw) => serde_json::from_str::<PythonText>(raw).map_err(|_| {
                        RetrievalError::Invalid("query expansion must return nonempty text".into())
                    }),
                    None => Ok(PythonText::from("persist durable cookie")),
                }
            })
                as Rc<ken_retrieval::candidates::QueryExpander<'static>>)
        } else {
            None
        };
        let runtime = EvidenceReranker::new(
            model.clone(),
            encoder.clone(),
            stems.clone(),
            Some(ExpansionConfig {
                expand_query: callback,
                revision: case.input.expansion_revision.clone(),
            }),
        )?;
        if case.kind == "prepare" {
            return Ok(serde_json::to_value(
                runtime.prepare_query(case.input.base.query.as_ref().unwrap())?,
            )
            .unwrap());
        }
        if case.kind == "validate" {
            use ken_retrieval::word_encoder::WordEncoder;
            let mut spec = json!({"model_revision":model.fingerprint().unwrap(),"word_model":encoder.spec(),"expansion_revision":case.input.expansion_revision,"feature_version":runtime.feature_version()});
            for (k, v) in &case.input.profile {
                spec[k] = v.clone();
            }
            runtime.validate(&serde_json::from_value::<EvidenceRanking>(spec).unwrap())?;
            return Ok(json!(true));
        }
        let request = f::request(&case.input.base);
        let descriptions = f::descriptions(&case.input.base);
        let mut trace = if case.kind == "rank_trace" {
            Some(RankingTrace::new(Some(
                case.input
                    .request_id
                    .clone()
                    .unwrap_or("fixed-rank-trace".into()),
            ))?)
        } else {
            None
        };
        let before = candidates.clone();
        let mut matches = runtime.rank(
            &request,
            &candidates,
            &descriptions,
            case.input.base.expanded.as_ref(),
            case.input.evidence_version.unwrap_or(1),
            trace.as_mut(),
        )?;
        if let Some(query) = &case.input.second_query {
            matches = runtime.rank(
                &request.with_query(query.clone())?,
                &candidates,
                &descriptions,
                None,
                case.input.evidence_version.unwrap_or(1),
                trace.as_mut(),
            )?;
        }
        let mut result = json!({"matches":matches,"unchanged":candidates==before});
        if let Some(trace) = trace {
            let raw = trace.to_json(true)?;
            result["trace"] = serde_json::from_str(&trace.to_json(false)?).unwrap();
            result["with_query"] = serde_json::from_str(&raw).unwrap();
            result["restored"] =
                serde_json::from_str(&RankingTrace::from_json(&raw, &model)?.to_json(true)?)
                    .unwrap();
            if matches.len() >= 2 {
                result["pair"] = trace.compare(&matches[0].entity, &matches[1].entity)?;
            }
        }
        Ok(result)
    })();
    match (got, case.error.as_ref()) {
        (Ok(got), None) => equal(&got, case.result.as_ref().unwrap(), &case.id),
        (Err(got), Some(want)) => {
            assert_eq!(want["type"], "ValueError", "{}", case.id);
            assert_eq!(
                got.to_string(),
                want["message"].as_str().unwrap(),
                "{}",
                case.id
            );
        }
        (got, want) => panic!("{}: {got:?}, wanted {want:?}", case.id),
    }
    assert_eq!(
        *encoder.calls.borrow(),
        case.encoder_calls,
        "encoder {}",
        case.id
    );
    assert_eq!(
        *stems.calls.lock().unwrap(),
        case.stemmer_calls,
        "stems {}",
        case.id
    );
    assert_eq!(
        *calls.borrow(),
        case.expansion_calls,
        "expansion {}",
        case.id
    );
}
fn key(path: &str, name: &str) -> ken_retrieval::EntityKey {
    ken_retrieval::EntityKey {
        path: path.into(),
        kind: "function".into(),
        qualname: Some(name.into()),
        owner: None,
        definition_ordinal: 0,
    }
}
fn uuid4(s: &str) -> bool {
    s.len() == 36
        && s.as_bytes()[14] == b'4'
        && b"89ab".contains(&s.as_bytes()[19])
        && s.bytes().enumerate().all(|(i, c)| {
            if [8, 13, 18, 23].contains(&i) {
                c == b'-'
            } else {
                c.is_ascii_hexdigit()
            }
        })
}
fn tamper(v: &mut Value, kind: Option<&str>) {
    match kind {
        Some("model") => v["model_fingerprint"] = json!("0".repeat(64)),
        Some("names") => v["feature_names"].as_array_mut().unwrap().reverse(),
        Some("proposal") => v["owners"][0]["proposal_index"] = json!(8),
        Some("ranks") => v["owners"][0]["rank"] = json!(0),
        Some("duplicate") => {
            v["owners"][1]["path"] = v["owners"][0]["path"].clone();
            v["owners"][1]["entity"] = v["owners"][0]["entity"].clone();
        }
        Some("scores") => {
            let score = v["owners"][0]["score"].as_f64().unwrap();
            v["owners"][0]["score"] = json!(score + 1.);
        }
        Some("order") => {
            let a = v["owners"][0]["rank"].clone();
            v["owners"][0]["rank"] = v["owners"][1]["rank"].clone();
            v["owners"][1]["rank"] = a;
        }
        Some("policy") => v["policy"] = json!("unsupported"),
        Some("exact-policy") => v["policy"] = json!("unique_exact"),
        Some("query") => v["query"] = json!("tampered query"),
        Some("expanded") => v["expanded_query_sha256"] = json!("0".repeat(64)),
        Some("drop-query") => {
            v.as_object_mut().unwrap().remove("query");
            v.as_object_mut().unwrap().remove("expanded_query");
        }
        None => {}
        Some(x) => panic!("unknown tamper {x}"),
    }
}
fn equal(a: &Value, b: &Value, path: &str) {
    match (a, b) {
        (Value::Number(a), Value::Number(b)) => {
            let (a, b) = (a.as_f64().unwrap(), b.as_f64().unwrap());
            assert!(
                (a - b).abs() <= 1e-12 + 1e-12 * b.abs(),
                "{path}: {a:?} vs {b:?}"
            );
        }
        (Value::Array(a), Value::Array(b)) => {
            assert_eq!(a.len(), b.len(), "{path}");
            for (i, (a, b)) in a.iter().zip(b).enumerate() {
                equal(a, b, &format!("{path}/{i}"));
            }
        }
        (Value::Object(a), Value::Object(b)) => {
            assert_eq!(
                a.keys().collect::<Vec<_>>(),
                b.keys().collect::<Vec<_>>(),
                "{path}"
            );
            for (k, a) in a {
                equal(a, &b[k], &format!("{path}/{k}"));
            }
        }
        _ => assert_eq!(a, b, "{path}"),
    }
}
