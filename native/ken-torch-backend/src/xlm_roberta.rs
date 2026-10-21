//! XLM-R positions, biased layers and bidirectional attention with owned weights.
use crate::{CoreError, invalid, weights::finite, xlm_roberta_weights::XlmRobertaWeights};
use ken_native_model_api::{TransformerBatch, TransformerWeightLayout};
use serde::Deserialize;
use tch::{Device, Kind, Tensor};

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct XlmRobertaConfig {
    pub model_type: String,
    pub hidden_size: i64,
    pub intermediate_size: i64,
    pub num_hidden_layers: usize,
    pub num_attention_heads: i64,
    pub vocab_size: i64,
    pub max_position_embeddings: usize,
    pub type_vocab_size: i64,
    pub pad_token_id: i64,
    pub layer_norm_eps: f64,
    pub hidden_act: String,
    pub position_embedding_type: String,
    #[serde(default)]
    pub is_decoder: bool,
    #[serde(default)]
    pub add_cross_attention: bool,
    #[serde(default)]
    pub architectures: Option<Vec<String>>,
    #[serde(skip)]
    pub(crate) layout: Option<TransformerWeightLayout>,
}
impl XlmRobertaConfig {
    pub fn from_json(input: &str, layout: TransformerWeightLayout) -> Result<Self, CoreError> {
        let mut value: Self = serde_json::from_str(input)?;
        value.layout = Some(layout);
        value.validate()?;
        Ok(value)
    }
    pub(crate) fn validate(&self) -> Result<(), CoreError> {
        if self.model_type != "xlm-roberta"
            || self.hidden_act != "gelu"
            || self.position_embedding_type != "absolute"
            || self.is_decoder
            || self.add_cross_attention
            || self.num_hidden_layers == 0
            || self.num_hidden_layers > 256
            || [
                self.hidden_size,
                self.intermediate_size,
                self.num_attention_heads,
                self.vocab_size,
                self.type_vocab_size,
            ]
            .iter()
            .any(|&n| n <= 0 || n > (1 << 24))
            || self.hidden_size % self.num_attention_heads != 0
            || self.max_position_embeddings == 0
            || self.max_position_embeddings > (1 << 24)
            || self.pad_token_id < 0
            || self.pad_token_id >= self.vocab_size
            || self.pad_token_id as usize + 1 >= self.max_position_embeddings
            || !self.layer_norm_eps.is_finite()
            || self.layer_norm_eps <= 0.0
            || self.layout.is_none()
            || self
                .architectures
                .as_ref()
                .is_some_and(|names| names != &["XLMRobertaModel"])
        {
            return Err(invalid(
                "unsupported or invalid XLM-R base-model configuration",
            ));
        }
        Ok(())
    }
}

