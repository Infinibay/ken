//! Reactive channel: scores targets the agent has touched in the current
//! session. The signal is "what is this agent doing *now*".
//!
//! Pipeline per target:
//!   1. Each interaction contributes a base weight derived from its
//!      `EventType` (`Read=1.0`, `Edited=2.0`, `Cited=2.5`, etc.) multiplied
//!      by the caller-supplied `weight` field (lets the integrator boost
//!      forced calls).
//!   2. Exponential decay against the session iteration distance —
//!      `weight × exp(-λ × Δi)`. λ defaults to `0.15` (matches infinidev).
//!   3. Sum the decayed weights per target.
//!   4. Classify the per-target event sequence into a `Pattern` and
//!      multiply by `Pattern::multiplier()`. This is the productivity-aware
//!      adjustment — `Cited` (2.5x) and `ReadEdit` (2.0x) amplify, while
//!      `ReadRepeated` (0.7x) and `Dismissed` (0.3x) damp the score.

use ahash::AHashMap;

use crate::postgres::PostgresStorage;
use crate::rank::merge::ChannelHit;
use crate::rank::stats::exp_decay;
use crate::types::{EventType, NodeRef, Pattern, SessionId};

/// Slim view of a session interaction — only the fields the reactive
/// channel actually consumes. Returned by `interactions_for_reactive` and
/// fed to `score_from_events`. The full `SessionInteraction` (with
/// timestamps, IDs, tool_name, etc.) is for forensics/feedback paths.
#[derive(Debug, Clone)]
pub struct ReactiveEvent {
    pub target: NodeRef,
    pub event_type: EventType,
    pub weight: f32,
    pub iteration: u32,
}

/// Default exponential-decay rate per iteration distance. Half-life ≈ 4.6
/// iterations; an event 5 iters old retains ~47% of its weight.
pub const DEFAULT_LAMBDA: f32 = 0.15;

/// Per-event-type base weight. Larger = stronger signal that the target
/// matters. `Dismissed` is negative — explicit rejection should *push down*
/// the target, not just leave it neutral.
pub fn event_base_weight(e: EventType) -> f32 {
    match e {
        EventType::Retrieved => 0.5,
        EventType::Read => 1.0,
        EventType::Edited => 2.0,
        EventType::Cited => 2.5,
        EventType::Dismissed => -1.0,
    }
}

#[derive(Debug, Clone)]
pub struct ReactiveConfig {
    pub lambda: f32,
    /// Maximum iteration distance to consider. Events older than
    /// `current_iteration - iteration_window` are skipped at the SQL
    /// level (no wire transfer, no decode). With λ=0.15 the default
    /// window of 30 keeps everything contributing >1% of weight.
    pub iteration_window: u32,
}

impl Default for ReactiveConfig {
    fn default() -> Self {
        Self { lambda: DEFAULT_LAMBDA, iteration_window: 30 }
    }
}

/// Score every target the current session has interacted with. Only positive
/// final scores are returned (negative scores from dismissals are clamped to
/// `0.0` and dropped — this channel surfaces what's *interesting*, not what's
/// being avoided).
pub async fn reactive_scores(
    storage: &PostgresStorage,
    session_id: SessionId,
    current_iteration: u32,
    cfg: &ReactiveConfig,
) -> Vec<ChannelHit> {
    let min_iter = current_iteration.saturating_sub(cfg.iteration_window);
    let events = storage.interactions_for_reactive(session_id, min_iter).await;
    score_from_events(&events, current_iteration, cfg)
}

