//! Typed native inference with independent model files and actual preparation identity.
use crate::{
    ModelError, NativeTransformerRuntime, TransformerModel, TransformerRole,
    TransformerRuntimeIdentity, VerifiedModelFiles, transformer_client::NativeHandle,
};
use ken_native_model_api::{
    TransformerBatch, TransformerDevice, TransformerDeviceRequest, TransformerDtype,
    TransformerOpenRequest, TransformerOutput, TransformerPrepared, TransformerRunRequest,
    TransformerRunResult,
};
use serde::Serialize;
use std::sync::Arc;

fn invalid(message: impl std::fmt::Display) -> ModelError {
    ModelError::Inference(message.to_string())
}

#[derive(Clone, Debug, Serialize)]
pub struct TransformerTrace {
    pub runtime: TransformerRuntimeIdentity,
    pub core_version: String,
    pub device: TransformerDevice,
    pub dtype: TransformerDtype,
    pub model_fingerprint: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct TransformerBatchResult {
    pub rows: usize,
    pub columns: usize,
    pub values: Vec<f32>,
    pub trace: TransformerTrace,
}

pub struct TransformerSession {
    // Model Drop calls close before the independently verified files disappear.
    model: NativeHandle,
    _files: Arc<VerifiedModelFiles>,
    trace: TransformerTrace,
    dimension: usize,
    vocabulary: u64,
    sequence_limit: usize,
    role: TransformerRole,
}

impl TransformerSession {
    pub fn prepare(
        model: &TransformerModel,
        files: Arc<VerifiedModelFiles>,
        runtime: NativeTransformerRuntime,
        device: TransformerDevice,
        dtype: TransformerDtype,
    ) -> Result<Self, ModelError> {
        if files.fingerprint() != model.assets().fingerprint() {
            return Err(invalid("model files belong to a different registration"));
        }
        model.validate_files(&files)?;
        let sequence_limit = model
            .configuration("config.json")
            .and_then(|v| v["max_position_embeddings"].as_u64())
            .and_then(|v| usize::try_from(v).ok())
            .filter(|&v| v > 0)
            .ok_or_else(|| invalid("invalid native sequence bound"))?;
        let request = TransformerOpenRequest {
            schema: 1,
            snapshot: files
                .root()
                .to_str()
                .ok_or_else(|| invalid("model snapshot path must be UTF-8"))?
                .into(),
            architecture: model.architecture(),
            weight_files: model.weight_files().to_vec(),
            weight_layout: model.weight_layout(),
            dtype,
            device: match device {
                TransformerDevice::Cpu => TransformerDeviceRequest::Cpu,
                TransformerDevice::Mps => TransformerDeviceRequest::Mps,
                TransformerDevice::Cuda(i) => TransformerDeviceRequest::Cuda(i),
            },
            pooling: model.pooling(),
            normalize_modules: model.normalize_modules(),
        };
        request.validate_schema().map_err(invalid)?;
        let owner = runtime.owner()?;
        let identity = owner.identity.clone();
        let (native, prepared): (NativeHandle, TransformerPrepared) =
            NativeHandle::open(owner, &request)?;
        if prepared.core_version != identity.declared_core_version
            || prepared.device != device
            || prepared.dtype != dtype
            || prepared.dimension != model.dimension()
        {
            return Err(invalid(
                "native preparation differs from registered core/device/dtype/dimension",
            ));
        }
        Ok(Self {
            model: native,
            trace: TransformerTrace {
                runtime: identity,
                core_version: prepared.core_version,
                device: prepared.device,
                dtype: prepared.dtype,
                model_fingerprint: files.fingerprint().into(),
            },
            _files: files,
            dimension: model.dimension(),
            vocabulary: model.vocabulary(),
            sequence_limit,
            role: model.role(),
        })
    }

    pub fn trace(&self) -> &TransformerTrace {
        &self.trace
    }

    pub fn run(
        &mut self,
        batch: &TransformerBatch,
        output: &TransformerOutput,
    ) -> Result<TransformerBatchResult, ModelError> {
        let columns = match (self.role, output) {
            (TransformerRole::Judge, TransformerOutput::YesMinusNo { .. }) => 1,
            (
                TransformerRole::Encoder,
                TransformerOutput::Sentence | TransformerOutput::MLXLast,
            ) => self.dimension,
            _ => {
                return Err(invalid(
                    "requested output is incompatible with registered model role",
                ));
            }
        };
        batch
            .validate(self.vocabulary, self.sequence_limit, usize::MAX)
            .map_err(invalid)?;
        output.validate(self.vocabulary).map_err(invalid)?;
        let result: TransformerRunResult = self.model.run(&TransformerRunRequest {
            schema: 1,
            batch: batch.clone(),
            output: output.clone(),
        })?;
        result
            .validate(batch.input_ids.len(), columns)
            .map_err(invalid)?;
        Ok(TransformerBatchResult {
            rows: result.rows,
            columns: result.columns,
            values: result.values,
            trace: self.trace.clone(),
        })
    }
}
