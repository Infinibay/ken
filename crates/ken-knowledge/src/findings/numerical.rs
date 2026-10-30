//! Explicit numerical ownership. Production supplies its admitted CPU/BLAS
//! strategy; ScalarMath is a named policy for simple tests, not a parity claim.
use crate::{Result, invalid};
pub trait VectorMath {
    fn query_norm(&self, vector: &[f32]) -> Result<f32>;
    fn row_norm(&self, row: &[f32]) -> Result<f32>;
    fn scores(&self, matrix: &[f32], rows: usize, query: &[f32]) -> Result<Vec<f32>>;
    fn symmetric_product(&self, matrix: &[f32], rows: usize, width: usize) -> Result<Vec<f32>>;
}
#[derive(Debug, Clone, Copy)]
pub struct ScalarMath;
impl VectorMath for ScalarMath {
    fn query_norm(&self, vector: &[f32]) -> Result<f32> {
        Ok(vector.iter().fold(0f32, |s, x| s + x * x).sqrt())
    }
    fn row_norm(&self, row: &[f32]) -> Result<f32> {
        self.query_norm(row)
    }
    fn scores(&self, matrix: &[f32], rows: usize, query: &[f32]) -> Result<Vec<f32>> {
        if rows.checked_mul(query.len()) != Some(matrix.len()) {
            return Err(invalid("compatible matrix/query shapes required"));
        }
        if query.is_empty() {
            return Ok(vec![0.0; rows]);
        }
        Ok(matrix
            .chunks_exact(query.len())
            .map(|row| row.iter().zip(query).fold(0f32, |s, (a, b)| s + a * b))
            .collect())
    }
    fn symmetric_product(&self, matrix: &[f32], rows: usize, width: usize) -> Result<Vec<f32>> {
        if rows.checked_mul(width) != Some(matrix.len()) {
            return Err(invalid("rectangular finding vectors required"));
        }
        let size = rows
            .checked_mul(rows)
            .ok_or_else(|| invalid("finding similarity shape overflow"))?;
        let mut output = vec![0.; size];
        if width == 0 {
            return Ok(output);
        }
        for i in 0..rows {
            for j in 0..rows {
                output[i * rows + j] = matrix[i * width..(i + 1) * width]
                    .iter()
                    .zip(&matrix[j * width..(j + 1) * width])
                    .fold(0f32, |s, (a, b)| s + a * b);
            }
        }
        Ok(output)
    }
}
