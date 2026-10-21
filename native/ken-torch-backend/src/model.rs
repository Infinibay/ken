//! Prepare a complete network, then dispatch its declared native output policy.
use crate::{CoreConfig, CoreError, device, invalid, output, qwen3::Qwen3, weights::TorchWeights};
use ken_native_model_api::{
    TransformerArchitecture, TransformerDevice, TransformerDeviceRequest, TransformerDtype,
    TransformerOpenRequest, TransformerOutput, TransformerPooling, TransformerPrepared,
    TransformerRunRequest, TransformerRunResult,
};
use std::path::Path;
use tch::{Device, Kind};

pub(crate) struct Model {
    core: Network,
    vocab_size: u64,
    max_position_embeddings: usize,
    pooling: TransformerPooling,
    normalize_modules: usize,
    device: TransformerDevice,
}

impl Model {
    pub(crate) fn prepare(
        request: TransformerOpenRequest,
    ) -> Result<(Self, TransformerPrepared), CoreError> {
        request
            .validate_schema()
            .map_err(|e| invalid(e.to_string()))?;
        if request.weight_files.len() != 1 {
            return Err(invalid(
                "this native profile requires one registered parameter file",
            ));
        }
        let version = device::core_version()?;
        if version != "2.9.0" {
            return Err(invalid(format!(
                "executing native core version mismatch: {version}"
            )));
        }
        let requested = select_device(request.device)?;
        if requested == TransformerDevice::Mps {
            device::prepare_mps()?;
        }
        tch::set_num_threads(2);
        let source = Path::new(&request.snapshot);
        let json = std::fs::read_to_string(source.join("config.json"))?;
        let path = source.join(&request.weight_files[0]);
        let (core, vocab_size, max_position_embeddings) = match request.architecture {
            TransformerArchitecture::Qwen3 => {
                let config = CoreConfig::from_json(&json, request.weight_layout)?;
                let limits = (config.vocab_size as u64, config.max_position_embeddings);
                let weights = TorchWeights::load(&config, &path, requested, request.dtype)?;
                (
                    Network::Qwen3(Qwen3::load(config, weights)?),
                    limits.0,
                    limits.1,
                )
            }
            TransformerArchitecture::XlmRoberta => {
                let config =
                    crate::xlm_roberta::XlmRobertaConfig::from_json(&json, request.weight_layout)?;
                let limits = (config.vocab_size as u64, config.max_position_embeddings);
                let weights = crate::xlm_roberta_weights::XlmRobertaWeights::load(
                    &config,
                    &path,
                    requested,
                    request.dtype,
                )?;
                (
                    Network::XlmRoberta(crate::xlm_roberta::XlmRoberta::load(config, weights)?),
                    limits.0,
                    limits.1,
                )
            }
        };
        let (actual_device, actual_kind, dimension) = core.observed_identity()?;
        let actual_device = match actual_device {
            Device::Cpu => TransformerDevice::Cpu,
            Device::Mps => TransformerDevice::Mps,
            Device::Cuda(index) => TransformerDevice::Cuda(index),
            _ => return Err(invalid("unsupported actual tensor device")),
        };
        let actual_dtype = match actual_kind {
            Kind::Float => TransformerDtype::Float32,
            Kind::Half => TransformerDtype::Float16,
            Kind::BFloat16 => TransformerDtype::BFloat16,
            _ => return Err(invalid("unsupported actual tensor precision")),
        };
        let prepared = TransformerPrepared {
            core_version: version,
            device: actual_device,
            dtype: actual_dtype,
            dimension,
        };
        Ok((
            Self {
                core,
                vocab_size,
                max_position_embeddings,
                pooling: request.pooling,
                normalize_modules: request.normalize_modules,
                device: actual_device,
            },
            prepared,
        ))
    }

