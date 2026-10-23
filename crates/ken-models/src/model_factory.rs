//! Coordinate catalog selection and four shared owners; adapters own execution.
use crate::{
    AcquisitionPolicy, ArtifactCache, ContextEncoder, EncoderBackend, EncoderSpec,
    LegacyRuntimeIdentity, LocalQueryExpansion, ManagedEncoder, ModelCatalog, ModelError,
    OnnxReranker, PreparedModelResources, RelevanceJudge, RerankOptions, TransformerDeviceRequest,
    TransformerSettings, model_sources::ModelSources,
};
use std::{
    collections::VecDeque,
    sync::{Arc, Mutex},
};

#[derive(Clone)]
enum Cached {
    Encoder(Arc<ManagedEncoder>),
    Judge(Arc<RelevanceJudge>),
    Context(Arc<ContextEncoder>),
    Reranker(Arc<OnnxReranker>),
    Expansion(Arc<LocalQueryExpansion>),
}

pub struct ModelFactory {
    catalog: ModelCatalog,
    sources: Arc<ModelSources>,
    owners: Mutex<VecDeque<(String, Cached)>>,
}

impl ModelFactory {
    pub fn new(
        catalog: ModelCatalog,
        cache: ArtifactCache,
        resources: PreparedModelResources,
        policy: AcquisitionPolicy,
    ) -> Self {
        Self {
            catalog,
            sources: Arc::new(ModelSources::new(cache, resources, policy)),
            owners: Mutex::new(VecDeque::new()),
        }
    }

    fn cached(
        &self,
        key: String,
        build: impl FnOnce() -> Result<Cached, ModelError>,
    ) -> Result<Cached, ModelError> {
        self.sources.resources.validate_paths()?;
        let mut owners = self
            .owners
            .lock()
            .map_err(|_| crate::profile::invalid("factory owner lock poisoned"))?;
        if let Some(index) = owners.iter().position(|(name, _)| name == &key) {
            let found = owners
                .remove(index)
                .ok_or_else(|| crate::profile::invalid("factory cache entry disappeared"))?;
            let value = found.1.clone();
            owners.push_back(found);
            return Ok(value);
        }
        let value = build()?;
        owners.push_back((key, value.clone()));
        while owners.len() > 4 {
            owners.pop_front();
        }
        Ok(value)
    }

    fn profile_key(
        role: &str,
        spec: &EncoderSpec,
        legacy: &LegacyRuntimeIdentity,
    ) -> Result<String, ModelError> {
        // The resource context is immutable and private to this factory. No
        // owner is shared with another factory's source overrides or SDK paths.
        Ok(format!(
            "{role}:{}",
            crate::assets::python_json(&serde_json::json!({"spec":spec,"legacy":legacy}))
        ))
    }

    pub fn encoder(
        &self,
        spec: &EncoderSpec,
        legacy: &LegacyRuntimeIdentity,
    ) -> Result<Arc<ManagedEncoder>, ModelError> {
        let definition = self.catalog.encoder(spec, legacy)?;
        match self.cached(Self::profile_key("encoder", spec, legacy)?, || {
            Ok(Cached::Encoder(Arc::new(ManagedEncoder::new(
                definition,
                self.sources.clone(),
            ))))
        })? {
            Cached::Encoder(owner) => Ok(owner),
            _ => Err(crate::profile::invalid(
                "factory encoder cache kind mismatch",
            )),
        }
    }

    pub fn legacy_encoder(&self, name: &str) -> Result<Arc<ManagedEncoder>, ModelError> {
        let definition = self.catalog.legacy_encoder(name)?;
        match self.cached(format!("legacy:{name}"), || {
            Ok(Cached::Encoder(Arc::new(ManagedEncoder::new(
                definition,
                self.sources.clone(),
            ))))
        })? {
            Cached::Encoder(owner) => Ok(owner),
            _ => Err(crate::profile::invalid(
                "factory legacy cache kind mismatch",
            )),
        }
    }

