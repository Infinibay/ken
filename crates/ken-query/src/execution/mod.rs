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
mod terms;
pub use control::{
    Cancellation, EvidenceMode, Execution, ExecutionOptions, Interruption, Planning, QueryBudget,
};
pub use engine::ExecutionError;
pub use evidence::{Match, QueryOutcome, QueryStats};
pub use graph::{FactProbe, GraphRead, MemoryGraph};
pub type Result<T> = std::result::Result<T, ExecutionError>;
