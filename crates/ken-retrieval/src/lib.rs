//! Source passages, lexical vocabulary, and transactional retrieval projections.
mod model;
mod passages;
mod roles;
pub mod vocabulary;
pub use model::{EntityKey, Passage, PassageFields, Span};
pub use passages::{
    EXTRACTOR_VERSION, LexicalCounter, PassagePolicy, TokenCounter, extract_passages,
};
pub use roles::classify_role;
#[derive(Debug, thiserror::Error)]
pub enum RetrievalError {
    #[error("{0}")]
    Invalid(String),
    #[error("{0}")]
    Version(String),
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}
pub type Result<T> = std::result::Result<T, RetrievalError>;

pub mod storage;
