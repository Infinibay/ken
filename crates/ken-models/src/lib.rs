//! Verified native model execution, independent of project discovery and storage.
mod assets;
mod context_encoder;
mod context_model;
mod model2vec;
mod native_onnx;
mod static_table;
mod table_npz;
mod term_cache;
mod tokenization;
mod verified_file;

pub use assets::{ModelAssets, VerifiedSnapshot};
pub use context_encoder::{ContextEncoder, ContextInput, ContextTokens};
pub use context_model::ContextModel;
pub use model2vec::Model2VecEncoder;
pub use native_onnx::{NativeOnnxRuntime, RuntimeIdentity};
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
    #[error("native ONNX runtime: {0}")]
    Runtime(String),
}
