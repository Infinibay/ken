//! Channel merging and post-filters.
//!
//! Pure functions over `Vec<ChannelHit>` — no DB. Three stages:
//!
//! 1. `blend_reactive_predictive(reactive, predictive, iteration, …)` —
//!    saturating alpha blend; reactive grows with session iteration but never
//!    fully eclipses predictive (cap = 0.85). If reactive is sparse, alpha
//!    is dampened so we don't trust shaky early signals.
//! 2. `max_merge(channels)` — per-target `max` across channels. Preserves the
//!    reason of the channel that "won". Avoids spuriously stacking weak
//!    signals into a high score.
//! 3. `apply_confidence_and_mad(items, …)` — reject the whole result if no
//!    score clears the gate; otherwise drop long-tail items below a
//!    `bottom_median + K × MAD × 1.4826` threshold.
//!
//! Defaults follow infinidev v3 (`docs/03-ranking.md`). Constants are tunable
//! through the `MergeConfig` struct.

use ahash::AHashMap;
use ordered_float::OrderedFloat;

use crate::rank::stats::{mad, median, normal_inv_cdf, MAD_TO_STDDEV};
use crate::types::NodeRef;

/// One channel's verdict on one target.
#[derive(Debug, Clone)]
pub struct ChannelHit {
    pub target: NodeRef,
    pub score: f32,
    pub reason: String,
}

/// Final ranker output row.
#[derive(Debug, Clone)]
pub struct RankItem {
    pub target: NodeRef,
    pub score: f32,
    pub reason: String,
}

#[derive(Debug, Clone)]
pub struct MergeConfig {
    /// Cap on reactive's share of the blend even at saturation. Predictive
    /// always retains at least `1 - alpha_max` weight.
    pub alpha_max: f32,
    /// Iteration at which alpha hits `alpha_max` (linear ramp from 0).
    pub alpha_saturate_iter: u32,
    /// If reactive contributed fewer than this many distinct targets, halve
    /// alpha. Avoids letting a single shaky reactive hit dominate.
    pub alpha_min_reactive_signals: usize,
    pub alpha_sparse_dampening: f32,
    /// If max raw score across all channels is below this, return empty.
    pub confidence_gate: f32,
    /// One-sided percentile for the MAD outlier filter. `0.95` ⇒ K ≈ 1.6449.
    pub mad_percentile: f64,
    /// Hard cap on how many items the ranker returns (taken AFTER the MAD
    /// filter; `0` disables the cap).
    pub top_k: usize,
}

impl Default for MergeConfig {
    fn default() -> Self {
        Self {
            alpha_max: 0.85,
            alpha_saturate_iter: 8,
            alpha_min_reactive_signals: 3,
            alpha_sparse_dampening: 0.5,
            confidence_gate: 0.5,
            mad_percentile: 0.95,
            top_k: 50,
        }
    }
}

/// Compute the reactive-vs-predictive blend coefficient for the given
/// iteration. Linear ramp from 0 (cold start: trust history) to `alpha_max`
/// (mid session: trust the current trajectory). Damped by half if reactive
/// is sparse.
pub fn compute_alpha(
    iteration: u32,
    reactive_signal_count: usize,
    cfg: &MergeConfig,
) -> f32 {
    let saturate = cfg.alpha_saturate_iter.max(1) as f32;
    let raw = (iteration as f32 / saturate).min(cfg.alpha_max);
    if reactive_signal_count < cfg.alpha_min_reactive_signals {
        raw * cfg.alpha_sparse_dampening
    } else {
        raw
    }
}

/// Blend two channels (reactive, predictive) into a single ChannelHit list.
/// Per-target: `alpha × reactive + (1 - alpha) × predictive`. Targets present
/// in only one channel still contribute (the missing side is treated as 0).
pub fn blend_reactive_predictive(
    reactive: Vec<ChannelHit>,
    predictive: Vec<ChannelHit>,
    iteration: u32,
    cfg: &MergeConfig,
) -> Vec<ChannelHit> {
    let alpha = compute_alpha(iteration, reactive.len(), cfg);
    let beta = 1.0 - alpha;

    let mut by_target: AHashMap<NodeRef, ChannelHit> = AHashMap::new();
    for hit in reactive {
        by_target.insert(
            hit.target.clone(),
            ChannelHit {
                target: hit.target,
                score: alpha * hit.score,
                reason: format!("reactive(α={alpha:.2}): {}", hit.reason),
            },
        );
    }
    for hit in predictive {
        by_target
            .entry(hit.target.clone())
            .and_modify(|existing| {
                existing.score += beta * hit.score;
                existing.reason = format!(
                    "{} | predictive(β={beta:.2}): {}",
                    existing.reason, hit.reason
                );
            })
            .or_insert(ChannelHit {
                target: hit.target,
                score: beta * hit.score,
                reason: format!("predictive(β={beta:.2}): {}", hit.reason),
            });
    }
    by_target.into_values().collect()
}

