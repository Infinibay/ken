//! Stateless Qwen3 hidden states: weights own data, layers own network rules.
use crate::{
    CoreConfig, CoreError, invalid,
    weights::{TorchWeights, finite},
};
use ken_native_model_api::TransformerBatch;
use tch::{Device, Kind, Tensor};

pub struct Qwen3 {
    config: CoreConfig,
    weights: TorchWeights,
    inv_frequency: Tensor,
}

impl Qwen3 {
    pub(crate) fn to_cpu_float32(&self) -> Result<Self, CoreError> {
        let weights = self.weights.to_cpu_float32()?;
        let inv_frequency = self
            .inv_frequency
            .f_to_device(Device::Cpu)?
            .f_to_kind(Kind::Float)?;
        finite(&inv_frequency, "converted RoPE buffer")?;
        Ok(Self {
            config: self.config.clone(),
            weights,
            inv_frequency,
        })
    }
    pub(crate) fn validate_output_head(&self) -> Result<(), CoreError> {
        self.weights.output_head().map(|_| ())
    }
    pub(crate) fn projection_difference(
        &self,
        true_id: u32,
        false_id: u32,
    ) -> Result<Tensor, CoreError> {
        let weight = self.weights.output_head()?;
        // The original Torch judge casts each selected row before subtraction.
        // Lower-precision subtraction followed by casting changes the logits.
        Ok(weight
            .f_select(0, i64::from(true_id))?
            .f_to_kind(Kind::Float)?
            .f_sub(
                &weight
                    .f_select(0, i64::from(false_id))?
                    .f_to_kind(Kind::Float)?,
            )?)
    }
    pub(crate) fn observed_identity(&self) -> Result<(Device, Kind, usize), CoreError> {
        let embedding = self.weights.get("embed_tokens.weight")?;
        let dimension = usize::try_from(embedding.size()[1])
            .map_err(|_| invalid("invalid actual network dimension"))?;
        Ok((embedding.device(), embedding.kind(), dimension))
    }
    pub fn load(config: CoreConfig, weights: TorchWeights) -> Result<Self, CoreError> {
        config.validate()?;
        if config != weights.config {
            return Err(invalid("weights belong to a different Qwen3 configuration"));
        }
        // Original HF initializes this buffer on CPU, then moves it. Computing
        // pow on MPS changes FP16 output despite mathematically identical RoPE.
        let powers =
            Tensor::f_arange_start_step(0, config.head_dim, 2, (Kind::Int64, Device::Cpu))?
                .f_to_kind(Kind::Float)?
                .f_div_scalar(config.head_dim as f64)?;
        let inv_frequency = Tensor::f_full(
            [config.head_dim / 2],
            config.rope_theta,
            (Kind::Float, Device::Cpu),
        )?
        .f_pow(&powers)?
        .f_reciprocal()?
        .f_to_device(weights.device)?;
        Ok(Self {
            config,
            weights,
            inv_frequency,
        })
    }

