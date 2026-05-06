//! Production embedder backed by `fastembed-rs` (ONNX Runtime).
//!
//! Default model: `all-MiniLM-L6-v2` **quantized** (`AllMiniLML6V2Q`,
//! 384 dims, Apache 2.0). Same model infinidev runs in production. The
//! quantized variant is ~5–10× faster on CPU than nomic-embed-text-v1.5
//! and uses ~3× less memory at the cost of slightly lower retrieval
//! quality on long-form text. Good enough for code / chunk search and
//! light enough to run on a developer laptop.
//!
//! `AllMiniLML6V2Q` is **symmetric** — query and passage encodings use
//! the same forward pass, so we don't prepend a task prefix.
//!
//! # Memory
//!
//! Two knobs matter for ingest stability — both addressing **ORT runtime
//! memory growth**, which is invisible to Rust's allocator (mimalloc can't
//! reclaim ORT's internal arenas):
//!
//! - `KEN_EMBED_BATCH_SIZE` (default 64): cap on inputs per `embed()` call.
//!   Larger batches grow the ORT working set; we split the caller's slice
//!   into sub-batches of this size and call `embed(_, None)` per piece.
//!   Each call computes its own dynamic-quant range, which is acceptable
//!   for cosine retrieval (post-L2 normalisation makes the small range
//!   drift irrelevant).
//! - `reset()` (called by ingest paths every N files): drops the entire
//!   ONNX session and rebuilds it. Releases ORT's accumulated state back
//!   to the OS — the only known way to bound RSS during long ingests.
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
//! | value         | model                       | dim | speed (CPU)  | notes                                  |
//! |---------------|-----------------------------|-----|--------------|----------------------------------------|
//! | `mini-q`      | `AllMiniLML6V2Q` (default)  | 384 | fastest      | symmetric, low memory                  |
//! | `bge-small-q` | `BGESmallENV15Q`            | 384 | ~2× mini     | symmetric, slightly better on prose    |
//!
//! Both options match the schema's `vector(384)` columns. Larger models
//! (`NomicEmbedTextV15`, etc.) used to live here; they were removed when
//! the schema migrated to 384 dims (migration 0005). Bringing back a
//! 768-dim model means writing another migration first.
//!
//! See `docs/04-storage.md` for the rationale behind the 384-dim choice.

use std::sync::Mutex;

use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};

use crate::embed::{l2_normalize, Embedder};

/// 384 — matches the schema's `vector(384)` columns. Both supported
/// models (`mini-q`, `bge-small-q`) emit 384-dim vectors; the schema
/// is hard-coded for v2 (post-migration 0005).
pub const EMBED_DIM: usize = 384;

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
    /// Stored so `reset()` can rebuild the same model variant.
    model: EmbeddingModel,
    /// Cap on input size handed to a single `fastembed.embed()` call. Larger
    /// inputs are split into sub-batches of this size externally. Bounds the
    /// per-call ORT working set so a file with hundreds of chunks doesn't
    /// balloon ORT's internal buffers in one go.
    batch_size: usize,
}

impl FastEmbedder {
    /// Build the production embedder. Picks the model from `KEN_EMBEDDER_MODEL`
    /// (defaults to `mini-q`). Triggers a one-time download to the fastembed
    /// cache on first run.
    pub fn from_env() -> Result<Self, FastEmbedderError> {
        let key = std::env::var("KEN_EMBEDDER_MODEL")
            .unwrap_or_else(|_| "mini-q".to_string())
            .to_ascii_lowercase();
        let (model, dim, label) = match key.as_str() {
            "mini-q" | "minilm-q" | "all-mini-q" | "" => {
                (EmbeddingModel::AllMiniLML6V2Q, 384, "mini-q")
            }
            "bge-small-q" | "bge_small_q" | "bge-small" => {
                (EmbeddingModel::BGESmallENV15Q, 384, "bge-small-q")
            }
            other => {
                return Err(FastEmbedderError::Init(format!(
                    "unknown KEN_EMBEDDER_MODEL={other:?}; valid: mini-q (default, 384d), bge-small-q (384d)"
                )));
            }
        };
        let batch_size = read_batch_size_env();
        tracing::info!(model = %label, dim, batch_size, "loading FastEmbedder");
        let inner = TextEmbedding::try_new(InitOptions::new(model.clone()))
            .map_err(|e| FastEmbedderError::Init(e.to_string()))?;
        Ok(Self {
            inner: Mutex::new(inner),
            dim,
            model,
            batch_size,
        })
    }

