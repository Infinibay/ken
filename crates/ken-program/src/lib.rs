//! Source program semantics independent of transport, persistence and execution.
mod boundaries;
mod ir;
mod model;
pub use boundaries::{BodyRange, body_ranges};
pub use ir::IR_VERSION;
pub use ir::{Attributes, Entity, Fact, Operation, StructuralIr};
pub use model::VERSION as AST_VERSION;
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

mod types;
pub use types::{TypeRef, parse_type, split_types};

mod attributes;
mod kinds;
mod normalize;
pub use normalize::{normalize, normalize_syntax};

mod environment;
pub use environment::{Environment, Resolution};

mod bindings;
pub mod control;

pub mod project;

mod semantic;
