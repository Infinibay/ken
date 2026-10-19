//! Associate an upstream model with its exact derived graph and prepared bytes.
use crate::{ModelAssets, ModelError, VerifiedSnapshot, assets::python_json};
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use sha2::{Digest, Sha256};
use std::{path::Path, sync::Arc};

const CONFIGS: [&str; 3] = ["tokenizer.json", "config.json", "tokenizer_config.json"];
const RECIPE: &str = "CLS-Dense-exactGELU-LayerNorm-eps1e-5-Dense-FP32-v1";

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Graph {
    path: String,
    bytes: u64,
    sha256: String,
}
#[derive(Deserialize)]
struct Declaration {
    // Preserve nested duplicates until the authoritative ModelAssets parser.
    source: Box<RawValue>,
    graph: Graph,
    recipe: Option<String>,
}

#[derive(Clone, Debug)]
pub struct RerankerModel {
    source: ModelAssets,
    prepared: ModelAssets,
    graph_name: String,
    recipe_key: String,
}

#[derive(Clone, Debug)]
pub struct PreparedReranker {
    pub(crate) snapshot: Arc<VerifiedSnapshot>,
    graph_name: String,
}

impl RerankerModel {
    pub fn from_json(input: &str) -> Result<Self, ModelError> {
        let declaration: Declaration = serde_json::from_str(input)?;
        let source = ModelAssets::from_json(declaration.source.get())?;
        if declaration
            .recipe
            .as_deref()
            .is_some_and(|value| value != RECIPE)
        {
            return Err(ModelError::Registration(
                "unsupported reranker recipe".into(),
            ));
        }
        let source_json = serde_json::to_value(&source)?;
        let mut artifacts = serde_json::Map::new();
        for name in CONFIGS {
            let record = source_json["artifacts"].get(name).ok_or_else(|| {
                ModelError::Registration(format!("reranker source requires {name}"))
            })?;
            artifacts.insert(name.into(), record.clone());
        }
        if artifacts.contains_key(&declaration.graph.path) {
            return Err(ModelError::Registration(
                "graph collides with configuration".into(),
            ));
        }
        artifacts.insert(
            declaration.graph.path.clone(),
            json!({
            "bytes":declaration.graph.bytes,"sha256":declaration.graph.sha256}),
        );
        let prepared = ModelAssets::from_json(&json!({"model_id":source_json["model_id"],
            "revision":source_json["revision"],"license":source_json["license"],"artifacts":artifacts}).to_string())?;
        let definition: Value = serde_json::from_str(input)?;
        let recipe_key = format!("{:x}", Sha256::digest(python_json(&definition).as_bytes()));
        Ok(Self {
            source,
            prepared,
            graph_name: declaration.graph.path,
            recipe_key,
        })
    }

    pub fn source_assets(&self) -> &ModelAssets {
        &self.source
    }
    pub fn prepared_assets(&self) -> ModelAssets {
        self.prepared.clone()
    }
    pub fn recipe_key(&self) -> String {
        self.recipe_key.clone()
    }
    pub(crate) fn graph_name(&self) -> &str {
        &self.graph_name
    }
    pub(crate) fn accredits(&self, prepared: &PreparedReranker) -> bool {
        self.graph_name == prepared.graph_name && self.prepared.accredits(&prepared.snapshot)
    }
    pub fn verify_prepared(&self, root: &Path) -> Result<PreparedReranker, ModelError> {
        Ok(PreparedReranker {
            snapshot: Arc::new(self.prepared.verify_artifacts(root)?),
            graph_name: self.graph_name.clone(),
        })
    }
}

impl PreparedReranker {
    pub fn graph(&self) -> Result<&[u8], ModelError> {
        self.snapshot.artifact(&self.graph_name)
    }
}
