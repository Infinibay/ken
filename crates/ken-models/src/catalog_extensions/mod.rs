//! Authenticated additional recipes for existing native encoder owners.
mod distinct;

use crate::{
    EncoderBackend, EncoderFamily, EncoderSpec, FastEmbedModel, ModelAssets, ModelDescriptor,
    ModelError, ModelRegistration, TransformerDtype, TransformerModel, TransformerRole,
    TransformerSettings, model_catalog::EncoderDefinition,
};
use serde::{Deserialize, Serialize};
use serde_json::value::RawValue;
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, io, path::Path};

const MAX_BYTES: u64 = 2 * 1024 * 1024;
const MAX_MODELS: usize = 512;
fn invalid(message: impl Into<String>) -> ModelError {
    ModelError::Registration(message.into())
}
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Declaration {
    format: String,
    models: Vec<Box<RawValue>>,
}
#[derive(Deserialize)]
enum Backend {
    #[serde(rename = "fastembed")]
    Onnx,
    #[serde(rename = "sentence-transformers")]
    Transformer,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Prompts {
    query: String,
    passage: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Row {
    backend: Backend,
    recipe: Box<RawValue>,
    prompts: Option<Prompts>,
}

#[derive(Clone)]
enum Recipe {
    Onnx(FastEmbedModel),
    Transformer(TransformerModel),
}

#[derive(Clone)]
pub(crate) struct Entry {
    name: String,
    selector: String,
    source_sha256: String,
    recipe_sha256: String,
    profile_revision: String,
    recipe: Recipe,
}
impl Entry {
    pub(crate) fn name(&self) -> &str {
        &self.name
    }
    pub(crate) fn selector(&self) -> &str {
        &self.selector
    }
    pub(crate) fn assets(&self) -> &ModelAssets {
        match &self.recipe {
            Recipe::Onnx(model) => model.assets(),
            Recipe::Transformer(model) => model.assets(),
        }
    }
    fn family(&self) -> EncoderFamily {
        match &self.recipe {
            Recipe::Onnx(_) => EncoderFamily::FastEmbed,
            Recipe::Transformer(_) => EncoderFamily::SentenceTransformer,
        }
    }
    pub(crate) fn definition(&self) -> EncoderDefinition {
        match &self.recipe {
            Recipe::Onnx(model) => EncoderDefinition::FastEmbed(model.clone()),
            Recipe::Transformer(model) => {
                EncoderDefinition::Sentence(model.clone(), TransformerSettings::default())
            }
        }
    }
    pub(crate) fn transformer_for(
        &self,
        spec: &EncoderSpec,
        role: TransformerRole,
    ) -> Option<TransformerModel> {
        if role != TransformerRole::Encoder
            || spec.model_id != self.name
            || spec.revision != self.profile_revision
        {
            return None;
        }
        match &self.recipe {
            Recipe::Transformer(model) => Some(model.clone()),
            Recipe::Onnx(_) => None,
        }
    }
    pub(crate) fn descriptor(&self) -> ModelDescriptor {
        let assets = self.assets();
        ModelDescriptor {
            model: self.selector.clone(),
            dim: Some(match &self.recipe {
                Recipe::Onnx(model) => model.dim(),
                Recipe::Transformer(model) => model.dimension(),
            }),
            bytes: assets
                .artifact_records()
                .values()
                .map(|value| value.bytes)
                .sum(),
            backend: self.family(),
            registration: ModelRegistration {
                model_id: assets.model_id().into(),
                revision: assets.revision().into(),
                assets: Some(assets.clone()),
            },
            native_inference_accepted: false,
        }
    }
    pub(crate) fn spec(&self) -> Result<EncoderSpec, ModelError> {
        if !matches!(&self.recipe, Recipe::Transformer(_)) {
            return Err(invalid(
                "ONNX extension requires its explicit immutable selector; FastEmbed is not an original EncoderSpec backend",
            ));
        }
        Ok(EncoderSpec {
            model_id: self.name.clone(),
            revision: self.profile_revision.clone(),
            backend: EncoderBackend::SentenceTransformers,
            dtype: TransformerDtype::Float32,
            sequence_length: 512,
            batch_size: 16,
        })
    }
    pub(crate) fn status(&self, snapshot: Option<&Path>) -> Result<ExtensionStatus, ModelError> {
        let resources = if let Some(snapshot) = snapshot {
            let assets = self.assets();
            assets.validate_snapshot(snapshot)?;
            // Keep large weights bounded in memory and retain the artifact
            // owner's opened-inode/size/hash checks, without preparing a core.
            for (name, expected) in assets.artifact_records() {
                crate::verified_file::copy(
                    &snapshot.join(name),
                    expected.bytes,
                    &expected.sha256,
                    &mut io::sink(),
                )
                .map_err(|error| {
                    ModelError::Artifact(format!("extension source {name}: {error}"))
                })?;
            }
            ResourceAvailability::Verified
        } else {
            ResourceAvailability::NotChecked
        };
        Ok(ExtensionStatus {
            registered: true,
            selector: self.selector.clone(),
            model: self.name.clone(),
            catalogue_sha256: self.source_sha256.clone(),
            recipe_sha256: self.recipe_sha256.clone(),
            family: self.family(),
            resources,
            native_inference_accepted: false,
        })
    }
}

/// Asset verification and inference qualification are independent observations.
#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ResourceAvailability {
    NotChecked,
    Verified,
}
#[derive(Clone, Debug, Serialize)]
pub struct ExtensionStatus {
    pub registered: bool,
    pub selector: String,
    pub model: String,
    pub catalogue_sha256: String,
    pub recipe_sha256: String,
    pub family: EncoderFamily,
    pub resources: ResourceAvailability,
    pub native_inference_accepted: bool,
}

/// Immutable declarations authenticated against a caller-provided raw SHA256.
/// Parsing data does not establish native numerical acceptance.
#[derive(Clone)]
pub struct CatalogExtensions {
    identity: String,
    entries: Vec<Entry>,
}
impl CatalogExtensions {
    pub fn from_file(path: &Path, bytes: u64, expected_sha256: &str) -> Result<Self, ModelError> {
        if bytes > MAX_BYTES {
            return Err(invalid("bounded catalogue extension declaration required"));
        }
        let raw = crate::verified_file::read(path, bytes, expected_sha256)
            .map_err(|error| ModelError::Artifact(format!("catalogue extension: {error}")))?;
        let raw =
            std::str::from_utf8(&raw).map_err(|_| invalid("UTF8 catalogue extension required"))?;
        Self::from_json(raw, expected_sha256)
    }
    pub fn from_json(raw: &str, expected_sha256: &str) -> Result<Self, ModelError> {
        if raw.len() as u64 > MAX_BYTES
            || !crate::profile::hex_revision(expected_sha256, &[64])
            || hash(raw.as_bytes()) != expected_sha256
        {
            return Err(invalid("catalogue extension source SHA256/size mismatch"));
        }
        distinct::validate(raw)?;
        let declaration: Declaration = serde_json::from_str(raw)?;
        if declaration.format != "ken-model-catalog-extensions/1"
            || declaration.models.is_empty()
            || declaration.models.len() > MAX_MODELS
        {
            return Err(invalid(
                "bounded nonempty native catalogue extension required",
            ));
        }
        let mut names = BTreeSet::new();
        let mut entries = Vec::new();
        for raw_row in declaration.models {
            let row: Row = serde_json::from_str(raw_row.get())?;
            let recipe_sha256 = hash(row.recipe.get().as_bytes());
            let (name, recipe) = match row.backend {
                Backend::Onnx => {
                    let prompts = row
                        .prompts
                        .ok_or_else(|| invalid("explicit no-prefix ONNX prompt policy required"))?;
                    if !prompts.query.is_empty() || !prompts.passage.is_empty() {
                        return Err(invalid(
                            "additional ONNX recipes currently support only explicit empty query/passage prefixes",
                        ));
                    }
                    let model = FastEmbedModel::from_json(row.recipe.get())?;
                    let established = crate::model_policy::prompts_for(model.name());
                    if !established.query.is_empty() || !established.passage.is_empty() {
                        return Err(invalid(
                            "additional no-prefix ONNX recipe conflicts with established name prompt policy",
                        ));
                    }
                    (model.name().to_owned(), Recipe::Onnx(model))
                }
                Backend::Transformer => {
                    if row.prompts.is_some() {
                        return Err(invalid(
                            "transformer prompts belong to authenticated module metadata",
                        ));
                    }
                    let model = TransformerModel::from_json(row.recipe.get())?;
                    if model.role() != TransformerRole::Encoder {
                        return Err(invalid("catalogue extensions register encoder roles only"));
                    }
                    (
                        model.assets().model_id().to_owned(),
                        Recipe::Transformer(model),
                    )
                }
            };
            let assets = match &recipe {
                Recipe::Onnx(model) => model.assets(),
                Recipe::Transformer(model) => model.assets(),
            };
            assets
                .artifact_records()
                .values()
                .try_fold(0_u64, |total, artifact| {
                    artifact
                        .bytes
                        .checked_add(1)
                        .and_then(|_| total.checked_add(artifact.bytes))
                })
                .ok_or_else(|| invalid("catalogue artifact byte total overflow"))?;
            // A selector contains one unambiguous repository-style name. Its
            // source identity comes from the catalogue, never an alias lookup.
            let components: Vec<_> = name.split('/').collect();
            if components.len() != 2
                || components.iter().any(|part| {
                    part.is_empty()
                        || !part
                            .bytes()
                            .all(|c| c.is_ascii_alphanumeric() || b"_.-".contains(&c))
                })
            {
                return Err(invalid("additional encoder repository-style name required"));
            }
            if !names.insert(name.to_lowercase()) {
                return Err(invalid(
                    "duplicate case-insensitive catalogue extension name",
                ));
            }
            let selector = format!("ken-catalogue:{expected_sha256}:{name}");
            let profile_revision = hash(
                format!("ken-catalogue-encoder/1\0{expected_sha256}\0{name}\0{recipe_sha256}")
                    .as_bytes(),
            );
            entries.push(Entry {
                name,
                selector,
                source_sha256: expected_sha256.into(),
                recipe_sha256,
                profile_revision,
                recipe,
            });
        }
        Ok(Self {
            identity: expected_sha256.into(),
            entries,
        })
    }
    pub fn identity(&self) -> &str {
        &self.identity
    }
    pub(crate) fn entries(&self) -> &[Entry] {
        &self.entries
    }
    pub(crate) fn name(&self, name: &str) -> Option<&Entry> {
        self.entries.iter().find(|entry| entry.name == name)
    }
    pub(crate) fn selector(&self, selector: &str) -> Option<&Entry> {
        self.entries.iter().find(|entry| entry.selector == selector)
    }
}