/// Per-target `max` across N channels. Preserves the reason of the
/// highest-scoring channel for that target. Channels passed in here have
/// already been blended where appropriate (e.g. reactive+predictive).
pub fn max_merge(channels: Vec<Vec<ChannelHit>>) -> Vec<ChannelHit> {
    let mut by_target: AHashMap<NodeRef, ChannelHit> = AHashMap::new();
    for channel in channels {
        for hit in channel {
            by_target
                .entry(hit.target.clone())
                .and_modify(|existing| {
                    if hit.score > existing.score {
                        existing.score = hit.score;
                        existing.reason = hit.reason.clone();
                    }
                })
                .or_insert(hit);
        }
    }
    by_target.into_values().collect()
}

/// Apply confidence gate + MAD outlier filter, then sort desc and trim to
/// `top_k`. Returns `Vec::new()` if the confidence gate rejects the result.
pub fn apply_confidence_and_mad(
    mut items: Vec<ChannelHit>,
    cfg: &MergeConfig,
) -> Vec<RankItem> {
    if items.is_empty() {
        return Vec::new();
    }

    let max_score = items.iter().map(|i| i.score).fold(f32::NEG_INFINITY, f32::max);
    if max_score < cfg.confidence_gate {
        return Vec::new();
    }

    items.sort_by_key(|i| std::cmp::Reverse(OrderedFloat(i.score)));

    let threshold = mad_threshold(&items, cfg.mad_percentile);
    let mut kept: Vec<RankItem> = items
        .into_iter()
        .filter(|i| i.score >= threshold)
        .map(|i| RankItem {
            target: i.target,
            score: i.score,
            reason: i.reason,
        })
        .collect();

    if cfg.top_k > 0 && kept.len() > cfg.top_k {
        kept.truncate(cfg.top_k);
    }
    kept
}

