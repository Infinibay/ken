//! Native Qwen3 graph. Each request creates a stream on its calling thread.
use crate::{
    CoreError, invalid,
    weights::{MlxWeights, finite},
};
use ken_native_model_api::{Qwen3Config, TransformerBatch};
use mlx_rs::{Array, Device, Dtype, fast, nn, with_device};

pub struct Qwen3 {
    config: Qwen3Config,
    weights: MlxWeights,
}
impl Qwen3 {
    pub fn load(config: Qwen3Config, weights: MlxWeights) -> Result<Self, CoreError> {
        config.validate()?;
        if config != weights.config {
            return Err(invalid("MLX weights belong to a different architecture"));
        }
        Ok(Self { config, weights })
    }
    pub fn forward(&self, batch: &TransformerBatch) -> Result<Array, CoreError> {
        batch.validate(
            self.config.vocab_size as u64,
            self.config.max_position_embeddings,
            usize::MAX,
        )?;
        let ids: Vec<Vec<i32>> = batch
            .input_ids
            .iter()
            .map(|row| {
                row.iter()
                    .map(|&n| i32::try_from(n).map_err(|_| invalid("MLX token ID overflow")))
                    .collect()
            })
            .collect::<Result<_, _>>()?;
        with_device(Device::gpu(), || {
            let value = infer(&self.config, &self.weights, &ids)?;
            value.eval()?;
            finite(&value, "hidden states")?;
            Ok(value)
        })
    }
    pub(crate) fn dtype(&self) -> Result<Dtype, CoreError> {
        Ok(self.weights.get("embed_tokens.weight")?.dtype())
    }
    pub(crate) fn dimension(&self) -> usize {
        self.config.hidden_size as usize
    }
    pub(crate) fn validate_output_head(&self) -> Result<(), CoreError> {
        if self.weights.head.is_some() || self.config.tie_word_embeddings {
            Ok(())
        } else {
            Err(invalid("missing untied MLX language model output weights"))
        }
    }
    pub(crate) fn projection_difference(&self, yes: u32, no: u32) -> Result<Array, CoreError> {
        let head = if let Some(head) = &self.weights.head {
            head
        } else if self.config.tie_word_embeddings {
            self.weights.get("embed_tokens.weight")?
        } else {
            return Err(invalid("missing untied MLX language model output weights"));
        };
        with_device(Device::gpu(), || {
            Ok(head
                .take_axis(Array::from_int(yes as i32), 0)?
                .as_dtype(Dtype::Float32)?
                .subtract(
                    head.take_axis(Array::from_int(no as i32), 0)?
                        .as_dtype(Dtype::Float32)?,
                )?)
        })
    }
}
fn linear(x: &Array, w: &MlxWeights, name: &str) -> Result<Array, CoreError> {
    Ok(x.matmul(w.get(&format!("{name}.weight"))?.transpose()?)?)
}
fn norm(x: &Array, w: &MlxWeights, name: &str, eps: f32) -> Result<Array, CoreError> {
    Ok(fast::rms_norm(
        x,
        Some(w.get(&format!("{name}.weight"))?),
        eps,
    )?)
}
fn infer(c: &Qwen3Config, w: &MlxWeights, ids: &[Vec<i32>]) -> Result<Array, CoreError> {
    let batch = ids.len() as i32;
    let length = ids[0].len() as i32;
    let hidden = c.hidden_size as i32;
    let heads = c.num_attention_heads as i32;
    let kv = c.num_key_value_heads as i32;
    let head_dim = c.head_dim as i32;
    let eps = c.rms_norm_eps as f32;
    let theta = c.rope_theta as f32;
    let input = Array::from_slice(
        &ids.iter().flatten().copied().collect::<Vec<_>>(),
        &[batch, length],
    );
    let mut x = w.get("embed_tokens.weight")?.take_axis(&input, 0)?;
    for layer in 0..c.num_hidden_layers {
        let p = format!("layers.{layer}");
        let normalized = norm(&x, w, &format!("{p}.input_layernorm"), eps)?;
        let queries = linear(&normalized, w, &format!("{p}.self_attn.q_proj"))?
            .reshape(&[batch, length, heads, head_dim])?;
        let keys = linear(&normalized, w, &format!("{p}.self_attn.k_proj"))?
            .reshape(&[batch, length, kv, head_dim])?;
        let values = linear(&normalized, w, &format!("{p}.self_attn.v_proj"))?
            .reshape(&[batch, length, kv, head_dim])?
            .transpose_axes(&[0, 2, 1, 3])?;
        let queries = norm(&queries, w, &format!("{p}.self_attn.q_norm"), eps)?
            .transpose_axes(&[0, 2, 1, 3])?;
        let keys =
            norm(&keys, w, &format!("{p}.self_attn.k_norm"), eps)?.transpose_axes(&[0, 2, 1, 3])?;
        let queries = fast::rope(&queries, head_dim, false, Some(theta), 1.0, 0, None)?;
        let keys = fast::rope(&keys, head_dim, false, Some(theta), 1.0, 0, None)?;
        let mask = if length > 1 {
            Some(fast::ScaledDotProductAttentionMask::Causal)
        } else {
            None
        };
        let attention = fast::scaled_dot_product_attention(
            &queries,
            &keys,
            &values,
            (head_dim as f32).powf(-0.5),
            mask,
            None,
        )?
        .transpose_axes(&[0, 2, 1, 3])?
        .reshape(&[batch, length, heads * head_dim])?;
        x = x.add(linear(&attention, w, &format!("{p}.self_attn.o_proj"))?)?;
        let normalized = norm(&x, w, &format!("{p}.post_attention_layernorm"), eps)?;
        let gate = nn::silu(linear(&normalized, w, &format!("{p}.mlp.gate_proj"))?)?;
        let inner = gate.multiply(linear(&normalized, w, &format!("{p}.mlp.up_proj"))?)?;
        x = x.add(linear(&inner, w, &format!("{p}.mlp.down_proj"))?)?;
    }
    if x.shape() != [batch, length, hidden] {
        return Err(invalid(
            "MLX network output shape differs from declared dimensions",
        ));
    }
    norm(&x, w, "norm", eps)
}