pub struct XlmRoberta {
    config: XlmRobertaConfig,
    weights: XlmRobertaWeights,
}
impl XlmRoberta {
    pub fn load(config: XlmRobertaConfig, weights: XlmRobertaWeights) -> Result<Self, CoreError> {
        config.validate()?;
        if config != weights.config {
            return Err(invalid("weights belong to a different XLM-R configuration"));
        }
        Ok(Self { config, weights })
    }
    pub(crate) fn observed_identity(&self) -> Result<(Device, Kind, usize), CoreError> {
        let embedding = self.weights.get("embeddings.word_embeddings.weight")?;
        Ok((
            embedding.device(),
            embedding.kind(),
            embedding.size()[1] as usize,
        ))
    }
    pub fn forward(&self, batch: &TransformerBatch) -> Result<Tensor, CoreError> {
        let _no_grad = tch::no_grad_guard();
        let c = &self.config;
        let w = &self.weights;
        batch
            .validate(c.vocab_size as u64, c.max_position_embeddings, usize::MAX)
            .map_err(|e| invalid(e.to_string()))?;
        let n = batch.input_ids.len() as i64;
        let s = batch.input_ids[0].len() as i64;
        let h = c.hidden_size;
        let ids: Vec<i64> = batch.input_ids.iter().flatten().copied().collect();
        let mut positions = Vec::with_capacity(ids.len());
        for row in &batch.input_ids {
            let mut count = c.pad_token_id;
            for &id in row {
                let position = if id == c.pad_token_id {
                    c.pad_token_id
                } else {
                    count += 1;
                    count
                };
                if position as usize >= c.max_position_embeddings {
                    return Err(invalid("XLM-R position exceeds registered table"));
                }
                positions.push(position);
            }
        }
        let ids = Tensor::f_from_slice(&ids)?.f_to_device(w.device)?;
        let positions = Tensor::f_from_slice(&positions)?.f_to_device(w.device)?;
        let words = w
            .get("embeddings.word_embeddings.weight")?
            .f_index_select(0, &ids)?
            .f_reshape([n, s, h])?;
        let types = w
            .get("embeddings.token_type_embeddings.weight")?
            .f_select(0, 0)?;
        let positions = w
            .get("embeddings.position_embeddings.weight")?
            .f_index_select(0, &positions)?
            .f_reshape([n, s, h])?;
        let mut x = layer_norm(
            &words.f_add(&types)?.f_add(&positions)?,
            w,
            "embeddings.LayerNorm",
            c.layer_norm_eps,
        )?;
        let mask = if batch.attention_mask.iter().flatten().any(|&n| n == 0) {
            let minimum = match w.kind {
                Kind::Half => -65504.0_f32,
                Kind::BFloat16 => -3.389_531_4e38_f32,
                _ => f32::MIN,
            };
            let entries = (n as usize)
                .checked_mul(s as usize)
                .and_then(|n| n.checked_mul(s as usize))
                .ok_or_else(|| invalid("XLM-R mask size overflow"))?;
            let mut values = Vec::new();
            values
                .try_reserve_exact(entries)
                .map_err(|e| invalid(e.to_string()))?;
            for row in &batch.attention_mask {
                for _ in 0..s {
                    values.extend(row.iter().map(|&v| if v == 0 { minimum } else { 0.0 }));
                }
            }
            Some(
                Tensor::f_from_slice(&values)?
                    .f_to_kind(w.kind)?
                    .f_to_device(w.device)?
                    .f_reshape([n, 1, s, s])?,
            )
        } else {
            None
        };
        for index in 0..c.num_hidden_layers {
            let p = format!("encoder.layer.{index}");
            let heads = c.num_attention_heads;
            let width = h / heads;
            let q = linear(&x, w, &format!("{p}.attention.self.query"))?
                .f_reshape([n, s, heads, width])?
                .f_transpose(1, 2)?;
            let k = linear(&x, w, &format!("{p}.attention.self.key"))?
                .f_reshape([n, s, heads, width])?
                .f_transpose(1, 2)?;
            let v = linear(&x, w, &format!("{p}.attention.self.value"))?
                .f_reshape([n, s, heads, width])?
                .f_transpose(1, 2)?;
            let attention = Tensor::f_scaled_dot_product_attention(
                &q,
                &k,
                &v,
                mask.as_ref(),
                0.0,
                false,
                None,
                false,
            )?
            .f_transpose(1, 2)?
            .f_contiguous()?
            .f_reshape([n, s, h])?;
            x = layer_norm(
                &linear(&attention, w, &format!("{p}.attention.output.dense"))?.f_add(&x)?,
                w,
                &format!("{p}.attention.output.LayerNorm"),
                c.layer_norm_eps,
            )?;
            let intermediate = linear(&x, w, &format!("{p}.intermediate.dense"))?.f_gelu("none")?;
            x = layer_norm(
                &linear(&intermediate, w, &format!("{p}.output.dense"))?.f_add(&x)?,
                w,
                &format!("{p}.output.LayerNorm"),
                c.layer_norm_eps,
            )?;
        }
        finite(&x, "XLM-R hidden states")?;
        Ok(x)
    }
}
fn linear(x: &Tensor, w: &XlmRobertaWeights, name: &str) -> Result<Tensor, CoreError> {
    Ok(x.f_linear(
        w.get(&format!("{name}.weight"))?,
        Some(w.get(&format!("{name}.bias"))?),
    )?)
}
fn layer_norm(
    x: &Tensor,
    w: &XlmRobertaWeights,
    name: &str,
    eps: f64,
) -> Result<Tensor, CoreError> {
    Ok(x.f_layer_norm(
        [w.config.hidden_size],
        Some(w.get(&format!("{name}.weight"))?),
        Some(w.get(&format!("{name}.bias"))?),
        eps,
        true,
    )?)
}
