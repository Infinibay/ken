//! Durable authored KQL modules and immutable request-local import resolution.
mod reader;
mod registry;
mod resolver;
pub use reader::{RegistryReader, RegistrySnapshot};
pub use registry::{ModuleRegistry, RegisteredModule, module_tree};
pub use resolver::{ModuleResolver, ResolvedQuery, validate_entry};
#[derive(Debug, thiserror::Error)]
pub enum ModuleError {
    #[error("{0}")]
    Invalid(String),
    #[error("{0}")]
    Owner(String),
    #[error(transparent)]
    Parse(#[from] ken_query::ParseError),
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Store(#[from] ken_store::StoreError),
    #[error(transparent)]
    Project(#[from] ken_core::project::ProjectError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}
pub type Result<T> = std::result::Result<T, ModuleError>;
fn invalid(message: impl Into<String>) -> ModuleError {
    ModuleError::Invalid(message.into())
}
