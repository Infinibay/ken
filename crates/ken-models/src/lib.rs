//! Verified native model execution, independent of project discovery and storage.
mod assets;
mod context_encoder;
mod context_model;
mod embedding_pool;
mod fastembed_encoder;
mod fastembed_model;
mod fastembed_session;
mod fastembed_tokens;
mod file_assets;
mod model2vec;
pub mod model_policy;
mod native_onnx;
mod onnx_dependencies;
mod onnx_providers;
mod onnx_reranker;
mod onnx_wire;
mod published_head;
mod python_unicode;
mod query_expansion;
mod query_policy;
mod reranker_model;
mod reranker_preparation;
mod reranker_tokens;
mod static_table;
mod table_npz;
mod term_cache;
mod tokenization;
mod transformer_client;
mod transformer_model;
mod transformer_runtime;
mod transformer_session;
mod translation_json;
mod translation_model;
mod translation_preparation;
mod verified_file;

pub use assets::{ModelAssets, VerifiedSnapshot};
pub use context_encoder::{ContextEncoder, ContextInput, ContextTokens};
pub use context_model::ContextModel;
pub use fastembed_encoder::{FastEmbedEncoder, FastEmbedRun};
pub use fastembed_model::{FastEmbedCatalog, FastEmbedModel, FastEmbedNotice};
pub use fastembed_session::{
    EmbeddingBatch, EmbeddingSession, FastEmbedBatchTrace, FastEmbedPreparation,
    FastEmbedProviderAttempt, FastEmbedTensorI64,
};
pub use fastembed_tokens::{FastEmbedInput, FastEmbedTokenizer, FastEmbedTokens};
pub use file_assets::{ModelFileSource, VerifiedModelFiles};
pub use ken_native_model_api::{
    TransformerArchitecture, TransformerBatch, TransformerDevice, TransformerDeviceRequest,
    TransformerDtype, TransformerOutput, TransformerPooling, TransformerWeightLayout,
};
pub use model2vec::Model2VecEncoder;
pub use native_onnx::{NativeOnnxRuntime, RuntimeIdentity};
pub use onnx_dependencies::verify_onnx_dependencies;
pub use onnx_providers::{FastEmbedDevice, FastEmbedDeviceRequest};
pub use onnx_reranker::{
    OnnxReranker, RerankDetails, RerankOptions, RerankSessionPolicy, ScoredPool,
};
pub use published_head::compile_head;
pub use query_expansion::{
    ExpandedQuery, ExpansionAttempt, LocalQueryExpansion, TranslationInput,
    TranslationRuntimeIdentity, TranslationTokens, TranslationTrace,
};
pub use query_policy::{ProtectedQuery, QueryExpansionPlan, plan_query};
pub use reranker_model::{PreparedReranker, RerankerModel};
pub use reranker_tokens::PairTokens;
pub use static_table::StaticTableEncoder;
pub use tokenization::ModelTokenizer;
pub use transformer_model::{TransformerModel, TransformerRole, TransformerSettings};
pub use transformer_runtime::{
    NativeTransformerRuntime, TransformerNativeArtifact, TransformerRuntimeIdentity,
};
pub use transformer_session::{TransformerBatchResult, TransformerSession, TransformerTrace};
pub use translation_model::{FrozenTranslationRuntime, PreparedTranslation, TranslationModel};

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

mod transformer_order;

mod transformer_tokens;

pub use transformer_tokens::{PreparedTransformerText, TransformerTokens};

mod sentence_encoder;

pub use sentence_encoder::{SentenceEncoder, TransformerPreparation};

#[cfg(test)]
mod transformer_test_support;

mod mlx_encoder;
pub use mlx_encoder::MLXEncoder;
