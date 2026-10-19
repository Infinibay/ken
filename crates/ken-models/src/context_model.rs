//! The registered contextual policy and its legacy compatible vector identity.
use crate::{ModelAssets, ModelError, assets::python_json};
use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

#[derive(Clone)]
pub struct ContextModel {
    assets: ModelAssets,
    query_prefix: String,
    document_projection: String,
}

#[derive(Deserialize)]
struct Policy {
    query_prefix: String,
    document_projection: String,
}

fn digest(value: &Value) -> String {
    format!("{:x}", Sha256::digest(python_json(value).as_bytes()))
}

impl ContextModel {
    pub fn from_json(registration: &str) -> Result<Self, ModelError> {
        let assets = ModelAssets::from_json(registration)?;
        let policy: Policy = serde_json::from_str(registration)?;
        let names = assets.artifact_hashes();
        if names.len() != 2
            || !names.contains_key("onnx/model.onnx")
            || !names.contains_key("tokenizer.json")
            || policy.document_projection.is_empty()
        {
            return Err(ModelError::Registration(
                "context requires graph, tokenizer and source projection".into(),
            ));
        }
        Ok(Self {
            assets,
            query_prefix: policy.query_prefix,
            document_projection: policy.document_projection,
        })
    }

    pub fn assets(&self) -> &ModelAssets {
        &self.assets
    }
    pub(crate) fn query_prefix(&self) -> &str {
        &self.query_prefix
    }

    /// Compatibility is with the independently frozen original profile.
    /// Actual executing Rust/native libraries are reported by the runtime owner.
    pub fn compatible_identity(&self) -> Value {
        let revision = digest(&json!({
            "model_id": self.assets.model_id(), "upstream_revision": self.assets.revision(),
            "artifacts": self.assets.artifact_hashes(), "query_prefix": self.query_prefix,
            "document_projection": self.document_projection,
            "policy": "CPU-raw-CLS-runtime-L2-no-padding-prefix512-batch1-v1",
            "runtime": {"numpy":"2.4.4", "onnxruntime":"1.25.1", "tokenizers":"0.22.2"}
        }));
        let spec = json!({"model_id":self.assets.model_id(), "revision":revision,
            "backend":"provided", "dtype":"float32", "sequence_length":512, "batch_size":1});
        let options = digest(&json!({"config":spec,"runtime":[]}));
        json!({"spec":spec,
            "spec_key": format!("{}@{}:{}",self.assets.model_id(),revision,&options[..16]),
            "tokenizer_revision": &digest(&json!([]))[..16]})
    }
}
