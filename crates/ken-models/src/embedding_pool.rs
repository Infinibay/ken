//! One owner of FastEmbed's four output recipes and their cast boundaries.
use crate::{FastEmbedTokens, ModelError, fastembed_model::Pooling};

fn invalid() -> ModelError {
    ModelError::Inference("invalid FastEmbed output shape, mask or finite arithmetic".into())
}

pub(crate) fn pool(
    mode: Pooling,
    dim: usize,
    values: &[f32],
    shape: &[usize],
    tokens: &FastEmbedTokens,
) -> Result<Vec<Vec<f32>>, ModelError> {
    let [batch, sequence] = tokens.shape;
    let token_count = batch.checked_mul(sequence).ok_or_else(invalid)?;
    if dim == 0
        || (batch > 0 && sequence == 0)
        || tokens.ids.len() != token_count
        || tokens.attention_mask.len() != token_count
        || tokens
            .attention_mask
            .iter()
            .any(|value| !matches!(value, 0 | 1))
        || shape.first() != Some(&batch)
        || shape.last() != Some(&dim)
        || values.iter().any(|value| !value.is_finite())
    {
        return Err(invalid());
    }
    let count = shape
        .iter()
        .try_fold(1_usize, |size, value| size.checked_mul(*value))
        .ok_or_else(invalid)?;
    if count != values.len() {
        return Err(invalid());
    }
    let matrix = shape.len() == 2;
    let hidden = shape.len() == 3 && shape[1] == sequence;
    match mode {
        Pooling::Raw if !matrix => return Err(invalid()),
        Pooling::ClsOrSentenceL2 if !matrix && !hidden => return Err(invalid()),
        Pooling::Mean | Pooling::MeanL2 if !hidden => return Err(invalid()),
        _ => (),
    }
    let mut vectors = Vec::with_capacity(batch);
    for row in 0..batch {
        let vector = match mode {
            Pooling::Raw | Pooling::ClsOrSentenceL2 => {
                let start = if matrix {
                    row * dim
                } else {
                    row * sequence * dim
                };
                let mut vector = values[start..start + dim].to_vec();
                if matches!(mode, Pooling::ClsOrSentenceL2) {
                    let square = vector.iter().fold(0_f32, |sum, value| sum + value * value);
                    if !square.is_finite() {
                        return Err(invalid());
                    }
                    let norm = square.sqrt().max(1e-12);
                    for value in &mut vector {
                        *value /= norm;
                    }
                }
                vector
            }
            Pooling::Mean | Pooling::MeanL2 => {
                let mut vector = vec![0_f64; dim];
                let mut count = 0_f64;
                for token in 0..sequence {
                    let mask = tokens.attention_mask[row * sequence + token] as f64;
                    count += mask;
                    let start = (row * sequence + token) * dim;
                    for (output, input) in vector.iter_mut().zip(&values[start..start + dim]) {
                        *output += f64::from(*input) * mask;
                    }
                }
                for value in &mut vector {
                    *value /= count.max(1e-9);
                }
                if matches!(mode, Pooling::MeanL2) {
                    let norm = vector.iter().map(|value| value * value).sum::<f64>().sqrt();
                    if !norm.is_finite() {
                        return Err(invalid());
                    }
                    for value in &mut vector {
                        *value /= norm.max(1e-12);
                    }
                }
                if vector.iter().any(|value| !value.is_finite()) {
                    return Err(invalid());
                }
                vector.into_iter().map(|value| value as f32).collect()
            }
        };
        if vector.iter().any(|value| !value.is_finite()) {
            return Err(invalid());
        }
        vectors.push(vector);
    }
    Ok(vectors)
}