    pub fn forward(&self, batch: &TransformerBatch) -> Result<Tensor, CoreError> {
        let _no_grad = tch::no_grad_guard();
        let c = &self.config;
        let w = &self.weights;
        batch
            .validate(c.vocab_size as u64, c.max_position_embeddings, usize::MAX)
            .map_err(|e| invalid(e.to_string()))?;
        let n = i64::try_from(batch.input_ids.len())
            .map_err(|_| invalid("batch dimension overflow"))?;
        let s = i64::try_from(batch.input_ids[0].len())
            .map_err(|_| invalid("sequence dimension overflow"))?;
        let ids = Tensor::f_from_slice(
            &batch
                .input_ids
                .iter()
                .flatten()
                .copied()
                .collect::<Vec<_>>(),
        )?
        .f_to_device(w.device)?;
        let mut x = w
            .get("embed_tokens.weight")?
            .f_index_select(0, &ids)?
            .f_reshape([n, s, c.hidden_size])?;
        let positions = Tensor::f_arange(s, (Kind::Float, w.device))?;
        let frequencies = self
            .inv_frequency
            .f_reshape([1, c.head_dim / 2, 1])?
            .f_matmul(&positions.f_reshape([1, 1, s])?)?
            .f_transpose(1, 2)?;
        let angles = Tensor::f_cat(&[&frequencies, &frequencies], -1)?;
        let cos = angles.f_cos()?.f_to_kind(w.kind)?.f_unsqueeze(1)?;
        let sin = angles.f_sin()?.f_to_kind(w.kind)?.f_unsqueeze(1)?;
        let padding = batch.attention_mask.iter().flatten().any(|&v| v == 0);
        let mask = if padding {
            let entries = batch
                .attention_mask
                .len()
                .checked_mul(s as usize)
                .and_then(|v| v.checked_mul(s as usize))
                .ok_or_else(|| invalid("attention mask size overflow"))?;
            let mut allowed = Vec::new();
            allowed
                .try_reserve_exact(entries)
                .map_err(|e| invalid(e.to_string()))?;
            for row in &batch.attention_mask {
                for query in 0..s as usize {
                    for (key, &real) in row.iter().enumerate() {
                        allowed.push(u8::from(key <= query && real != 0));
                    }
                }
            }
            Some(
                Tensor::f_from_slice(&allowed)?
                    .f_to_kind(Kind::Bool)?
                    .f_to_device(w.device)?
                    .f_reshape([n, 1, s, s])?,
            )
        } else {
            None
        };
        for layer in 0..c.num_hidden_layers {
            let prefix = format!("layers.{layer}");
            let normalized = norm(
                &x,
                w.get(&format!("{prefix}.input_layernorm.weight"))?,
                c.rms_norm_eps,
            )?;
            let q = norm(
                &linear(&normalized, w, &format!("{prefix}.self_attn.q_proj"))?.f_reshape([
                    n,
                    s,
                    c.num_attention_heads,
                    c.head_dim,
                ])?,
                w.get(&format!("{prefix}.self_attn.q_norm.weight"))?,
                c.rms_norm_eps,
            )?
            .f_transpose(1, 2)?;
            let k = norm(
                &linear(&normalized, w, &format!("{prefix}.self_attn.k_proj"))?.f_reshape([
                    n,
                    s,
                    c.num_key_value_heads,
                    c.head_dim,
                ])?,
                w.get(&format!("{prefix}.self_attn.k_norm.weight"))?,
                c.rms_norm_eps,
            )?
            .f_transpose(1, 2)?;
            let v = linear(&normalized, w, &format!("{prefix}.self_attn.v_proj"))?
                .f_reshape([n, s, c.num_key_value_heads, c.head_dim])?
                .f_transpose(1, 2)?;
            let q = q
                .f_mul(&cos)?
                .f_add(&rotate(&q, c.head_dim / 2)?.f_mul(&sin)?)?;
            let k = k
                .f_mul(&cos)?
                .f_add(&rotate(&k, c.head_dim / 2)?.f_mul(&sin)?)?;
            let (k, v, gqa) = if padding {
                (
                    repeat(&k, c.num_attention_heads / c.num_key_value_heads)?,
                    repeat(&v, c.num_attention_heads / c.num_key_value_heads)?,
                    false,
                )
            } else {
                (k, v, true)
            };
            let attention = Tensor::f_scaled_dot_product_attention(
                &q,
                &k,
                &v,
                mask.as_ref(),
                0.0,
                !padding && s > 1,
                Some((c.head_dim as f64).powf(-0.5)),
                gqa,
            )?
            .f_transpose(1, 2)?
            .f_contiguous()?
            .f_reshape([n, s, c.num_attention_heads * c.head_dim])?;
            x = x.f_add(&linear(
                &attention,
                w,
                &format!("{prefix}.self_attn.o_proj"),
            )?)?;
            let normalized = norm(
                &x,
                w.get(&format!("{prefix}.post_attention_layernorm.weight"))?,
                c.rms_norm_eps,
            )?;
            let gate = linear(&normalized, w, &format!("{prefix}.mlp.gate_proj"))?.f_silu()?;
            let update = gate.f_mul(&linear(&normalized, w, &format!("{prefix}.mlp.up_proj"))?)?;
            x = x.f_add(&linear(&update, w, &format!("{prefix}.mlp.down_proj"))?)?;
        }
        let hidden = norm(&x, w.get("norm.weight")?, c.rms_norm_eps)?;
        finite(&hidden, "Qwen3 output")?;
        Ok(hidden)
    }
}

fn norm(x: &Tensor, weight: &Tensor, eps: f64) -> Result<Tensor, CoreError> {
    let float = x.f_to_kind(Kind::Float)?;
    // Preserve the actual pow(2) operator; x*x differs on MPS lower precision.
    let variance =
        float
            .f_pow_tensor_scalar(2)?
            .f_mean_dim([-1_i64].as_slice(), true, Kind::Float)?;
    Ok(weight.f_mul(
        &float
            .f_mul(&variance.f_add_scalar(eps)?.f_rsqrt()?)?
            .f_to_kind(x.kind())?,
    )?)
}

fn linear(x: &Tensor, weights: &TorchWeights, name: &str) -> Result<Tensor, CoreError> {
    Ok(x.f_matmul(&weights.get(&format!("{name}.weight"))?.f_transpose(0, 1)?)?)
}

fn rotate(x: &Tensor, half: i64) -> Result<Tensor, CoreError> {
    Ok(Tensor::f_cat(
        &[
            x.f_narrow(-1, half, half)?.f_neg()?,
            x.f_narrow(-1, 0, half)?,
        ],
        -1,
    )?)
}

fn repeat(x: &Tensor, groups: i64) -> Result<Tensor, CoreError> {
    let shape = x.size();
    Ok(x.f_unsqueeze(2)?
        .f_expand([shape[0], shape[1], groups, shape[2], shape[3]], true)?
        .f_reshape([shape[0], shape[1] * groups, shape[2], shape[3]])?)
}
