use crate::ModelError;
use serde::{Deserialize, Deserializer, Serialize, de};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fmt, path::Path};

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub(crate) struct Artifact {
    pub(crate) bytes: u64,
    pub(crate) sha256: String,
}

/// The immutable declaration of public model data, not a download client.
#[derive(Clone, Debug, Serialize)]
pub struct ModelAssets {
    model_id: String,
    revision: String,
    license: String,
    artifacts: BTreeMap<String, Artifact>,
}

#[derive(Deserialize)]
struct Declaration {
    model_id: String,
    revision: String,
    #[serde(default)]
    license: String,
    #[serde(deserialize_with = "distinct_artifacts")]
    artifacts: BTreeMap<String, Artifact>,
}

fn distinct_artifacts<'de, D>(deserializer: D) -> Result<BTreeMap<String, Artifact>, D::Error>
where
    D: Deserializer<'de>,
{
    struct Artifacts;
    impl<'de> de::Visitor<'de> for Artifacts {
        type Value = BTreeMap<String, Artifact>;
        fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            f.write_str("distinct artifact declarations")
        }
        fn visit_map<M: de::MapAccess<'de>>(self, mut map: M) -> Result<Self::Value, M::Error> {
            let mut result = BTreeMap::new();
            while let Some((key, value)) = map.next_entry::<String, Artifact>()? {
                if result.insert(key, value).is_some() {
                    return Err(de::Error::custom("duplicate model artifact"));
                }
            }
            Ok(result)
        }
    }
    deserializer.deserialize_map(Artifacts)
}

fn lowercase_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

pub(crate) fn valid_artifact_name(name: &str) -> bool {
    !name.starts_with('/')
        && !name
            .split('/')
            .any(|part| part.is_empty() || part == "." || part == "..")
        && name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_./-".contains(&byte))
}

