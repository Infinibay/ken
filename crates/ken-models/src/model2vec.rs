use crate::{ModelError, ModelTokenizer, VerifiedSnapshot, term_cache::TermCache};
use half::f16;
use safetensors::{Dtype, SafeTensors};
use std::sync::Mutex;

enum Weights {
    Half(Vec<f16>),
    Single(Vec<f32>),
}

/// Registered native mean pooling with Model2Vec's dtype and batching semantics.
pub struct Model2VecEncoder {
    tokenizer: ModelTokenizer,
    weights: Weights,
    dimension: usize,
    terms: Mutex<TermCache>,
}

fn rounded(value: f32) -> f32 {
    f16::from_f32(value).to_f32()
}

impl Model2VecEncoder {
    pub fn load(snapshot: &VerifiedSnapshot) -> Result<Self, ModelError> {
        let tokenizer = ModelTokenizer::load(snapshot.artifact("tokenizer.json")?)?;
        let tensors = SafeTensors::deserialize(snapshot.artifact("model.safetensors")?)
            .map_err(|e| ModelError::Weights(e.to_string()))?;
        if tensors.len() != 1 {
            return Err(ModelError::Weights(
                "only the registered unquantized embeddings tensor is supported".into(),
            ));
        }
        let tensor = tensors
            .tensor("embeddings")
            .map_err(|e| ModelError::Weights(e.to_string()))?;
        let shape = tensor.shape();
        if shape.len() != 2 || shape[0] != tokenizer.vocabulary_len() || shape[1] == 0 {
            return Err(ModelError::Weights(
                "embedding shape must match vocabulary and nonzero dimension".into(),
            ));
        }
        let weights = match tensor.dtype() {
            Dtype::F16 => Weights::Half(
                tensor
                    .data()
                    .chunks_exact(2)
                    .map(|b| f16::from_le_bytes([b[0], b[1]]))
                    .collect(),
            ),
            Dtype::F32 => Weights::Single(
                tensor
                    .data()
                    .chunks_exact(4)
                    .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
                    .collect(),
            ),
            _ => return Err(ModelError::Weights("F16 or F32 embeddings required".into())),
        };
        let finite = match &weights {
            Weights::Half(values) => values.iter().all(|v| v.is_finite()),
            Weights::Single(values) => values.iter().all(|v| v.is_finite()),
        };
        if !finite {
            return Err(ModelError::Weights("nonfinite embeddings".into()));
        }
        Ok(Self {
            tokenizer,
            weights,
            dimension: shape[1],
            terms: Mutex::new(TermCache::default()),
        })
    }

    pub fn dim(&self) -> usize {
        self.dimension
    }

    pub fn token_ids(&self, text: &str, max_length: Option<usize>) -> Result<Vec<u32>, ModelError> {
        self.tokenizer.token_ids(text, max_length)
    }

    pub fn embed_query(&self, text: &str) -> Result<Vec<f32>, ModelError> {
        Ok(self.embed_passages(&[text.into()])?.remove(0))
    }

    pub fn embed_passages(&self, texts: &[String]) -> Result<Vec<Vec<f32>>, ModelError> {
        let mut result = vec![None; texts.len()];
        let mut missing = Vec::new();
        {
            let mut terms = self
                .terms
                .lock()
                .map_err(|_| ModelError::Inference("term cache lock poisoned".into()))?;
            for (index, text) in texts.iter().enumerate() {
                if let Some(value) = terms.get(text) {
                    result[index] = Some(value);
                } else {
                    missing.push(index);
                }
            }
        }
        let mut values = Vec::with_capacity(missing.len());
        for batch in missing.chunks(1024) {
            let ids: Vec<_> = batch
                .iter()
                .map(|&index| self.token_ids(&texts[index], Some(512)))
                .collect::<Result<_, _>>()?;
            let promoted = ids.iter().any(Vec::is_empty);
            for row in ids {
                values.push(self.encode_row(&row, promoted)?);
            }
        }
        {
            let mut terms = self
                .terms
                .lock()
                .map_err(|_| ModelError::Inference("term cache lock poisoned".into()))?;
            for (index, value) in missing.into_iter().zip(values) {
                terms.insert(&texts[index], &value);
                result[index] = Some(value);
            }
        }
        Ok(result
            .into_iter()
            .map(|v| v.expect("every cache miss was encoded"))
            .collect())
    }

    fn encode_row(&self, ids: &[u32], promoted: bool) -> Result<Vec<f32>, ModelError> {
        if ids.is_empty() {
            return Ok(vec![0.0; self.dimension]);
        }
        let mut mean = vec![0.0_f32; self.dimension];
        let half = matches!(self.weights, Weights::Half(_));
        for &id in ids {
            let offset = id as usize * self.dimension;
            match &self.weights {
                Weights::Half(weights) => {
                    for (sum, value) in mean
                        .iter_mut()
                        .zip(&weights[offset..offset + self.dimension])
                    {
                        *sum += value.to_f32();
                    }
                }
                Weights::Single(weights) => {
                    for (sum, value) in mean
                        .iter_mut()
                        .zip(&weights[offset..offset + self.dimension])
                    {
                        *sum += value;
                    }
                }
            }
        }
        for value in &mut mean {
            *value /= ids.len() as f32;
            if half {
                *value = rounded(*value);
            }
        }
        if promoted {
            let norm = mean
                .iter()
                .map(|&v| f64::from(v).powi(2))
                .sum::<f64>()
                .sqrt()
                + 1e-32;
            for value in &mut mean {
                *value = (f64::from(*value) / norm) as f32;
            }
        } else if half {
            let squares = mean.iter().map(|v| rounded(v * v)).sum::<f32>();
            let norm = rounded(rounded(squares).sqrt());
            for value in &mut mean {
                *value = rounded(*value / norm);
            }
        } else {
            let norm = mean.iter().map(|v| v * v).sum::<f32>().sqrt() + 1e-32;
            for value in &mut mean {
                *value /= norm;
            }
        }
        if !mean.iter().all(|v| v.is_finite()) {
            return Err(ModelError::Inference("nonfinite output vector".into()));
        }
        Ok(mean)
    }
}
