//! Sentence pooling and normalization remain distinct from network execution.
use crate::{CoreError, invalid, weights::finite};
use ken_native_model_api::{TransformerBatch, TransformerPooling, TransformerRunResult};
use tch::{Device, Kind, Tensor};

pub(crate) fn sentence(
    hidden: &Tensor,
    batch: &TransformerBatch,
    pooling: TransformerPooling,
    normalize_modules: usize,
) -> Result<TransformerRunResult, CoreError> {
    let shape = hidden.size();
    if shape.len() != 3 {
        return Err(invalid("sentence output requires rank-three hidden states"));
    }
    let mut pooled = match pooling {
        TransformerPooling::Cls => hidden.f_select(1, 0)?,
        TransformerPooling::Last => last_real(hidden, batch)?,
        TransformerPooling::Mean => {
            let mask = Tensor::f_from_slice(
                &batch
                    .attention_mask
                    .iter()
                    .flatten()
                    .copied()
                    .collect::<Vec<_>>(),
            )?
            .f_reshape([shape[0], shape[1], 1])?
            .f_to_device(hidden.device())?
            .f_to_kind(hidden.kind())?
            .f_expand(shape.as_slice(), true)?;
            let sum =
                hidden
                    .f_mul(&mask)?
                    .f_sum_dim_intlist([1_i64].as_slice(), false, None::<Kind>)?;
            sum.f_div(
                &mask
                    .f_sum_dim_intlist([1_i64].as_slice(), false, None::<Kind>)?
                    .f_clamp_min(1e-9)?,
            )?
        }
    };
    for _ in 0..normalize_modules {
        pooled = normalize(&pooled)?;
    }
    pooled = normalize(&pooled)?; // Original encode(normalize_embeddings=true).
    let vectors = normalize(&pooled.f_to_kind(Kind::Float)?)?; // Ken outgoing F32 canonicalization.
    finite(&vectors, "sentence vectors")?;
    let values: Vec<f32> = Vec::try_from(&vectors.f_to_device(Device::Cpu)?.f_reshape([-1])?)?;
    let columns = usize::try_from(shape[2]).map_err(|_| invalid("sentence dimension overflow"))?;
    let result = TransformerRunResult {
        rows: batch.input_ids.len(),
        columns,
        values,
    };
    result
        .validate(result.rows, columns)
        .map_err(|e| invalid(e.to_string()))?;
    for row in result.values.chunks_exact(columns) {
        let norm = row.iter().map(|&v| (v as f64).powi(2)).sum::<f64>().sqrt();
        if (norm - 1.0).abs() > 1e-4 {
            return Err(invalid("sentence output is zero or nonunit"));
        }
    }
    Ok(result)
}

fn normalize(value: &Tensor) -> Result<Tensor, CoreError> {
    Ok(value.f_div(
        &value
            .f_norm_scalaropt_dim(2.0, [-1_i64], true)?
            .f_clamp_min(1e-12)?,
    )?)
}

pub(crate) fn yes_minus_no(
    hidden: &Tensor,
    batch: &TransformerBatch,
    difference: &Tensor,
) -> Result<TransformerRunResult, CoreError> {
    let scores = last_real(hidden, batch)?
        .f_to_kind(Kind::Float)?
        .f_matmul(difference)?;
    finite(&scores, "yes/no raw scores")?;
    let values = Vec::<f32>::try_from(&scores.f_to_device(Device::Cpu)?.f_reshape([-1])?)?;
    let result = TransformerRunResult {
        rows: batch.input_ids.len(),
        columns: 1,
        values,
    };
    result
        .validate(result.rows, 1)
        .map_err(|e| invalid(e.to_string()))?;
    Ok(result)
}

fn last_real(hidden: &Tensor, batch: &TransformerBatch) -> Result<Tensor, CoreError> {
    let rows = batch
        .attention_mask
        .iter()
        .enumerate()
        .map(|(row, mask)| {
            let last = mask
                .iter()
                .rposition(|&value| value != 0)
                .ok_or_else(|| invalid("output row has no real token"))?;
            Ok(hidden.f_select(0, row as i64)?.f_select(0, last as i64)?)
        })
        .collect::<Result<Vec<_>, CoreError>>()?;
    Ok(Tensor::f_stack(&rows, 0)?)
}
