//! Explicit legacy compatibility data; no package installation or native loading.
use crate::profile::invalid;
use crate::{EncoderBackend, EncoderSpec, ModelError, RetrievalProfile};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

type Versions = Vec<(String, String)>;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct LegacyRuntimeIdentity {
    format: String,
    backends: BTreeMap<EncoderBackend, Versions>,
    evidence: Versions,
    contextual: Versions,
}

fn packages(backend: EncoderBackend) -> &'static [&'static str] {
    match backend {
        EncoderBackend::Static => &["numpy", "tokenizers"],
        EncoderBackend::Model2Vec => &["numpy", "model2vec", "tokenizers", "safetensors"],
        EncoderBackend::SentenceTransformers => &[
            "numpy",
            "torch",
            "transformers",
            "tokenizers",
            "sentence-transformers",
            "huggingface-hub",
        ],
        EncoderBackend::Mlx => &[
            "numpy",
            "mlx",
            "mlx-lm",
            "transformers",
            "tokenizers",
            "huggingface-hub",
        ],
        EncoderBackend::Provided => &[],
    }
}

fn check_versions(versions: &[(String, String)], expected: &[&str]) -> Result<(), ModelError> {
    if versions.len() != expected.len()
        || versions
            .iter()
            .zip(expected)
            .any(|((name, version), want)| name != want || version.is_empty())
    {
        return Err(invalid(
            "complete original ordered package versions required",
        ));
    }
    Ok(())
}

fn digest(value: &Value) -> String {
    format!(
        "{:x}",
        Sha256::digest(crate::assets::python_json(value).as_bytes())
    )
}

impl LegacyRuntimeIdentity {
    pub fn from_json(input: &str) -> Result<Self, ModelError> {
        let value: Self = serde_json::from_str(input)?;
        if value.format != "ken-legacy-runtime/1" || value.backends.len() != 5 {
            return Err(invalid(
                "explicit complete legacy runtime declaration required",
            ));
        }
        for backend in [
            EncoderBackend::Static,
            EncoderBackend::Model2Vec,
            EncoderBackend::SentenceTransformers,
            EncoderBackend::Mlx,
            EncoderBackend::Provided,
        ] {
            check_versions(value.backend(backend)?, packages(backend))?;
        }
        check_versions(&value.evidence, &["numpy", "snowballstemmer"])?;
        check_versions(&value.contextual, &["numpy", "tokenizers", "onnxruntime"])?;
        Ok(value)
    }

    pub fn backend(&self, backend: EncoderBackend) -> Result<&[(String, String)], ModelError> {
        self.backends
            .get(&backend)
            .map(Vec::as_slice)
            .ok_or_else(|| invalid("missing original backend version declaration"))
    }
}

impl EncoderSpec {
    pub fn key(&self, legacy: &LegacyRuntimeIdentity) -> Result<String, ModelError> {
        self.key_with_runtime(legacy.backend(self.backend)?)
    }

    /// Provided source policies have no external package runtime in their key.
    pub fn provided_key(&self) -> Result<String, ModelError> {
        if self.backend != EncoderBackend::Provided {
            return Err(invalid("provided encoder policy required"));
        }
        self.key_with_runtime(&[])
    }
    fn key_with_runtime(&self, versions: &[(String, String)]) -> Result<String, ModelError> {
        self.validate()?;
        let options = digest(&json!({"config":self,"runtime":versions}));
        Ok(format!(
            "{}@{}:{}",
            self.model_id,
            self.revision,
            &options[..16]
        ))
    }

    pub fn tokenizer_revision(&self, legacy: &LegacyRuntimeIdentity) -> Result<String, ModelError> {
        self.validate()?;
        let versions: Vec<_> = legacy
            .backend(self.backend)?
            .iter()
            .filter(|(name, _)| matches!(name.as_str(), "transformers" | "tokenizers"))
            .collect();
        Ok(digest(&serde_json::to_value(versions)?)[..16].to_owned())
    }
}

impl RetrievalProfile {
    pub fn fingerprint(&self, legacy: &LegacyRuntimeIdentity) -> Result<String, ModelError> {
        self.validate()?;
        let mut runtime = BTreeMap::from([
            (
                "identity",
                serde_json::to_value(legacy.backend(self.identity.backend)?)?,
            ),
            (
                "behavior",
                serde_json::to_value(legacy.backend(self.behavior.backend)?)?,
            ),
            (
                "joint",
                match &self.joint {
                    Some(joint) => serde_json::to_value(legacy.backend(joint.model.backend)?)?,
                    None => json!([]),
                },
            ),
        ]);
        if let Some(evidence) = &self.evidence {
            runtime.insert("evidence", serde_json::to_value(&legacy.evidence)?);
            runtime.insert(
                "word_model",
                serde_json::to_value(legacy.backend(evidence.word_model.backend)?)?,
            );
        }
        if let Some(contextual) = &self.contextual {
            runtime.insert("contextual", serde_json::to_value(&legacy.contextual)?);
            runtime.insert(
                "contextual_model",
                serde_json::to_value(legacy.backend(contextual.model.backend)?)?,
            );
            if let Some(view) = &contextual.view_model {
                runtime.insert(
                    "contextual_views",
                    serde_json::to_value(legacy.backend(view.backend)?)?,
                );
            }
        }
        Ok(digest(&json!({"config":self,"runtime":runtime})))
    }

    pub fn vector_revision(
        &self,
        view: &str,
        legacy: &LegacyRuntimeIdentity,
    ) -> Result<String, ModelError> {
        self.validate()?;
        let encoder = match view {
            "identity" => &self.identity,
            "behavior" => &self.behavior,
            _ => return Err(invalid("unknown profile vector view")),
        };
        let projection = digest(&json!({"version":self.representation_version,"view":view}));
        Ok(format!(
            "{}:projection-{}",
            encoder.key(legacy)?,
            &projection[..16]
        ))
    }
}
