//! Dedicated structural snapshots. No query may scan nodes outside membership.
mod ast;
mod leases;
mod projection;
mod scalar;
mod schema;
mod store;
pub use scalar::Scalar;
pub use schema::{migrate, validate};
pub use store::{Collection, NodeFilter, SnapshotScan, StoredNode, StructuralStore};
use thiserror::Error;
#[derive(Debug, Error)]
pub enum StructuralError {
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Program(#[from] ken_program::ProgramError),
    #[error("{0}")]
    Format(&'static str),
    #[error("{0}")]
    Invalid(&'static str),
    #[error("structural record not found: {0}")]
    Missing(i64),
    #[error("structural retention budget exceeded; use an ephemeral store")]
    Retention,
    #[error("snapshot lease expired; restart acquisition")]
    Expired,
}
pub type Result<T> = std::result::Result<T, StructuralError>;

pub mod graph;
