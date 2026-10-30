//! Native checks composition. Domain policy remains in ken-contracts.
mod application;
mod clock;
mod native;
mod process;
mod resources;
mod scheduler;
mod worker;
pub use application::ChecksApplication;
pub use resources::{Resources, WorkerControl, WorkerLimits, WorkerProgram};
pub use scheduler::{SchedulerHost, SchedulerOptions};
pub use worker::worker_main;
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Invalid(String),
    #[error("timeout")]
    Timeout,
    #[error("cancelled")]
    Cancelled,
    #[error("{0}")]
    Worker(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Contracts(#[from] ken_contracts::checks::Error),
    #[error(transparent)]
    Session(#[from] ken_structural::application::sessions::SessionError),
    #[error(transparent)]
    Module(#[from] ken_structural::application::modules::ModuleError),
    #[error(transparent)]
    Catalog(#[from] ken_structural::application::catalog::CatalogError),
    #[error(transparent)]
    Grammar(#[from] ken_syntax::ParseError),
}
pub type Result<T> = std::result::Result<T, Error>;
fn contract(error: impl std::fmt::Display) -> ken_contracts::checks::Error {
    ken_contracts::checks::Error::Invalid(error.to_string())
}
