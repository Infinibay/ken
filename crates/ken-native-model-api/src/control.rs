//! Versioned native state changes are distinct from inference tensor requests.
use crate::{ApiError, TransformerRunRequest};
use serde::{Deserialize, Serialize};
#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TransformerControl {
    CpuFloat32,
    ValidateCausalHead,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TransformerControlRequest {
    pub schema: u32,
    pub operation: TransformerControl,
}
impl TransformerControlRequest {
    pub fn validate(&self) -> Result<(), ApiError> {
        if self.schema != 1 {
            Err(ApiError::Invalid("unknown native control schema".into()))
        } else {
            Ok(())
        }
    }
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(untagged)]
pub enum TransformerCall {
    Inference(TransformerRunRequest),
    Control(TransformerControlRequest),
}
