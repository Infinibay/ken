//! Per-project native service lifecycle, background indexing, and host hooks.
pub mod client;
pub mod hooks;
pub mod native;
pub mod queue;
mod runtime;
pub mod server;
pub mod state;
pub mod watcher;
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Invalid(String),
    #[error("missing field: {0}")]
    Missing(String),
    #[error("not found")]
    NotFound,
    #[error("daemon closed")]
    Closed,
    #[error("request accepted but response timed out")]
    AcceptedTimeout,
    #[error("HTTP {0}")]
    Http(u16),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Store(#[from] ken_store::StoreError),
    #[error(transparent)]
    Retrieval(#[from] ken_retrieval::RetrievalError),
    #[error(transparent)]
    Context(#[from] ken_context::Error),
    #[error(transparent)]
    Index(#[from] ken_index::IndexError),
    #[error(transparent)]
    Checks(#[from] ken_checks_application::Error),
}
pub type Result<T> = std::result::Result<T, Error>;
fn invalid(error: impl std::fmt::Display) -> Error {
    Error::Invalid(error.to_string())
}