    pub(crate) fn control(
        &mut self,
        request: ken_native_model_api::TransformerControlRequest,
    ) -> Result<TransformerPrepared, CoreError> {
        request.validate()?;
        if matches!(
            request.operation,
            ken_native_model_api::TransformerControl::ValidateCausalHead
        ) {
            match &self.core {
                Network::Qwen3(core) => core.validate_output_head()?,
                Network::XlmRoberta(_) => return Err(invalid("XLM-R has no causal output head")),
            };
            let (_, kind, dimension) = self.core.observed_identity()?;
            let dtype = match kind {
                Kind::Float => TransformerDtype::Float32,
                Kind::Half => TransformerDtype::Float16,
                Kind::BFloat16 => TransformerDtype::BFloat16,
                _ => return Err(invalid("unsupported current Torch precision")),
            };
            return Ok(TransformerPrepared {
                core_version: device::core_version()?,
                device: self.device,
                dtype,
                dimension,
            });
        }

        let replacement = match &self.core {
            Network::Qwen3(core) => Network::Qwen3(core.to_cpu_float32()?),
            Network::XlmRoberta(_) => {
                return Err(invalid(
                    "CPU conversion control is restricted to the Qwen judge",
                ));
            }
        };
        let (device, kind, dimension) = replacement.observed_identity()?;
        if device != Device::Cpu || kind != Kind::Float {
            return Err(invalid(
                "native conversion did not produce CPU Float32 weights",
            ));
        }
        let prepared = TransformerPrepared {
            core_version: device::core_version()?,
            device: TransformerDevice::Cpu,
            dtype: TransformerDtype::Float32,
            dimension,
        };
        self.core = replacement;
        self.device = TransformerDevice::Cpu;
        Ok(prepared)
    }

    pub(crate) fn run(
        &self,
        request: TransformerRunRequest,
    ) -> Result<TransformerRunResult, CoreError> {
        request
            .validate(self.vocab_size, self.max_position_embeddings, usize::MAX)
            .map_err(|e| invalid(e.to_string()))?;
        let result = (|| {
            let hidden = self.core.forward(&request.batch)?;
            match request.output {
                TransformerOutput::YesMinusNo { true_id, false_id } => output::yes_minus_no(
                    &hidden,
                    &request.batch,
                    &self.core.projection_difference(true_id, false_id)?,
                ),
                TransformerOutput::SentenceEncoded => output::sentence_encoded(
                    &hidden,
                    &request.batch,
                    self.pooling,
                    self.normalize_modules,
                ),
                TransformerOutput::Sentence => output::sentence(
                    &hidden,
                    &request.batch,
                    self.pooling,
                    self.normalize_modules,
                ),
                _ => Err(invalid(
                    "requested output mode is unavailable in this native profile",
                )),
            }
        })();
        if self.device == TransformerDevice::Mps {
            device::empty_mps_cache()?;
        }
        result
    }
}

fn select_device(request: TransformerDeviceRequest) -> Result<TransformerDevice, CoreError> {
    let gpu = || {
        if tch::Cuda::is_available() {
            Some(TransformerDevice::Cuda(0))
        } else if tch::utils::has_mps() {
            Some(TransformerDevice::Mps)
        } else {
            None
        }
    };
    match request {
        TransformerDeviceRequest::Cpu => Ok(TransformerDevice::Cpu),
        TransformerDeviceRequest::Mps if tch::utils::has_mps() => Ok(TransformerDevice::Mps),
        TransformerDeviceRequest::Cuda(index)
            if tch::Cuda::is_available() && (index as u128) < tch::Cuda::device_count() as u128 =>
        {
            Ok(TransformerDevice::Cuda(index))
        }
        TransformerDeviceRequest::Auto => Ok(gpu().unwrap_or(TransformerDevice::Cpu)),
        TransformerDeviceRequest::Gpu => gpu().ok_or_else(|| invalid("no native GPU available")),
        _ => Err(invalid("requested native device unavailable")),
    }
}

enum Network {
    Qwen3(Qwen3),
    XlmRoberta(crate::xlm_roberta::XlmRoberta),
}
impl Network {
    fn observed_identity(&self) -> Result<(Device, Kind, usize), CoreError> {
        match self {
            Self::Qwen3(core) => core.observed_identity(),
            Self::XlmRoberta(core) => core.observed_identity(),
        }
    }
    fn forward(
        &self,
        batch: &ken_native_model_api::TransformerBatch,
    ) -> Result<tch::Tensor, CoreError> {
        match self {
            Self::Qwen3(core) => core.forward(batch),
            Self::XlmRoberta(core) => core.forward(batch),
        }
    }
    fn projection_difference(&self, true_id: u32, false_id: u32) -> Result<tch::Tensor, CoreError> {
        match self {
            Self::Qwen3(core) => core.projection_difference(true_id, false_id),
            Self::XlmRoberta(_) => Err(invalid("XLM-R encoder has no declared yes/no head")),
        }
    }
}
