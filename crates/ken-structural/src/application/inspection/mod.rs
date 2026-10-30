//! Focused source acquisition and honest interpretations of native KQL evidence.
mod availability;
mod exploration;
mod impact;
mod imports;
mod native;
mod observations;
mod program;
mod queries;
mod roles;
mod service;
mod sources;
pub use availability::describe as available;
pub use exploration::{
    ExploreRequest, InspectionQueries, ObservationKind, ObservationRequest, explore,
};
pub use impact::analyze as impact;
pub use impact::result_uses;
pub use imports::{dependencies, select_sources};
pub use native::{SessionQueries, inspect_native};
pub use observations::ObservationLog;
pub use program::{Call, Program, Use, identity, location, qualname};
pub use roles::describe as roles;
pub use service::{InspectRequest, inspect_with};
pub use sources::{
    ImportAlias, ImportStatement, InspectionSources, NativeSources, SourceFacts, source_facts,
};
#[derive(Debug, thiserror::Error)]
pub enum InspectionError {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Project(#[from] ken_core::project::ProjectError),
}
pub type Result<T> = std::result::Result<T, InspectionError>;
fn invalid(message: impl Into<String>) -> InspectionError {
    InspectionError::Invalid(message.into())
}
fn truth(value: &serde_json::Value) -> bool {
    match value {
        serde_json::Value::Null => false,
        serde_json::Value::Bool(b) => *b,
        serde_json::Value::String(s) => !s.is_empty(),
        serde_json::Value::Array(v) => !v.is_empty(),
        serde_json::Value::Object(m) => !m.is_empty(),
        serde_json::Value::Number(n) => n.as_f64().is_some_and(|v| v != 0.),
    }
}
