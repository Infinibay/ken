use super::{Calls, raw};
use ken_models::{ContextualRetrieval, EncoderSpec};
use ken_retrieval::{
    EntityKey, Passage, Result,
    contextual::{ContextualRetriever, OwnerVectorSnapshot},
    description::describe_owner,
    query::Candidate,
    query_encoder::QueryEncoder,
    source_views::{SourceViewSnapshot, owner_view_texts},
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
use std::{cell::RefCell, collections::BTreeMap, rc::Rc};
#[derive(Deserialize, Clone)]
struct ViewInput {
    model: EncoderSpec,
    matrix: Vec<Vec<Value>>,
    rows: BTreeMap<String, Vec<Value>>,
    generation: Option<i64>,
    owners: Option<Vec<EntityKey>>,
    source_hashes: Option<Vec<String>>,
    query_model: Option<EncoderSpec>,
}
#[derive(Deserialize)]
struct Input {
    owners: Vec<(EntityKey, Vec<Passage>)>,
    model: EncoderSpec,
    matrix: Vec<Vec<Value>>,
    snapshot_generation: i64,
    generation: i64,
    original: String,
    expanded: String,
    query_vectors: BTreeMap<String, Vec<Value>>,
    #[serde(default = "default_limit")]
    limit: isize,
    #[serde(default = "default_indices")]
    enrich_indices: Vec<usize>,
    #[serde(default = "projection")]
    projection_version: usize,
    owner_keys: Option<Vec<EntityKey>>,
    source_hashes: Option<Vec<String>>,
    encoder_model: Option<EncoderSpec>,
    policy_model: Option<EncoderSpec>,
    policy_view_model: Option<EncoderSpec>,
    views: Option<ViewInput>,
    #[serde(default)]
    omit_owner: bool,
    #[serde(default)]
    stale_owner: bool,
}
fn default_limit() -> isize {
    2
}
fn default_indices() -> Vec<usize> {
    vec![2, 0]
}
fn projection() -> usize {
    1
}
fn floats(v: &[Value]) -> Vec<f32> {
    v.iter()
        .map(|x| match x.as_str() {
            Some("nan") => f32::NAN,
            Some("inf") => f32::INFINITY,
            _ => x.as_f64().unwrap() as f32,
        })
        .collect()
}
fn matrix(v: &[Vec<Value>]) -> Vec<Vec<f32>> {
    v.iter().map(|v| floats(v)).collect()
}
struct Encoder {
    vectors: BTreeMap<String, Vec<Value>>,
    calls: Rc<RefCell<Vec<PythonText>>>,
}
impl QueryEncoder for Encoder {
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>> {
        self.calls.borrow_mut().push(text.clone());
        Ok(floats(&self.vectors[&text.to_utf8().unwrap()]))
    }
}
#[derive(serde::Serialize, Debug)]
struct Output {
    original: Vec<f32>,
    expanded: Vec<f32>,
    proposed: Vec<Candidate>,
    candidates: Vec<Candidate>,
    query_calls: Vec<PythonText>,
}
fn execute(i: Input, kind: &str, calls: Rc<RefCell<Vec<PythonText>>>) -> Result<Output> {
    let keys = i.owners.iter().map(|(e, _)| e.clone()).collect::<Vec<_>>();
    let hashes = i
        .owners
        .iter()
        .map(|(_, ps)| ps[0].source_hash.clone())
        .collect::<Vec<_>>();
    let views = if let Some(v) = i.views {
        let rows = v
            .rows
            .into_iter()
            .map(|(name, values)| {
                (
                    name,
                    values.iter().map(|x| x.as_i64().unwrap_or(-1)).collect(),
                )
            })
            .collect();
        Some(SourceViewSnapshot::new(
            v.model,
            v.generation.unwrap_or(i.snapshot_generation),
            v.owners.unwrap_or(keys.clone()),
            v.source_hashes.unwrap_or(hashes.clone()),
            matrix(&v.matrix),
            rows,
            v.query_model.unwrap_or(i.model.clone()),
        )?)
    } else {
        None
    };
    let mut candidates = i
        .enrich_indices
        .iter()
        .map(|&index| Candidate {
            entity: i.owners[index].0.clone(),
            passages: i.owners[index].1.clone(),
            signals: BTreeMap::new(),
            owned_regions: Vec::new(),
        })
        .collect::<Vec<_>>();
    if kind == "source_views" {
        let a = floats(&i.query_vectors[&i.original]);
        let b = floats(&i.query_vectors[&i.expanded]);
        let expanded = if i.original == i.expanded { &a } else { &b };
        views.unwrap().enrich(&mut candidates, &a, expanded)?;
        return Ok(Output {
            original: vec![],
            expanded: vec![],
            proposed: vec![],
            candidates,
            query_calls: calls.borrow().clone(),
        });
    }
    let source = OwnerVectorSnapshot::new(
        i.model.clone(),
        i.snapshot_generation,
        i.owner_keys.unwrap_or(keys),
        i.source_hashes.unwrap_or(hashes),
        matrix(&i.matrix),
        i.projection_version,
    )?;
    let runtime = ContextualRetriever::new(
        Rc::new(Encoder {
            vectors: i.query_vectors,
            calls: calls.clone(),
        }),
        i.encoder_model.unwrap_or(i.model.clone()),
        source,
        views,
    )?;
    let policy:ContextualRetrieval=serde_json::from_value(serde_json::json!({"model":i.policy_model.unwrap_or(i.model),"channel_limit":2,"broad_limit":8,"view_model":i.policy_view_model})).unwrap();
    let mut owners = i.owners;
    if i.omit_owner {
        owners.pop();
    }
    if i.stale_owner {
        for p in &mut owners[0].1 {
            p.source_hash = "changed".into();
        }
    }
    let scores = runtime.score(
        &i.original.clone().into(),
        &i.expanded.clone().into(),
        &owners,
        i.generation,
        &policy,
    )?;
    let proposed = scores.propose(&owners, i.limit)?;
    scores.enrich(&mut candidates)?;
    Ok(Output {
        original: scores.original().to_vec(),
        expanded: scores.expanded().to_vec(),
        proposed,
        candidates,
        query_calls: calls.borrow().clone(),
    })
}

pub(super) fn run(input: &str, kind: &str, trace: &Calls) -> Result<Box<RawValue>> {
    if kind == "view_texts" {
        #[derive(Deserialize)]
        struct TextInput {
            passages: Vec<Passage>,
        }
        let i: TextInput = serde_json::from_str(input)?;
        return raw(&owner_view_texts(&describe_owner(&i.passages)?));
    }
    let input: Input = serde_json::from_str(input)?;
    let calls = Rc::new(RefCell::new(Vec::new()));
    let outcome = execute(input, kind, calls.clone());
    for call in calls.borrow().iter() {
        trace.push(call)?;
    }
    let outcome = outcome?;
    if kind == "source_views" {
        #[derive(serde::Serialize)]
        struct ViewOutput {
            candidates: Vec<Candidate>,
            query_calls: Vec<PythonText>,
        }
        raw(&ViewOutput {
            candidates: outcome.candidates,
            query_calls: outcome.query_calls,
        })
    } else {
        raw(&outcome)
    }
}
