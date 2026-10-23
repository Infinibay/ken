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
    #[error(transparent)]
    Model(#[from] ken_models::ModelError),
    #[error("{0}")]
    Invalid(String),
    #[error("{0}")]
    Version(String),
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Store(#[from] ken_store::StoreError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}
pub type Result<T> = std::result::Result<T, RetrievalError>;

pub mod storage;

pub mod encoder;
pub use encoder::{DocumentEncoder, EncoderCounter};

pub mod embedding_store;
pub mod projections;
pub mod representations;

pub mod query;

pub mod lexical;

pub mod dense;
mod dense_math;
#[cfg(target_os = "linux")]
pub use dense_math::verify_dense_runtime;

pub mod candidates;
pub mod contextual;
pub mod description;
pub mod intent;
mod normalized_matrix;
pub mod proposals;
pub mod query_encoder;
pub mod ranking;
pub mod source_locator;
pub mod source_views;
mod text_patterns;

pub mod matrix;
pub mod numeric_ranker;
mod rank_json;

mod snowball;
pub mod stemming;
