//! Detached public response fields and lossless JSON delivery.
use super::*;
use ken_program::value::GraphValue;
use ken_query::{
    Program,
    execution::{indexed_runtime::IndexedOutcome, values::Value},
};
use std::collections::BTreeSet;
#[derive(Clone, Debug, Serialize)]
pub struct QueryResponse {
    pub language: &'static str,
    pub capability: &'static str,
    pub query: String,
    pub columns: Vec<String>,
    pub rows: Vec<Vec<Value>>,
    pub complete: bool,
    pub coverage_complete: bool,
    pub unknown_candidates: u64,
    pub reason: Option<String>,
    pub results_truncated: bool,
    pub plan: Vec<Json>,
    pub optional_evidence: Vec<Json>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub diagnostics: Option<Vec<Json>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_scope: Option<Json>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub entities: Option<BTreeMap<String, Json>>,
    // Keep analysis last so its elapsed total can be finalized without parsing the
    // already-encoded typed rows (which may contain Python lone-surrogate strings).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub analysis: Option<Json>,
    #[serde(skip)]
    pub(crate) states: u64,
    #[serde(skip)]
    pub(crate) scanned_nodes: u64,
    #[serde(skip)]
    pub(crate) elapsed_ms: f64,
    #[serde(skip)]
    pub(crate) profile: Vec<Json>,
}
impl QueryResponse {
    /// JSON's Rust string model cannot hold Python lone surrogates. This convenience
    /// is explicitly fallible; transport must serialize this typed response directly.
    pub fn to_json(&self) -> Result<Json> {
        Ok(serde_json::to_value(self)?)
    }
}
pub fn query_response(program: &Program, outcome: IndexedOutcome, coverage: bool) -> QueryResponse {
    QueryResponse {
        language: "kql/2",
        capability: "structural-source/1",
        query: program.name.clone(),
        columns: program
            .projection
            .iter()
            .enumerate()
            .map(|(i, e)| {
                if e.value.is_empty() {
                    format!("column_{}", i + 1)
                } else {
                    e.value.clone()
                }
            })
            .collect(),
        rows: outcome.rows,
        complete: outcome.complete,
        coverage_complete: coverage,
        unknown_candidates: outcome.unknown_candidates,
        reason: outcome.reason,
        results_truncated: outcome.results_truncated,
        plan: outcome.plan,
        optional_evidence: outcome.optional_evidence,
        diagnostics: None,
        source_scope: None,
        entities: None,
        analysis: None,
        states: outcome.states,
        scanned_nodes: outcome.scanned_nodes,
        elapsed_ms: outcome.elapsed_ms,
        profile: outcome.profile,
    }
}
pub(super) fn encoded_total(mut encoded: String, total: f64) -> Result<String> {
    let marker = "\"total_ms\":";
    let start = encoded
        .rfind(marker)
        .ok_or_else(|| SessionError::Invalid("encoded response has no delivery total".into()))?
        + marker.len();
    let end = encoded[start..]
        .find([',', '}'])
        .map(|i| start + i)
        .ok_or_else(|| {
            SessionError::Invalid("encoded response has an incomplete delivery total".into())
        })?;
    encoded.replace_range(start..end, &serde_json::to_string(&total)?);
    Ok(encoded)
}
fn local_id(value: &Value) -> Option<String> {
    match value {
        Value::Node(v) => Some(v.local_id.clone()),
        Value::Operation(v) => Some(v.local_id.clone()),
        Value::Scalar(GraphValue::String(s)) => s.to_utf8(),
        Value::Scalar(GraphValue::Dict(items)) => items
            .iter()
            .find(|(key, _)| key.to_utf8().as_deref() == Some("local_id"))
            .and_then(|(_, value)| value.string()),
        _ => None,
    }
}
pub(super) fn locations(
    revision: &Revision,
    rows: &[Vec<Value>],
) -> Result<BTreeMap<String, Json>> {
    let ids = rows
        .iter()
        .flatten()
        .filter_map(local_id)
        .filter(|id| id.contains("::"))
        .collect::<BTreeSet<_>>();
    let mut result = BTreeMap::new();
    let store = revision.project.source_store();
    store.check_pinned_snapshot(revision.snapshot)?;
    for id in ids {
        if let Some(node) = store.node_by_local_id(revision.snapshot, &id)?
            && id
                .split_once("::")
                .is_some_and(|(path, _)| path == node.path)
        {
            result.insert(id.clone(),json!({"local_id":id,"kind":node.kind,"name":node.name,"path":node.path,"line":node.line}));
        }
    }
    store.check_pinned_snapshot(revision.snapshot)?;
    Ok(result)
}
