//! Pool-relative contextual measurements retain stable proposal ties.
use crate::source_views::SOURCE_VIEW_NAMES;
use crate::{
    Result, RetrievalError,
    feature_matrix::{FeatureMatrix, pool_stats},
    matrix::Matrix,
    query::Candidate,
};
use ken_text::PythonText;
const STATS: [&str; 4] = ["raw", "to_max", "range_relative", "reciprocal_rank"];
pub fn feature_names(source_views: bool) -> Vec<PythonText> {
    let mut names = Vec::new();
    for q in ["original", "expanded"] {
        for stat in STATS {
            names.push(format!("code_{q}_{stat}").into());
        }
    }
    if source_views {
        for view in SOURCE_VIEW_NAMES {
            for q in ["original", "expanded"] {
                for stat in STATS {
                    names.push(format!("view_{view}_{q}_{stat}").into());
                }
            }
        }
    }
    names
}
pub fn contextual_features(candidates: &[Candidate], source_views: bool) -> Result<FeatureMatrix> {
    let names = feature_names(source_views);
    let mut signals = vec![
        "cosine_code_original".to_owned(),
        "cosine_code_expanded".to_owned(),
    ];
    if source_views {
        for view in SOURCE_VIEW_NAMES {
            for q in ["original", "expanded"] {
                signals.push(format!("cosine_view_{view}_{q}"));
            }
        }
    }
    let mut rows = vec![Vec::new(); candidates.len()];
    for signal in signals {
        if candidates.iter().any(|c| !c.signals.contains_key(&signal)) {
            return Err(RetrievalError::Invalid(
                "contextual ranking requires scores for every proposed owner".into(),
            ));
        }
        let values: Vec<_> = candidates.iter().map(|c| c.signals[&signal]).collect();
        if values.iter().any(|v| !v.is_finite()) {
            return Err(RetrievalError::Invalid(
                "contextual scores must be finite".into(),
            ));
        }
        let stats = pool_stats(&values);
        for (i, row) in rows.iter_mut().enumerate() {
            row.extend([
                values[i],
                stats.to_max[i],
                stats.relative[i],
                stats.reciprocal_rank[i],
            ]);
        }
    }
    let values = Matrix::new(
        candidates.len(),
        names.len(),
        rows.into_iter().flatten().collect(),
    )?;
    Ok(FeatureMatrix { names, values })
}
