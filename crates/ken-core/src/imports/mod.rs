//! Resolve indexed import edges from explicit ordered project inputs.
mod paths;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use thiserror::Error;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ImportRequest {
    pub module: String,
    pub source_path: String,
    pub language: Option<String>,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Resolution {
    Internal,
    Unresolved,
    External,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ImportResolution {
    pub target: Option<String>,
    pub resolution: Resolution,
}
#[derive(Debug, Error)]
pub enum ImportError {
    #[error("import resolution stage pending: {0}")]
    Pending(&'static str),
    #[error("invalid import config {path}: {reason}")]
    Config { path: String, reason: String },
}

pub struct ImportCatalog {
    files: BTreeSet<String>,
    python_suffixes: BTreeMap<String, Vec<String>>,
}
impl ImportCatalog {
    pub fn from_inputs(
        files: Vec<String>,
        configs: Option<BTreeMap<String, Vec<u8>>>,
    ) -> Result<Self, ImportError> {
        if configs.is_some() {
            return Err(ImportError::Pending("project configuration"));
        }
        let python_suffixes = paths::python_suffixes(&files);
        Ok(Self {
            files: files.into_iter().collect(),
            python_suffixes,
        })
    }
    /// The original language-independent structural phase; ambiguity is absence.
    pub fn structural_target(&self, module: &str, source: Option<&str>) -> Option<String> {
        paths::structural_target(module, source, &self.files, &self.python_suffixes)
    }
    pub fn resolve(&self, request: &ImportRequest) -> Result<ImportResolution, ImportError> {
        if let Some(target) = self.structural_target(&request.module, Some(&request.source_path)) {
            return Ok(ImportResolution {
                target: Some(target),
                resolution: Resolution::Internal,
            });
        }
        Err(ImportError::Pending("language policies and classification"))
    }
}