    pub fn judge(
        &self,
        spec: &EncoderSpec,
        legacy: &LegacyRuntimeIdentity,
    ) -> Result<Arc<RelevanceJudge>, ModelError> {
        let model = self.catalog.judge(spec, legacy)?;
        match self.cached(Self::profile_key("judge", spec, legacy)?, || {
            let resources = &self.sources.resources;
            let (runtime, device) = if spec.backend == EncoderBackend::Mlx {
                (resources.mlx.clone(), TransformerDeviceRequest::Mps)
            } else {
                (resources.torch.clone(), resources.transformer_device)
            };
            let runtime = runtime.ok_or_else(|| {
                crate::profile::invalid("explicit judge runtime preparation required")
            })?;
            let backend = if spec.backend == EncoderBackend::Mlx {
                "mlx"
            } else {
                "torch"
            };
            if runtime.backend() != backend {
                return Err(crate::profile::invalid(
                    "judge runtime backend differs from selected profile",
                ));
            }
            let provider = self.sources.preparation_provider(
                crate::model_sources::asset_bytes(model.assets())?,
                runtime.private_copy_bytes()?,
            );
            let settings = TransformerSettings {
                dtype: Some(spec.dtype),
                sequence_length: Some(spec.sequence_length),
                batch_size: Some(spec.batch_size),
            };
            Ok(Cached::Judge(Arc::new(
                RelevanceJudge::with_source_provider(
                    model,
                    provider,
                    resources.private_parent.clone(),
                    runtime,
                    settings,
                    device,
                )?,
            )))
        })? {
            Cached::Judge(owner) => Ok(owner),
            _ => Err(crate::profile::invalid("factory judge cache kind mismatch")),
        }
    }

    pub fn context(&self) -> Result<Arc<ContextEncoder>, ModelError> {
        match self.cached("role:context".into(), || {
            let runtime =
                self.sources.resources.onnx.clone().ok_or_else(|| {
                    crate::profile::invalid("explicit context ONNX runtime required")
                })?;
            let model = self.catalog.context.clone();
            let provider = self
                .sources
                .preparation_provider(0, runtime.private_copy_bytes());
            Ok(Cached::Context(Arc::new(
                ContextEncoder::with_source_provider(model, provider, runtime),
            )))
        })? {
            Cached::Context(owner) => Ok(owner),
            _ => Err(crate::profile::invalid(
                "factory context cache kind mismatch",
            )),
        }
    }

    pub fn reranker(&self) -> Result<Arc<OnnxReranker>, ModelError> {
        match self.cached("role:reranker".into(), || {
            let runtime = self.sources.resources.onnx.clone().ok_or_else(|| {
                crate::profile::invalid("explicit reranker ONNX runtime required")
            })?;
            let model = self.catalog.reranker.clone();
            let cache = model.cache_path(&self.sources.resources.private_parent);
            let provider = self.sources.preparation_provider(
                crate::model_sources::asset_bytes(&model.prepared_assets())?,
                runtime.private_copy_bytes(),
            );
            Ok(Cached::Reranker(Arc::new(
                OnnxReranker::with_source_provider(
                    model,
                    provider,
                    cache,
                    runtime,
                    RerankOptions::default(),
                )?,
            )))
        })? {
            Cached::Reranker(owner) => Ok(owner),
            _ => Err(crate::profile::invalid(
                "factory reranker cache kind mismatch",
            )),
        }
    }

    pub fn expansion(&self) -> Result<Arc<LocalQueryExpansion>, ModelError> {
        match self.cached("role:expansion".into(), || {
            let model = self.catalog.translation.clone();
            let cache = model.cache_path(&self.sources.resources.private_parent);
            let provider = self.sources.preparation_provider(
                crate::model_sources::asset_bytes(&model.prepared_assets())?,
                0,
            );
            Ok(Cached::Expansion(Arc::new(
                LocalQueryExpansion::with_source_provider(model, provider, cache)?,
            )))
        })? {
            Cached::Expansion(owner) => Ok(owner),
            _ => Err(crate::profile::invalid(
                "factory expansion cache kind mismatch",
            )),
        }
    }
}
