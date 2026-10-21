//! Validate the complete declared network before publishing owned native tensors.
pub(crate) use crate::parameter_zip::read as read_parameter_zip;
use crate::{CoreConfig, CoreError, invalid};
use ken_native_model_api::{TransformerDevice, TransformerDtype, TransformerWeightLayout};
use std::{collections::BTreeMap, path::Path};
use tch::{Device, Kind, Tensor};

pub struct TorchWeights {
    pub(crate) config: CoreConfig,
    tensors: BTreeMap<String, Tensor>,
    head: Option<Tensor>,
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
        let expected = config.parameter_shapes();
        let maximum = expected
            .values()
            .try_fold(0_u64, |total, shape| {
                let elements = shape
                    .iter()
                    .try_fold(1_u64, |n, &size| n.checked_mul(size as u64))?;
                total.checked_add(elements.checked_mul(4)?)
            })
            .and_then(|v| {
                v.checked_add(
                    (config.vocab_size as u64)
                        .checked_mul(config.hidden_size as u64)?
                        .checked_mul(4)?,
                )
            })
            .and_then(|v| v.checked_add(ken_native_model_api::MAX_PAYLOAD as u64 + 8))
            .ok_or_else(|| invalid("weight storage size overflow"))?;
        let mut loaded = crate::parameter_file::read(path, maximum)?;
        let mut head = None;
        if let Some(index) = loaded.iter().position(|(name, _)| name == "lm_head.weight") {
            if config.tie_word_embeddings {
                return Err(invalid(
                    "an explicit Torch head requires an untied output declaration",
                ));
            }
            let (_, value) = loaded.remove(index);
            if value.size() != [config.vocab_size, config.hidden_size] {
                return Err(invalid("invalid explicit Torch output head shape"));
            }
            finite(&value, "source output head")?;
            let value = value.f_to_device(device)?.f_to_kind(kind)?;
            finite(&value, "cast output head")?;
            head = Some(value);
        }
        let tensors = owned_tensors(loaded, expected, config.layout(), device, kind)?;
        Ok(Self {
            config: config.clone(),
            tensors,
            head,
            device,
            kind,
        })
    }

    pub(crate) fn to_cpu_float32(&self) -> Result<Self, CoreError> {
        let mut tensors = BTreeMap::new();
        for (name, value) in &self.tensors {
            let converted = value.f_to_device(Device::Cpu)?.f_to_kind(Kind::Float)?;
            finite(&converted, name)?;
            tensors.insert(name.clone(), converted);
        }
        Ok(Self {
            config: self.config.clone(),
            tensors,
            head: self
                .head
                .as_ref()
                .map(|head| head.f_to_device(Device::Cpu)?.f_to_kind(Kind::Float))
                .transpose()?,
            device: Device::Cpu,
            kind: Kind::Float,
        })
    }

    pub(crate) fn output_head(&self) -> Result<&Tensor, CoreError> {
        if let Some(head) = &self.head {
            Ok(head)
        } else if self.config.tie_word_embeddings {
            self.get("embed_tokens.weight")
        } else {
            Err(invalid(
                "untied output projection requires an explicit registered head",
            ))
        }
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

#[cfg(test)]
mod recast_tests {
    use super::*;
    #[test]
    fn cpu_float32_conversion_preserves_rounding_of_already_loaded_weights() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/qwen");
        let config = CoreConfig::from_json(
            &std::fs::read_to_string(root.join("config.json")).unwrap(),
            TransformerWeightLayout::Unprefixed,
        )
        .unwrap();
        let source = tempfile::tempdir().unwrap();
        let path = source.path().join("model.safetensors");
        std::fs::copy(root.join("model.safetensors"), &path).unwrap();
        let mut bytes = std::fs::read(&path).unwrap();
        let header = u64::from_le_bytes(bytes[..8].try_into().unwrap()) as usize;
        let metadata: serde_json::Value = serde_json::from_slice(&bytes[8..8 + header]).unwrap();
        let offset = 8
            + header
            + metadata["embed_tokens.weight"]["data_offsets"][0]
                .as_u64()
                .unwrap() as usize;
        bytes[offset..offset + 4].copy_from_slice(&1.0004_f32.to_le_bytes());
        std::fs::write(&path, bytes).unwrap();

        let full = TorchWeights::load(
            &config,
            &path,
            TransformerDevice::Cpu,
            TransformerDtype::Float32,
        )
        .unwrap();
        let half = TorchWeights::load(
            &config,
            &path,
            TransformerDevice::Cpu,
            TransformerDtype::Float16,
        )
        .unwrap();
        let original: Vec<f32> = Vec::try_from(
            &full
                .get("embed_tokens.weight")
                .unwrap()
                .f_reshape([-1])
                .unwrap(),
        )
        .unwrap();
        let rounded: Vec<f32> = Vec::try_from(
            &half
                .get("embed_tokens.weight")
                .unwrap()
                .f_to_kind(Kind::Float)
                .unwrap()
                .f_reshape([-1])
                .unwrap(),
        )
        .unwrap();
        assert!(original.iter().zip(&rounded).any(|(a, b)| a != b));
        std::fs::remove_file(path).unwrap();
        let converted = half.to_cpu_float32().unwrap();
        let actual: Vec<f32> = Vec::try_from(
            &converted
                .get("embed_tokens.weight")
                .unwrap()
                .f_reshape([-1])
                .unwrap(),
        )
        .unwrap();
        assert_eq!(actual, rounded);
        assert_eq!(converted.device, Device::Cpu);
        assert_eq!(converted.kind, Kind::Float);
    }
    #[test]
    fn explicit_untied_head_uses_its_own_rows_after_requested_dtype_cast() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/qwen");
        let mut declaration: serde_json::Value =
            serde_json::from_slice(&std::fs::read(root.join("config.json")).unwrap()).unwrap();
        declaration["tie_word_embeddings"] = serde_json::json!(false);
        let config = CoreConfig::from_json(
            &declaration.to_string(),
            TransformerWeightLayout::Unprefixed,
        )
        .unwrap();
        let source = tempfile::tempdir().unwrap();
        let path = source.path().join("explicit.safetensors");
        let head = Tensor::f_from_slice(
            &(0..32)
                .map(|n| 1.0004_f32 + n as f32 * 0.1234)
                .collect::<Vec<_>>(),
        )
        .unwrap()
        .f_reshape([8, 4])
        .unwrap();
        let wanted = head
            .f_to_kind(Kind::Half)
            .unwrap()
            .f_to_kind(Kind::Float)
            .unwrap();
        let wanted = wanted
            .f_select(0, 1)
            .unwrap()
            .f_sub(&wanted.f_select(0, 6).unwrap())
            .unwrap();
        let mut tensors =
            crate::parameter_file::read(&root.join("model.safetensors"), 1024 * 1024).unwrap();
        tensors.push(("lm_head.weight".into(), head));
        Tensor::write_safetensors(&tensors, &path).unwrap();
        let weights = TorchWeights::load(
            &config,
            &path,
            TransformerDevice::Cpu,
            TransformerDtype::Float16,
        )
        .unwrap();
        let model = crate::qwen3::Qwen3::load(config, weights).unwrap();
        let actual = model.projection_difference(1, 6).unwrap();
        assert_eq!(
            Vec::<f32>::try_from(&actual).unwrap(),
            Vec::<f32>::try_from(&wanted).unwrap()
        );
        let converted = model.to_cpu_float32().unwrap();
        assert_eq!(
            Vec::<f32>::try_from(&converted.projection_difference(1, 6).unwrap()).unwrap(),
            Vec::<f32>::try_from(&wanted).unwrap()
        );
    }
    #[test]
    fn absent_untied_or_malformed_explicit_head_is_rejected_before_judge_use() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/qwen");
        let mut declaration: serde_json::Value =
            serde_json::from_slice(&std::fs::read(root.join("config.json")).unwrap()).unwrap();
        declaration["tie_word_embeddings"] = serde_json::json!(false);
        let config = CoreConfig::from_json(
            &declaration.to_string(),
            TransformerWeightLayout::Unprefixed,
        )
        .unwrap();
        let weights = TorchWeights::load(
            &config,
            &root.join("model.safetensors"),
            TransformerDevice::Cpu,
            TransformerDtype::Float32,
        )
        .unwrap();
        assert!(weights.output_head().is_err());
        let temp = tempfile::tempdir().unwrap();
        for (shape, value) in [([7, 4], 1.0_f32), ([8, 4], f32::NAN), ([8, 4], f32::MAX)] {
            let mut tensors =
                crate::parameter_file::read(&root.join("model.safetensors"), 1024 * 1024).unwrap();
            let head = Tensor::f_from_slice(&vec![value; (shape[0] * shape[1]) as usize])
                .unwrap()
                .f_reshape(shape)
                .unwrap();
            tensors.push(("lm_head.weight".into(), head));
            let path = temp.path().join("bad.safetensors");
            Tensor::write_safetensors(&tensors, &path).unwrap();
            assert!(
                TorchWeights::load(
                    &config,
                    &path,
                    TransformerDevice::Cpu,
                    TransformerDtype::Float16
                )
                .is_err()
            );
        }
    }
}
