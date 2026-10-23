//! Resolve declared data and bound disk preparation, independently of inference.
use crate::{
    AcquisitionPolicy, ArtifactCache, ArtifactRequest, ArtifactTransport, FastEmbedDeviceRequest,
    ModelAssets, ModelError, NativeOnnxRuntime, NativeTransformerRuntime, PublicModelTransport,
    TransformerDeviceRequest,
};
use std::{
    collections::BTreeMap,
    io::Read,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
};

#[derive(Clone)]
pub struct PreparedModelResources {
    pub private_parent: PathBuf,
    pub bundled_npz: PathBuf,
    pub source_overrides: BTreeMap<String, PathBuf>,
    pub onnx: Option<NativeOnnxRuntime>,
    pub torch: Option<NativeTransformerRuntime>,
    pub mlx: Option<NativeTransformerRuntime>,
    pub fastembed_device: FastEmbedDeviceRequest,
    pub transformer_device: TransformerDeviceRequest,
}
impl PreparedModelResources {
    pub(crate) fn validate_paths(&self) -> Result<(), ModelError> {
        if !self.private_parent.is_absolute()
            || !self.bundled_npz.is_absolute()
            || self.source_overrides.values().any(|p| !p.is_absolute())
        {
            return Err(crate::profile::invalid(
                "absolute prepared model resource paths required",
            ));
        }
        Ok(())
    }
    pub fn new(private_parent: &Path, bundled_npz: &Path) -> Result<Self, ModelError> {
        if !private_parent.is_absolute() || !bundled_npz.is_absolute() {
            return Err(crate::profile::invalid(
                "absolute prepared model resource paths required",
            ));
        }
        Ok(Self {
            private_parent: private_parent.into(),
            bundled_npz: bundled_npz.into(),
            source_overrides: BTreeMap::new(),
            onnx: None,
            torch: None,
            mlx: None,
            fastembed_device: FastEmbedDeviceRequest::from_inputs(None, None),
            transformer_device: TransformerDeviceRequest::Auto,
        })
    }
}

pub(crate) trait SnapshotProvider: Send + Sync {
    fn snapshot(&self, assets: &ModelAssets) -> Result<PathBuf, ModelError>;
}

struct LazyPublic(Mutex<Option<PublicModelTransport>>);
impl ArtifactTransport for LazyPublic {
    fn open(&self, request: &ArtifactRequest) -> Result<Box<dyn Read + Send>, ModelError> {
        let mut client = self
            .0
            .lock()
            .map_err(|_| crate::profile::invalid("model transport lock poisoned"))?;
        if client.is_none() {
            *client = Some(PublicModelTransport::new()?);
        }
        client
            .as_ref()
            .ok_or_else(|| crate::profile::invalid("public model client absent"))?
            .open(request)
    }
}
struct Offline;
impl ArtifactTransport for Offline {
    fn open(&self, _: &ArtifactRequest) -> Result<Box<dyn Read + Send>, ModelError> {
        Err(crate::profile::invalid(
            "offline model transport must not be invoked",
        ))
    }
}

pub(crate) struct ModelSources {
    pub(crate) resources: PreparedModelResources,
    cache: ArtifactCache,
    policy: AcquisitionPolicy,
    transport: Arc<dyn ArtifactTransport>,
}
impl ModelSources {
    pub(crate) fn new(
        cache: ArtifactCache,
        resources: PreparedModelResources,
        policy: AcquisitionPolicy,
    ) -> Self {
        let transport: Arc<dyn ArtifactTransport> = match policy {
            AcquisitionPolicy::Offline => Arc::new(Offline),
            AcquisitionPolicy::Public => Arc::new(LazyPublic(Mutex::new(None))),
        };
        Self {
            resources,
            cache,
            policy,
            transport,
        }
    }

    pub(crate) fn source(
        &self,
        assets: &ModelAssets,
    ) -> Result<crate::ModelFileSource, ModelError> {
        self.resources.validate_paths()?;
        let snapshot = self.snapshot(assets)?;
        std::fs::create_dir_all(&self.resources.private_parent).map_err(|source| {
            ModelError::Io {
                artifact: "private model parent".into(),
                source,
            }
        })?;
        crate::ModelFileSource::new(&snapshot, &self.resources.private_parent)
    }

