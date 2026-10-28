//! An immutable row-major matrix admitted with the original axis-wise norm.
use crate::{Result, RetrievalError, dense_math::DenseMath};

/// A borrow of immutable source values, without exposing mutable backing storage.
#[derive(Clone, Copy, Debug)]
pub struct MatrixView<'a> {
    pub values: &'a [f32],
    pub shape: [usize; 2],
    pub is_mapped: bool,
}
#[derive(Debug)]
enum Backing {
    Owned(Vec<f32>),
    Mapped(crate::npy_matrix::MappedNpy),
}
#[derive(Debug)]
pub(crate) struct NormalizedMatrix {
    backing: Backing,
    rows: usize,
    width: usize,
}
impl NormalizedMatrix {
    pub(crate) fn new(matrix: Vec<Vec<f32>>, empty: &str, invalid: &str) -> Result<Self> {
        let width = matrix.first().map_or(0, Vec::len);
        if matrix.is_empty() || width == 0 || matrix.iter().any(|r| r.len() != width) {
            return Err(RetrievalError::Invalid(empty.into()));
        }
        let value = Self {
            rows: matrix.len(),
            width,
            backing: Backing::Owned(matrix.into_iter().flatten().collect()),
        };
        value.validate(empty, invalid)?;
        Ok(value)
    }
    pub(crate) fn mapped(
        matrix: crate::npy_matrix::MappedNpy,
        empty: &str,
        invalid: &str,
    ) -> Result<Self> {
        let value = Self {
            rows: matrix.rows(),
            width: matrix.width(),
            backing: Backing::Mapped(matrix),
        };
        value.validate(empty, invalid)?;
        Ok(value)
    }
    fn validate(&self, empty: &str, invalid: &str) -> Result<()> {
        if self.rows == 0 || self.width == 0 {
            return Err(RetrievalError::Invalid(empty.into()));
        }
        for row in self.values().chunks_exact(self.width) {
            // Preserve original axis-wise pairwise summation, not vector BLAS norm.
            let norm = ken_models::numpy_pairwise_sum(self.width, &|i| row[i] * row[i]).sqrt();
            if row.iter().any(|x| !x.is_finite()) || (norm - 1.).abs() > 2e-5 || !norm.is_finite() {
                return Err(RetrievalError::Invalid(invalid.into()));
            }
        }
        Ok(())
    }
    fn values(&self) -> &[f32] {
        match &self.backing {
            Backing::Owned(v) => v,
            Backing::Mapped(m) => m.values(),
        }
    }
    pub(crate) fn view(&self) -> MatrixView<'_> {
        MatrixView {
            values: self.values(),
            shape: [self.rows, self.width],
            is_mapped: matches!(self.backing, Backing::Mapped(_)),
        }
    }
    pub(crate) fn rows(&self) -> usize {
        self.rows
    }
    pub(crate) fn width(&self) -> usize {
        self.width
    }
    pub(crate) fn scores(&self, query: &[f32]) -> Result<Vec<f32>> {
        self.check_query(query)?;
        DenseMath::platform()?.scores(self.values(), self.rows, query)
    }
    pub(crate) fn gathered_scores(&self, rows: &[usize], query: &[f32]) -> Result<Vec<f32>> {
        self.check_query(query)?;
        let mut gathered = Vec::with_capacity(rows.len() * self.width);
        for &row in rows {
            gathered.extend_from_slice(&self.values()[row * self.width..(row + 1) * self.width]);
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
