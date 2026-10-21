//! Validate the complete declared network before publishing owned native tensors.
pub(crate) use crate::parameter_zip::read as read_parameter_zip;
use crate::{CoreConfig, CoreError, invalid};
use ken_native_model_api::{TransformerDevice, TransformerDtype, TransformerWeightLayout};
use std::{collections::BTreeMap, path::Path};
use tch::{Device, Kind, Tensor};

pub struct TorchWeights {
    pub(crate) config: CoreConfig,
    tensors: BTreeMap<String, Tensor>,
    pub(crate) device: Device,
    pub(crate) kind: Kind,
}

impl TorchWeights {
    pub fn load(
        config: &CoreConfig,
        path: &Path,
        device: TransformerDevice,
        dtype: TransformerDtype,
    ) -> Result<Self, CoreError> {
        config.validate()?;
        let device = resolve_device(device)?;
        let kind = resolve_kind(dtype);
        let expected = expected(config);
        let maximum = expected
            .values()
            .try_fold(0_u64, |total, shape| {
                let elements = shape
                    .iter()
                    .try_fold(1_u64, |n, &size| n.checked_mul(size as u64))?;
                total.checked_add(elements.checked_mul(4)?)
            })
            .and_then(|v| v.checked_add(ken_native_model_api::MAX_PAYLOAD as u64 + 8))
            .ok_or_else(|| invalid("weight storage size overflow"))?;
        let tensors = owned_tensors(
            crate::parameter_file::read(path, maximum)?,
            expected,
            config.layout,
            device,
            kind,
        )?;
        Ok(Self {
            config: config.clone(),
            tensors,
            device,
            kind,
        })
    }

    pub(crate) fn get(&self, name: &str) -> Result<&Tensor, CoreError> {
        self.tensors
            .get(name)
            .ok_or_else(|| invalid(format!("missing owned weight: {name}")))
    }
}

pub(crate) fn finite(tensor: &Tensor, name: &str) -> Result<(), CoreError> {
    if tensor.f_isfinite()?.f_all()?.f_int64_value(&[])? != 1 {
        return Err(invalid(format!("nonfinite native tensor: {name}")));
    }
    Ok(())
}

fn expected(c: &CoreConfig) -> BTreeMap<String, Vec<i64>> {
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

pub(crate) fn resolve_device(device: TransformerDevice) -> Result<Device, CoreError> {
    match device {
        TransformerDevice::Cpu => Ok(Device::Cpu),
        TransformerDevice::Mps if tch::utils::has_mps() => Ok(Device::Mps),
        TransformerDevice::Cuda(index)
            if tch::Cuda::is_available() && (index as u128) < tch::Cuda::device_count() as u128 =>
        {
            Ok(Device::Cuda(index))
        }
        _ => Err(invalid("requested native tensor device is unavailable")),
    }
}

pub(crate) fn resolve_kind(dtype: TransformerDtype) -> Kind {
    match dtype {
        TransformerDtype::Float32 => Kind::Float,
        TransformerDtype::Float16 => Kind::Half,
        TransformerDtype::BFloat16 => Kind::BFloat16,
    }
}

pub(crate) fn owned_tensors(
    items: Vec<(String, Tensor)>,
    mut expected: BTreeMap<String, Vec<i64>>,
    layout: Option<TransformerWeightLayout>,
    device: Device,
    kind: Kind,
) -> Result<BTreeMap<String, Tensor>, CoreError> {
    let mut tensors = BTreeMap::new();
    for (name, tensor) in items {
        let canonical = match layout {
            Some(TransformerWeightLayout::Unprefixed) => name.as_str(),
            Some(TransformerWeightLayout::ModelPrefix) => name
                .strip_prefix("model.")
                .ok_or_else(|| invalid(format!("wrong declared tensor prefix: {name}")))?,
            None => return Err(invalid("missing declared weight layout")),
        };
        let shape = expected
            .remove(canonical)
            .ok_or_else(|| invalid(format!("unexpected or duplicate weight: {name}")))?;
        if tensor.size() != shape
            || !matches!(tensor.kind(), Kind::Float | Kind::Half | Kind::BFloat16)
        {
            return Err(invalid(format!("wrong tensor shape/dtype: {name}")));
        }
        finite(&tensor, &name)?;
        let tensor = tensor.f_to_kind(kind)?;
        finite(&tensor, &name)?;
        tensors.insert(canonical.into(), tensor.f_to_device(device)?);
    }
    if !expected.is_empty() {
        return Err(invalid(format!(
            "missing weights: {}",
            expected.keys().cloned().collect::<Vec<_>>().join(", ")
        )));
    }
    Ok(tensors)
}
