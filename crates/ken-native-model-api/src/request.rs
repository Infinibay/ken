//! Tensor-independent input/output policy shared by hosts and native modules.
use crate::ApiError;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum TransformerDtype {
    Float32,
    Float16,
    BFloat16,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(
    tag = "kind",
    content = "index",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum TransformerDevice {
    Cpu,
    Mps,
    Cuda(usize),
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(
    tag = "kind",
    content = "index",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum TransformerDeviceRequest {
    Auto,
    Cpu,
    Gpu,
    Mps,
    Cuda(usize),
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TransformerArchitecture {
    Qwen3,
    #[serde(alias = "xlm-roberta")]
    XlmRoberta,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TransformerWeightLayout {
    Unprefixed,
    #[serde(alias = "model-prefix")]
    ModelPrefix,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TransformerPooling {
    Cls,
    Mean,
    Last,
}

/// The host supplies only paths already owned/verified by ModelAssets and its
/// private-file owner. No expected result or executing identity is an input.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TransformerOpenRequest {
    pub schema: u32,
    pub snapshot: String,
    pub architecture: TransformerArchitecture,
    pub weight_files: Vec<String>,
    pub weight_layout: TransformerWeightLayout,
    pub dtype: TransformerDtype,
    pub device: TransformerDeviceRequest,
    pub pooling: TransformerPooling,
    pub normalize_modules: usize,
}

impl TransformerOpenRequest {
    pub fn validate_schema(&self) -> Result<(), ApiError> {
        let mut names = std::collections::BTreeSet::new();
        if self.schema != 1
            || !std::path::Path::new(&self.snapshot).is_absolute()
            || self.weight_files.is_empty()
            || self.weight_files.iter().any(|name| {
                !names.insert(name)
                    || name
                        .split('/')
                        .any(|part| part.is_empty() || part == "." || part == "..")
                    || !name
                        .bytes()
                        .all(|byte| byte.is_ascii_alphanumeric() || b"_./-".contains(&byte))
            })
        {
            return Err(ApiError::Invalid(
                "invalid versioned native model request".into(),
            ));
        }
        Ok(())
    }
}

/// Reported by the native model after actual preparation, then checked by the
/// host against its declaration. Requests cannot prepopulate this identity.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TransformerPrepared {
    pub core_version: String,
    pub device: TransformerDevice,
    pub dtype: TransformerDtype,
    pub dimension: usize,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TransformerRunRequest {
    pub schema: u32,
    pub batch: TransformerBatch,
    pub output: TransformerOutput,
}

impl TransformerRunRequest {
    pub fn validate(
        &self,
        vocabulary: u64,
        sequence_limit: usize,
        batch_limit: usize,
    ) -> Result<(), ApiError> {
        if self.schema != 1 {
            return Err(ApiError::Invalid("unknown native run schema".into()));
        }
        self.batch
            .validate(vocabulary, sequence_limit, batch_limit)?;
        self.output.validate(vocabulary)
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TransformerRunResult {
    pub rows: usize,
    pub columns: usize,
    pub values: Vec<f32>,
}

impl TransformerRunResult {
    pub fn validate(&self, rows: usize, columns: usize) -> Result<(), ApiError> {
        if rows == 0
            || columns == 0
            || self.rows != rows
            || self.columns != columns
            || rows.checked_mul(columns) != Some(self.values.len())
            || self.values.iter().any(|value| !value.is_finite())
        {
            return Err(ApiError::Invalid(
                "invalid native output shape or nonfinite values".into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct TransformerBatch {
    pub input_ids: Vec<Vec<i64>>,
    pub attention_mask: Vec<Vec<i64>>,
}

impl TransformerBatch {
    /// Require the original adapters' rectangular, nonempty right-padded batch.
    /// A literal pad-token ID may still have mask1; real lengths come from the
    /// tokenizer's attention mask, never from guessing which IDs are padding.
    pub fn validate(
        &self,
        vocabulary: u64,
        sequence_limit: usize,
        batch_limit: usize,
    ) -> Result<(), ApiError> {
        let rows = self.input_ids.len();
        let columns = self.input_ids.first().map_or(0, Vec::len);
        if vocabulary == 0
            || rows == 0
            || columns == 0
            || rows > batch_limit
            || columns > sequence_limit
            || rows.checked_mul(columns).is_none()
            || self.attention_mask.len() != rows
        {
            return Err(ApiError::Invalid(
                "empty or oversized transformer batch".into(),
            ));
        }
        for (ids, mask) in self.input_ids.iter().zip(&self.attention_mask) {
            if ids.len() != columns || mask.len() != columns {
                return Err(ApiError::Invalid("nonrectangular transformer batch".into()));
            }
            if ids.iter().any(|&id| id < 0 || id as u64 >= vocabulary) {
                return Err(ApiError::Invalid(
                    "token outside registered vocabulary".into(),
                ));
            }
            let mut padding = false;
            let mut real = 0;
            for &value in mask {
                match value {
                    0 => padding = true,
                    1 if !padding => real += 1,
                    _ => {
                        return Err(ApiError::Invalid(
                            "attention mask is not binary right padding".into(),
                        ));
                    }
                }
            }
            if real == 0 {
                return Err(ApiError::Invalid("attention row has no real tokens".into()));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum TransformerOutput {
    Sentence,
    /// ST-normalized values before application F32 canonicalization/guards.
    SentenceEncoded,
    #[serde(rename = "mlx_last")]
    MLXLast,
    YesMinusNo {
        true_id: u32,
        false_id: u32,
    },
}

impl TransformerOutput {
    pub fn validate(&self, vocabulary: u64) -> Result<(), ApiError> {
        if vocabulary == 0 {
            return Err(ApiError::Invalid("empty registered vocabulary".into()));
        }
        if let Self::YesMinusNo { true_id, false_id } = self
            && (true_id == false_id
                || u64::from(*true_id) >= vocabulary
                || u64::from(*false_id) >= vocabulary)
        {
            return Err(ApiError::Invalid("invalid yes/no projection IDs".into()));
        }
        Ok(())
    }
}