    pub(crate) fn private_capacity(
        &self,
        assets: &ModelAssets,
        runtime_bytes: u64,
    ) -> Result<(), ModelError> {
        self.require_capacity(&[asset_bytes(assets)?, runtime_bytes])
    }

    fn require_capacity(&self, parts: &[u64]) -> Result<(), ModelError> {
        let required = parts
            .iter()
            .try_fold(3 * 1024 * 1024 * 1024_u64, |total, bytes| {
                total.checked_add(*bytes)
            })
            .ok_or_else(|| crate::profile::invalid("model preparation capacity overflow"))?;
        self.cache.ensure_capacity(required)
    }

    pub(crate) fn complete_capacity(
        &self,
        assets: &ModelAssets,
        private_bytes: u64,
        runtime_bytes: u64,
    ) -> Result<(), ModelError> {
        self.require_capacity(&[asset_bytes(assets)?, private_bytes, runtime_bytes])
    }

    pub(crate) fn preparation_provider(
        self: &Arc<Self>,
        private_bytes: u64,
        runtime_bytes: u64,
    ) -> Arc<dyn SnapshotProvider> {
        Arc::new(PreparationProvider {
            sources: self.clone(),
            private_bytes,
            runtime_bytes,
        })
    }
}
impl SnapshotProvider for ModelSources {
    fn snapshot(&self, assets: &ModelAssets) -> Result<PathBuf, ModelError> {
        if let Some(path) = self.resources.source_overrides.get(assets.model_id()) {
            if !path.is_absolute() {
                return Err(crate::profile::invalid(
                    "absolute borrowed model source required",
                ));
            }
            assets.validate_snapshot(path)?;
            return Ok(path.clone());
        }
        // Only source data belongs here. The preparing adapter separately
        // reserves its own weights/derived files and selected native core.
        if self.policy == AcquisitionPolicy::Public && !self.cache.contains_snapshot(assets)? {
            self.require_capacity(&[asset_bytes(assets)?])?;
        }
        self.cache
            .resolve(assets, self.policy, self.transport.as_ref())
    }
}

pub(crate) fn asset_bytes(assets: &ModelAssets) -> Result<u64, ModelError> {
    assets
        .artifact_records()
        .values()
        .try_fold(0_u64, |total, record| total.checked_add(record.bytes))
        .ok_or_else(|| crate::profile::invalid("registered model footprint overflow"))
}

struct PreparationProvider {
    sources: Arc<ModelSources>,
    private_bytes: u64,
    runtime_bytes: u64,
}
impl SnapshotProvider for PreparationProvider {
    fn snapshot(&self, assets: &ModelAssets) -> Result<PathBuf, ModelError> {
        self.sources.resources.validate_paths()?;
        self.sources
            .complete_capacity(assets, self.private_bytes, self.runtime_bytes)?;
        self.sources.snapshot(assets)
    }
}

pub(crate) enum TransformerSource {
    Borrowed(crate::ModelFileSource),
    Deferred {
        provider: Arc<dyn SnapshotProvider>,
        private_parent: PathBuf,
    },
}
impl TransformerSource {
    pub(crate) fn resolve(
        &self,
        assets: &ModelAssets,
    ) -> Result<crate::ModelFileSource, ModelError> {
        match self {
            Self::Borrowed(source) => Ok(source.clone()),
            Self::Deferred {
                provider,
                private_parent,
            } => {
                if !private_parent.is_absolute() {
                    return Err(crate::profile::invalid(
                        "absolute private model parent required",
                    ));
                }
                let snapshot = provider.snapshot(assets)?;
                std::fs::create_dir_all(private_parent).map_err(|source| ModelError::Io {
                    artifact: "private model parent".into(),
                    source,
                })?;
                crate::ModelFileSource::new(&snapshot, private_parent)
            }
        }
    }
}

