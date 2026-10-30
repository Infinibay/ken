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
struct CatalogueFile {
    path: PathBuf,
    bytes: u64,
    sha256: String,
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
    #[serde(default)]
    torch: Option<TranslationFiles>,
    #[serde(default)]
    catalogue_extensions: Option<CatalogueFile>,
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
    catalogue_extensions: Option<ken_models::CatalogExtensions>,
    factory: RefCell<Option<Arc<ModelFactory>>>,
    loaded: RefCell<Option<Rc<RegisteredSearchResources>>>,
}
impl InstalledResources {
    fn factory(&self) -> std::result::Result<Arc<ModelFactory>, ModelError> {
        if let Some(factory) = self.factory.borrow().as_ref() {
            return Ok(factory.clone());
        }
        let factory = Arc::new(ModelFactory::new(
            compose_catalogue(self.catalogue_extensions.clone())?,
            ArtifactCache::new(&self.cache)?,
            self.resources.clone(),
            self.acquisition,
        ));
        self.factory.replace(Some(factory.clone()));
        Ok(factory)
    }
}
impl SearchResourceProvider for InstalledResources {
    fn build(&self) -> Result<SearchResources> {
        let existing = self.loaded.borrow().clone();
        let provider = if let Some(provider) = existing {
            provider
        } else {
            let factory = self.factory().map_err(RetrievalError::from)?;
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
    /// Read authenticated catalogue metadata without preparing source assets,
    /// optional runtimes, grammars, ranking data, or writable model caches.
    pub fn model_catalog(path: &Path) -> std::result::Result<ModelCatalog, InstallationError> {
        let (base, raw) = read_manifest(path)?;
        let manifest: Manifest = serde_json::from_slice(&raw)?;
        if manifest.format != "ken-search-installation/1" {
            return Err(InstallationError::Invalid(
                "unsupported installation format".into(),
            ));
        }
        Ok(compose_catalogue(read_catalogue(&base, &manifest)?)?)
    }

    /// Open only the declared model owner. This path does not read grammars,
    /// ranking trees, or prepare optional search roles and their native cores.
    pub fn open_model_factory(
        path: &Path,
    ) -> std::result::Result<Arc<ModelFactory>, InstallationError> {
        Self::open_model_factory_with_devices(
            path,
            ken_models::FastEmbedDeviceRequest::from_inputs(None, None),
            ken_models::TransformerDeviceRequest::Auto,
        )
    }

    /// Hosts pass their captured device policy without preparing model assets.
    pub fn open_model_factory_with_devices(
        path: &Path,
        fastembed: ken_models::FastEmbedDeviceRequest,
        transformer: ken_models::TransformerDeviceRequest,
    ) -> std::result::Result<Arc<ModelFactory>, InstallationError> {
        let (base, raw) = read_manifest(path)?;
        let manifest: Manifest = serde_json::from_slice(&raw)?;
        if manifest.format != "ken-search-installation/1" {
            return Err(InstallationError::Invalid(
                "unsupported installation format".into(),
            ));
        }
        let mut resources = prepared_resources(&base, &manifest)?;
        resources.fastembed_device = fastembed;
        resources.transformer_device = transformer;
        Ok(Arc::new(ModelFactory::new(
            compose_catalogue(read_catalogue(&base, &manifest)?)?,
            ArtifactCache::new(&resolve(&base, &manifest.cache_parent)?)?,
            resources,
            match manifest.acquisition {
                Acquisition::Offline => AcquisitionPolicy::Offline,
                Acquisition::Public => AcquisitionPolicy::Public,
            },
        )))
    }

    pub fn model_factory(&self) -> std::result::Result<Arc<ModelFactory>, InstallationError> {
        Ok(self.resources.factory()?)
    }

    pub fn legacy_runtime(&self) -> LegacyRuntimeIdentity {
        self.resources.legacy.clone()
    }

    pub fn grammars(&self) -> Arc<GrammarCatalog> {
        self.grammars.clone()
    }

    /// Resolve only the immutable ranking declaration without loading assets.
    pub fn ranking_directory(path: &Path) -> std::result::Result<PathBuf, InstallationError> {
        #[derive(Deserialize)]
        struct RankingManifest {
            format: String,
            ranking_directory: PathBuf,
        }
        let (base, raw) = read_manifest(path)?;
        let manifest: RankingManifest = serde_json::from_slice(&raw)?;
        if manifest.format != "ken-search-installation/1" {
            return Err(InstallationError::Invalid(
                "unsupported installation format".into(),
            ));
        }
        resolve(&base, &manifest.ranking_directory)
    }

    pub fn declared_legacy_runtime(
        path: &Path,
    ) -> std::result::Result<LegacyRuntimeIdentity, InstallationError> {
        #[derive(Deserialize)]
        struct RuntimeManifest {
            format: String,
            legacy_runtime: Value,
        }
        let (_, raw) = read_manifest(path)?;
        let manifest: RuntimeManifest = serde_json::from_slice(&raw)?;
        if manifest.format != "ken-search-installation/1" {
            return Err(InstallationError::Invalid(
                "unsupported installation format".into(),
            ));
        }
        Ok(LegacyRuntimeIdentity::from_json(
            &manifest.legacy_runtime.to_string(),
        )?)
    }

    /// Resolve only the grammar declaration; no model declarations are needed.
    pub fn grammar_manifest(path: &Path) -> std::result::Result<PathBuf, InstallationError> {
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
        resolve(&base, &manifest.grammar_manifest)
    }
    /// Read only grammar configuration; syntax tools never prepare model assets.
    pub fn open_grammars(path: &Path) -> std::result::Result<GrammarCatalog, InstallationError> {
        Ok(GrammarCatalog::prepared(&Self::grammar_manifest(path)?)?)
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
        let resources = prepared_resources(base, &manifest)?;
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
                catalogue_extensions: read_catalogue(base, &manifest)?,
                acquisition: match manifest.acquisition {
                    Acquisition::Offline => AcquisitionPolicy::Offline,
                    Acquisition::Public => AcquisitionPolicy::Public,
                },
                factory: RefCell::new(None),
                loaded: RefCell::new(None),
            }),
        })
    }

    pub fn into_search(self) -> BestSearch {
        BestSearch::new(self.grammars, self.resources)
    }
}
fn prepared_resources(
    base: &Path,
    manifest: &Manifest,
) -> std::result::Result<PreparedModelResources, InstallationError> {
    let mut resources = PreparedModelResources::new(
        &resolve(base, &manifest.private_parent)?,
        &resolve(base, &manifest.bundled_npz)?,
    )?;
    for (model, path) in &manifest.sources {
        resources
            .source_overrides
            .insert(model.clone(), resolve(base, path)?);
    }
    if let Some(library) = &manifest.onnx_library {
        resources.onnx = Some(NativeOnnxRuntime::from_json(
            include_str!("../../ken-models/resources/onnx-runtime-libraries.json"),
            &resolve(base, library)?,
        )?);
    }
    if let Some(translation) = &manifest.translation {
        resources.translation = Some(NativeTranslationRuntime::from_json(
            &translation.registration.to_string(),
            &resolve(base, &translation.module_path)?,
            &resolve(base, &translation.core_root)?,
        )?);
    }
    if let Some(torch) = &manifest.torch {
        resources.torch = Some(ken_models::NativeTransformerRuntime::from_json(
            &torch.registration.to_string(),
            &resolve(base, &torch.module_path)?,
            &resolve(base, &torch.core_root)?,
        )?);
    }
    Ok(resources)
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

fn compose_catalogue(
    extension: Option<ken_models::CatalogExtensions>,
) -> std::result::Result<ModelCatalog, ModelError> {
    let catalog = ModelCatalog::built_in()?;
    match extension {
        Some(extension) => catalog.with_extensions(extension),
        None => Ok(catalog),
    }
}
fn read_catalogue(
    base: &Path,
    manifest: &Manifest,
) -> std::result::Result<Option<ken_models::CatalogExtensions>, InstallationError> {
    manifest
        .catalogue_extensions
        .as_ref()
        .map(|declared| {
            Ok(ken_models::CatalogExtensions::from_file(
                &resolve(base, &declared.path)?,
                declared.bytes,
                &declared.sha256,
            )?)
        })
        .transpose()
}
