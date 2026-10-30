//! Syntax-only KQL execution over immutable raw preorder units.
mod plan;
mod runtime;
mod tree;
use crate::execution::{ExecutionError, Result};
pub use plan::SyntaxPlan;
pub(crate) use plan::effective_steps;
pub use runtime::{SyntaxExecutionOptions, SyntaxOutcome, execute};
pub use tree::{NodeRecord, SyntaxUnit};
fn invalid(message: impl Into<String>) -> ExecutionError {
    ExecutionError::Invalid(message.into())
}
