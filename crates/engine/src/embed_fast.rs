//! Production embedder backed by `fastembed-rs` (ONNX Runtime).
//!
//! Default model: `nomic-embed-text-v1.5` (768 dims, Apache 2.0). The model
//! is **asymmetric** — it produces different vectors for documents being
//! indexed vs queries being issued. We apply the canonical `search_document:`
//! and `search_query:` prefixes ourselves; fastembed-rs does not auto-prefix.
//!
//! On first construction the model files are downloaded from HuggingFace
//! into `~/.cache/fastembed_cache` (override via `FASTEMBED_CACHE_DIR`); the
//! ONNX session is held for the process lifetime. Each `embed_*` call runs
//! synchronously and is CPU-bound — callers in async contexts must dispatch
//! via `tokio::task::spawn_blocking`.

use std::sync::Mutex;

use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};

use crate::embed::{l2_normalize, Embedder};

/// Prefixes nomic-embed-text-v1.5 (and v1) expects for asymmetric search.
/// Other tasks (`classification:`, `clustering:`) are not used here.
const PASSAGE_PREFIX: &str = "search_document: ";
const QUERY_PREFIX: &str = "search_query: ";

/// 768 — `nomic-embed-text-v1.5`. Other supported models with different
/// dimensions would require a schema migration on the `vector(768)` columns.
pub const NOMIC_V15_DIM: usize = 768;

#[derive(Debug, thiserror::Error)]
pub enum FastEmbedderError {
    #[error("model init failed: {0}")]
    Init(String),
    #[error("inference failed: {0}")]
    Inference(String),
}

pub struct FastEmbedder {
    inner: Mutex<TextEmbedding>,
    dim: usize,
}

impl FastEmbedder {
    /// Build a `FastEmbedder` for `nomic-embed-text-v1.5`. Triggers model
    /// download on first call (cached afterward).
    pub fn nomic_v15() -> Result<Self, FastEmbedderError> {
        let model = TextEmbedding::try_new(InitOptions::new(EmbeddingModel::NomicEmbedTextV15))
            .map_err(|e| FastEmbedderError::Init(e.to_string()))?;
        Ok(Self {
            inner: Mutex::new(model),
            dim: NOMIC_V15_DIM,
        })
    }

    fn embed_with_prefix(&self, prefix: &str, texts: &[&str]) -> Vec<Vec<f32>> {
        let prefixed: Vec<String> = texts.iter().map(|t| format!("{prefix}{t}")).collect();
        let mut guard = self.inner.lock().expect("FastEmbedder mutex poisoned");
        let result = guard
            .embed(prefixed, None)
            .unwrap_or_else(|e| {
                tracing::error!(error = %e, "fastembed inference failed; returning zero vectors");
                vec![vec![0.0; self.dim]; texts.len()]
            });
        result
            .into_iter()
            .map(|mut v| {
                l2_normalize(&mut v);
                v
            })
            .collect()
    }
}

impl Embedder for FastEmbedder {
    fn dim(&self) -> usize {
        self.dim
    }

    fn embed_passages(&self, texts: &[&str]) -> Vec<Vec<f32>> {
        if texts.is_empty() {
            return Vec::new();
        }
        self.embed_with_prefix(PASSAGE_PREFIX, texts)
    }

    fn embed_query(&self, text: &str) -> Vec<f32> {
        self.embed_with_prefix(QUERY_PREFIX, &[text])
            .into_iter()
            .next()
            .unwrap_or_else(|| vec![0.0; self.dim])
    }
}
