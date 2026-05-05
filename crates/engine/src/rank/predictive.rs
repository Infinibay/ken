//! Predictive channel: scores targets that were *productive* in past
//! sessions whose context resembles the current query.
//!
//! Algorithm:
//!   1. Pull recent context embeddings from past sessions (excluding the
//!      current one), within a `lookback_days` window.
//!   2. Group them by `session_id` and, per session, compute the **max**
//!      cosine similarity between the query embedding and any context in
//!      that session.
//!   3. For sessions that clear `min_similarity`, fetch the
//!      `session_scores` snapshot (per-target productivity) and emit a hit
//!      per target with score
//!         `sim² × session_decay × edit_mult × productivity`
//!      where `session_decay = base^(days_ago / 7)`.
//!
//! The `sim²` exponent (vs raw `sim`) is the v3 trick from infinidev:
//! high-confidence matches dominate naturally, low-confidence noise dies off
//! quadratically.

use ahash::AHashMap;

use crate::postgres::PostgresStorage;
use crate::rank::merge::ChannelHit;
use crate::storage::now_millis;
use crate::types::{NodeRef, SessionId, WorkspaceId};

#[derive(Debug, Clone)]
pub struct PredictiveConfig {
    pub lookback_days: u64,
    pub min_similarity: f32,
    /// Weekly decay base. `0.5` halves a session's contribution every 7 days.
    pub session_decay_base: f32,
    /// Multiplier for targets that were edited in the past session.
    pub edit_multiplier: f32,
    /// Hard cap on how many past sessions to consider (most-similar first).
    /// Beyond this the tail contributions wouldn't survive the per-session
    /// decay anyway, and pulling more session_scores has cost.
    pub top_n_sessions: u32,
}

impl Default for PredictiveConfig {
    fn default() -> Self {
        Self {
            lookback_days: 180,
            min_similarity: 0.3,
            session_decay_base: 0.5,
            edit_multiplier: 2.0,
            top_n_sessions: 64,
        }
    }
}

pub async fn predictive_scores(
    storage: &PostgresStorage,
    workspace: WorkspaceId,
    current_session: SessionId,
    query_embedding: &[f32],
    cfg: &PredictiveConfig,
) -> Vec<ChannelHit> {
    let now = now_millis();
    let cutoff = now.saturating_sub(cfg.lookback_days.saturating_mul(86_400_000));

    // Postgres does the cosine + per-session aggregation, returning only
    // (session_id, max_sim, last_ts). Replaces the old "pull every recent
    // 768-dim embedding to app memory" pattern that was HIGH-5 in the audit.
    let passing = storage
        .recent_session_max_sims(
            workspace,
            query_embedding,
            cutoff,
            Some(current_session),
            cfg.min_similarity,
            cfg.top_n_sessions,
        )
        .await;
    if passing.is_empty() {
        return Vec::new();
    }
    let session_ids: Vec<SessionId> = passing.iter().map(|(sid, _, _)| *sid).collect();
    let all_scores = storage.session_scores_for_sessions(&session_ids).await;

    // Index per-session metadata for O(1) lookup while iterating scores.
    let mut session_meta: AHashMap<SessionId, (f32, f32)> = AHashMap::with_capacity(passing.len());
    for (sid, max_sim, last_ts) in &passing {
        let days_ago = now.saturating_sub(*last_ts) as f32 / 86_400_000.0;
        let session_decay = cfg.session_decay_base.powf(days_ago / 7.0);
        session_meta.insert(*sid, (*max_sim, session_decay));
    }

    let mut accum: AHashMap<NodeRef, (f32, String)> = AHashMap::new();
    for s in all_scores {
        let Some(&(max_sim, session_decay)) = session_meta.get(&s.session_id) else {
            continue;
        };
        let edit_mult = if s.was_edited { cfg.edit_multiplier } else { 1.0 };
        let contribution =
            max_sim.powi(2) * session_decay * edit_mult * s.productivity.max(0.0);
        if contribution <= 0.0 {
            continue;
        }
        let entry = accum
            .entry(s.target.clone())
            .or_insert((0.0, String::new()));
        entry.0 += contribution;
        if entry.1.is_empty() {
            entry.1 = format!(
                "past sim={:.2} prod={:.2} pat={:?}",
                max_sim, s.productivity, s.pattern
            );
        }
    }

    accum
        .into_iter()
        .map(|(target, (score, reason))| ChannelHit { target, score, reason })
        .collect()
}
