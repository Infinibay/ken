//! Confined live source revisions assembled into conservative semantic projects.
mod manifest;
mod project;
pub use manifest::{ManifestSource, ScanLimits, Skipped, SourceManifest};
pub use project::{
    BuildAnalysis, BuildReport, Frontend, NativeFrontend, ProjectBuilder, ResolutionCounts,
};
include!(concat!(env!("OUT_DIR"), "/identity.rs"));
#[derive(Debug, thiserror::Error)]
pub enum BuildError {
    #[error(transparent)]
    Project(#[from] ken_core::project::ProjectError),
    #[error(transparent)]
    Source(#[from] ken_core::source_filter::SourceError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Program(#[from] ken_program::ProgramError),
    #[error(transparent)]
    Store(#[from] ken_store::structural::StructuralError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error("path does not exist: {0}")]
    Missing(std::path::PathBuf),
    #[error("{0}")]
    Invalid(&'static str),
}
pub type Result<T> = std::result::Result<T, BuildError>;

mod acquisition;
pub use acquisition::{AcquiredProject, ProjectAcquisition};
