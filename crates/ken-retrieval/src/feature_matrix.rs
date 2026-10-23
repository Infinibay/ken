//! Ordered feature names and rectangular values form one observation.
use crate::matrix::Matrix;
use ken_text::PythonText;
#[derive(Clone, Debug)]
pub struct FeatureMatrix {
    pub names: Vec<PythonText>,
    pub values: Matrix<f64>,
}
pub(crate) struct PoolStats {
    pub to_max: Vec<f64>,
    pub relative: Vec<f64>,
    pub reciprocal_rank: Vec<f64>,
}
pub(crate) fn pool_stats(values: &[f64]) -> PoolStats {
    let min = values.iter().copied().reduce(f64::min).unwrap_or(0.);
    let max = values.iter().copied().reduce(f64::max).unwrap_or(0.);
    let mut order: Vec<_> = (0..values.len()).collect();
    order.sort_by(|a, b| {
        values[*b]
            .partial_cmp(&values[*a])
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let mut ranks = vec![0.; values.len()];
    for (rank, index) in order.into_iter().enumerate() {
        ranks[index] = 1. / (rank + 1) as f64;
    }
    PoolStats {
        to_max: values.iter().map(|v| v - max).collect(),
        relative: values
            .iter()
            .map(|v| (v - min) / (max - min).max(1e-9))
            .collect(),
        reciprocal_rank: ranks,
    }
}
