//! Immutable FastEmbed recipes; asset identity and requested spelling stay distinct.
use crate::{FastEmbedTokens, ModelAssets, ModelError};
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Pooling {
    ClsOrSentenceL2,
    Mean,
    MeanL2,
    Raw,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FastEmbedNotice {
    pub kind: String,
    pub message: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Declaration {
    format: String,
    name: String,
    assets: Box<RawValue>,
    graph: String,
    dimension: usize,
    pooling: Pooling,
    #[serde(default)]
    task_id: Option<i64>,
    advisories: Vec<FastEmbedNotice>,
}

#[derive(Clone, Debug)]
pub struct FastEmbedModel {
    name: String,
    assets: ModelAssets,
    graph: String,
    dimension: usize,
    pub(crate) pooling: Pooling,
    task_id: Option<i64>,
    advisories: Vec<FastEmbedNotice>,
}

impl FastEmbedModel {
    pub fn from_json(json: &str) -> Result<Self, ModelError> {
        let raw: Declaration = serde_json::from_str(json)?;
        let assets = ModelAssets::from_json(raw.assets.get())?;
        if raw.format != "ken-fastembed-model/1"
            || raw.name.is_empty()
            || raw.dimension == 0
            || raw.task_id.is_some_and(|id| id != 1)
            || !assets.artifact_records().contains_key(&raw.graph)
            || [
                "config.json",
                "tokenizer.json",
                "tokenizer_config.json",
                "special_tokens_map.json",
            ]
            .iter()
            .any(|name| !assets.artifact_records().contains_key(*name))
            || raw.advisories.iter().any(|notice| {
                !matches!(notice.kind.as_str(), "model_update" | "pooling_update")
                    || notice.message.is_empty()
            })
        {
            return Err(ModelError::Registration(
                "complete registered FastEmbed recipe required".into(),
            ));
        }
        Ok(Self {
            name: raw.name,
            assets,
            graph: raw.graph,
            dimension: raw.dimension,
            pooling: raw.pooling,
            task_id: raw.task_id,
            advisories: raw.advisories,
        })
    }

    pub fn name(&self) -> &str {
        &self.name
    }
    pub fn dim(&self) -> usize {
        self.dimension
    }
    pub fn assets(&self) -> &ModelAssets {
        &self.assets
    }
    pub fn source_id(&self) -> &str {
        self.assets.model_id()
    }
    pub fn source_revision(&self) -> &str {
        self.assets.revision()
    }
    pub fn graph(&self) -> &str {
        &self.graph
    }
    pub fn task_id(&self) -> Option<i64> {
        self.task_id
    }
    pub fn advisories(&self) -> &[FastEmbedNotice] {
        &self.advisories
    }

    pub fn fingerprint(&self) -> String {
        let value = serde_json::json!({"format":"ken-fastembed-model/1","name":self.name,
            "assets":self.assets,"graph":self.graph,"dimension":self.dimension,
            "pooling":self.pooling,"task_id":self.task_id,"advisories":self.advisories});
        format!(
            "{:x}",
            Sha256::digest(crate::assets::python_json(&value).as_bytes())
        )
    }

    pub fn with_requested_name(&self, name: &str) -> Result<Self, ModelError> {
        if name.to_lowercase() != self.name.to_lowercase() {
            return Err(ModelError::Registration(
                "requested alias must select the same registered model".into(),
            ));
        }
        let mut result = self.clone();
        result.name = name.into();
        for notice in &mut result.advisories {
            if notice.kind == "pooling_update" {
                let prefix = format!("The model {} ", self.name);
                if let Some(suffix) = notice.message.strip_prefix(&prefix) {
                    notice.message = format!("The model {name} {suffix}");
                }
            }
        }
        Ok(result)
    }

    pub fn pool(
        &self,
        values: &[f32],
        shape: &[usize],
        tokens: &FastEmbedTokens,
    ) -> Result<Vec<Vec<f32>>, ModelError> {
        crate::embedding_pool::pool(self.pooling, self.dimension, values, shape, tokens)
    }

    pub fn tokenizer(
        &self,
        source: &crate::ModelFileSource,
    ) -> Result<crate::FastEmbedTokenizer, ModelError> {
        crate::FastEmbedTokenizer::from_source(self, source)
    }

    pub fn tokenizer_from_files(
        &self,
        files: &crate::VerifiedModelFiles,
    ) -> Result<crate::FastEmbedTokenizer, ModelError> {
        crate::FastEmbedTokenizer::from_files(self, files)
    }
}

#[derive(Debug)]
pub struct FastEmbedCatalog {
    models: Vec<FastEmbedModel>,
    names: BTreeMap<String, usize>,
}

impl FastEmbedCatalog {
    pub fn from_json(json: &str) -> Result<Self, ModelError> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Catalog {
            format: String,
            models: Vec<Box<RawValue>>,
        }
        let raw: Catalog = serde_json::from_str(json)?;
        if raw.format != "ken-fastembed-catalog/1" || raw.models.is_empty() {
            return Err(ModelError::Registration(
                "nonempty FastEmbed catalogue required".into(),
            ));
        }
        let mut result = Self {
            models: Vec::new(),
            names: BTreeMap::new(),
        };
        for json in raw.models {
            let model = FastEmbedModel::from_json(json.get())?;
            if result
                .names
                .insert(model.name.to_lowercase(), result.models.len())
                .is_some()
            {
                return Err(ModelError::Registration(
                    "duplicate case-insensitive FastEmbed name".into(),
                ));
            }
            result.models.push(model);
        }
        Ok(result)
    }
    pub fn model(&self, name: &str) -> Result<&FastEmbedModel, ModelError> {
        self.names
            .get(&name.to_lowercase())
            .map(|index| &self.models[*index])
            .ok_or_else(|| ModelError::Registration(format!("unsupported FastEmbed model: {name}")))
    }
    pub fn models(&self) -> &[FastEmbedModel] {
        &self.models
    }
}
