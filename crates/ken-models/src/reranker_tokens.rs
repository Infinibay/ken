//! Published paired-text policy, independent of inference and cache publication.
use crate::{ModelError, PreparedReranker};
use serde::Serialize;
use serde_json::Value;
use tokenizers::{
    Encoding, PaddingParams, PostProcessor, Tokenizer, TruncationParams, TruncationStrategy,
};

#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct PairTokens {
    pub ids: Vec<i64>,
    pub attention_mask: Vec<i64>,
    pub overflowing: bool,
}

pub(crate) struct PairedTokenizer {
    paired: Tokenizer,
    query: Tokenizer,
    max_tokens: usize,
    special: usize,
    pub(crate) pad_id: u32,
}

fn invalid(error: impl std::fmt::Display) -> ModelError {
    ModelError::Tokenizer(error.to_string())
}

impl PairedTokenizer {
    pub(crate) fn new(prepared: &PreparedReranker, max_tokens: usize) -> Result<Self, ModelError> {
        let snapshot = &prepared.snapshot;
        let config: Value = serde_json::from_slice(snapshot.artifact("config.json")?)?;
        let token_config: Value =
            serde_json::from_slice(snapshot.artifact("tokenizer_config.json")?)?;
        for limit in [
            &config["max_position_embeddings"],
            &token_config["model_max_length"],
        ] {
            if !limit.is_null()
                && !limit
                    .as_u64()
                    .is_some_and(|n| n > 0 && (max_tokens as u128) <= u128::from(n))
            {
                return Err(invalid(
                    "token budget exceeds or conflicts with declared model limit",
                ));
            }
        }
        let mut paired =
            Tokenizer::from_bytes(snapshot.artifact("tokenizer.json")?).map_err(invalid)?;
        let single_special = paired
            .get_post_processor()
            .map_or(0, |processor| processor.added_tokens(false));
        paired
            .with_truncation(Some(TruncationParams {
                // tokenizers validates via an unchecked single-sequence
                // subtraction even though this owner only encodes pairs.
                max_length: max_tokens.max(single_special),
                strategy: TruncationStrategy::OnlySecond,
                ..Default::default()
            }))
            .map_err(invalid)?;
        paired
            .get_truncation_mut()
            .ok_or_else(|| invalid("paired truncation missing"))?
            .max_length = max_tokens;
        let token = token_config["pad_token"]
            .as_str()
            .or_else(|| token_config["pad_token"]["content"].as_str())
            .ok_or_else(|| invalid("inconsistent published padding configuration"))?;
        let pad_id = config["pad_token_id"]
            .as_u64()
            .and_then(|n| u32::try_from(n).ok())
            .filter(|id| paired.token_to_id(token) == Some(*id))
            .ok_or_else(|| invalid("inconsistent published padding configuration"))?;
        if token_config
            .get("padding_side")
            .is_some_and(|side| side.as_str() != Some("right"))
        {
            return Err(invalid("inconsistent published padding configuration"));
        }
        paired.with_padding(Some(PaddingParams {
            pad_id,
            pad_token: token.to_owned(),
            ..Default::default()
        }));
        let special = paired
            .get_post_processor()
            .map_or(0, |processor| processor.added_tokens(true));
        let mut query =
            Tokenizer::from_bytes(snapshot.artifact("tokenizer.json")?).map_err(invalid)?;
        query.with_padding(None);
        query.with_truncation(None).map_err(invalid)?;
        Ok(Self {
            paired,
            query,
            max_tokens,
            special,
            pad_id,
        })
    }

    pub(crate) fn check_query(&self, query: &str) -> Result<(), ModelError> {
        // Python len(str) counts Unicode scalars; using UTF-8 bytes would reject
        // valid multilingual questions at a different boundary.
        let capacity = self
            .max_tokens
            .checked_sub(self.special)
            .and_then(|n| n.checked_sub(1));
        if query.chars().count() > 65536 || capacity.is_none() {
            return Err(invalid(
                "query is too long for reranking; shorten the search question",
            ));
        }
        let count = self
            .query
            .encode(query, false)
            .map_err(invalid)?
            .get_ids()
            .len();
        if count > capacity.unwrap_or(0) {
            return Err(invalid(
                "query is too long for reranking; shorten the search question",
            ));
        }
        Ok(())
    }

    pub(crate) fn pair_fits(&self, query: &str, text: &str) -> Result<bool, ModelError> {
        Ok(self
            .query
            .encode((query, text), true)
            .map_err(invalid)?
            .get_ids()
            .len()
            <= self.max_tokens)
    }

    pub(crate) fn encode(
        &self,
        query: &str,
        texts: &[&str],
    ) -> Result<Vec<PairTokens>, ModelError> {
        // The dependency also subtracts paired special tokens unchecked at
        // encoding time. score's query guard rejects these budgets first;
        // the public token inspection path must return an error as well.
        if !texts.is_empty() && self.max_tokens < self.special {
            return Err(invalid(
                "token budget cannot accommodate paired special tokens",
            ));
        }
        let inputs: Vec<_> = texts.iter().map(|text| (query, *text)).collect();
        let encodings = self.paired.encode_batch(inputs, true).map_err(invalid)?;
        Ok(encodings.into_iter().map(Self::tokens).collect())
    }

    fn tokens(encoded: Encoding) -> PairTokens {
        PairTokens {
            ids: encoded.get_ids().iter().map(|n| i64::from(*n)).collect(),
            attention_mask: encoded
                .get_attention_mask()
                .iter()
                .map(|n| i64::from(*n))
                .collect(),
            overflowing: !encoded.get_overflowing().is_empty(),
        }
    }
}
