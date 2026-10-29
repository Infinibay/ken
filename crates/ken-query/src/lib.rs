//! KQL syntax and pure module preparation, independent of source acquisition.
pub mod ast;
mod body;
mod calls;
mod clauses;
mod expressions;
mod lexer;
mod parser;
mod preparation;
mod regex_syntax;
mod repr;
pub use ast::{File, Span};
pub use parser::{parse, parse_bytes};
pub use preparation::{resolve_libraries, specialize_models};
pub use repr::PythonRepr;
#[derive(Clone, Copy, Debug)]
pub struct ParseLimits {
    pub max_bytes: usize,
    pub max_depth: usize,
}
impl Default for ParseLimits {
    fn default() -> Self {
        Self {
            max_bytes: 2_000_000,
            max_depth: 96,
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize, thiserror::Error)]
#[error("{source}:{start}: {message}",source=.span.source,start=.span.start)]
pub struct ParseError {
    pub message: String,
    pub span: Span,
    pub code: String,
}
impl ParseError {
    pub(crate) fn new(message: impl Into<String>, span: Span) -> Self {
        Self {
            message: message.into(),
            span,
            code: "syntax_error".into(),
        }
    }
    pub(crate) fn resource(message: impl Into<String>, span: Span) -> Self {
        Self {
            message: message.into(),
            span,
            code: "resource_limit".into(),
        }
    }
}
pub type Result<T> = std::result::Result<T, ParseError>;

mod alternatives;
pub use alternatives::expand_indexed_alternatives;
mod predicates;
pub use predicates::{Predicate, predicate_components};

mod rewrite;

mod validation;

mod type_patterns;

mod body_forms;
mod clause_forms;

mod conditionals;

// Preserve grammar limits on small caller stacks without allocating a new thread.
// All recursive grammar entrances pass here; flat syntax uses explicit stacks.
pub(crate) fn with_stack<T>(work: impl FnOnce() -> T) -> T {
    stacker::maybe_grow(256 * 1024, 2 * 1024 * 1024, work)
}
