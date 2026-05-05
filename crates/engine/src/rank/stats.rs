//! Numeric helpers for the ranker.
//!
//! Most operations are over short slices of `f32` (top-K scores), so we
//! implement them in plain Rust. The only third-party math we pull in is
//! `statrs`'s normal-distribution inverse-CDF, used by the MAD outlier
//! filter to translate a percentile into a `K` constant.

use statrs::distribution::{ContinuousCDF, Normal};

/// Median of a slice. Returns `None` for an empty slice. Sorts a clone — does
/// not mutate the input. NaNs are propagated (a NaN anywhere makes the result
/// NaN), which matches Python's `statistics.median` behavior on numpy arrays.
pub fn median(values: &[f32]) -> Option<f32> {
    if values.is_empty() {
        return None;
    }
    let mut buf: Vec<f32> = values.to_vec();
    buf.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = buf.len();
    Some(if n % 2 == 1 {
        buf[n / 2]
    } else {
        0.5 * (buf[n / 2 - 1] + buf[n / 2])
    })
}

/// Median Absolute Deviation. For each value `x`, computes `|x - median|`,
/// then returns the median of those deviations. Robust spread estimator —
/// less sensitive to outliers than standard deviation.
pub fn mad(values: &[f32]) -> Option<f32> {
    let m = median(values)?;
    let deviations: Vec<f32> = values.iter().map(|v| (v - m).abs()).collect();
    median(&deviations)
}

/// Normal-distribution scaling constant `1.4826` — multiplied with `MAD` to
/// get an estimator of the standard deviation that's consistent with `σ`
/// when the underlying data is Gaussian. (Wikipedia: "Median absolute
/// deviation".)
pub const MAD_TO_STDDEV: f32 = 1.4826;

/// Inverse normal CDF for `p` ∈ (0, 1). Used to translate a desired
/// outlier-survival percentile into the `K` constant of the MAD threshold:
/// `threshold = bottom_median + K * MAD * MAD_TO_STDDEV`.
///
/// At `p = 0.95`, `K ≈ 1.6449`. At `p = 0.99`, `K ≈ 2.3263`.
///
/// Returns `None` if `p` is outside the open interval `(0, 1)`.
pub fn normal_inv_cdf(p: f64) -> Option<f64> {
    if !(0.0 < p && p < 1.0) {
        return None;
    }
    Normal::new(0.0, 1.0).ok().map(|n| n.inverse_cdf(p))
}

/// Cosine similarity between two `f32` slices. Returns `0.0` if either side
/// is the zero vector or the slices have different lengths (treated as a
/// definitional non-match rather than an error — callers don't need to guard
/// every site).
pub fn cosine(a: &[f32], b: &[f32]) -> f32 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }
    let mut dot = 0.0f32;
    let mut na = 0.0f32;
    let mut nb = 0.0f32;
    for i in 0..a.len() {
        let x = a[i];
        let y = b[i];
        dot += x * y;
        na += x * x;
        nb += y * y;
    }
    let denom = na.sqrt() * nb.sqrt();
    if denom == 0.0 { 0.0 } else { dot / denom }
}

/// Exponential decay of a per-iteration weight: `weight × exp(-λ × Δ)`.
/// Used by the reactive channel — events further from the current iteration
/// contribute less. `lambda` controls the decay rate; with `lambda = 0.15`,
/// an event 5 iterations old retains ~47% of its weight.
pub fn exp_decay(weight: f32, delta: u32, lambda: f32) -> f32 {
    weight * (-(lambda * delta as f32)).exp()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn approx_eq(a: f32, b: f32, eps: f32) -> bool {
        (a - b).abs() < eps
    }

    #[test]
    fn median_odd_and_even() {
        assert_eq!(median(&[1.0, 3.0, 2.0]), Some(2.0));
        assert_eq!(median(&[1.0, 2.0, 3.0, 4.0]), Some(2.5));
    }

    #[test]
    fn median_empty_is_none() {
        assert_eq!(median(&[]), None);
    }

    #[test]
    fn median_single_element() {
        assert_eq!(median(&[42.0]), Some(42.0));
    }

    #[test]
    fn mad_known_case() {
        // 1, 1, 2, 2, 4, 6, 9 — median is 2; deviations are 1,1,0,0,2,4,7;
        // sorted: 0,0,1,1,2,4,7 → MAD = 1.
        let v = [1.0, 1.0, 2.0, 2.0, 4.0, 6.0, 9.0];
        assert_eq!(mad(&v), Some(1.0));
    }

    #[test]
    fn mad_zero_when_constant() {
        assert_eq!(mad(&[5.0, 5.0, 5.0, 5.0]), Some(0.0));
    }

    #[test]
    fn normal_inv_cdf_known_quantiles() {
        // 95% one-sided ≈ 1.6449; 99% ≈ 2.3263; 50% = 0.
        let q95 = normal_inv_cdf(0.95).unwrap();
        let q99 = normal_inv_cdf(0.99).unwrap();
        let q50 = normal_inv_cdf(0.5).unwrap();
        assert!((q95 - 1.6449).abs() < 1e-3);
        assert!((q99 - 2.3263).abs() < 1e-3);
        assert!(q50.abs() < 1e-9);
    }

    #[test]
    fn normal_inv_cdf_rejects_out_of_range() {
        assert!(normal_inv_cdf(0.0).is_none());
        assert!(normal_inv_cdf(1.0).is_none());
        assert!(normal_inv_cdf(-0.1).is_none());
        assert!(normal_inv_cdf(1.5).is_none());
    }

    #[test]
    fn cosine_orthogonal_is_zero() {
        let a = [1.0, 0.0];
        let b = [0.0, 1.0];
        assert_eq!(cosine(&a, &b), 0.0);
    }

    #[test]
    fn cosine_parallel_is_one() {
        let a = [3.0, 4.0];
        let b = [6.0, 8.0];
        assert!(approx_eq(cosine(&a, &b), 1.0, 1e-6));
    }

    #[test]
    fn cosine_anti_parallel_is_minus_one() {
        let a = [1.0, 0.0];
        let b = [-1.0, 0.0];
        assert!(approx_eq(cosine(&a, &b), -1.0, 1e-6));
    }

    #[test]
    fn cosine_zero_vector_is_zero() {
        let a = [0.0, 0.0];
        let b = [1.0, 1.0];
        assert_eq!(cosine(&a, &b), 0.0);
    }

    #[test]
    fn cosine_mismatched_length_is_zero() {
        let a = [1.0, 0.0, 0.0];
        let b = [1.0, 0.0];
        assert_eq!(cosine(&a, &b), 0.0);
    }

    #[test]
    fn exp_decay_zero_delta_keeps_weight() {
        assert_eq!(exp_decay(2.5, 0, 0.15), 2.5);
    }

    #[test]
    fn exp_decay_grows_with_delta() {
        let near = exp_decay(1.0, 1, 0.15);
        let far = exp_decay(1.0, 10, 0.15);
        assert!(near > far);
        assert!(near > 0.0 && near < 1.0);
        assert!(far > 0.0 && far < near);
    }
}
