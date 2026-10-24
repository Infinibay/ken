//! Combine ordinal neural evidence with a fixed pool's existing order.
use crate::{Result, RetrievalError};

/// Return original indices; neural and fusion ties retain the existing order.
/// Membership and display limits belong to the caller, not this policy.
pub fn fused_reranker_order(
    scores: &[f64],
    neural_weight: f64,
    rank_offset: f64,
) -> Result<Vec<usize>> {
    if !neural_weight.is_finite() || !(0.0..=1.0).contains(&neural_weight) {
        return Err(RetrievalError::Invalid(
            "neural weight must lie in [0, 1]".into(),
        ));
    }
    if !rank_offset.is_finite() || rank_offset < 0.0 {
        return Err(RetrievalError::Invalid(
            "rank offset must be finite and nonnegative".into(),
        ));
    }
    if scores.iter().any(|score| !score.is_finite()) {
        return Err(RetrievalError::Invalid(
            "finite reranker scores required".into(),
        ));
    }
    let mut neural: Vec<_> = (0..scores.len()).collect();
    neural.sort_by(|&a, &b| scores[b].partial_cmp(&scores[a]).unwrap().then(a.cmp(&b)));
    let mut positions = vec![0; scores.len()];
    for (rank, index) in neural.into_iter().enumerate() {
        positions[index] = rank + 1;
    }
    let fused: Vec<_> = positions
        .into_iter()
        .enumerate()
        .map(|(index, rank)| {
            (1.0 - neural_weight) / (rank_offset + index as f64 + 1.0)
                + neural_weight / (rank_offset + rank as f64)
        })
        .collect();
    let mut order: Vec<_> = (0..scores.len()).collect();
    order.sort_by(|&a, &b| fused[b].partial_cmp(&fused[a]).unwrap().then(a.cmp(&b)));
    Ok(order)
}
