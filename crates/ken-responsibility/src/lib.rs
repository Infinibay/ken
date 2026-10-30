//! Evidence-backed hypotheses about documented code responsibilities.
pub mod assessment;
mod model;
pub mod reasoners;
pub mod report;
pub mod retrieval;
mod service;
mod source;
pub mod structure;
mod text;
mod vectors;
pub use model::*;
pub use reasoners::default_reasoners;
pub use report::WhoOutput;
pub use service::who_with;
pub use source::{CurrentSources, NativeSources};
pub use vectors::{NativeVectors, ResponsibilityVectors};
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Database(#[from] rusqlite::Error),
    #[error(transparent)]
    Retrieval(#[from] ken_retrieval::RetrievalError),
    #[error(transparent)]
    Model(#[from] ken_models::ModelError),
    #[error(transparent)]
    Inspection(#[from] ken_structural::application::inspection::InspectionError),
    #[error(transparent)]
    Project(#[from] ken_core::project::ProjectError),
}
pub type Result<T> = std::result::Result<T, Error>;
pub(crate) fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
pub(crate) fn rounded(value: f64, digits: usize) -> f64 {
    format!("{value:.digits$}").parse().unwrap_or(value)
}
