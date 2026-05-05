//! Semantic channel: cosine similarity between the query embedding and
//! every chunk in the workspace, served by pgvector's HNSW index.
//!
//! Score for an accepted chunk is `(sim - min_similarity) × scale`:
//! linear above the threshold, zero below. Anything that doesn't clear
//! `min_similarity` is dropped (the noise filter — most chunks have weak
//! cosine to any random query).

use crate::postgres::PostgresStorage;
use crate::rank::merge::ChannelHit;
use crate::types::{NodeRef, WorkspaceId};

#[derive(Debug, Clone)]
pub struct SemanticConfig {
    /// pgvector returns top-K rows by `<=>` distance — we ask for `top_k`
    /// candidates and then post-filter by `min_similarity`. K is the upper
    /// bound on how many semantic hits one rank call inspects.
    pub top_k: u32,
    /// Cosine similarity floor. Below this we treat the match as noise.
    pub min_similarity: f32,
    /// Multiplier from raw above-threshold similarity to channel score —
    /// brings semantic into the same range as reactive/predictive.
    pub scale: f32,
    /// Restrict to chunks whose owning document is `current=TRUE`.
    pub current_only: bool,
}

impl Default for SemanticConfig {
    fn default() -> Self {
        Self {
            top_k: 200,
            min_similarity: 0.4,
            scale: 3.0,
            current_only: true,
        }
    }
}

pub async fn semantic_scores(
    storage: &PostgresStorage,
    workspace: WorkspaceId,
    query_embedding: &[f32],
    cfg: &SemanticConfig,
) -> Vec<ChannelHit> {
    let hits = storage
        .semantic_search_chunks(workspace, query_embedding, cfg.top_k, cfg.current_only)
        .await;
    hits.into_iter()
        .filter(|(_, sim)| *sim >= cfg.min_similarity)
        .map(|(cid, sim)| ChannelHit {
            target: NodeRef::Chunk(cid),
            score: (sim - cfg.min_similarity) * cfg.scale,
            reason: format!("semantic sim={:.3}", sim),
        })
        .collect()
}
