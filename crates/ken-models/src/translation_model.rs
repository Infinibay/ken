//! One measured source/derived translation profile and its legacy identity.
use crate::{ModelAssets, ModelError, VerifiedSnapshot, assets::python_json, translation_json};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
    sync::Arc,
};

pub(crate) const TRANSLATION_FILES: [&str; 5] = [
    "model.bin",
    "config.json",
    "shared_vocabulary.json",
    "source.spm",
    "target.spm",
];

#[derive(Clone, Copy, Debug)]
pub enum FrozenTranslationRuntime {
    MacOS483,
    Linux482,
}

#[derive(Clone, Debug)]
pub struct TranslationModel {
    source: ModelAssets,
    derived: ModelAssets,
    recipe_key: String,
}

#[derive(Clone, Debug)]
pub struct PreparedTranslation {
    pub(crate) snapshot: Arc<VerifiedSnapshot>,
}

fn digest(value: &Value) -> String {
    format!("{:x}", Sha256::digest(python_json(value).as_bytes()))
}

impl TranslationModel {
    pub fn from_json(input: &str) -> Result<Self, ModelError> {
        let value = translation_json::definition(input)?;
        if value
            .get("recipe")
            .is_some_and(|recipe| recipe.as_str() != Some("json-indent2-ascii-config-newline-v1"))
        {
            return Err(ModelError::Registration(
                "unsupported translation recipe".into(),
            ));
        }
        let source = ModelAssets::from_json(&value["source"].to_string())?;
        let derived = ModelAssets::from_json(&value["derived"].to_string())?;
        for assets in [&source, &derived] {
            if assets
                .artifact_hashes()
                .into_keys()
                .collect::<BTreeSet<_>>()
                != TRANSLATION_FILES.into_iter().collect()
            {
                return Err(ModelError::Registration(
                    "translation requires the complete measured file set".into(),
                ));
            }
        }
        Ok(Self {
            source,
            derived,
            recipe_key: digest(&value),
        })
    }
    pub fn source_assets(&self) -> &ModelAssets {
        &self.source
    }
    pub fn prepared_assets(&self) -> ModelAssets {
        self.derived.clone()
    }
    pub fn recipe_key(&self) -> &str {
        &self.recipe_key
    }
    pub fn cache_path(&self, root: &Path) -> PathBuf {
        root.join("models/translation")
            .join(&self.recipe_key)
            .join(self.derived.revision())
    }
    pub(crate) fn check_destination(&self, root: &Path) -> Result<(), ModelError> {
        if root.file_name().and_then(|value| value.to_str()) != Some(self.derived.revision()) {
            return Err(ModelError::Registration(
                "derived translation directory must match its origin revision".into(),
            ));
        }
        Ok(())
    }
    pub fn verify_prepared(&self, root: &Path) -> Result<PreparedTranslation, ModelError> {
        self.check_destination(root)?;
        Ok(PreparedTranslation {
            snapshot: Arc::new(self.derived.verify(root)?),
        })
    }
    pub fn compatible_identity(&self, profile: FrozenTranslationRuntime) -> Value {
        let ct2 = match profile {
            FrozenTranslationRuntime::MacOS483 => "4.8.3",
            FrozenTranslationRuntime::Linux482 => "4.8.2",
        };
        let derived =
            serde_json::to_value(&self.derived).expect("validated model declarations serialize");
        json!({"model_id":derived["model_id"],"revision":derived["revision"],"artifacts":derived["artifacts"],
            "runtime":{"ctranslate2":ct2,"sentencepiece":"0.2.1"},"device":"cpu","compute_type":"int8",
            "intra_threads":2,"inter_threads":1,"beam_size":1,"max_decoding_length":256,
            "preprocessing":"spanish-lexicon-two-or-question-protect-qualified-identifiers-v1"})
    }
    pub fn compatible_revision(&self, profile: FrozenTranslationRuntime) -> String {
        digest(&self.compatible_identity(profile))
    }
}

impl PreparedTranslation {
    pub fn artifact(&self, name: &str) -> Result<&[u8], ModelError> {
        self.snapshot.artifact(name)
    }
}
