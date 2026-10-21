//! Last-real-token outputs; embeddings and raw judge projections stay distinct.
use crate::{CoreError, invalid, weights::finite};
use ken_native_model_api::{TransformerBatch, TransformerRunResult};
use mlx_rs::{Array, Dtype};
fn last_real(hidden: &Array, batch: &TransformerBatch) -> Result<Array, CoreError> {
    let shape = hidden.shape();
    if shape.len() != 3 {
        return Err(invalid("MLX output requires rank-three hidden states"));
    }
    let positions: Vec<i32> = batch
        .attention_mask
        .iter()
        .enumerate()
        .map(|(row, mask)| {
            let last = mask
                .iter()
                .rposition(|&n| n != 0)
                .ok_or_else(|| invalid("MLX row has no real token"))?;
            row.checked_mul(shape[1] as usize)
                .and_then(|n| n.checked_add(last))
                .and_then(|n| i32::try_from(n).ok())
                .ok_or_else(|| invalid("MLX pooling position overflow"))
        })
        .collect::<Result<_, _>>()?;
    Ok(hidden
        .reshape(&[-1, shape[2]])?
        .take_axis(Array::from_slice(&positions, &[positions.len() as i32]), 0)?
        .as_dtype(Dtype::Float32)?)
}
pub(crate) fn embedding(
    hidden: &Array,
    batch: &TransformerBatch,
) -> Result<TransformerRunResult, CoreError> {
    let pooled = last_real(hidden, batch)?;
    pooled.eval()?;
    finite(&pooled, "pooled hidden state")?;
    let mut values = pooled.as_slice::<f32>().to_vec();
    let columns = hidden.shape()[2] as usize;
    for row in values.chunks_exact_mut(columns) {
        let norm = row.iter().map(|v| v * v).sum::<f32>().sqrt();
        if !norm.is_finite() || norm <= 0.0 {
            return Err(invalid("MLX encoder returned invalid vectors"));
        }
        for value in row {
            *value /= norm;
        }
    }
    let result = TransformerRunResult {
        rows: batch.input_ids.len(),
        columns,
        values,
    };
    result.validate(result.rows, columns)?;
    Ok(result)
}
pub(crate) fn yes_minus_no(
    hidden: &Array,
    batch: &TransformerBatch,
    difference: &Array,
) -> Result<TransformerRunResult, CoreError> {
    let scores = last_real(hidden, batch)?.matmul(difference)?;
    scores.eval()?;
    finite(&scores, "raw yes/no scores")?;
    let result = TransformerRunResult {
        rows: batch.input_ids.len(),
        columns: 1,
        values: scores.as_slice::<f32>().to_vec(),
    };
    result.validate(result.rows, 1)?;
    Ok(result)
}