impl ModelAssets {
    pub fn from_json(json: &str) -> Result<Self, ModelError> {
        let raw: Declaration = serde_json::from_str(json)?;
        let assets = Self {
            model_id: raw.model_id,
            revision: raw.revision,
            license: raw.license,
            artifacts: raw.artifacts,
        };
        let components: Vec<_> = assets.model_id.split('/').collect();
        if components.len() != 2
            || components.iter().any(|part| {
                part.is_empty()
                    || !part
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b))
            })
        {
            return Err(ModelError::Registration(
                "public model identifier required".into(),
            ));
        }
        if !lowercase_hex(&assets.revision, 40) {
            return Err(ModelError::Registration(
                "immutable revision required".into(),
            ));
        }
        if assets.artifacts.is_empty() {
            return Err(ModelError::Registration(
                "distinct artifacts required".into(),
            ));
        }
        for (name, record) in &assets.artifacts {
            if !valid_artifact_name(name) || !lowercase_hex(&record.sha256, 64) {
                return Err(ModelError::Registration(format!("invalid artifact {name}")));
            }
        }
        Ok(assets)
    }

    pub fn fingerprint(&self) -> String {
        // ModelAssets can contain only strings and nonnegative integer sizes.
        let value = serde_json::to_value(self).expect("model declarations serialize");
        format!("{:x}", Sha256::digest(python_json(&value).as_bytes()))
    }

    pub fn verify(&self, snapshot: &Path) -> Result<VerifiedSnapshot, ModelError> {
        self.validate_snapshot(snapshot)?;
        self.verify_artifacts(snapshot)
    }

    pub(crate) fn validate_snapshot(&self, snapshot: &Path) -> Result<(), ModelError> {
        if snapshot.file_name().and_then(|s| s.to_str()) != Some(self.revision.as_str())
            || !snapshot.is_dir()
        {
            return Err(ModelError::Registration(
                "registered revision directory required".into(),
            ));
        }
        Ok(())
    }

    pub(crate) fn read_source_artifact(
        &self,
        snapshot: &Path,
        name: &str,
    ) -> Result<Vec<u8>, ModelError> {
        self.validate_snapshot(snapshot)?;
        let record = self
            .artifacts
            .get(name)
            .ok_or_else(|| ModelError::Artifact(name.into()))?;
        crate::verified_file::read(&snapshot.join(name), record.bytes, &record.sha256).map_err(
            |error| match error {
                crate::verified_file::VerificationError::Io(source) => ModelError::Io {
                    artifact: name.into(),
                    source,
                },
                crate::verified_file::VerificationError::Invalid(_) => {
                    ModelError::Artifact(name.into())
                }
            },
        )
    }

    pub fn verify_files(
        &self,
        source: &crate::ModelFileSource,
    ) -> Result<crate::VerifiedModelFiles, ModelError> {
        crate::file_assets::verify(self, source)
    }

    pub(crate) fn artifact_records(&self) -> &BTreeMap<String, Artifact> {
        &self.artifacts
    }

    /// Derived caches have caller-chosen names, unlike upstream HF snapshots.
    /// Keep all byte/provenance checks here; only the source revision guard differs.
    pub(crate) fn verify_artifacts(&self, root: &Path) -> Result<VerifiedSnapshot, ModelError> {
        if !root.is_dir() {
            return Err(ModelError::Artifact("artifact directory required".into()));
        }
        let mut files = BTreeMap::new();
        for (name, record) in &self.artifacts {
            let bytes = crate::verified_file::read(&root.join(name), record.bytes, &record.sha256)
                .map_err(|error| match error {
                    crate::verified_file::VerificationError::Io(source) => ModelError::Io {
                        artifact: name.clone(),
                        source,
                    },
                    crate::verified_file::VerificationError::Invalid(_) => {
                        ModelError::Artifact(name.clone())
                    }
                })?;
            files.insert(name.clone(), bytes);
        }
        Ok(VerifiedSnapshot {
            files,
            artifacts: self.artifacts.clone(),
        })
    }

    pub(crate) fn model_id(&self) -> &str {
        &self.model_id
    }
    pub(crate) fn revision(&self) -> &str {
        &self.revision
    }
    pub(crate) fn artifact_hashes(&self) -> BTreeMap<&str, &str> {
        self.artifacts
            .iter()
            .map(|(name, artifact)| (name.as_str(), artifact.sha256.as_str()))
            .collect()
    }
    pub(crate) fn accredits(&self, snapshot: &VerifiedSnapshot) -> bool {
        self.artifacts == snapshot.artifacts
    }
}

/// Owns exactly the bytes checked by ModelAssets; no unchecked public constructor.
#[derive(Debug)]
pub struct VerifiedSnapshot {
    files: BTreeMap<String, Vec<u8>>,
    artifacts: BTreeMap<String, Artifact>,
}

impl VerifiedSnapshot {
    pub fn artifact(&self, name: &str) -> Result<&[u8], ModelError> {
        self.files
            .get(name)
            .map(Vec::as_slice)
            .ok_or_else(|| ModelError::Artifact(name.into()))
    }
}

pub(crate) fn python_json(value: &serde_json::Value) -> String {
    match value {
        serde_json::Value::String(s) => {
            let mut out = String::from("\"");
            for c in s.chars() {
                match c {
                    '"' => out.push_str("\\\""),
                    '\\' => out.push_str("\\\\"),
                    '\n' => out.push_str("\\n"),
                    '\r' => out.push_str("\\r"),
                    '\t' => out.push_str("\\t"),
                    '\u{8}' => out.push_str("\\b"),
                    '\u{c}' => out.push_str("\\f"),
                    ' '..='~' => out.push(c),
                    _ => {
                        for unit in c.encode_utf16(&mut [0; 2]) {
                            out.push_str(&format!("\\u{unit:04x}"));
                        }
                    }
                }
            }
            out.push('"');
            out
        }
        serde_json::Value::Array(values) => format!(
            "[{}]",
            values
                .iter()
                .map(python_json)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        serde_json::Value::Object(map) => format!(
            "{{{}}}",
            map.iter()
                .map(|(k, v)| format!(
                    "{}: {}",
                    python_json(&serde_json::Value::String(k.clone())),
                    python_json(v)
                ))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        other => other.to_string(),
    }
}