/// Pure variant — extracted so we can unit-test without DB. `events`
/// is the ordered sequence of session events the channel scores.
pub fn score_from_events(
    events: &[ReactiveEvent],
    current_iteration: u32,
    cfg: &ReactiveConfig,
) -> Vec<ChannelHit> {
    let mut sum_by_target: AHashMap<NodeRef, f32> = AHashMap::new();
    let mut events_by_target: AHashMap<NodeRef, Vec<EventType>> = AHashMap::new();
    // Targets that the session committed to (received an `Edited` event).
    // Used by `classify_pattern` to distinguish "Read once, never edited
    // anywhere" (neutral — agent may still be exploring) from "Read once,
    // session edited *something else*" (the agent looked at this file and
    // moved on — a soft rejection signal).
    let mut edited_targets: ahash::AHashSet<NodeRef> = ahash::AHashSet::new();

    for ev in events {
        let delta = current_iteration.saturating_sub(ev.iteration);
        let base = event_base_weight(ev.event_type) * ev.weight;
        let decayed = exp_decay(base, delta, cfg.lambda);
        *sum_by_target.entry(ev.target.clone()).or_default() += decayed;
        events_by_target
            .entry(ev.target.clone())
            .or_default()
            .push(ev.event_type);
        if ev.event_type == EventType::Edited {
            edited_targets.insert(ev.target.clone());
        }
    }

    let mut out = Vec::with_capacity(sum_by_target.len());
    for (target, raw) in sum_by_target {
        let target_events = events_by_target.get(&target).map(|v| v.as_slice()).unwrap_or(&[]);
        // "Edit elsewhere" = at least one *other* target in the session got
        // an `Edited` event. A single edited target is enough to make a
        // read-only file in the same session look like a discarded lead.
        let edit_elsewhere = edited_targets.iter().any(|t| t != &target);
        let pattern = classify_pattern(target_events, edit_elsewhere);
        let final_score = raw * pattern.multiplier();
        if final_score > 0.0 {
            out.push(ChannelHit {
                target,
                score: final_score,
                reason: format!("{} events, pattern={:?}", events_by_target.len(), pattern),
            });
        }
    }
    out
}

