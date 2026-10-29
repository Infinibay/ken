//! Native search and navigation over the indexed project.
mod best_search;
pub use best_search::{BestSearch, PreparationReport, PreparedProjectInfo};
mod resources;
pub use resources::{SearchResourceInputs, SearchResourceProvider, SearchResources, SearchWords};
#[derive(Debug, thiserror::Error)]
pub enum SearchError {
    #[error(transparent)]
    Retrieval(#[from] ken_retrieval::RetrievalError),
    #[error(transparent)]
    Index(#[from] ken_index::IndexError),
    #[error(transparent)]
    Store(#[from] ken_store::StoreError),
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Source(#[from] ken_retrieval::source_snapshot::SourceError),
}
pub type Result<T> = std::result::Result<T, SearchError>;
mod registered;
pub use registered::RegisteredSearchResources;
mod context_encoder;
mod installation;
pub use installation::{InstallationError, SearchInstallation};
pub mod navigation;
pub mod public;
pub mod text_search;
