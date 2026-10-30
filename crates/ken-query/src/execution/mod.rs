//! Snapshot-scoped relational execution, independent of persistence and hosts.
pub mod body_runtime;
mod cardinality;
mod control;
mod engine;
mod evidence;
mod graph;
pub mod indexed_runtime;
mod numbers;
mod operators;
mod plan;
mod planning;
pub mod regex_runtime;
mod source;
mod source_occurrences;
mod source_operators;
mod source_plan;
mod terms;
pub mod values;
pub use control::{
    Cancellation, EvidenceMode, Execution, ExecutionOptions, Interruption, Planning, QueryBudget,
};
pub use engine::ExecutionError;
pub use evidence::{Match, QueryOutcome, QueryStats};
pub use graph::{FactProbe, GraphRead, MemoryGraph, OperationProbe, SourceProbe};
pub type Result<T> = std::result::Result<T, ExecutionError>;
pub(crate) use terms::Comparisons;

mod source_effects;
mod source_fields;
mod source_initializers;
mod source_inventory;
mod source_usages;

mod relational_body;
