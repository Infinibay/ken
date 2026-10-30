mod automation;
mod boundary;
mod execution;
mod integration;
mod model;
mod observation;
mod operation;
mod raw_report;
mod report;
mod rules;
mod selection;
mod service;
mod snapshot;
mod store;
mod wire;
pub use automation::{Batch, Job, Scheduler, edited_paths, message, message_report};
pub use boundary::{
    Clock, ExplicitModules, ModuleResolver, QueryEngine, QueryRequest, SourceInputs,
};
pub use execution::{
    execute, execute_batch, execute_batch_observation, execute_observation, unknown,
};
pub use model::{Rule, digest, judgment, relative};
pub use report::{compare, locations, observation_view, query_view, run_view};
pub use selection::{affected, changed_paths, changed_paths_checked, overlaps};
pub use service::Service;
pub use snapshot::{capture_sources, capture_sources_checked};
pub use store::Store;
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}
pub type Result<T> = std::result::Result<T, Error>;
fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}

pub use observation::{
    Admission, BatchObservation, CheckObservation, Observation, RawReport, Receipt,
    judgment_observation,
};
pub use raw_report::{compare_receipts, observation_report, query_report, receipt_report};
