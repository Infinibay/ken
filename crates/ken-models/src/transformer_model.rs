//! Registered transformer data and policies; declarations never load a core.
use crate::{ModelAssets, ModelError};
use ken_native_model_api::{
    TransformerArchitecture, TransformerDtype, TransformerPooling, TransformerWeightLayout,
};
use serde::Deserialize;
use serde_json::Value;
use std::collections::BTreeMap;

fn invalid(message: impl Into<String>) -> ModelError {
    ModelError::Registration(message.into())
}

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TransformerRole {
    Encoder,
    Judge,
}

#[derive(Clone, Debug, Default)]
pub struct TransformerSettings {
    pub dtype: Option<TransformerDtype>,
    pub sequence_length: Option<usize>,
    pub batch_size: Option<usize>,
}

impl TransformerSettings {
    pub fn effective_dtype(&self) -> TransformerDtype {
        self.dtype.unwrap_or(TransformerDtype::Float32)
    }
    pub fn validate(&self) -> Result<(), ModelError> {
        if self.sequence_length == Some(0) || self.batch_size == Some(0) {
            return Err(invalid(
                "transformer sequence and batch limits must be positive",
            ));
        }
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Registration {
    name: String,
    assets: Value,
    dimension: usize,
    architecture: TransformerArchitecture,
    weight_layout: TransformerWeightLayout,
    role: TransformerRole,
    configs: BTreeMap<String, Value>,
}

#[derive(Clone)]
pub struct TransformerModel {
    assets: ModelAssets,
    dimension: usize,
    architecture: TransformerArchitecture,
    weight_layout: TransformerWeightLayout,
    role: TransformerRole,
    configs: BTreeMap<String, Value>,
    vocabulary: u64,
    weight_files: Vec<String>,
    pooling: TransformerPooling,
    normalize_modules: usize,
}

impl TransformerModel {
    pub fn from_json(input: &str) -> Result<Self, ModelError> {
        let raw: Registration = serde_json::from_str(input)?;
        let assets = ModelAssets::from_json(&serde_json::to_string(&raw.assets)?)?;
        let config = raw
            .configs
            .get("config.json")
            .ok_or_else(|| invalid("missing transformer configuration"))?;
        let model_type = match raw.architecture {
            TransformerArchitecture::Qwen3 => "qwen3",
            TransformerArchitecture::XlmRoberta => "xlm-roberta",
        };
        let vocabulary = config["vocab_size"]
            .as_u64()
            .filter(|n| *n > 0)
            .ok_or_else(|| invalid("invalid transformer vocabulary"))?;
        if raw.name != assets.model_id()
            || raw.dimension == 0
            || config["hidden_size"].as_u64() != Some(raw.dimension as u64)
            || config["model_type"] != model_type
            || (raw.role == TransformerRole::Judge
                && raw.architecture != TransformerArchitecture::Qwen3)
            || (raw.architecture == TransformerArchitecture::XlmRoberta
                && raw.weight_layout != TransformerWeightLayout::Unprefixed)
        {
            return Err(invalid(
                "transformer identity, dimension or architecture mismatch",
            ));
        }
        let artifacts = assets.artifact_hashes();
        if !artifacts.contains_key("config.json")
            || !artifacts.contains_key("tokenizer.json")
            || raw
                .configs
                .keys()
                .any(|name| !artifacts.contains_key(name.as_str()))
        {
            return Err(invalid(
                "transformer configurations must be registered artifacts",
            ));
        }
        let weight_files: Vec<_> = artifacts
            .keys()
            .copied()
            .filter(|name| name.ends_with(".safetensors") || *name == "pytorch_model.bin")
            .map(str::to_owned)
            .collect();
        if weight_files.is_empty() {
            return Err(invalid("missing registered transformer weights"));
        }
        let (pooling, normalize_modules) = if raw.role == TransformerRole::Judge {
            (TransformerPooling::Last, 0)
        } else {
            sentence_policy(&raw.configs, raw.dimension)?
        };
        Ok(Self {
            assets,
            dimension: raw.dimension,
            architecture: raw.architecture,
            weight_layout: raw.weight_layout,
            role: raw.role,
            configs: raw.configs,
            vocabulary,
            weight_files,
            pooling,
            normalize_modules,
        })
    }

    pub fn assets(&self) -> &ModelAssets {
        &self.assets
    }
    pub fn dimension(&self) -> usize {
        self.dimension
    }
    pub fn architecture(&self) -> TransformerArchitecture {
        self.architecture
    }
    pub fn weight_layout(&self) -> TransformerWeightLayout {
        self.weight_layout
    }
    pub fn role(&self) -> TransformerRole {
        self.role
    }
    pub fn vocabulary(&self) -> u64 {
        self.vocabulary
    }
    pub fn weight_files(&self) -> &[String] {
        &self.weight_files
    }
    pub fn pooling(&self) -> TransformerPooling {
        self.pooling
    }
    pub fn normalize_modules(&self) -> usize {
        self.normalize_modules
    }
    pub fn configuration(&self, name: &str) -> Option<&Value> {
        self.configs.get(name)
    }

    pub(crate) fn validate_files(
        &self,
        files: &crate::VerifiedModelFiles,
    ) -> Result<(), ModelError> {
        for (name, expected) in &self.configs {
            let actual: Value = serde_json::from_slice(&files.read(name)?)?;
            if &actual != expected {
                return Err(invalid(format!(
                    "registered metadata differs from artifact {name}"
                )));
            }
        }
        Ok(())
    }
}

fn sentence_policy(
    configs: &BTreeMap<String, Value>,
    dimension: usize,
) -> Result<(TransformerPooling, usize), ModelError> {
    let modules = configs
        .get("modules.json")
        .and_then(Value::as_array)
        .ok_or_else(|| invalid("missing Sentence Transformers modules"))?;
    let mut transformer = false;
    let mut pooling = None;
    let mut normalize = 0;
    for (index, module) in modules.iter().enumerate() {
        if module["idx"].as_u64() != Some(index as u64) {
            return Err(invalid("unordered transformer modules"));
        }
        let kind = module["type"]
            .as_str()
            .ok_or_else(|| invalid("missing module kind"))?;
        if kind == "sentence_transformers.models.Transformer" && index == 0 && !transformer {
            transformer = true;
        } else if kind == "sentence_transformers.models.Pooling"
            && transformer
            && pooling.is_none()
            && normalize == 0
        {
            let path = module["path"]
                .as_str()
                .ok_or_else(|| invalid("missing pooling module path"))?;
            let config = configs
                .get(&format!("{path}/config.json"))
                .ok_or_else(|| invalid("missing pooling configuration"))?;
            if config["word_embedding_dimension"].as_u64() != Some(dimension as u64) {
                return Err(invalid("pooling dimension mismatch"));
            }
            for unsupported in [
                "pooling_mode_max_tokens",
                "pooling_mode_mean_sqrt_len_tokens",
                "pooling_mode_weightedmean_tokens",
            ] {
                if config[unsupported] == true {
                    return Err(invalid("unsupported registered pooling module"));
                }
            }
            let selected: Vec<_> = [
                ("pooling_mode_cls_token", TransformerPooling::Cls),
                ("pooling_mode_mean_tokens", TransformerPooling::Mean),
                ("pooling_mode_lasttoken", TransformerPooling::Last),
            ]
            .into_iter()
            .filter(|(name, _)| config[*name] == true)
            .map(|(_, mode)| mode)
            .collect();
            if selected.len() != 1 {
                return Err(invalid("one declared pooling mode required"));
            }
            pooling = Some(selected[0]);
        } else if kind == "sentence_transformers.models.Normalize" && pooling.is_some() {
            normalize += 1;
        } else {
            return Err(invalid(
                "unsupported registered transformer module sequence",
            ));
        }
    }
    Ok((
        pooling.ok_or_else(|| invalid("missing pooling module"))?,
        normalize,
    ))
}