    /// Build a `FastEmbedder` for `AllMiniLML6V2Q` (the default). Kept as
    /// an explicit constructor for tests that need to bypass env config.
    pub fn mini_q() -> Result<Self, FastEmbedderError> {
        let model = EmbeddingModel::AllMiniLML6V2Q;
        let inner = TextEmbedding::try_new(InitOptions::new(model.clone()))
            .map_err(|e| FastEmbedderError::Init(e.to_string()))?;
        Ok(Self {
            inner: Mutex::new(inner),
            dim: EMBED_DIM,
            model,
            batch_size: read_batch_size_env(),
        })
    }

    fn embed_one_batch(&self, texts: Vec<String>, expected: usize) -> Option<Vec<Vec<f32>>> {
        // Single call into fastembed for one sub-batch. We always pass `None`
        // for fastembed's batch_size argument — the supported models are
        // dynamically quantised and fastembed hard-rejects an explicit
        // `Some(_)` for those. We do our own external batching instead.
        let mut guard = self.inner.lock().expect("FastEmbedder mutex poisoned");
        match guard.embed(texts, None) {
            Ok(v) => {
                if v.len() != expected {
                    tracing::error!(
                        expected,
                        got = v.len(),
                        "fastembed returned wrong vector count"
                    );
                    return None;
                }
                Some(v)
            }
            Err(e) => {
                tracing::error!(error = %e, n = expected, "fastembed inference failed");
                None
            }
        }
    }

    fn embed_batch(&self, texts: &[&str]) -> Vec<Vec<f32>> {
        // Split the caller's slice into sub-batches of `self.batch_size` and
        // call fastembed once per piece. On any sub-batch failure we return
        // `Vec::new()` — the caller (ingest_uri) detects the length mismatch
        // and bails the file as an adapter error, which is the right thing:
        // partial embeddings would silently corrupt retrieval.
        let mut out: Vec<Vec<f32>> = Vec::with_capacity(texts.len());
        for sub in texts.chunks(self.batch_size.max(1)) {
            let owned: Vec<String> = sub.iter().map(|t| t.to_string()).collect();
            match self.embed_one_batch(owned, sub.len()) {
                Some(v) => out.extend(v),
                None => return Vec::new(),
            }
        }
        for v in out.iter_mut() {
            l2_normalize(v);
        }
        out
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
        self.embed_batch(texts)
    }

    fn embed_query(&self, text: &str) -> Vec<f32> {
        self.embed_batch(&[text])
            .into_iter()
            .next()
            .unwrap_or_else(|| vec![0.0; self.dim])
    }

    fn reset(&self) -> Result<(), String> {
        // Drop the existing TextEmbedding (which owns the ONNX session and
        // ORT's per-session arenas) and build a fresh one. This is the only
        // reliable way to reclaim ORT's accumulated working memory during a
        // long-running ingest — that memory lives outside Rust's allocator.
        let new_inner = TextEmbedding::try_new(InitOptions::new(self.model.clone()))
            .map_err(|e| format!("reset failed: {e}"))?;
        let mut guard = self.inner.lock().map_err(|_| "FastEmbedder mutex poisoned")?;
        *guard = new_inner;
        Ok(())
    }
}

fn read_batch_size_env() -> usize {
    std::env::var("KEN_EMBED_BATCH_SIZE")
        .ok()
        .and_then(|v| v.parse().ok())
        .filter(|n: &usize| *n > 0)
        .unwrap_or(64)
}
