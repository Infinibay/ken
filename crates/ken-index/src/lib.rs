//! Incremental canonical indexing built from native source, retrieval, and storage owners.
mod documents;
pub mod intents;
pub mod postings;
mod prepared;
mod writer;
pub use documents::{Document, DocumentTarget, encode_pending};
pub use ken_retrieval::DocumentEncoder;
pub use postings::rebuild_name_tokens;
pub use prepared::{PreparedFile, SourceMetadata};
pub use writer::{IndexWriter, LegacyStores, WriterOptions, delete_file, delete_path};
#[derive(Debug, thiserror::Error)]
pub enum IndexError {
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Parse(#[from] ken_syntax::ParseError),
    #[error(transparent)]
    Import(#[from] ken_core::imports::ImportError),
    #[error(transparent)]
    Retrieval(#[from] ken_retrieval::RetrievalError),
    #[error(transparent)]
    Store(#[from] ken_store::StoreError),
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error("{0}")]
    Invalid(String),
}
pub type Result<T> = std::result::Result<T, IndexError>;

mod legacy;

pub mod encoder;

pub mod changes;
mod imports;
mod indexer;
pub mod parse_batch;
pub use indexer::{IndexOptions, IndexStats, Indexer, PARSER_VERSION, Progress, VectorStorage};
