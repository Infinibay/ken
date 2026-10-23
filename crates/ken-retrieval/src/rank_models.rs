//! Verify immutable registered artifacts and retain each forest only on first use.
use crate::{Result, RetrievalError, numeric_ranker::NumericRanker};
use flate2::read::GzDecoder;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::File,
    io::Read,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
};
const MANIFEST: &[u8] = include_bytes!("../resources/ranking/manifest.json");
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct Artifact {
    file: String,
    compressed_bytes: u64,
    compressed_sha256: String,
    decoded_bytes: u64,
    decoded_sha256: String,
    fingerprint: String,
    feature_count: usize,
    trees: usize,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Registry {
    schema: usize,
    models: BTreeMap<String, Artifact>,
}
struct LazyForest {
    artifact: Artifact,
    model: Mutex<Option<Arc<NumericRanker>>>,
}
pub struct ProductionRankModels {
    directory: PathBuf,
    native: LazyForest,
    piece: LazyForest,
}
fn invalid(message: impl Into<String>) -> RetrievalError {
    RetrievalError::Invalid(message.into())
}
fn bounded(path: &Path, limit: u64) -> Result<Vec<u8>> {
    let file = File::open(path)
        .map_err(|e| invalid(format!("ranking resource {}: {e}", path.display())))?;
    let mut bytes = Vec::new();
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| invalid(format!("ranking resource read: {e}")))?;
    Ok(bytes)
}
fn identity(bytes: &[u8], length: u64, sha: &str) -> bool {
    bytes.len() as u64 == length && format!("{:x}", Sha256::digest(bytes)) == sha
}
fn decode(bytes: &[u8], record: &Artifact) -> Result<NumericRanker> {
    if !identity(bytes, record.compressed_bytes, &record.compressed_sha256) {
        return Err(invalid(
            "bundled production ranking compressed identity mismatch",
        ));
    }
    let mut decoded = Vec::new();
    GzDecoder::new(bytes)
        .take(record.decoded_bytes + 1)
        .read_to_end(&mut decoded)
        .map_err(|e| invalid(format!("bundled production ranking gzip: {e}")))?;
    if !identity(&decoded, record.decoded_bytes, &record.decoded_sha256) {
        return Err(invalid(
            "bundled production ranking decoded identity mismatch",
        ));
    }
    let raw = std::str::from_utf8(&decoded)
        .map_err(|_| invalid("bundled production ranking model is not UTF-8"))?;
    let model = NumericRanker::from_json(raw)?;
    if model.fingerprint()? != record.fingerprint
        || model.features().len() != record.feature_count
        || model.tree_count() != record.trees
    {
        return Err(invalid(
            "bundled production ranking model identity mismatch",
        ));
    }
    Ok(model)
}
impl ProductionRankModels {
    pub fn open(resources: impl AsRef<Path>) -> Result<Self> {
        let directory = resources.as_ref().to_path_buf();
        if bounded(&directory.join("manifest.json"), MANIFEST.len() as u64)? != MANIFEST {
            return Err(invalid(
                "bundled production ranking registry identity mismatch",
            ));
        }
        let mut registry: Registry = serde_json::from_slice(MANIFEST)?;
        if registry.schema != 1 || registry.models.len() != 2 {
            return Err(invalid(
                "bundled production ranking registry schema mismatch",
            ));
        }
        let mut take = |role| -> Result<LazyForest> {
            Ok(LazyForest {
                artifact: registry
                    .models
                    .remove(role)
                    .ok_or_else(|| invalid("bundled production ranking role missing"))?,
                model: Mutex::new(None),
            })
        };
        Ok(Self {
            directory,
            native: take("native")?,
            piece: take("piece")?,
        })
    }
    fn load(&self, forest: &LazyForest) -> Result<Arc<NumericRanker>> {
        let mut slot = forest
            .model
            .lock()
            .map_err(|_| invalid("production ranking model lock poisoned"))?;
        if let Some(model) = &*slot {
            return Ok(model.clone());
        }
        let bytes = bounded(
            &self.directory.join(&forest.artifact.file),
            forest.artifact.compressed_bytes,
        )?;
        let model = Arc::new(decode(&bytes, &forest.artifact)?);
        *slot = Some(model.clone());
        Ok(model)
    }
    pub fn native(&self) -> Result<Arc<NumericRanker>> {
        self.load(&self.native)
    }
    pub fn piece(&self) -> Result<Arc<NumericRanker>> {
        self.load(&self.piece)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    #[test]
    fn decoded_schema_and_canonical_identity_are_verified_after_transport() {
        let registry: Registry = serde_json::from_slice(MANIFEST).unwrap();
        for (raw, expected) in [
            (
                r#"{"schema":2,"features":["x"],"trees":[{"value":0}]}"#,
                "unsupported numeric ranking schema",
            ),
            (
                r#"{"schema":1,"features":["x"],"trees":[{"value":0}]}"#,
                "bundled production ranking model identity mismatch",
            ),
        ] {
            let mut record = registry.models["native"].clone();
            let mut encoder =
                flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
            encoder.write_all(raw.as_bytes()).unwrap();
            let bytes = encoder.finish().unwrap();
            record.compressed_bytes = bytes.len() as u64;
            record.compressed_sha256 = format!("{:x}", Sha256::digest(&bytes));
            record.decoded_bytes = raw.len() as u64;
            record.decoded_sha256 = format!("{:x}", Sha256::digest(raw.as_bytes()));
            let error = decode(&bytes, &record).unwrap_err().to_string();
            assert!(error.contains(expected), "{error}");
        }
    }
}
