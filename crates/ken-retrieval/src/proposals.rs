//! One vote per named run and canonical owner, retaining the proposed evidence.
use crate::{
    EntityKey, Result, RetrievalError,
    query::{Candidate, Signals, merge_spans},
};
use std::collections::{BTreeMap, HashMap, HashSet};
pub(crate) fn max_signals(target: &mut Signals, source: &Signals) {
    for (name, &value) in source {
        target
            .entry(name.clone())
            .and_modify(|prior| {
                if (*prior).partial_cmp(&value) != Some(std::cmp::Ordering::Greater) {
                    *prior = value
                }
            })
            .or_insert(value);
    }
}
pub fn fuse_proposals(
    channels: &[(String, Vec<Candidate>)],
    limit: usize,
    rrf_k: usize,
) -> Result<Vec<Candidate>> {
    if limit == 0 || rrf_k == 0 {
        return Err(RetrievalError::Invalid(
            "positive proposal and reciprocal-rank budgets required".into(),
        ));
    }
    let mut merged: Vec<Candidate> = Vec::new();
    let mut positions: HashMap<EntityKey, usize> = HashMap::new();
    let mut source_versions: HashMap<&str, &str> = HashMap::new();
    let mut registered = HashSet::new();
    for (channel, candidates) in channels {
        if !registered.insert(channel) {
            return Err(RetrievalError::Invalid("duplicate proposal channel".into()));
        }
        let mut seen = HashSet::new();
        for candidate in candidates {
            if candidate.passages.is_empty() {
                return Err(RetrievalError::Invalid(
                    "proposal requires source evidence".into(),
                ));
            }
            for passage in &candidate.passages {
                let previous = source_versions
                    .entry(candidate.entity.path.as_str())
                    .or_insert(&passage.source_hash);
                if *previous != passage.source_hash {
                    return Err(RetrievalError::Invalid(
                        "mixed source generations in file proposals".into(),
                    ));
                }
            }
            let next = positions.len();
            let index = *positions
                .entry(candidate.entity.clone())
                .or_insert_with(|| {
                    merged.push(Candidate {
                        entity: candidate.entity.clone(),
                        passages: Vec::new(),
                        signals: Signals::from([("rrf".into(), 0.)]),
                        owned_regions: Vec::new(),
                    });
                    next
                });
            let combined = &mut merged[index];
            let measurements: Signals = candidate
                .signals
                .iter()
                .filter(|(name, _)| name.as_str() != "rrf")
                .map(|(name, &v)| (name.clone(), v))
                .collect();
            max_signals(&mut combined.signals, &measurements);
            if seen.insert(&candidate.entity) {
                let rank = seen.len() as f64;
                combined
                    .signals
                    .insert(format!("proposal_{channel}"), 1. / rank);
                *combined
                    .signals
                    .get_mut("rrf")
                    .expect("initialized reciprocal rank") += 1. / (rrf_k as f64 + rank);
            }
            let mut spans: BTreeMap<_, _> = combined
                .passages
                .iter()
                .enumerate()
                .map(|(i, p)| (p.span, i))
                .collect();
            for passage in &candidate.passages {
                if passage.entity != candidate.entity {
                    return Err(RetrievalError::Invalid(
                        "proposal contains another source owner".into(),
                    ));
                }
                if let Some(&index) = spans.get(&passage.span) {
                    max_signals(&mut combined.passages[index].signals, &passage.signals)
                } else {
                    spans.insert(passage.span, combined.passages.len());
                    combined.passages.push(passage.clone())
                }
            }
            let mut regions = combined.owned_regions.clone();
            regions.extend_from_slice(&candidate.owned_regions);
            combined.owned_regions = merge_spans(&regions);
        }
    }
    merged.sort_by(|a, b| {
        b.signals
            .get("exact")
            .unwrap_or(&0.)
            .partial_cmp(a.signals.get("exact").unwrap_or(&0.))
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| {
                b.signals["rrf"]
                    .partial_cmp(&a.signals["rrf"])
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| a.entity.path.cmp(&b.entity.path))
            .then_with(|| {
                a.passages
                    .iter()
                    .map(|p| p.span.start_line)
                    .min()
                    .cmp(&b.passages.iter().map(|p| p.span.start_line).min())
            })
    });
    merged.truncate(limit);
    Ok(merged)
}
