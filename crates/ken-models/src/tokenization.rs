use crate::ModelError;
use tokenizers::Tokenizer;

/// Model2Vec's token policy, including the character prefix before tokenization.
#[derive(Debug)]
pub struct ModelTokenizer {
    tokenizer: Tokenizer,
    median_length: usize,
    unknown_id: Option<u32>,
}

impl ModelTokenizer {
    pub fn load(bytes: &[u8]) -> Result<Self, ModelError> {
        let mut tokenizer =
            Tokenizer::from_bytes(bytes).map_err(|e| ModelError::Tokenizer(e.to_string()))?;
        tokenizer.with_padding(None);
        tokenizer
            .with_truncation(None)
            .map_err(|e| ModelError::Tokenizer(e.to_string()))?;
        let vocabulary = tokenizer.get_vocab(true);
        if vocabulary.is_empty()
            || vocabulary
                .values()
                .collect::<std::collections::HashSet<_>>()
                .len()
                != vocabulary.len()
            || vocabulary
                .values()
                .any(|id| *id as usize >= vocabulary.len())
        {
            return Err(ModelError::Tokenizer(
                "dense nonempty vocabulary required".into(),
            ));
        }
        let serialized: serde_json::Value = serde_json::from_slice(bytes)?;
        let unknown_id = serialized["model"]["unk_token"]
            .as_str()
            .and_then(|s| vocabulary.get(s))
            .copied();
        let mut lengths: Vec<_> = vocabulary.keys().map(|s| s.chars().count()).collect();
        lengths.sort_unstable();
        let middle = lengths.len() / 2;
        let median_length = if lengths.len().is_multiple_of(2) {
            lengths[middle - 1] + (lengths[middle] - lengths[middle - 1]) / 2
        } else {
            lengths[middle]
        };
        Ok(Self {
            tokenizer,
            median_length,
            unknown_id,
        })
    }

    pub fn token_ids(&self, text: &str, max_length: Option<usize>) -> Result<Vec<u32>, ModelError> {
        let end = max_length
            .and_then(|limit| {
                text.char_indices()
                    .nth(limit.saturating_mul(self.median_length))
                    .map(|(index, _)| index)
            })
            .unwrap_or(text.len());
        let encoded = self
            .tokenizer
            .encode_fast(&text[..end], false)
            .map_err(|e| ModelError::Tokenizer(e.to_string()))?;
        Ok(encoded
            .get_ids()
            .iter()
            .copied()
            .filter(|id| Some(*id) != self.unknown_id)
            .take(max_length.unwrap_or(usize::MAX))
            .collect())
    }

    pub fn token_count(&self, text: &str) -> Result<usize, ModelError> {
        self.token_ids(text, None).map(|ids| ids.len())
    }

    pub(crate) fn vocabulary_len(&self) -> usize {
        self.tokenizer.get_vocab_size(true)
    }
}
