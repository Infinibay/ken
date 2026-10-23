//! An immutable row-major matrix admitted with the original axis-wise norm.
use crate::{Result, RetrievalError, dense_math::DenseMath};

#[derive(Debug)]
pub(crate) struct NormalizedMatrix {
    values: Vec<f32>,
    rows: usize,
    width: usize,
}
impl NormalizedMatrix {
    pub(crate) fn new(matrix: Vec<Vec<f32>>, empty: &str, invalid: &str) -> Result<Self> {
        let width = matrix.first().map_or(0, Vec::len);
        if matrix.is_empty() || width == 0 || matrix.iter().any(|r| r.len() != width) {
            return Err(RetrievalError::Invalid(empty.into()));
        }
        for row in &matrix {
            // np.linalg.norm(matrix, axis=1) reduces squared elements with NumPy's
            // pairwise add, unlike the BLAS norm of a single query vector.
            let norm = ken_models::numpy_pairwise_sum(width, &|i| row[i] * row[i]).sqrt();
            if row.iter().any(|x| !x.is_finite()) || (norm - 1.).abs() > 2e-5 || !norm.is_finite() {
                return Err(RetrievalError::Invalid(invalid.into()));
            }
        }
        Ok(Self {
            rows: matrix.len(),
            width,
            values: matrix.into_iter().flatten().collect(),
        })
    }
    pub(crate) fn rows(&self) -> usize {
        self.rows
    }
    pub(crate) fn width(&self) -> usize {
        self.width
    }
    pub(crate) fn scores(&self, query: &[f32]) -> Result<Vec<f32>> {
        self.check_query(query)?;
        DenseMath::platform()?.scores(&self.values, self.rows, query)
    }
    pub(crate) fn gathered_scores(&self, rows: &[usize], query: &[f32]) -> Result<Vec<f32>> {
        self.check_query(query)?;
        let mut gathered = Vec::with_capacity(rows.len() * self.width);
        for &row in rows {
            gathered.extend_from_slice(&self.values[row * self.width..(row + 1) * self.width]);
        }
        DenseMath::platform()?.scores(&gathered, rows.len(), query)
    }
    fn check_query(&self, query: &[f32]) -> Result<()> {
        if query.len() != self.width {
            return Err(RetrievalError::Invalid(
                "source view query dimension does not match its vectors".into(),
            ));
        }
        Ok(())
    }
}
