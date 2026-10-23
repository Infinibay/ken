//! Immutable rectangular values shared by numerical projections and forests.
use crate::{Result, RetrievalError};
#[derive(Clone, Debug, PartialEq)]
pub struct Matrix<T> {
    rows: usize,
    columns: usize,
    values: Vec<T>,
}
impl<T> Matrix<T> {
    pub fn new(rows: usize, columns: usize, values: Vec<T>) -> Result<Self> {
        if rows.checked_mul(columns) != Some(values.len()) {
            return Err(RetrievalError::Invalid(
                "rectangular matrix shape mismatch".into(),
            ));
        }
        Ok(Self {
            rows,
            columns,
            values,
        })
    }
    pub fn rows(&self) -> usize {
        self.rows
    }
    pub fn columns(&self) -> usize {
        self.columns
    }
    pub fn values(&self) -> &[T] {
        &self.values
    }
}
