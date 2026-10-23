//! Resolve indexed import edges from explicit ordered project inputs.
mod aliases;
mod config;
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
    aliases: aliases::AliasResolver,
}
impl ImportCatalog {
    pub fn from_inputs(
        files: Vec<String>,
        configs: Option<BTreeMap<String, Vec<u8>>>,
    ) -> Result<Self, ImportError> {
        let aliases = if let Some(configs) = configs {
            aliases::AliasResolver::from_inputs(&files, &configs)?
        } else {
            aliases::AliasResolver::default()
        };
        let python_suffixes = paths::python_suffixes(&files);
        Ok(Self {
            files: files.into_iter().collect(),
            python_suffixes,
            aliases,
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
        if matches!(
            request.language.as_deref(),
            Some("typescript" | "javascript")
        ) {
            let target = self
                .aliases
                .resolve(&request.module, &request.source_path, &self.files);
            let module = paths::trim(
                paths::trim(&request.module)
                    .trim_matches('"')
                    .trim_matches('\'')
                    .trim_end_matches(';'),
            );
            let resolution = if target.is_some() {
                Resolution::Internal
            } else if module.starts_with("./")
                || module.starts_with("../")
                || self.aliases.is_internal_shape(module, &request.source_path)
            {
                Resolution::Unresolved
            } else {
                Resolution::External
            };
            return Ok(ImportResolution { target, resolution });
        }
        Err(ImportError::Pending("language policies and classification"))
    }
}
