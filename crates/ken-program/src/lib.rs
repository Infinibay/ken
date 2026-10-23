//! Source program semantics independent of transport, persistence and execution.
mod boundaries;
mod ir;
mod model;
pub use boundaries::{BodyRange, body_ranges};
pub use ir::{Attributes, Entity, Fact, Operation, StructuralIr};
pub use model::{Link, Node, Program, Reference, Scope, Symbol};

#[derive(Debug, thiserror::Error)]
pub enum ProgramError {
    #[error("invalid program data: {0}")]
    Json(#[from] serde_json::Error),
    #[error("{0}")]
    Invalid(&'static str),
}
fn nullable<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: serde::Deserialize<'de>,
{
    <Option<T> as serde::Deserialize>::deserialize(deserializer)
}
