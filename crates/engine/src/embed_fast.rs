//! Production embedder backed by `fastembed-rs` (ONNX Runtime).
//!
//! Default model: `nomic-embed-text-v1.5` **quantized** (`NomicEmbedTextV15Q`,
//! 768 dims, Apache 2.0). The quantized variant lives in the same embedding
//! space as the full-precision model — cosine similarity drift is well
//! under 1% on benchmarks — but runs ~2× faster on CPU. Same schema, no
//! migration needed.
//!
//! The model is **asymmetric** — it produces different vectors for documents
//! being indexed vs queries being issued. We apply the canonical
//! `search_document:` and `search_query:` prefixes ourselves; fastembed-rs
//! does not auto-prefix.
//!
//! On first construction the model files are downloaded from HuggingFace
//! into `~/.cache/fastembed_cache` (override via `FASTEMBED_CACHE_DIR`); the
//! ONNX session is held for the process lifetime. Each `embed_*` call runs
//! synchronously and is CPU-bound — callers in async contexts must dispatch
//! via `tokio::task::spawn_blocking`.
//!
//! # Picking a model
//!
//! Set `KEN_EMBEDDER_MODEL` to one of:
//!
//! | value         | model                          | dim | speed (CPU) | notes                                  |
//! |---------------|--------------------------------|-----|-------------|----------------------------------------|
//! | `nomic-q`     | `NomicEmbedTextV15Q` (default) | 768 | ~2× nomic   | quantized, same schema as `nomic`      |
//! | `nomic`       | `NomicEmbedTextV15`            | 768 | baseline    | full precision                         |
//! | `bge-small-q` | `BGESmallENV15Q`               | 384 | ~5-10×      | needs DB wipe — different dim          |
//! | `mini-q`      | `AllMiniLML6V2Q`               | 384 | fastest     | needs DB wipe — different dim, less acc |
//!
//! Switching between same-dim models (`nomic` ↔ `nomic-q`) is free: queries
//! still compare to existing chunk embeddings since the latent space is
//! shared. Switching dim (`bge-small-q`, `mini-q`) requires wiping the
//! `vector(768)` columns; the schema is hard-coded for v1.

use std::sync::Mutex;

use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};

use crate::embed::{l2_normalize, Embedder};

/// Prefixes nomic-embed-text-v1.5 (and v1) expects for asymmetric search.
/// Other tasks (`classification:`, `clustering:`) are not used here.
const PASSAGE_PREFIX: &str = "search_document: ";
const QUERY_PREFIX: &str = "search_query: ";

/// 768 — the schema's `vector(768)` columns are sized for this. Models with
/// different dims live behind a feature flag in the model selector below
/// and require a one-shot DB migration before they can be used.
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
    /// Some embedders (BGE, all-MiniLM) don't take asymmetric query/passage
    /// prefixes. We track that so `embed_with_prefix` can no-op the prefix
    /// when irrelevant.
    asymmetric: bool,
}

impl FastEmbedder {
    /// Build the production embedder. Picks the model from `KEN_EMBEDDER_MODEL`
    /// (defaults to `nomic-q`). Triggers a one-time download to the fastembed
    /// cache on first run.
    pub fn from_env() -> Result<Self, FastEmbedderError> {
        let key = std::env::var("KEN_EMBEDDER_MODEL")
            .unwrap_or_else(|_| "nomic-q".to_string())
            .to_ascii_lowercase();
        let (model, dim, asymmetric, label) = match key.as_str() {
            "nomic-q" | "nomic_q" | "nomicq" | "" => {
                (EmbeddingModel::NomicEmbedTextV15Q, 768, true, "nomic-q")
            }
            "nomic" => (EmbeddingModel::NomicEmbedTextV15, 768, true, "nomic"),
            "bge-small-q" | "bge_small_q" | "bge-small" => {
                (EmbeddingModel::BGESmallENV15Q, 384, false, "bge-small-q")
            }
            "mini-q" | "minilm-q" | "all-mini-q" => {
                (EmbeddingModel::AllMiniLML6V2Q, 384, false, "mini-q")
            }
            other => {
                return Err(FastEmbedderError::Init(format!(
                    "unknown KEN_EMBEDDER_MODEL={other:?}; valid: nomic-q (default), nomic, bge-small-q, mini-q"
                )));
            }
        };
        tracing::info!(model = %label, dim, asymmetric, "loading FastEmbedder");
        let model =
            TextEmbedding::try_new(InitOptions::new(model)).map_err(|e| FastEmbedderError::Init(e.to_string()))?;
        Ok(Self {
            inner: Mutex::new(model),
            dim,
            asymmetric,
        })
    }

    /// Build a `FastEmbedder` for `nomic-embed-text-v1.5` (full precision).
    /// Kept for backwards compat / explicit tests; the env-driven
    /// [`from_env`] is the preferred entry point.
    pub fn nomic_v15() -> Result<Self, FastEmbedderError> {
        let model = TextEmbedding::try_new(InitOptions::new(EmbeddingModel::NomicEmbedTextV15))
            .map_err(|e| FastEmbedderError::Init(e.to_string()))?;
        Ok(Self {
            inner: Mutex::new(model),
            dim: NOMIC_V15_DIM,
            asymmetric: true,
        })
    }

    fn embed_with_prefix(&self, prefix: &str, texts: &[&str]) -> Vec<Vec<f32>> {
        // Only nomic-style models want the asymmetric prefix; BGE / MiniLM
        // are trained without one. Pre-format once to keep the inner allocs
        // out of the mutex critical section.
        let prefixed: Vec<String> = if self.asymmetric {
            texts.iter().map(|t| format!("{prefix}{t}")).collect()
        } else {
            texts.iter().map(|t| t.to_string()).collect()
        };
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
