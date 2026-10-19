//! Native storage for existing Ken SQLite and vector data.
mod database;
mod error;
mod model_state;
mod schema;
pub mod slots;
mod transaction;

pub use database::ProjectDatabase;
pub use error::{StoreError, StoreResult};
pub use model_state::StoredModelState;
pub use slots::{VectorSpace, allocate, high_water, release};
pub use transaction::WriteTransaction;