/// Compute the MAD-based cutoff. Uses the BOTTOM half of scores as the
/// baseline (so a few high outliers don't inflate `MAD` and bury themselves).
/// Mirrors infinidev v3.
fn mad_threshold(items_sorted_desc: &[ChannelHit], percentile: f64) -> f32 {
    if items_sorted_desc.len() < 4 {
        // Too few items for a stable MAD estimate; keep them all.
        return f32::NEG_INFINITY;
    }
    let n = items_sorted_desc.len();
    let max_score = items_sorted_desc[0].score;
    let bottom: Vec<f32> = items_sorted_desc
        .iter()
        .skip(n / 2)
        .map(|i| i.score)
        .collect();
    let Some(med) = median(&bottom) else { return f32::NEG_INFINITY };
    let Some(spread) = mad(&bottom) else { return f32::NEG_INFINITY };
    let raw_threshold = if spread < 0.05 {
        // Degenerate baseline (everything in the bottom half is essentially
        // identical). Fall back to a multiplicative ratio test: keep items
        // ≥ 2× the bottom median.
        (2.0 * med).max(0.0)
    } else {
        let k = normal_inv_cdf(percentile).unwrap_or(1.6449) as f32;
        med + k * spread * MAD_TO_STDDEV
    };
    // Guard: if the threshold would reject everything (top score below it),
    // there is no real long tail to trim — keep all items. This handles the
    // tightly-clustered embedding case (common in single-domain code
    // corpora) where 2×median exceeds max(score).
    if raw_threshold > max_score {
        f32::NEG_INFINITY
    } else {
        raw_threshold
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{ChunkId, DocumentId};

    fn doc(id: u64) -> NodeRef {
        NodeRef::Document(DocumentId(id))
    }
    fn chunk(id: u64) -> NodeRef {
        NodeRef::Chunk(ChunkId(id))
    }
    fn hit(target: NodeRef, score: f32, reason: &str) -> ChannelHit {
        ChannelHit { target, score, reason: reason.into() }
    }

    #[test]
    fn alpha_zero_at_iteration_zero() {
        let cfg = MergeConfig::default();
        assert_eq!(compute_alpha(0, 10, &cfg), 0.0);
    }

    #[test]
    fn alpha_saturates_at_alpha_max() {
        let cfg = MergeConfig::default();
        let a = compute_alpha(100, 10, &cfg);
        assert!((a - cfg.alpha_max).abs() < 1e-6);
    }

    #[test]
    fn alpha_dampened_when_reactive_sparse() {
        let cfg = MergeConfig::default();
        let dampened = compute_alpha(8, 1, &cfg); // < min_reactive_signals
        let full = compute_alpha(8, 5, &cfg);
        assert!(dampened < full);
        assert!((dampened - full * cfg.alpha_sparse_dampening).abs() < 1e-6);
    }

    #[test]
    fn blend_combines_overlapping_targets() {
        let cfg = MergeConfig::default();
        let r = vec![hit(doc(1), 1.0, "edited")];
        let p = vec![hit(doc(1), 2.0, "similar past")];
        let blended = blend_reactive_predictive(r, p, 0, &cfg);
        // alpha=0 ⇒ 0×1 + 1×2 = 2
        assert_eq!(blended.len(), 1);
        assert!((blended[0].score - 2.0).abs() < 1e-6);
    }

    #[test]
    fn blend_preserves_unique_targets_from_each_side() {
        let cfg = MergeConfig::default();
        let r = vec![hit(doc(1), 1.0, "r")];
        let p = vec![hit(doc(2), 1.0, "p")];
        let blended = blend_reactive_predictive(r, p, 4, &cfg);
        assert_eq!(blended.len(), 2);
    }

    #[test]
    fn max_merge_keeps_winner_reason() {
        let merged = max_merge(vec![
            vec![hit(doc(1), 0.3, "weak channel A")],
            vec![hit(doc(1), 0.9, "strong channel B")],
        ]);
        assert_eq!(merged.len(), 1);
        assert!((merged[0].score - 0.9).abs() < 1e-6);
        assert!(merged[0].reason.contains("strong channel B"));
    }

    #[test]
    fn confidence_gate_returns_empty_when_below_threshold() {
        let cfg = MergeConfig { confidence_gate: 0.5, ..MergeConfig::default() };
        let items = vec![hit(doc(1), 0.4, "meh"), hit(doc(2), 0.3, "meh")];
        let out = apply_confidence_and_mad(items, &cfg);
        assert!(out.is_empty());
    }

    #[test]
    fn confidence_gate_accepts_when_max_above_threshold() {
        let cfg = MergeConfig { confidence_gate: 0.5, top_k: 0, mad_percentile: 0.95, ..MergeConfig::default() };
        let items = vec![hit(doc(1), 0.6, "ok"), hit(doc(2), 0.55, "ok")];
        let out = apply_confidence_and_mad(items, &cfg);
        assert!(!out.is_empty());
    }

    #[test]
    fn mad_filter_drops_long_tail() {
        // Three very high scores, many low scores. The high should pass, low should be dropped.
        let mut items = vec![
            hit(chunk(1), 5.0, "hot"),
            hit(chunk(2), 4.5, "hot"),
            hit(chunk(3), 4.0, "hot"),
        ];
        for i in 4..30 {
            items.push(hit(chunk(i), 0.9, "tail"));
        }
        let cfg = MergeConfig { confidence_gate: 0.0, top_k: 0, ..MergeConfig::default() };
        let out = apply_confidence_and_mad(items, &cfg);
        assert!(out.len() <= 5, "expected the tail filtered, got {}", out.len());
        // The three hot items should be there.
        assert!(out.iter().any(|x| x.target == chunk(1)));
        assert!(out.iter().any(|x| x.target == chunk(2)));
        assert!(out.iter().any(|x| x.target == chunk(3)));
    }

    #[test]
    fn top_k_truncates_after_filter() {
        let items: Vec<ChannelHit> = (0..20)
            .map(|i| hit(chunk(i as u64), 1.0 + i as f32 * 0.1, "ok"))
            .collect();
        let cfg = MergeConfig { confidence_gate: 0.0, top_k: 5, mad_percentile: 0.99, ..MergeConfig::default() };
        let out = apply_confidence_and_mad(items, &cfg);
        assert!(out.len() <= 5);
        // Sorted desc — top score first.
        assert!(out.windows(2).all(|w| w[0].score >= w[1].score));
    }

    #[test]
    fn small_input_skips_mad_and_keeps_all() {
        let items = vec![
            hit(doc(1), 0.9, "a"),
            hit(doc(2), 0.8, "b"),
            hit(doc(3), 0.7, "c"),
        ];
        let cfg = MergeConfig { confidence_gate: 0.0, top_k: 0, ..MergeConfig::default() };
        let out = apply_confidence_and_mad(items, &cfg);
        assert_eq!(out.len(), 3);
    }
}
