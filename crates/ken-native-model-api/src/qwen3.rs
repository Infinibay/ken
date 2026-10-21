//! Qwen architectural dimensions, independent of weight storage and execution.
use crate::{ApiError, TransformerWeightLayout};
use std::collections::BTreeMap;
fn invalid(message: impl Into<String>) -> ApiError {
    ApiError::Invalid(message.into())
}
use serde::Deserialize;

#[derive(Clone, Debug, Deserialize, PartialEq)]
pub struct Qwen3Config {
    pub model_type: String,
    pub hidden_size: i64,
    pub intermediate_size: i64,
    pub num_hidden_layers: usize,
    pub num_attention_heads: i64,
    pub num_key_value_heads: i64,
    pub head_dim: i64,
    pub vocab_size: i64,
    pub max_position_embeddings: usize,
    pub rms_norm_eps: f64,
    pub rope_theta: f64,
    pub hidden_act: String,
    #[serde(default)]
    pub attention_bias: bool,
    #[serde(default)]
    pub use_sliding_window: bool,
    #[serde(default)]
    pub rope_scaling: Option<serde_json::Value>,
    #[serde(default)]
    pub tie_word_embeddings: bool,
    #[serde(skip)]
    pub(crate) layout: Option<TransformerWeightLayout>,
}

impl Qwen3Config {
    pub fn from_json(input: &str, layout: TransformerWeightLayout) -> Result<Self, ApiError> {
        let mut value: Self = serde_json::from_str(input)
            .map_err(|e| invalid(format!("Qwen3 configuration: {e}")))?;
        value.layout = Some(layout);
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ApiError> {
        if self.model_type != "qwen3"
            || self.hidden_act != "silu"
            || self.attention_bias
            || self.use_sliding_window
            || self.rope_scaling.is_some()
            || self.num_hidden_layers == 0
            || self.num_hidden_layers > 256
            || self.max_position_embeddings == 0
            || self.max_position_embeddings > (1 << 24)
            || [
                self.hidden_size,
                self.intermediate_size,
                self.head_dim,
                self.num_attention_heads,
                self.num_key_value_heads,
                self.vocab_size,
            ]
            .iter()
            .any(|&v| v <= 0 || v > (1 << 24))
            || self.head_dim % 2 != 0
            || self.num_attention_heads % self.num_key_value_heads != 0
            || self
                .num_attention_heads
                .checked_mul(self.head_dim)
                .is_none()
            || !self.rms_norm_eps.is_finite()
            || self.rms_norm_eps <= 0.0
            || !self.rope_theta.is_finite()
            || self.rope_theta <= 0.0
            || self.layout.is_none()
        {
            return Err(invalid("unsupported or invalid Qwen3 configuration"));
        }
        Ok(())
    }
}

impl Qwen3Config {
    pub fn layout(&self) -> Option<TransformerWeightLayout> {
        self.layout
    }
    pub fn parameter_shapes(&self) -> BTreeMap<String, Vec<i64>> {
        let c = self;
        let mut result = BTreeMap::from([
            (
                "embed_tokens.weight".into(),
                vec![c.vocab_size, c.hidden_size],
            ),
            ("norm.weight".into(), vec![c.hidden_size]),
        ]);
        for layer in 0..c.num_hidden_layers {
            let prefix = format!("layers.{layer}");
            for (name, shape) in [
                ("input_layernorm.weight", vec![c.hidden_size]),
                ("post_attention_layernorm.weight", vec![c.hidden_size]),
                ("self_attn.q_norm.weight", vec![c.head_dim]),
                ("self_attn.k_norm.weight", vec![c.head_dim]),
                (
                    "self_attn.q_proj.weight",
                    vec![c.num_attention_heads * c.head_dim, c.hidden_size],
                ),
                (
                    "self_attn.k_proj.weight",
                    vec![c.num_key_value_heads * c.head_dim, c.hidden_size],
                ),
                (
                    "self_attn.v_proj.weight",
                    vec![c.num_key_value_heads * c.head_dim, c.hidden_size],
                ),
                (
                    "self_attn.o_proj.weight",
                    vec![c.hidden_size, c.num_attention_heads * c.head_dim],
                ),
                (
                    "mlp.gate_proj.weight",
                    vec![c.intermediate_size, c.hidden_size],
                ),
                (
                    "mlp.up_proj.weight",
                    vec![c.intermediate_size, c.hidden_size],
                ),
                (
                    "mlp.down_proj.weight",
                    vec![c.hidden_size, c.intermediate_size],
                ),
            ] {
                result.insert(format!("{prefix}.{name}"), shape);
            }
        }
        result
    }
}
