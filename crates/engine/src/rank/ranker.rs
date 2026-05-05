//! Public ranker — composes reactive + predictive + semantic + merge.
//!
//! ```text
//! query_embedding ─┐
//!                  ├─ reactive(session)         ─┐
//!                  ├─ predictive(workspace)     ─┴─ alpha-blend ─┐
//!                  └─ semantic(pgvector top-K)                   ├─ max-merge → confidence + MAD → top-K
//! ```
//!
//! The caller pre-computes the query embedding (so HTTP handlers can
//! dispatch the heavy ONNX call into `tokio::task::spawn_blocking` and so
//! the same embedding can be reused across iterations of a session — see
//! the latency budget in `docs/03-ranking.md`).

use crate::postgres::PostgresStorage;
use crate::rank::merge::{
    apply_confidence_and_mad, blend_reactive_predictive, max_merge, MergeConfig, RankItem,
};
use crate::rank::predictive::{predictive_scores, PredictiveConfig};
use crate::rank::reactive::{reactive_scores, ReactiveConfig};
use crate::rank::semantic::{semantic_scores, SemanticConfig};
use crate::types::{SessionId, WorkspaceId};

#[derive(Debug, Clone, Default)]
pub struct RankerConfig {
    pub reactive: ReactiveConfig,
    pub predictive: PredictiveConfig,
    pub semantic: SemanticConfig,
    pub merge: MergeConfig,
}

#[derive(Debug, Clone)]
pub struct RankRequest {
    pub workspace: WorkspaceId,
    pub session: SessionId,
    /// Query embedded with the **query**-side prefix of the active model.
    /// Callers are responsible for using `Embedder::embed_query` (which is
    /// async-safe because it can run inside `spawn_blocking`).
    pub query_embedding: Vec<f32>,
    pub iteration: u32,
}

#[derive(Debug, Clone)]
pub struct RankResult {
    pub items: Vec<RankItem>,
}

pub struct Ranker<'a> {
    storage: &'a PostgresStorage,
    config: RankerConfig,
}

impl<'a> Ranker<'a> {
    pub fn new(storage: &'a PostgresStorage) -> Self {
        Self { storage, config: RankerConfig::default() }
    }

    pub fn with_config(mut self, config: RankerConfig) -> Self {
        self.config = config;
        self
    }

    pub async fn rank(&self, req: RankRequest) -> RankResult {
        // Channels run concurrently — they share `&self` but no &mut state.
        let (reactive, predictive, semantic) = tokio::join!(
            reactive_scores(self.storage, req.session, req.iteration, &self.config.reactive),
            predictive_scores(
                self.storage,
                req.workspace,
                req.session,
                &req.query_embedding,
                &self.config.predictive,
            ),
            semantic_scores(self.storage, req.workspace, &req.query_embedding, &self.config.semantic),
        );

        let blended = blend_reactive_predictive(reactive, predictive, req.iteration, &self.config.merge);
        let merged = max_merge(vec![blended, semantic]);
        let items = apply_confidence_and_mad(merged, &self.config.merge);
        RankResult { items }
    }
}
