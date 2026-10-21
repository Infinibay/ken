//! Authenticate tokenizer data without loading weights; preserve original text/feed ordering.
use crate::{ModelError, ModelFileSource, TransformerModel, TransformerSettings, model_policy};
use ken_native_model_api::TransformerBatch;
use tokenizers::{
    PaddingDirection, PaddingParams, PaddingStrategy, Tokenizer, TruncationDirection,
    TruncationParams, TruncationStrategy,
};

fn invalid(message: impl std::fmt::Display) -> ModelError {
    ModelError::Tokenizer(message.to_string())
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum TextPolicy {
    Sentence,
    Mlx,
}

pub struct TransformerTokens {
    policy: TextPolicy,
    raw: Tokenizer,
    prepared: Tokenizer,
    sequence_limit: usize,
    batch_size: usize,
    pad: Option<(u32, String)>,
    prompts: model_policy::ModelPrompts,
    default_prompt: String,
}

pub struct PreparedTransformerText {
    batches: Vec<TransformerBatch>,
    order: Vec<usize>,
}
impl PreparedTransformerText {
    pub fn batches(&self) -> &[TransformerBatch] {
        &self.batches
    }
    pub fn original_indices(&self) -> &[usize] {
        &self.order
    }
    pub fn restore<T>(&self, values: Vec<T>) -> Result<Vec<T>, ModelError> {
        if values.len() != self.order.len() {
            return Err(invalid(
                "encoded row count differs from original text count",
            ));
        }
        let mut restored: Vec<Option<T>> =
            std::iter::repeat_with(|| None).take(values.len()).collect();
        for (value, &index) in values.into_iter().zip(&self.order) {
            restored[index] = Some(value);
        }
        restored
            .into_iter()
            .collect::<Option<Vec<_>>>()
            .ok_or_else(|| invalid("incomplete restored text batch"))
    }
}
impl TransformerTokens {
    pub fn load(
        model: &TransformerModel,
        source: &ModelFileSource,
        settings: &TransformerSettings,
    ) -> Result<Self, ModelError> {
        Self::load_policy(model, source, settings, TextPolicy::Sentence)
    }
    pub fn for_mlx(
        model: &TransformerModel,
        source: &ModelFileSource,
        settings: &TransformerSettings,
    ) -> Result<Self, ModelError> {
        Self::load_policy(model, source, settings, TextPolicy::Mlx)
    }
    fn load_policy(
        model: &TransformerModel,
        source: &ModelFileSource,
        settings: &TransformerSettings,
        policy: TextPolicy,
    ) -> Result<Self, ModelError> {
        settings.validate()?;
        for name in [
            "config.json",
            "tokenizer_config.json",
            "sentence_bert_config.json",
            "config_sentence_transformers.json",
        ] {
            if policy == TextPolicy::Mlx && !matches!(name, "config.json" | "tokenizer_config.json")
            {
                continue;
            }
            if let Some(expected) = model.configuration(name) {
                let value: serde_json::Value = serde_json::from_slice(
                    &model
                        .assets()
                        .read_source_artifact(source.snapshot(), name)?,
                )?;
                if &value != expected {
                    return Err(invalid(format!(
                        "registered tokenizer metadata differs from {name}"
                    )));
                }
            }
        }
        let raw = model
            .assets()
            .read_source_artifact(source.snapshot(), "tokenizer.json")?;
        let mut tokenizer = Tokenizer::from_bytes(raw).map_err(invalid)?;
        tokenizer.with_padding(None);
        tokenizer.with_truncation(None).map_err(invalid)?;
        let configuration = model
            .configuration("tokenizer_config.json")
            .ok_or_else(|| invalid("missing tokenizer configuration"))?;
        if (policy == TextPolicy::Sentence
            && configuration["padding_side"]
                .as_str()
                .is_some_and(|s| s != "right"))
            || configuration["truncation_side"]
                .as_str()
                .is_some_and(|s| s != "right")
        {
            return Err(invalid(
                "this registered native profile requires right padding and truncation",
            ));
        }
        let mut prepared = tokenizer.clone();
        if policy == TextPolicy::Sentence
            && model
                .configuration("sentence_bert_config.json")
                .is_some_and(|c| c["do_lower_case"] == true)
        {
            use tokenizers::normalizers::{
                NormalizerWrapper,
                utils::{Lowercase, Sequence},
            };
            let existing: Vec<NormalizerWrapper> = match tokenizer.get_normalizer() {
                Some(NormalizerWrapper::Sequence(sequence)) => sequence.as_ref().to_vec(),
                Some(normalizer) => vec![normalizer.clone()],
                None => Vec::new(),
            };
            if !existing
                .iter()
                .any(|n| matches!(n, NormalizerWrapper::Lowercase(_)))
            {
                let mut all = vec![NormalizerWrapper::from(Lowercase)];
                all.extend(existing);
                prepared.with_normalizer(Some(Sequence::new(all)));
            }
        }
        let model_limit = model
            .configuration("config.json")
            .and_then(|v| v["max_position_embeddings"].as_u64())
            .and_then(|n| usize::try_from(n).ok())
            .ok_or_else(|| invalid("missing registered sequence bound"))?;
        let tokenizer_limit = configuration["model_max_length"]
            .as_u64()
            .and_then(|n| usize::try_from(n).ok())
            .unwrap_or(model_limit);
        let original_limit = model
            .configuration("sentence_bert_config.json")
            .and_then(|c| c["max_seq_length"].as_u64())
            .and_then(|n| usize::try_from(n).ok())
            .unwrap_or(model_limit.min(tokenizer_limit));
        let sequence_limit = if policy == TextPolicy::Sentence {
            original_limit.min(settings.sequence_length.unwrap_or(512))
        } else {
            settings.sequence_length.unwrap_or(512)
        };
        if sequence_limit == 0 {
            return Err(invalid("registered sequence bound must be positive"));
        }
        let pad = configuration["pad_token"]
            .as_str()
            .or_else(|| configuration["pad_token"]["content"].as_str())
            .map(|name| {
                tokenizer
                    .token_to_id(name)
                    .map(|id| (id, name.to_owned()))
                    .ok_or_else(|| invalid("pad token is absent from registered tokenizer"))
            })
            .transpose()?;
        let mut default_prompt = String::new();
        if policy == TextPolicy::Sentence
            && let Some(config) = model.configuration("config_sentence_transformers.json")
            && let Some(name) = config["default_prompt_name"].as_str()
        {
            default_prompt = config["prompts"][name]
                .as_str()
                .ok_or_else(|| invalid("missing default Sentence Transformers prompt"))?
                .to_owned();
        }
        Ok(Self {
            policy,
            raw: tokenizer,
            prepared,
            sequence_limit,
            batch_size: settings.batch_size.unwrap_or(16),
            pad,
            prompts: model_policy::prompts_for(model.assets().model_id()),
            default_prompt,
        })
    }
    pub fn sequence_limit(&self) -> usize {
        self.sequence_limit
    }
    pub fn encode_content(&self, text: &str) -> Result<Vec<i64>, ModelError> {
        Ok(self
            .raw
            .encode(text, false)
            .map_err(invalid)?
            .get_ids()
            .iter()
            .map(|&n| i64::from(n))
            .collect())
    }
    pub fn raw_count(&self, text: &str) -> Result<usize, ModelError> {
        Ok(self.raw.encode(text, false).map_err(invalid)?.len())
    }
    pub fn passages(&self, texts: &[&str]) -> Result<PreparedTransformerText, ModelError> {
        self.prepare(texts, self.prompts.passage)
    }
    pub fn queries(&self, texts: &[&str]) -> Result<PreparedTransformerText, ModelError> {
        self.prepare(texts, self.prompts.query)
    }
    fn prepare(&self, texts: &[&str], prompt: &str) -> Result<PreparedTransformerText, ModelError> {
        if texts.is_empty() {
            return Ok(PreparedTransformerText {
                batches: Vec::new(),
                order: Vec::new(),
            });
        }
        let payload: Vec<_> = texts
            .iter()
            .map(|text| format!("{}{prompt}{text}", self.default_prompt))
            .collect();
        if self.policy == TextPolicy::Mlx {
            return self.prepare_mlx(&payload);
        }
        let lengths: Vec<_> = payload.iter().map(|s| s.chars().count()).collect();
        let order = crate::transformer_order::sentence_indices(&lengths);
        let (pad_id, pad_token) = self
            .pad
            .as_ref()
            .ok_or_else(|| invalid("batch padding requires a registered pad token"))?;
        let mut tokenizer = self.prepared.clone();
        tokenizer
            .with_truncation(Some(TruncationParams {
                direction: TruncationDirection::Right,
                max_length: self.sequence_limit,
                strategy: TruncationStrategy::LongestFirst,
                stride: 0,
            }))
            .map_err(invalid)?;
        tokenizer.with_padding(Some(PaddingParams {
            strategy: PaddingStrategy::BatchLongest,
            direction: PaddingDirection::Right,
            pad_to_multiple_of: None,
            pad_id: *pad_id,
            pad_type_id: 0,
            pad_token: pad_token.clone(),
        }));
        let mut batches = Vec::new();
        for indices in order.chunks(self.batch_size) {
            let input: Vec<_> = indices.iter().map(|&i| payload[i].as_str()).collect();
            let encodings = tokenizer.encode_batch(input, true).map_err(invalid)?;
            batches.push(TransformerBatch {
                input_ids: encodings
                    .iter()
                    .map(|e| e.get_ids().iter().map(|&n| i64::from(n)).collect())
                    .collect(),
                attention_mask: encodings
                    .iter()
                    .map(|e| {
                        e.get_attention_mask()
                            .iter()
                            .map(|&n| i64::from(n))
                            .collect()
                    })
                    .collect(),
            });
        }
        Ok(PreparedTransformerText { batches, order })
    }
    fn prepare_mlx(&self, payload: &[String]) -> Result<PreparedTransformerText, ModelError> {
        let (pad_id, _) = self
            .pad
            .as_ref()
            .ok_or_else(|| invalid("MLX right padding requires its registered pad ID"))?;
        let mut tokenizer = self.raw.clone();
        tokenizer
            .with_truncation(Some(TruncationParams {
                direction: TruncationDirection::Right,
                max_length: self.sequence_limit,
                strategy: TruncationStrategy::LongestFirst,
                stride: 0,
            }))
            .map_err(invalid)?;
        let encoded = tokenizer
            .encode_batch(payload.to_vec(), true)
            .map_err(invalid)?;
        let mut order: Vec<_> = (0..encoded.len()).collect();
        order.sort_by_key(|&i| encoded[i].len());
        let mut batches = Vec::new();
        for indices in order.chunks(self.batch_size) {
            let length = indices
                .iter()
                .map(|&i| encoded[i].len())
                .max()
                .ok_or_else(|| invalid("MLX empty batch"))?;
            if length == 0 {
                return Err(invalid("MLX text has no token after postprocessing"));
            }
            let mut ids = Vec::new();
            let mut mask = Vec::new();
            for &i in indices {
                let real = encoded[i].len();
                let mut row: Vec<_> = encoded[i]
                    .get_ids()
                    .iter()
                    .map(|&id| i64::from(id))
                    .collect();
                row.resize(length, i64::from(*pad_id));
                let mut attention = vec![1_i64; real];
                attention.resize(length, 0);
                ids.push(row);
                mask.push(attention);
            }
            batches.push(TransformerBatch {
                input_ids: ids,
                attention_mask: mask,
            });
        }
        Ok(PreparedTransformerText { batches, order })
    }
}

#[cfg(test)]
mod tests {
    use super::TransformerTokens;
    use crate::{ModelFileSource, TransformerModel, TransformerSettings};
    use serde_json::Value;
    use std::path::PathBuf;
    #[test]
    fn real_original_feeds_and_raw_counts_require_only_tokenizer_data() {
        let catalog: Value =
            serde_json::from_str(include_str!("../resources/transformer-catalog.json")).unwrap();
        let sources = PathBuf::from(
            std::env::var_os("KEN_TRANSFORMER_SOURCE_ROOT")
                .expect("prepare original pinned tokenizer data"),
        );
        for raw in [
            include_str!("../tests/fixtures/transformer-tokens/qwen.json"),
            include_str!("../tests/fixtures/transformer-tokens/bge.json"),
        ] {
            let golden: Value = serde_json::from_str(raw).unwrap();
            let registration = catalog["models"]
                .as_array()
                .unwrap()
                .iter()
                .find(|m| m["name"] == golden["model"])
                .unwrap();
            let model = TransformerModel::from_json(&registration.to_string()).unwrap();
            let original = sources
                .join(model.assets().model_id().replace('/', "--"))
                .join(model.assets().revision());
            let temporary = tempfile::tempdir().unwrap();
            let snapshot = temporary.path().join(model.assets().revision());
            std::fs::create_dir(&snapshot).unwrap();
            for name in [
                "tokenizer.json",
                "tokenizer_config.json",
                "config.json",
                "sentence_bert_config.json",
                "config_sentence_transformers.json",
            ] {
                if name != "tokenizer.json" && model.configuration(name).is_none() {
                    continue;
                }
                std::fs::copy(original.join(name), snapshot.join(name)).unwrap();
            }
            for name in model.weight_files() {
                assert!(!snapshot.join(name).exists());
            }
            let source = ModelFileSource::new(&snapshot, temporary.path()).unwrap();
            let tokens = TransformerTokens::load(
                &model,
                &source,
                &TransformerSettings {
                    sequence_length: Some(512),
                    batch_size: Some(16),
                    ..Default::default()
                },
            )
            .unwrap();
            for case in golden["cases"].as_array().unwrap() {
                let texts: Vec<_> = case["texts"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|v| v.as_str().unwrap())
                    .collect();
                let counts: Vec<_> = texts
                    .iter()
                    .map(|text| tokens.raw_count(text).unwrap())
                    .collect();
                assert_eq!(
                    serde_json::to_value(counts).unwrap(),
                    case["counts"],
                    "{} {} counts",
                    golden["model"],
                    case["id"]
                );
                let prepared = if case["side"] == "query" {
                    tokens.queries(&texts)
                } else {
                    tokens.passages(&texts)
                }
                .unwrap();
                assert_eq!(
                    serde_json::to_value(prepared.batches()).unwrap(),
                    case["feeds"],
                    "{} {} feeds",
                    golden["model"],
                    case["id"]
                );
                let sorted = prepared.original_indices().to_vec();
                assert_eq!(
                    prepared.restore(sorted).unwrap(),
                    (0..texts.len()).collect::<Vec<_>>()
                );
                assert!(prepared.restore(Vec::<usize>::new()).is_err());
            }
            let empty = tokens.passages(&[]).unwrap();
            assert!(empty.batches().is_empty());
            assert!(empty.restore(Vec::<usize>::new()).unwrap().is_empty());
        }
    }
    #[test]
    fn lowercasing_is_only_for_prepared_text_and_composes_with_default_prompt() {
        use serde_json::json;
        let (_temp, model, source, _runtime) =
            crate::transformer_test_support::fixture_with_configs(&[
                (
                    "sentence_bert_config.json",
                    json!({"max_seq_length":4,"do_lower_case":true}),
                ),
                (
                    "config_sentence_transformers.json",
                    json!({"default_prompt_name":"search","prompts":{"search":"FIND "}}),
                ),
            ]);
        let tokens = TransformerTokens::load(
            &model,
            &source,
            &TransformerSettings {
                sequence_length: Some(512),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(tokens.sequence_limit(), 4);
        assert_eq!(tokens.encode_content("FIND").unwrap(), vec![0]);
        let texts = tokens.queries(&["RED", "RED RED RED RED RED"]).unwrap();
        for batch in texts.batches() {
            for row in &batch.input_ids {
                assert_eq!(row, &vec![4, 1, 2, 5]);
            }
            for row in &batch.attention_mask {
                assert_eq!(row, &vec![1, 1, 1, 1]);
            }
        }
    }
    #[test]
    fn token_metadata_is_authenticated_and_lower_requested_limit_is_kept() {
        let (_temp, model, source, _runtime) = crate::transformer_test_support::fixture();
        let tokens = TransformerTokens::load(
            &model,
            &source,
            &TransformerSettings {
                sequence_length: Some(3),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(tokens.sequence_limit(), 3);
        assert_eq!(
            tokens.passages(&["find red"]).unwrap().batches()[0].input_ids,
            vec![vec![4, 1, 5]]
        );
        std::fs::write(source.snapshot().join("tokenizer.json"), b"{}").unwrap();
        assert!(TransformerTokens::load(&model, &source, &TransformerSettings::default()).is_err());
    }
    #[test]
    fn actual_mlx_feeds_use_stable_token_length_order_and_raw_counts() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/fixtures/transformer-tokens/mlx.json"
        ))
        .unwrap();
        let catalog: Value =
            serde_json::from_str(include_str!("../resources/transformer-catalog.json")).unwrap();
        let registration = catalog["models"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["name"] == golden["model"])
            .unwrap();
        let model = TransformerModel::from_json(&registration.to_string()).unwrap();
        let sources = PathBuf::from(
            std::env::var_os("KEN_TRANSFORMER_SOURCE_ROOT")
                .expect("prepare registered tokenizer source"),
        );
        let source = ModelFileSource::new(
            &sources
                .join(model.assets().model_id().replace('/', "--"))
                .join(model.assets().revision()),
            &sources,
        )
        .unwrap();
        let tokens = TransformerTokens::for_mlx(
            &model,
            &source,
            &TransformerSettings {
                sequence_length: Some(512),
                batch_size: Some(16),
                ..Default::default()
            },
        )
        .unwrap();
        for case in golden["cases"].as_array().unwrap() {
            let texts: Vec<_> = case["texts"]
                .as_array()
                .unwrap()
                .iter()
                .map(|s| s.as_str().unwrap())
                .collect();
            let counts: Vec<_> = texts.iter().map(|s| tokens.raw_count(s).unwrap()).collect();
            assert_eq!(serde_json::to_value(counts).unwrap(), case["counts"]);
            let prepared = if case["side"] == "query" {
                tokens.queries(&texts)
            } else {
                tokens.passages(&texts)
            }
            .unwrap();
            assert_eq!(
                serde_json::to_value(prepared.batches()).unwrap(),
                case["feeds"],
                "{} feeds",
                case["id"]
            );
            assert_eq!(
                serde_json::to_value(prepared.original_indices()).unwrap(),
                case["order"],
                "{} order",
                case["id"]
            );
        }
    }
    #[test]
    fn mlx_ignores_st_lowercase_default_prompt_and_lower_limit_and_overrides_left_padding() {
        use serde_json::json;
        let (_temp, model, source, _runtime) =
            crate::transformer_test_support::fixture_with_configs(&[
                (
                    "sentence_bert_config.json",
                    json!({"max_seq_length":4,"do_lower_case":true}),
                ),
                (
                    "tokenizer_config.json",
                    json!({"pad_token":"[PAD]","model_max_length":16,"padding_side":"left"}),
                ),
                (
                    "config_sentence_transformers.json",
                    json!({"default_prompt_name":"search","prompts":{"search":"find "}}),
                ),
            ]);
        let tokens = TransformerTokens::for_mlx(
            &model,
            &source,
            &TransformerSettings {
                sequence_length: Some(8),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(tokens.sequence_limit(), 8);
        let prepared = tokens
            .queries(&["FIND RED", "find red red red red red red red red"])
            .unwrap();
        assert_eq!(
            prepared.batches()[0].input_ids[0],
            vec![4, 0, 0, 5, 3, 3, 3, 3]
        );
        assert_eq!(
            prepared.batches()[0].attention_mask[0],
            vec![1, 1, 1, 1, 0, 0, 0, 0]
        );
        assert_eq!(prepared.batches()[0].input_ids[1].len(), 8);
    }
}
