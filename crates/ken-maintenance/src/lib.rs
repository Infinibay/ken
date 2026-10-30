//! Explicit project maintenance; storage, models and retrieval keep their invariants.
mod application;
mod benchmark;
mod config;
mod reembed;
mod retrieval;
pub mod retrieval_benchmark;
mod vectors;
pub use application::MaintenanceApplication;
pub use benchmark::{
    BenchCase, BenchDataset, BenchObservation, BenchOptions, BenchReport, BenchRunner,
    ContextBenchRunner, benchmark,
};
pub use config::{ConfigEnvironment, ModelSelection, UserConfig, models};
pub use reembed::{
    PROBE_TEXT, ProbeReport, ReembedEvent, ReembedOptions, ReembedReport, StoredEmbeddingInfo,
};
pub use retrieval::RetrievalApplication;
pub use vectors::{DatabaseReclaimer, NativeReclaimer, VectorAction};
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Store(#[from] ken_store::StoreError),
    #[error(transparent)]
    Model(#[from] ken_models::ModelError),
    #[error(transparent)]
    Retrieval(#[from] ken_retrieval::RetrievalError),
    #[error(transparent)]
    Index(#[from] ken_index::IndexError),
    #[error(transparent)]
    Search(#[from] ken_search::SearchError),
    #[error(transparent)]
    Context(#[from] ken_context::Error),
    #[error(transparent)]
    Project(#[from] ken_core::project::ProjectError),
    #[error(transparent)]
    Source(#[from] ken_core::source_filter::SourceError),
}
pub type Result<T> = std::result::Result<T, Error>;
pub(crate) fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .try_into()
        .unwrap_or(i64::MAX)
}
pub(crate) fn paths(root: &std::path::Path) -> Result<ken_core::project::ProjectPaths> {
    Ok(ken_core::project::ProjectPaths::at(
        root,
        &ken_core::project::DiscoveryContext {
            cwd: std::env::current_dir()?,
            forced_root: None,
            home: None,
        },
    )?)
}
pub(crate) fn round(value: f64, digits: usize) -> f64 {
    format!("{value:.digits$}").parse().unwrap_or(value)
}
