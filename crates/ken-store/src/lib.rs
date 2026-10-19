//! Native storage for existing Ken SQLite and vector data.
mod database;
mod error;
mod maintenance;
mod manifest;
mod model_state;
mod project;
mod recovery;
mod schema;
mod segments;
pub mod slots;
mod transaction;
mod vectors;

pub use database::ProjectDatabase;
pub use error::{StoreError, StoreResult};
pub use maintenance::{
    CompactionCount, MaintenanceEvent, compact, migrate_inline, reclaim_database,
};
pub use manifest::VectorManifest;
pub use model_state::StoredModelState;
pub use project::ProjectStore;
pub use slots::{VectorSpace, allocate, high_water, release};
pub use transaction::WriteTransaction;
pub use vectors::{LiveScores, VectorStore, VerificationReport, live_scores, verify};
