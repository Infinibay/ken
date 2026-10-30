//! Compile-only capabilities and warnings use the same immutable checked plans.
mod diagnostics;
mod exploration;
use crate::{CompiledQuery, ast::Span};
pub use diagnostics::diagnose;
use serde_json::{Value, json};
const SYNTAX_PROPERTIES: [&str; 14] = [
    "kind",
    "category",
    "native_kind",
    "role",
    "name",
    "text",
    "operator",
    "path",
    "language",
    "start_byte",
    "end_byte",
    "line",
    "normalized",
    "type_kind",
];
const SYNTAX_RELATIONS: [&str; 6] = [
    "contains",
    "contains_direct",
    "in_directory",
    "kind_is",
    "owns",
    "stable_id",
];
#[derive(Debug, thiserror::Error)]
#[error("{0}")]
pub struct AuthoringError(String);
pub type Result<T> = std::result::Result<T, AuthoringError>;
fn unsupported(capability: impl std::fmt::Display, span: Option<&Span>) -> AuthoringError {
    let location = span
        .map(|s| format!("{}:{}: ", s.source, s.start))
        .unwrap_or_default();
    AuthoringError(format!(
        "{location}exploration backend does not support {capability}"
    ))
}
pub fn capabilities() -> Value {
    let properties = &crate::capabilities::vocabulary().properties;
    let syntax = SYNTAX_PROPERTIES
        .into_iter()
        .map(|name| (name.to_owned(), json!(properties["node"][name])))
        .collect::<serde_json::Map<_, _>>();
    json!({"language":"kql/2","backends":{"exploration":{"selectors":["node","expression","statement"],"properties":syntax,"relations":SYNTAX_RELATIONS,"body":false,"graph":false,"meaning":"Syntax structure and spelling; no call resolution or implicit control flow."},"indexed":{"selector_properties":properties,"body":true,"graph":true,"meaning":"Source declarations, supported BODY value/CFG patterns and graph relations; preparation can require project linking."}},"syntax_kinds":ken_program::syntax_kinds(),"containment":{"nested_node":"immediate child","contains_direct":"immediate child","contains":"strict descendant"},"literal_matching":"Python: kind: \"literal\"; text: \"True\"; or text: \"None\";","limits":"Parser grammar is broader than each backend. Use --explain on the complete query to validate executable support."})
}
pub fn explain(compiled: &CompiledQuery, backend: &str) -> Result<Value> {
    match backend {
        "exploration" => exploration::validate(&compiled.program)?,
        "indexed" => {
            let execution =
                crate::execution::indexed_runtime::IndexedExecution::new(Default::default())
                    .map_err(|e| AuthoringError(e.to_string()))?;
            crate::execution::indexed_runtime::validate(
                &compiled.program,
                &execution.interruption(),
            )
            .map_err(|e| AuthoringError(e.to_string()))?;
        }
        other => return Err(AuthoringError(format!("unknown backend: {other}"))),
    }
    let program = &compiled.program;
    Ok(
        json!({"language":"kql/2","query":program.name,"backend":backend,"validated":true,"executed":false,"diagnostics":diagnose(program),"columns":program.projection.iter().enumerate().map(|(i,expr)|if expr.value.is_empty(){format!("column_{}",i+1)}else{expr.value.clone()}).collect::<Vec<_>>(),"diagnostic_scope":"source capture relationships; graph authoring warnings are not covered","claim":"Valid for this backend. Query validity and complete source coverage do not prove that the intended question is encoded or that runtime behavior is correct."}),
    )
}