/// Preserve original eager borrowed-source construction while enabling a factory
/// to obtain data only when the concrete role actually needs preparation.
pub(crate) enum PreparationSource {
    Borrowed(Option<PathBuf>),
    Deferred(Arc<dyn SnapshotProvider>),
}

impl PreparationSource {
    pub(crate) fn for_preparation(
        &self,
        assets: &ModelAssets,
        ready: &Path,
    ) -> Result<Option<PathBuf>, ModelError> {
        match self {
            Self::Borrowed(path) => Ok(path.clone()),
            Self::Deferred(_) if ready.exists() => Ok(None),
            Self::Deferred(provider) => provider.snapshot(assets).map(Some),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::{
        io::Cursor,
        sync::atomic::{AtomicUsize, Ordering},
    };

    struct Transport(AtomicUsize);
    impl ArtifactTransport for Transport {
        fn open(&self, _: &ArtifactRequest) -> Result<Box<dyn Read + Send>, ModelError> {
            self.0.fetch_add(1, Ordering::SeqCst);
            Ok(Box::new(Cursor::new(b"abc".to_vec())))
        }
    }
    fn assets(bytes: u64) -> ModelAssets {
        ModelAssets::from_json(&json!({"model_id":"test/data","revision":"a".repeat(40),"artifacts":{
            "data":{"bytes":bytes,"sha256":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}
        }}).to_string()).unwrap()
    }
    fn sources(root: &Path) -> (ModelSources, Arc<Transport>) {
        let transport = Arc::new(Transport(AtomicUsize::new(0)));
        let resources =
            PreparedModelResources::new(&root.join("owned"), &root.join("table.npz")).unwrap();
        (
            ModelSources {
                resources,
                cache: ArtifactCache::new(&root.join("cache")).unwrap(),
                policy: AcquisitionPolicy::Public,
                transport: transport.clone(),
            },
            transport,
        )
    }

    #[test]
    fn acquiring_data_never_depends_on_an_unselected_optional_core() {
        let root = tempfile::tempdir().unwrap();
        let (mut sources, transport) = sources(root.path());
        let declaration = json!({"format":"ken-native-transformer/1","backend":"torch","runtimes":[{
            "os":std::env::consts::OS,"arch":std::env::consts::ARCH,"core_version":"2.9.0",
            "module":{"bytes":u64::MAX-1,"sha256":"0".repeat(64)},"libraries":{"lib/core":{"bytes":2,"sha256":"0".repeat(64)}}
        }]});
        sources.resources.torch = Some(
            NativeTransformerRuntime::from_json(
                &declaration.to_string(),
                &root.path().join("absent-module"),
                &root.path().join("absent-core"),
            )
            .unwrap(),
        );
        let snapshot = sources.snapshot(&assets(3)).unwrap();
        assert_eq!(std::fs::read(snapshot.join("data")).unwrap(), b"abc");
        assert_eq!(sources.snapshot(&assets(3)).unwrap(), snapshot);
        assert_eq!(transport.0.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn overflow_and_unavailable_disk_budget_fail_before_opening_any_stream() {
        let root = tempfile::tempdir().unwrap();
        let (sources, transport) = sources(root.path());
        assert!(sources.snapshot(&assets(u64::MAX)).is_err());
        let provider = Arc::new(sources).preparation_provider(u64::MAX, 0);
        assert!(provider.snapshot(&assets(3)).is_err());
        assert_eq!(transport.0.load(Ordering::SeqCst), 0);
        assert!(!root.path().join("cache/models").exists());
    }

    #[test]
    fn a_relative_private_parent_is_rejected_before_network_or_directory_creation() {
        let root = tempfile::tempdir().unwrap();
        let (mut sources, transport) = sources(root.path());
        sources.resources.private_parent = PathBuf::from("../invalid-private-parent");
        assert!(sources.source(&assets(3)).is_err());
        assert_eq!(transport.0.load(Ordering::SeqCst), 0);
        assert!(!root.path().join("cache/models").exists());
    }
}
