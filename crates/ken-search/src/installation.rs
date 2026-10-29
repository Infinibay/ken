//! Resolve an explicit deployment and defer model resources until general search.
use crate::{
    BestSearch, RegisteredSearchResources, Result, SearchResourceProvider, SearchResources,
};
use ken_models::{
    AcquisitionPolicy, ArtifactCache, LegacyRuntimeIdentity, ModelCatalog, ModelError,
    ModelFactory, NativeOnnxRuntime, NativeTranslationRuntime, PreparedModelResources,
};
use ken_retrieval::{RetrievalError, rank_models::ProductionRankModels};
use ken_syntax::{GrammarCatalog, ParseError};
use serde::Deserialize;
use serde_json::Value;
use std::{
    cell::RefCell,
    collections::BTreeMap,
    fs::File,
    io::{self, Read},
    path::{Path, PathBuf},
    rc::Rc,
    sync::Arc,
};

#[derive(Debug, thiserror::Error)]
pub enum InstallationError {
    #[error("cannot read native search installation {path}: {source}")]
    Io { path: PathBuf, source: io::Error },
    #[error("invalid native search installation: {0}")]
    Invalid(String),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Model(#[from] ModelError),
    #[error(transparent)]
    Grammar(#[from] ParseError),
}
#[derive(Deserialize)]
#[serde(rename_all = "lowercase")]
enum Acquisition {
    Offline,
    Public,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TranslationFiles {
    registration: Value,
    module_path: PathBuf,
    core_root: PathBuf,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    format: String,
    grammar_manifest: PathBuf,
    ranking_directory: PathBuf,
    private_parent: PathBuf,
    cache_parent: PathBuf,
    bundled_npz: PathBuf,
    sources: BTreeMap<String, PathBuf>,
    acquisition: Acquisition,
    legacy_runtime: Value,
    onnx_library: Option<PathBuf>,
    translation: Option<TranslationFiles>,
}

fn resolve(base: &Path, path: &Path) -> std::result::Result<PathBuf, InstallationError> {
    if path.as_os_str().is_empty() || path.as_os_str().as_encoded_bytes().contains(&0) {
        return Err(InstallationError::Invalid(
            "nonempty resource path required".into(),
        ));
    }
    Ok(base.join(path))
}

struct InstalledResources {
    resources: PreparedModelResources,
    cache: PathBuf,
    ranking: PathBuf,
    legacy: LegacyRuntimeIdentity,
    acquisition: AcquisitionPolicy,
    loaded: RefCell<Option<Rc<RegisteredSearchResources>>>,
}
impl SearchResourceProvider for InstalledResources {
    fn build(&self) -> Result<SearchResources> {
        let existing = self.loaded.borrow().clone();
        let provider = if let Some(provider) = existing {
            provider
        } else {
            let factory = Arc::new(ModelFactory::new(
                ModelCatalog::built_in().map_err(RetrievalError::from)?,
                ArtifactCache::new(&self.cache).map_err(RetrievalError::from)?,
                self.resources.clone(),
                self.acquisition,
            ));
            let provider = Rc::new(RegisteredSearchResources::new(
                factory,
                Arc::new(ProductionRankModels::open(&self.ranking)?),
                self.legacy.clone(),
            ));
            self.loaded.replace(Some(provider.clone()));
            provider
        };
        provider.build()
    }
}

/// An immutable resource declaration; opening it loads no models or native code.
pub struct SearchInstallation {
    grammars: Arc<GrammarCatalog>,
    resources: Rc<InstalledResources>,
}
impl SearchInstallation {
    /// Read only grammar configuration; syntax tools never prepare model assets.
    pub fn open_grammars(path: &Path) -> std::result::Result<GrammarCatalog, InstallationError> {
        #[derive(Deserialize)]
        struct GrammarManifest {
            format: String,
            grammar_manifest: PathBuf,
        }
        let (base, raw) = read_manifest(path)?;
        let manifest: GrammarManifest = serde_json::from_slice(&raw)?;
        if manifest.format != "ken-search-installation/1" {
            return Err(InstallationError::Invalid(
                "unsupported installation format".into(),
            ));
        }
        Ok(GrammarCatalog::prepared(&resolve(
            &base,
            &manifest.grammar_manifest,
        )?)?)
    }
    pub fn open(path: &Path) -> std::result::Result<Self, InstallationError> {
        let (base, raw) = read_manifest(path)?;
        let base = base.as_path();
        let manifest: Manifest = serde_json::from_slice(&raw)?;
        if manifest.format != "ken-search-installation/1" {
            return Err(InstallationError::Invalid(
                "unsupported installation format".into(),
            ));
        }
        let legacy = LegacyRuntimeIdentity::from_json(&manifest.legacy_runtime.to_string())?;
        let mut resources = PreparedModelResources::new(
            &resolve(base, &manifest.private_parent)?,
            &resolve(base, &manifest.bundled_npz)?,
        )?;
        for (model, path) in manifest.sources {
            resources
                .source_overrides
                .insert(model, resolve(base, &path)?);
        }
        if let Some(library) = manifest.onnx_library {
            resources.onnx = Some(NativeOnnxRuntime::from_json(
                include_str!("../../ken-models/resources/onnx-runtime-libraries.json"),
                &resolve(base, &library)?,
            )?);
        }
        if let Some(translation) = manifest.translation {
            resources.translation = Some(NativeTranslationRuntime::from_json(
                &translation.registration.to_string(),
                &resolve(base, &translation.module_path)?,
                &resolve(base, &translation.core_root)?,
            )?);
        }
        Ok(Self {
            grammars: Arc::new(GrammarCatalog::prepared(&resolve(
                base,
                &manifest.grammar_manifest,
            )?)?),
            resources: Rc::new(InstalledResources {
                resources,
                cache: resolve(base, &manifest.cache_parent)?,
                ranking: resolve(base, &manifest.ranking_directory)?,
                legacy,
                acquisition: match manifest.acquisition {
                    Acquisition::Offline => AcquisitionPolicy::Offline,
                    Acquisition::Public => AcquisitionPolicy::Public,
                },
                loaded: RefCell::new(None),
            }),
        })
    }

    pub fn into_search(self) -> BestSearch {
        BestSearch::new(self.grammars, self.resources)
    }
}
fn read_manifest(path: &Path) -> std::result::Result<(PathBuf, Vec<u8>), InstallationError> {
    let io_error = |source| InstallationError::Io {
        path: path.into(),
        source,
    };
    let canonical = path.canonicalize().map_err(io_error)?;
    let base = canonical
        .parent()
        .ok_or_else(|| InstallationError::Invalid("installation directory required".into()))?
        .to_path_buf();
    let mut raw = Vec::new();
    File::open(&canonical)
        .map_err(io_error)?
        .take(1024 * 1024 + 1)
        .read_to_end(&mut raw)
        .map_err(io_error)?;
    if raw.len() > 1024 * 1024 {
        return Err(InstallationError::Invalid("manifest exceeds1MiB".into()));
    }
    Ok((base, raw))
}
