//! Durable findings and explicit reasoning, independent of model and query runtimes.
//! Callers supply their connection, workspace, clock, vectors and live check observations.
pub mod arithmetic;
pub mod context;
pub mod dependencies;
pub mod findings;
pub mod reasoning;
pub mod records;
mod wire;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}
pub type Result<T> = std::result::Result<T, Error>;
fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
