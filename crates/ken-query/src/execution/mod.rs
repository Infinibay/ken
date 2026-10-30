//! Snapshot-scoped relational execution, independent of persistence and hosts.
mod cardinality;
mod control;
mod engine;
mod evidence;
mod graph;
mod numbers;
mod operators;
mod plan;
mod planning;
mod source;
mod source_occurrences;
mod source_operators;
mod source_plan;
mod terms;
pub use control::{
    Cancellation, EvidenceMode, Execution, ExecutionOptions, Interruption, Planning, QueryBudget,
};
pub use engine::ExecutionError;
pub use evidence::{Match, QueryOutcome, QueryStats};
pub use graph::{FactProbe, GraphRead, MemoryGraph, OperationProbe};
pub type Result<T> = std::result::Result<T, ExecutionError>;

mod source_effects;
mod source_fields;
mod source_initializers;
mod source_inventory;
mod source_usages;