#[cfg(test)]
mod head_tests {
    use super::*;
    use ken_native_model_api::{TransformerDtype, TransformerWeightLayout};
    #[test]
    fn explicit_mlx_head_retains_source_precision_even_when_backbone_is_bfloat16() {
        let source = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../ken-torch-backend/tests/fixtures/qwen");
        let config = Qwen3Config::from_json(
            &std::fs::read_to_string(source.join("config.json")).unwrap(),
            TransformerWeightLayout::Unprefixed,
        )
        .unwrap();
        let raw = std::fs::read(source.join("model.safetensors")).unwrap();
        let length = u64::from_le_bytes(raw[..8].try_into().unwrap()) as usize;
        let data = &raw[8 + length..];
        let mut header: serde_json::Value = serde_json::from_slice(&raw[8..8 + length]).unwrap();
        let values: Vec<f32> = (0..32).map(|n| 1.0004_f32 + n as f32 * 0.1234).collect();
        let extra: Vec<_> = values.iter().flat_map(|n| n.to_le_bytes()).collect();
        header["lm_head.weight"] = serde_json::json!({"dtype":"F32","shape":[8,4],"data_offsets":[data.len(),data.len()+extra.len()]});
        let mut metadata = serde_json::to_vec(&header).unwrap();
        while !metadata.len().is_multiple_of(8) {
            metadata.push(b' ');
        }
        let mut bytes = (metadata.len() as u64).to_le_bytes().to_vec();
        bytes.extend(metadata);
        bytes.extend(data);
        bytes.extend(extra);
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("model.safetensors");
        std::fs::write(&path, bytes).unwrap();
        let weights = MlxWeights::load(&config, &path, TransformerDtype::BFloat16).unwrap();
        let core = Qwen3::load(config, weights).unwrap();
        with_device(Device::gpu(), || {
            let actual = core.projection_difference(1, 6).unwrap();
            actual.eval().unwrap();
            let wanted: Vec<_> = (0..4).map(|i| values[4 + i] - values[24 + i]).collect();
            assert_eq!(actual.as_slice::<f32>(), wanted);
            let rounded = Array::from_slice(&values, &[8, 4])
                .as_dtype(Dtype::Bfloat16)
                .unwrap()
                .as_dtype(Dtype::Float32)
                .unwrap();
            let rounded = rounded
                .take_axis(Array::from_int(1), 0)
                .unwrap()
                .subtract(rounded.take_axis(Array::from_int(6), 0).unwrap())
                .unwrap();
            rounded.eval().unwrap();
            assert_ne!(actual.as_slice::<f32>(), rounded.as_slice::<f32>());
        });
    }
}
