//! Native storage for existing Ken SQLite and vector data.
mod database;
mod error;
mod manifest;
mod model_state;
mod schema;
mod segments;
pub mod slots;
mod transaction;
mod vectors;

pub use database::ProjectDatabase;
pub use error::{StoreError, StoreResult};
pub use manifest::VectorManifest;
pub use model_state::StoredModelState;
pub use slots::{VectorSpace, allocate, high_water, release};
pub use transaction::WriteTransaction;
pub use vectors::{LiveScores, VectorStore, VerificationReport, live_scores, verify};
