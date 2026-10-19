//! Verified native model execution, independent of project discovery and storage.
mod assets;
mod model2vec;
mod static_table;
mod table_npz;
mod term_cache;
mod tokenization;

pub use assets::{ModelAssets, VerifiedSnapshot};
pub use model2vec::Model2VecEncoder;
pub use static_table::StaticTableEncoder;
pub use tokenization::ModelTokenizer;

#[derive(Debug, thiserror::Error)]
pub enum ModelError {
    #[error("invalid model registration: {0}")]
    Registration(String),
    #[error("invalid model JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("model artifact {artifact}: {source}")]
    Io {
        artifact: String,
        source: std::io::Error,
    },
    #[error("model artifact missing or changed: {0}")]
    Artifact(String),
    #[error("invalid model tokenizer: {0}")]
    Tokenizer(String),
    #[error("invalid model weights: {0}")]
    Weights(String),
    #[error("model inference failed: {0}")]
    Inference(String),
}
