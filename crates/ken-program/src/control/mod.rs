//! Structured source routes and lexical evidence, never runtime feasibility proofs.
mod cfg;
mod completions;
mod contexts;
mod exceptions;
mod execution;
mod index;
use crate::{Attributes, Fact, StructuralIr};
pub use cfg::structured_control;
pub use contexts::syntax_contexts;
pub use execution::lexical_execution;
use serde_json::{Value, value::to_raw_value};
fn attrs(value: Value) -> Attributes {
    value
        .as_object()
        .expect("control attributes object")
        .iter()
        .map(|(k, v)| (k.clone(), to_raw_value(v).expect("JSON control attribute")))
        .collect()
}
fn fact(
    subject: &str,
    relation: &str,
    object: &str,
    evidence: Option<String>,
    attributes: Value,
) -> Fact {
    Fact {
        subject: subject.into(),
        relation: relation.into(),
        object: object.into(),
        attrs: attrs(attributes),
        evidence: evidence.filter(|s| !s.is_empty()).into_iter().collect(),
    }
}
fn append(graph: &mut StructuralIr, facts: Vec<Fact>) {
    graph
        .relations
        .extend(facts.iter().map(|f| f.relation.clone()));
    graph.facts.extend(facts);
}
