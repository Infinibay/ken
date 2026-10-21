//! Prepare a complete verified Qwen graph before publishing native model state.
use crate::{CoreError, device, invalid, output, qwen3::Qwen3, weights::MlxWeights};
use ken_native_model_api::{
    Qwen3Config, TransformerArchitecture, TransformerDevice, TransformerDeviceRequest,
    TransformerDtype, TransformerOpenRequest, TransformerOutput, TransformerPrepared,
    TransformerRunRequest, TransformerRunResult,
};
use mlx_rs::{Device, Dtype, with_device};
use std::path::Path;
pub(crate) struct Model {
    core: Qwen3,
    vocabulary: u64,
    sequence_limit: usize,
}
impl Model {
    pub(crate) fn prepare(
        request: TransformerOpenRequest,
    ) -> Result<(Self, TransformerPrepared), CoreError> {
        request.validate_schema()?;
        if request.architecture != TransformerArchitecture::Qwen3
            || request.weight_files.len() != 1
            || !request.weight_files[0].ends_with(".safetensors")
        {
            return Err(invalid(
                "unsupported native MLX architecture/parameters/output policy",
            ));
        }
        if !matches!(
            request.device,
            TransformerDeviceRequest::Auto
                | TransformerDeviceRequest::Gpu
                | TransformerDeviceRequest::Mps
        ) {
            return Err(invalid(
                "MLX requires its actual Apple GPU; CPU/CUDA fallback is unavailable",
            ));
        }
        device::prepare()?;
        let source = Path::new(&request.snapshot);
        let config = Qwen3Config::from_json(
            &std::fs::read_to_string(source.join("config.json"))?,
            request.weight_layout,
        )?;
        let vocabulary = config.vocab_size as u64;
        let sequence_limit = config.max_position_embeddings;
        let weights = MlxWeights::load(
            &config,
            &source.join(&request.weight_files[0]),
            request.dtype,
        )?;
        let core = Qwen3::load(config, weights)?;
        let dtype = match core.dtype()? {
            Dtype::Float32 => TransformerDtype::Float32,
            Dtype::Float16 => TransformerDtype::Float16,
            Dtype::Bfloat16 => TransformerDtype::BFloat16,
            _ => return Err(invalid("unsupported actual MLX precision")),
        };
        let prepared = TransformerPrepared {
            core_version: device::core_version()?,
            device: TransformerDevice::Mps,
            dtype,
            dimension: core.dimension(),
        };
        Ok((
            Self {
                core,
                vocabulary,
                sequence_limit,
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
            self.core.validate_output_head()?;
            let dtype = match self.core.dtype()? {
                Dtype::Float32 => TransformerDtype::Float32,
                Dtype::Float16 => TransformerDtype::Float16,
                Dtype::Bfloat16 => TransformerDtype::BFloat16,
                _ => return Err(invalid("unsupported actual MLX precision")),
            };
            return Ok(TransformerPrepared {
                core_version: device::core_version()?,
                device: TransformerDevice::Mps,
                dtype,
                dimension: self.core.dimension(),
            });
        }

        Err(invalid("MLX cannot perform a CPU model demotion"))
    }

    pub(crate) fn run(
        &self,
        request: TransformerRunRequest,
    ) -> Result<TransformerRunResult, CoreError> {
        request.validate(self.vocabulary, self.sequence_limit, usize::MAX)?;
        with_device(Device::gpu(), || {
            let hidden = self.core.forward(&request.batch)?;
            match request.output {
                TransformerOutput::MLXLast => output::embedding(&hidden, &request.batch),
                TransformerOutput::YesMinusNo { true_id, false_id } => output::yes_minus_no(
                    &hidden,
                    &request.batch,
                    &self.core.projection_difference(true_id, false_id)?,
                ),
                _ => Err(invalid("unsupported native MLX output mode")),
            }
        })
    }
}
