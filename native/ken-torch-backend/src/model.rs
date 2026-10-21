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
    core: Qwen3,
    config: CoreConfig,
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
        if request.architecture != TransformerArchitecture::Qwen3 || request.weight_files.len() != 1
        {
            return Err(invalid(
                "this native profile requires one registered Qwen3 parameter file",
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
        let config = CoreConfig::from_json(
            &std::fs::read_to_string(source.join("config.json"))?,
            request.weight_layout,
        )?;
        let weights = TorchWeights::load(
            &config,
            &source.join(&request.weight_files[0]),
            requested,
            request.dtype,
        )?;
        let core = Qwen3::load(config.clone(), weights)?;
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
                config,
                pooling: request.pooling,
                normalize_modules: request.normalize_modules,
                device: actual_device,
            },
            prepared,
        ))
    }

    pub(crate) fn run(
        &self,
        request: TransformerRunRequest,
    ) -> Result<TransformerRunResult, CoreError> {
        request
            .validate(
                self.config.vocab_size as u64,
                self.config.max_position_embeddings,
                usize::MAX,
            )
            .map_err(|e| invalid(e.to_string()))?;
        let result = (|| {
            let hidden = self.core.forward(&request.batch)?;
            match request.output {
                TransformerOutput::YesMinusNo { true_id, false_id } => output::yes_minus_no(
                    &hidden,
                    &request.batch,
                    &self.core.projection_difference(true_id, false_id)?,
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
