//! Unversioned KenQL blocks lower directly to the shared relational operators.
mod convert;
mod parser;
mod tokens;
use crate::{
    execution::{ExecutionError, Result},
    relational::{PlanValue, QuotedTerm, RelationalEdge, RelationalNode, Term},
};
pub use convert::legacy_query;
use ken_program::value::GraphValue;
pub use parser::parse;
pub(crate) use tokens::{Grammar, Tokens};
fn invalid(message: impl Into<String>) -> ExecutionError {
    ExecutionError::Invalid(message.into())
}
fn py(text: &str) -> String {
    GraphValue::String(text.into()).repr()
}
fn text(value: impl Into<String>) -> PlanValue {
    PlanValue::Term(Term::Text(value.into()))
}
fn node(kind: &str, value: PlanValue, children: Vec<Vec<RelationalNode>>) -> RelationalNode {
    RelationalNode {
        kind: kind.into(),
        value,
        children,
    }
}
fn edge(
    subject: Term,
    relation: &str,
    object: Term,
    attrs: Vec<(String, String, String)>,
) -> RelationalNode {
    node(
        "fact",
        PlanValue::Edge(RelationalEdge {
            mode: "require".into(),
            subject,
            relation: relation.into(),
            object,
            attrs,
        }),
        vec![],
    )
}
fn term(raw: String) -> Result<Term> {
    if raw.starts_with('"') {
        let literal = serde_json::from_str(&raw).map_err(|e| invalid(e.to_string()))?;
        Ok(Term::Literal(QuotedTerm {
            token: raw,
            literal,
        }))
    } else {
        Ok(Term::Text(raw))
    }
}
