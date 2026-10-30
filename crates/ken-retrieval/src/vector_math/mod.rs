//! Shared vector arithmetic; callers retain ranking, persistence and model policy.
mod network;
mod ordering;
mod partition;
use crate::{Result, RetrievalError, dense_math::DenseMath};
pub use ordering::OrderingIdentity;
use std::collections::BTreeSet;
#[derive(Clone, Copy, Debug)]
pub enum QueryNorm {
    AddEpsilon(f32),
    ClampEpsilon(f64),
}
#[derive(Clone, Debug)]
pub struct RankedRows {
    pub kept: Vec<usize>,
    pub scores: Vec<f32>,
}
#[derive(Clone, Copy)]
pub struct NativeVectorMath {
    math: &'static DenseMath,
}
impl NativeVectorMath {
    pub fn platform() -> Result<Self> {
        Ok(Self {
            math: DenseMath::platform()?,
        })
    }
    pub fn ordering_profile(&self) -> Result<&'static str> {
        ordering::profile()
    }
    pub fn ordering_identity(&self) -> Result<OrderingIdentity> {
        ordering::identity()
    }
    pub fn query_norm(&self, query: &[f32]) -> Result<f32> {
        if query.is_empty() {
            Ok(0.)
        } else {
            self.math.norm(query)
        }
    }
    pub fn normalize_query(&self, query: &[f32], policy: QueryNorm) -> Result<Vec<f32>> {
        let norm = self.query_norm(query)?;
        let denominator = match policy {
            QueryNorm::AddEpsilon(epsilon) => {
                epsilon32(epsilon)?;
                norm + epsilon
            }
            QueryNorm::ClampEpsilon(epsilon) => {
                if !epsilon.is_finite() || epsilon < 0. {
                    return Err(invalid("finite nonnegative normalization epsilon required"));
                }
                let norm = f64::from(norm);
                (if norm < epsilon { epsilon } else { norm }) as f32
            }
        };
        Ok(query.iter().map(|value| value / denominator).collect())
    }
    pub fn row_norms(&self, matrix: &[f32], rows: usize, width: usize) -> Result<Vec<f32>> {
        rectangular(matrix, rows, width)?;
        if width == 0 {
            return zeros(rows);
        }
        Ok(matrix
            .chunks_exact(width)
            .map(|row| ken_models::numpy_pairwise_sum(width, &|i| row[i] * row[i]).sqrt())
            .collect())
    }
    pub fn normalize_rows_additive(
        &self,
        matrix: &[f32],
        rows: usize,
        width: usize,
        epsilon: f32,
    ) -> Result<Vec<f32>> {
        epsilon32(epsilon)?;
        let norms = self.row_norms(matrix, rows, width)?;
        if width == 0 {
            return Ok(vec![]);
        }
        let mut normalized = matrix.to_vec();
        for (row, norm) in normalized.chunks_exact_mut(width).zip(norms) {
            let divisor = norm + epsilon;
            for value in row {
                *value /= divisor;
            }
        }
        Ok(normalized)
    }
    /// Raw C rows times a vector; mapped-store callers preserve segment boundaries.
    pub fn scores(
        &self,
        matrix: &[f32],
        rows: usize,
        width: usize,
        query: &[f32],
    ) -> Result<Vec<f32>> {
        rectangular(matrix, rows, width)?;
        if query.len() != width {
            return Err(invalid("query dimension does not match matrix width"));
        }
        if matrix.is_empty() {
            return zeros(rows);
        }
        // NumPy scalar_vec uses its no-BLAS loop: initialize +0, then add the
        // single product. Direct multiplication would retain a negative zero.
        if width == 1 {
            return Ok(matrix
                .iter()
                .map(|value| 0.0_f32 + value * query[0])
                .collect());
        }
        self.math.scores(matrix, rows, query)
    }
    pub fn cosine_against(
        &self,
        query: &[f32],
        matrix: &[f32],
        rows: usize,
        width: usize,
    ) -> Result<Vec<f32>> {
        rectangular(matrix, rows, width)?;
        if query.len() != width {
            return Err(invalid("query dimension does not match matrix width"));
        }
        if matrix.is_empty() {
            return zeros(rows);
        }
        let query = self.normalize_query(query, QueryNorm::AddEpsilon(1e-12))?;
        let norms = self.row_norms(matrix, rows, width)?;
        let mut scores = self.scores(matrix, rows, width, &query)?;
        for (score, norm) in scores.iter_mut().zip(norms) {
            *score /= norm + 1e-12_f32;
        }
        Ok(scores)
    }
    pub fn product(
        &self,
        a: &[f32],
        rows: usize,
        width: usize,
        b: &[f32],
        columns: usize,
    ) -> Result<Vec<f32>> {
        rectangular(a, rows, width)?;
        rectangular(b, columns, width)?;
        let count = rows
            .checked_mul(columns)
            .ok_or_else(|| invalid("vector product output dimensions overflow"))?;
        if width == 1 {
            let mut output = zeros(count)?;
            for i in 0..rows {
                for j in 0..columns {
                    output[i * columns + j] += a[i] * b[j];
                }
            }
            return Ok(output);
        }
        if rows == columns && rows > 1 && width > 1 && std::ptr::eq(a.as_ptr(), b.as_ptr()) {
            DenseMath::symmetric_product32(a, rows, width)
        } else {
            DenseMath::product32(a, rows, width, b, columns)
        }
    }
    pub fn rank_against(
        &self,
        query: &[f32],
        blobs: &[Option<&[u8]>],
        strict: bool,
    ) -> Result<RankedRows> {
        let mut kept = vec![];
        let mut matrix = vec![];
        let mut stored = BTreeSet::new();
        for (index, blob) in blobs.iter().enumerate() {
            let Some(blob) = blob else {
                continue;
            };
            if blob.len() % 4 != 0 {
                return Err(invalid(
                    "embedding buffer size must be a multiple of float32 size",
                ));
            }
            let width = blob.len() / 4;
            stored.insert(width);
            if width != query.len() {
                continue;
            }
            matrix
                .try_reserve(width)
                .map_err(|e| invalid(format!("embedding matrix allocation: {e}")))?;
            kept.push(index);
            matrix.extend(
                blob.chunks_exact(4)
                    .map(|bytes| f32::from_le_bytes(bytes.try_into().expect("four-byte chunk"))),
            );
        }
        if kept.is_empty() && !stored.is_empty() && strict {
            return Err(invalid(format!(
                "stored embeddings are {:?}-dimensional but the live embedder produces {} — the index was built with a different model; run `ken reembed`",
                stored.into_iter().collect::<Vec<_>>(),
                query.len()
            )));
        }
        let scores = self.cosine_against(query, &matrix, kept.len(), query.len())?;
        Ok(RankedRows { kept, scores })
    }
    pub fn mean_std_f32(&self, values: &[f32]) -> Result<(f32, f32)> {
        if values.is_empty() {
            return Ok((f32::NAN, f32::NAN));
        }
        let count = values.len() as f32;
        let mean = (0.0 + ken_models::numpy_pairwise_sum(values.len(), &|i| values[i])) / count;
        let variance =
            (0.0 + ken_models::numpy_pairwise_sum(values.len(), &|i| {
                let difference = values[i] - mean;
                difference * difference
            })) / count;
        Ok((mean, variance.sqrt()))
    }
    pub fn argsort_descending_f32(&self, values: &[f32]) -> Result<Vec<usize>> {
        ordering::descending(values)
    }
    pub fn argpartition_f32(&self, values: &[f32], kth: usize) -> Result<Vec<usize>> {
        ordering::select(values, kth)
    }
    pub fn indices_at_least_f32(&self, values: &[f32], threshold: f64) -> Vec<usize> {
        let threshold = threshold as f32;
        values
            .iter()
            .enumerate()
            .filter_map(|(i, value)| (*value >= threshold).then_some(i))
            .collect()
    }
}
fn invalid(message: impl Into<String>) -> RetrievalError {
    RetrievalError::Invalid(message.into())
}
fn epsilon32(epsilon: f32) -> Result<()> {
    if epsilon.is_finite() && epsilon >= 0. {
        Ok(())
    } else {
        Err(invalid("finite nonnegative normalization epsilon required"))
    }
}
fn rectangular(values: &[f32], rows: usize, width: usize) -> Result<()> {
    if rows.checked_mul(width) == Some(values.len()) {
        Ok(())
    } else {
        Err(invalid("rectangular vector matrix required"))
    }
}
fn zeros(len: usize) -> Result<Vec<f32>> {
    let mut values = vec![];
    values
        .try_reserve_exact(len)
        .map_err(|e| invalid(format!("vector output allocation: {e}")))?;
    values.resize(len, 0.);
    Ok(values)
}
/// NumPy's F64 reduction identity plus the already-qualified pairwise kernel.
pub fn sum_f64(values: &[f64]) -> f64 {
    0.0 + crate::reductions::pairwise64(values)
}
/// Python3.12's compensated built-in sum, distinct from NumPy's reduction.
pub fn python_sum_f64(values: &[f64]) -> f64 {
    crate::reductions::python_sum(values.iter().copied())
}