/// Classify a per-target event sequence into a `Pattern`. Order:
///   1. `Cited` anywhere ⇒ Cited
///   2. `Dismissed` anywhere ⇒ Dismissed
///   3. `Read` + `Edited` (in any order) ⇒ ReadEdit
///   4. `Edited` only (no `Read`) ⇒ EditOnly
///   5. ≥3 `Read` events without `Edited` or `Cited` ⇒ ReadRepeated
///   6. 1–2 `Read` events, no edit on this target, *and the session edited
///      somewhere else* ⇒ ReadSkipped (the agent looked here and moved on)
///   7. otherwise ⇒ Neutral (single read, session still exploring)
fn classify_pattern(events: &[EventType], session_edited_elsewhere: bool) -> Pattern {
    use EventType::*;

    let has = |target: EventType| events.iter().any(|e| *e == target);
    let count = |target: EventType| events.iter().filter(|e| **e == target).count();

    if has(Cited) {
        Pattern::Cited
    } else if has(Dismissed) {
        Pattern::Dismissed
    } else if has(Read) && has(Edited) {
        Pattern::ReadEdit
    } else if has(Edited) {
        Pattern::EditOnly
    } else if count(Read) >= 3 {
        Pattern::ReadRepeated
    } else if has(Read) && session_edited_elsewhere {
        Pattern::ReadSkipped
    } else {
        Pattern::Neutral
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{DocumentId, EventType};

    fn ev(target_id: u64, kind: EventType, iteration: u32, weight: f32) -> ReactiveEvent {
        ReactiveEvent {
            iteration,
            event_type: kind,
            target: NodeRef::Document(DocumentId(target_id)),
            weight,
        }
    }

    #[test]
    fn classify_pattern_priority() {
        use EventType::*;
        // Single-target priorities — `session_edited_elsewhere=false` so the
        // ReadSkipped branch never fires here.
        assert_eq!(classify_pattern(&[Read, Edited, Cited], false), Pattern::Cited);
        assert_eq!(classify_pattern(&[Read, Dismissed], false), Pattern::Dismissed);
        assert_eq!(classify_pattern(&[Read, Edited], false), Pattern::ReadEdit);
        assert_eq!(classify_pattern(&[Edited], false), Pattern::EditOnly);
        assert_eq!(classify_pattern(&[Read, Read, Read], false), Pattern::ReadRepeated);
        assert_eq!(classify_pattern(&[Read], false), Pattern::Neutral);
        assert_eq!(classify_pattern(&[Retrieved], false), Pattern::Neutral);
    }

    #[test]
    fn read_only_with_edit_elsewhere_is_skipped() {
        use EventType::*;
        // 1–2 reads + edit-elsewhere = ReadSkipped (the agent looked here
        // and committed somewhere else — soft rejection signal).
        assert_eq!(classify_pattern(&[Read], true), Pattern::ReadSkipped);
        assert_eq!(classify_pattern(&[Read, Read], true), Pattern::ReadSkipped);
        // ≥3 reads still wins as ReadRepeated (the agent kept coming back).
        assert_eq!(classify_pattern(&[Read, Read, Read], true), Pattern::ReadRepeated);
        // Without edit-elsewhere, single read stays Neutral (still exploring).
        assert_eq!(classify_pattern(&[Read], false), Pattern::Neutral);
        // Edit on this target wins regardless — being the file that got
        // edited beats the cross-target signal.
        assert_eq!(classify_pattern(&[Read, Edited], true), Pattern::ReadEdit);
    }

    #[test]
    fn read_skipped_dampens_score_when_other_target_edited() {
        // End-to-end: a.rs read once, b.rs read+edited. a.rs should land
        // at 0.3× its raw weight (ReadSkipped) while b.rs gets 2.0×
        // (ReadEdit) — the file actually edited dominates.
        let cfg = ReactiveConfig::default();
        let evs = vec![
            ev(1, EventType::Read, 0, 1.0),    // a.rs: read only
            ev(2, EventType::Read, 0, 1.0),    // b.rs: read
            ev(2, EventType::Edited, 0, 1.0),  // b.rs: edited
        ];
        let out = score_from_events(&evs, 0, &cfg);
        let by = |id: u64| {
            out.iter()
                .find(|h| h.target == NodeRef::Document(DocumentId(id)))
                .map(|h| h.score)
                .expect("target must be present")
        };
        // a.rs: base 1.0 × decay 1.0 × 0.3 (ReadSkipped) = 0.3
        assert!((by(1) - 0.3).abs() < 1e-5, "a.rs got {}, expected 0.3", by(1));
        // b.rs: (1.0 read + 2.0 edit) × decay 1.0 × 2.0 (ReadEdit) = 6.0
        assert!((by(2) - 6.0).abs() < 1e-5, "b.rs got {}, expected 6.0", by(2));
        assert!(by(2) > by(1) * 10.0);
    }

    #[test]
    fn reactive_score_sums_decayed_weight() {
        let cfg = ReactiveConfig::default();
        let evs = vec![
            ev(1, EventType::Read, 0, 1.0),
            ev(1, EventType::Read, 5, 1.0),
            ev(2, EventType::Read, 5, 1.0),
        ];
        let out = score_from_events(&evs, 5, &cfg);
        assert_eq!(out.len(), 2);
        let by = |id: u64| {
            out.iter()
                .find(|h| h.target == NodeRef::Document(DocumentId(id)))
                .map(|h| h.score)
        };
        assert!((by(1).unwrap() - (1.0 + (-0.15f32 * 5.0).exp())).abs() < 1e-5);
        assert!((by(2).unwrap() - 1.0).abs() < 1e-5);
    }

    #[test]
    fn cited_pattern_amplifies() {
        let cfg = ReactiveConfig::default();
        let evs = vec![
            ev(1, EventType::Read, 0, 1.0),
            ev(1, EventType::Cited, 0, 1.0),
        ];
        let out = score_from_events(&evs, 0, &cfg);
        assert_eq!(out.len(), 1);
        assert!((out[0].score - 8.75).abs() < 1e-5);
    }

    #[test]
    fn dismissed_clamps_negative_to_drop() {
        let cfg = ReactiveConfig::default();
        let evs = vec![ev(1, EventType::Dismissed, 0, 1.0)];
        let out = score_from_events(&evs, 0, &cfg);
        assert!(out.is_empty());
    }

    #[test]
    fn caller_weight_multiplies() {
        let cfg = ReactiveConfig::default();
        let evs_low = vec![ev(1, EventType::Read, 0, 0.5)];
        let evs_high = vec![ev(1, EventType::Read, 0, 2.0)];
        let lo = score_from_events(&evs_low, 0, &cfg);
        let hi = score_from_events(&evs_high, 0, &cfg);
        assert!(hi[0].score > lo[0].score);
        assert!((hi[0].score - 4.0 * lo[0].score).abs() < 1e-5);
    }

    #[test]
    fn empty_input_returns_empty() {
        let out = score_from_events(&[], 0, &ReactiveConfig::default());
        assert!(out.is_empty());
    }
}
