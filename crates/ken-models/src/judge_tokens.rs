//! Exact original joint-model prompt, budget and document order.
use crate::{
    ModelError, ModelFileSource, TransformerModel,
    transformer_tokens::{authenticated_raw, registered_pad},
};
use ken_native_model_api::TransformerBatch;
use serde::Deserialize;
use std::collections::BTreeMap;
use tokenizers::{Tokenizer, TruncationDirection, TruncationParams, TruncationStrategy};
#[derive(Debug, thiserror::Error)]
pub enum JudgeTokenError {
    #[error("joint model sequence budget cannot contain query and source")]
    Budget,
    #[error("list index out of range")]
    EmptyDocuments,
    #[error(transparent)]
    Tokenizer(#[from] ModelError),
}
impl JudgeTokenError {
    pub fn original_kind(&self) -> &'static str {
        if matches!(self, Self::EmptyDocuments) {
            "IndexError"
        } else {
            "ValueError"
        }
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Policy {
    prefix: String,
    suffix: String,
    instructions: BTreeMap<String, String>,
    original_source_sha256: String,
}
pub struct JudgeTokens {
    raw: Tokenizer,
    pad: i64,
    prefix: Vec<i64>,
    suffix: Vec<i64>,
    policy: Policy,
    projection_ids: [u32; 2],
}
pub struct PreparedJudge {
    pub batches: Vec<TransformerBatch>,
    pub remaining: usize,
    pub query_ids: Vec<i64>,
    pub projection_ids: [u32; 2],
}
fn tokenizer_error(e: impl std::fmt::Display) -> ModelError {
    ModelError::Tokenizer(e.to_string())
}
impl JudgeTokens {
    pub fn load(model: &TransformerModel, source: &ModelFileSource) -> Result<Self, ModelError> {
        let policy: Policy = serde_json::from_str(include_str!("../resources/judge-policy.json"))?;
        let catalog: serde_json::Value =
            serde_json::from_str(include_str!("../resources/transformer-catalog.json"))?;
        if policy.original_source_sha256 != catalog["original_sources"]["judge"]["sha256"] {
            return Err(ModelError::Registration(
                "joint model prompt differs from frozen original".into(),
            ));
        }
        let raw = authenticated_raw(model, source, &["config.json", "tokenizer_config.json"])?;
        let pad = i64::from(
            registered_pad(model, &raw)?
                .ok_or_else(|| tokenizer_error("joint model requires a pad token"))?
                .0,
        );
        let encode = |text: &str| -> Result<Vec<i64>, ModelError> {
            Ok(raw
                .encode(text, false)
                .map_err(tokenizer_error)?
                .get_ids()
                .iter()
                .map(|&n| i64::from(n))
                .collect())
        };
        let prefix = encode(&policy.prefix)?;
        let suffix = encode(&policy.suffix)?;
        let yes = raw
            .token_to_id("yes")
            .ok_or_else(|| tokenizer_error("joint model has no yes token"))?;
        let no = raw
            .token_to_id("no")
            .ok_or_else(|| tokenizer_error("joint model has no no token"))?;
        if yes == no {
            return Err(tokenizer_error(
                "joint model yes/no tokens must be distinct",
            ));
        }
        Ok(Self {
            raw,
            pad,
            prefix,
            suffix,
            policy,
            projection_ids: [yes, no],
        })
    }
    pub fn prepare(
        &self,
        query: &str,
        documents: &[&str],
        purpose: &str,
        sequence_length: usize,
        batch_size: usize,
    ) -> Result<PreparedJudge, JudgeTokenError> {
        let mut query_ids = self.encode(query)?;
        query_ids.truncate(128);
        let instruction = self
            .policy
            .instructions
            .get(purpose)
            .or_else(|| self.policy.instructions.get("implementation"))
            .ok_or_else(|| tokenizer_error("missing implementation instruction"))?;
        let mut header = self.encode(&format!("<Instruct>: {instruction}\n<Query>: "))?;
        header.extend(&query_ids);
        header.extend(self.encode("\n<Document>: ")?);
        let remaining = self
            .prefix
            .len()
            .checked_add(header.len())
            .and_then(|n| n.checked_add(self.suffix.len()))
            .and_then(|n| sequence_length.checked_sub(n))
            .filter(|&n| n >= 16)
            .ok_or(JudgeTokenError::Budget)?;
        if documents.is_empty() {
            return Err(JudgeTokenError::EmptyDocuments);
        }
        if batch_size == 0 {
            return Err(tokenizer_error("joint model batch size must be positive").into());
        }
        let mut tokenizer = self.raw.clone();
        tokenizer
            .with_truncation(Some(TruncationParams {
                max_length: remaining,
                direction: TruncationDirection::Right,
                strategy: TruncationStrategy::LongestFirst,
                stride: 0,
            }))
            .map_err(tokenizer_error)?;
        let encoded = tokenizer
            .encode_batch(documents.to_vec(), false)
            .map_err(tokenizer_error)?;
        let mut batches = Vec::new();
        for chunk in encoded.chunks(batch_size) {
            let sequences: Vec<Vec<i64>> = chunk
                .iter()
                .map(|e| {
                    self.prefix
                        .iter()
                        .chain(&header)
                        .copied()
                        .chain(e.get_ids().iter().map(|&n| i64::from(n)))
                        .chain(self.suffix.iter().copied())
                        .collect()
                })
                .collect();
            let length = sequences
                .iter()
                .map(Vec::len)
                .max()
                .ok_or(JudgeTokenError::EmptyDocuments)?;
            let mut ids = Vec::new();
            let mut masks = Vec::new();
            for mut row in sequences {
                let mut mask = vec![1_i64; row.len()];
                mask.resize(length, 0);
                row.resize(length, self.pad);
                ids.push(row);
                masks.push(mask);
            }
            batches.push(TransformerBatch {
                input_ids: ids,
                attention_mask: masks,
            });
        }
        Ok(PreparedJudge {
            batches,
            remaining,
            query_ids,
            projection_ids: self.projection_ids,
        })
    }
    fn encode(&self, text: &str) -> Result<Vec<i64>, ModelError> {
        Ok(self
            .raw
            .encode(text, false)
            .map_err(tokenizer_error)?
            .get_ids()
            .iter()
            .map(|&n| i64::from(n))
            .collect())
    }
}
impl From<JudgeTokenError> for ModelError {
    fn from(error: JudgeTokenError) -> Self {
        match error {
            JudgeTokenError::Budget => Self::RelevanceBudget,
            JudgeTokenError::EmptyDocuments => Self::RelevanceEmptyDocuments,
            JudgeTokenError::Tokenizer(error) => error,
        }
    }
}
