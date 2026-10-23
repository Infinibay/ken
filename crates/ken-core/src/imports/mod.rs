//! Resolve indexed import edges from explicit ordered project inputs.
mod aliases;
mod classification;
mod config;
mod languages;
mod paths;
mod project_inputs;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use thiserror::Error;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
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
    #[error("invalid import config {path}: {reason}")]
    Config { path: String, reason: String },
}

pub struct ImportCatalog {
    files: BTreeSet<String>,
    python_suffixes: BTreeMap<String, Vec<String>>,
    aliases: aliases::AliasResolver,
    languages: languages::LanguageModules,
}
impl ImportCatalog {
    pub fn from_inputs(
        files: Vec<String>,
        configs: Option<BTreeMap<String, Vec<u8>>>,
    ) -> Result<Self, ImportError> {
        let aliases = if let Some(configs) = &configs {
            aliases::AliasResolver::from_inputs(&files, configs)?
        } else {
            aliases::AliasResolver::default()
        };
        Self::prepared(files, configs.as_ref(), aliases)
    }
    pub fn from_project(
        root: Option<&std::path::Path>,
        files: Vec<String>,
    ) -> Result<Self, ImportError> {
        let Some(root) = root else {
            return Self::from_inputs(files, None);
        };
        let inputs = project_inputs::ProjectImportInputs::read(root, &files)?;
        Self::prepared(files, Some(&inputs.bytes), inputs.aliases)
    }
    fn prepared(
        files: Vec<String>,
        configs: Option<&BTreeMap<String, Vec<u8>>>,
        aliases: aliases::AliasResolver,
    ) -> Result<Self, ImportError> {
        let python_suffixes = paths::python_suffixes(&files);
        let languages = languages::LanguageModules::from_inputs(&files, configs)?;
        Ok(Self {
            files: files.into_iter().collect(),
            python_suffixes,
            aliases,
            languages,
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
        let mut target = None;
        if matches!(
            request.language.as_deref(),
            Some("typescript" | "javascript")
        ) {
            target = self
                .aliases
                .resolve(&request.module, &request.source_path, &self.files);
        }
        if target.is_none() {
            target = self.languages.resolve(
                &request.module,
                &request.source_path,
                request.language.as_deref(),
                &self.files,
            );
        }
        let resolution = if target.is_some() {
            Resolution::Internal
        } else {
            classification::classify(
                &request.module,
                request.language.as_deref(),
                &request.source_path,
                &self.aliases,
                &self.languages,
                &self.files,
            )
        };
        Ok(ImportResolution { target, resolution })
    }
}
