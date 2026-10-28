//! One lazy adapter owner, preserving each family's established call semantics.
use crate::{
    EncoderFamily, FastEmbedEncoder, MLXEncoder, Model2VecEncoder, ModelError, SentenceEncoder,
    StaticTableEncoder, model_catalog::EncoderDefinition, model_sources::ModelSources,
};
use std::sync::{Arc, Mutex};

/// Read-only evidence of the adapter that actually completed preparation.
#[derive(Clone, Debug, serde::Serialize)]
#[serde(tag = "family", rename_all = "snake_case")]
pub enum EncoderPreparation {
    StaticTable {
        sha256: String,
    },
    Potion {
        assets_fingerprint: String,
    },
    FastEmbed {
        trace: crate::FastEmbedPreparation,
    },
    SentenceTransformer {
        trace: crate::TransformerPreparation,
    },
    Mlx {
        trace: crate::TransformerPreparation,
    },
}

enum Adapter {
    Static(StaticTableEncoder),
    Potion(Model2VecEncoder),
    FastEmbed(FastEmbedEncoder),
    Sentence(SentenceEncoder),
    Mlx(MLXEncoder),
}
impl Adapter {
    fn is_prepared(&self) -> Result<bool, ModelError> {
        match self {
            Self::Static(_) | Self::Potion(_) => Ok(true),
            Self::FastEmbed(encoder) => encoder.is_prepared(),
            Self::Sentence(encoder) => Ok(encoder.preparation()?.is_some()),
            Self::Mlx(encoder) => Ok(encoder.preparation()?.is_some()),
        }
    }
}

pub struct ManagedEncoder {
    definition: EncoderDefinition,
    sources: Arc<ModelSources>,
    adapter: Mutex<Option<Arc<Adapter>>>,
}

impl ManagedEncoder {
    pub(crate) fn new(definition: EncoderDefinition, sources: Arc<ModelSources>) -> Self {
        Self {
            definition,
            sources,
            adapter: Mutex::new(None),
        }
    }

    /// Registered feature identity of the prepared static model, distinct from
    /// the profile selecting its indexing adapter.
    pub fn registered_static_spec(
        &self,
        legacy: &crate::LegacyRuntimeIdentity,
    ) -> Result<crate::EncoderSpec, ModelError> {
        let EncoderDefinition::Potion(assets) = &self.definition else {
            return Err(crate::profile::invalid(
                "registered static identity requires a static model",
            ));
        };
        let adapter = self.adapter()?;
        let Adapter::Potion(encoder) = adapter.as_ref() else {
            return Err(crate::profile::invalid(
                "managed static definition/adapter mismatch",
            ));
        };
        encoder.registered_spec(assets, legacy)
    }
    pub fn family(&self) -> EncoderFamily {
        self.definition.family()
    }

    pub fn preparation(&self) -> Result<Option<EncoderPreparation>, ModelError> {
        let slot = self
            .adapter
            .lock()
            .map_err(|_| crate::profile::invalid("managed encoder lock poisoned"))?;
        let Some(adapter) = slot.as_ref() else {
            return Ok(None);
        };
        if !adapter.is_prepared()? {
            return Ok(None);
        }
        Ok(match (&self.definition, adapter.as_ref()) {
            (EncoderDefinition::Static(model), Adapter::Static(_)) => {
                Some(EncoderPreparation::StaticTable {
                    sha256: model.sha256.clone(),
                })
            }
            (EncoderDefinition::Potion(assets), Adapter::Potion(_)) => {
                Some(EncoderPreparation::Potion {
                    assets_fingerprint: assets.fingerprint(),
                })
            }
            (_, Adapter::FastEmbed(encoder)) => Some(EncoderPreparation::FastEmbed {
                trace: encoder.preparation()?,
            }),
            (_, Adapter::Sentence(encoder)) => encoder
                .preparation()?
                .map(|trace| EncoderPreparation::SentenceTransformer { trace }),
            (_, Adapter::Mlx(encoder)) => encoder
                .preparation()?
                .map(|trace| EncoderPreparation::Mlx { trace }),
            _ => {
                return Err(crate::profile::invalid(
                    "managed encoder definition/adapter mismatch",
                ));
            }
        })
    }

    pub fn is_prepared(&self) -> Result<bool, ModelError> {
        let slot = self
            .adapter
            .lock()
            .map_err(|_| crate::profile::invalid("managed encoder lock poisoned"))?;
        match slot.as_ref() {
            Some(adapter) => adapter.is_prepared(),
            None => Ok(false),
        }
    }

    fn adapter(&self) -> Result<Arc<Adapter>, ModelError> {
        let mut slot = self
            .adapter
            .lock()
            .map_err(|_| crate::profile::invalid("managed encoder lock poisoned"))?;
        if let Some(adapter) = slot.as_ref() {
            return Ok(adapter.clone());
        }
        let resources = &self.sources.resources;
        let adapter = match &self.definition {
            EncoderDefinition::Static(registered) => {
                let bytes = crate::verified_file::read(
                    &resources.bundled_npz,
                    registered.bytes,
                    &registered.sha256,
                )
                .map_err(|error| ModelError::Artifact(format!("bundled static table: {error}")))?;
                Adapter::Static(StaticTableEncoder::from_npz(&bytes)?)
            }
            EncoderDefinition::Potion(assets) => {
                use crate::model_sources::SnapshotProvider;
                let snapshot = assets.verify(&self.sources.snapshot(assets)?)?;
                Adapter::Potion(Model2VecEncoder::load(&snapshot)?)
            }
            EncoderDefinition::FastEmbed(model) => {
                let runtime = resources.onnx.clone().ok_or_else(|| {
                    crate::profile::invalid("explicit ONNX runtime preparation required")
                })?;
                let source = self.sources.source(model.assets())?;
                Adapter::FastEmbed(FastEmbedEncoder::new(
                    model.clone(),
                    source,
                    runtime,
                    resources.fastembed_device.clone(),
                )?)
            }
            EncoderDefinition::Sentence(model, settings) => {
                let runtime = resources.torch.clone().ok_or_else(|| {
                    crate::profile::invalid("explicit Torch runtime preparation required")
                })?;
                if runtime.backend() != "torch" {
                    return Err(crate::profile::invalid(
                        "Torch encoder requires the Torch runtime",
                    ));
                }
                let source = self.sources.source(model.assets())?;
                Adapter::Sentence(SentenceEncoder::new(
                    model.clone(),
                    source,
                    runtime,
                    settings.clone(),
                    resources.transformer_device,
                )?)
            }
            EncoderDefinition::Mlx(model, settings) => {
                let runtime = resources.mlx.clone().ok_or_else(|| {
                    crate::profile::invalid("explicit MLX runtime preparation required")
                })?;
                let source = self.sources.source(model.assets())?;
                Adapter::Mlx(MLXEncoder::new(
                    model.clone(),
                    source,
                    runtime,
                    settings.clone(),
                )?)
            }
        };
        let adapter = Arc::new(adapter);
        *slot = Some(adapter.clone());
        Ok(adapter)
    }

    fn preparation_capacity(&self, adapter: &Adapter) -> Result<(), ModelError> {
        if adapter.is_prepared()? {
            return Ok(());
        }
        let resources = &self.sources.resources;
        match &self.definition {
            EncoderDefinition::FastEmbed(model) => self.sources.private_capacity(
                model.assets(),
                resources
                    .onnx
                    .as_ref()
                    .map_or(0, |r| r.private_copy_bytes()),
            ),
            EncoderDefinition::Sentence(model, _) => self.sources.private_capacity(
                model.assets(),
                resources
                    .torch
                    .as_ref()
                    .map(|r| r.private_copy_bytes())
                    .transpose()?
                    .unwrap_or(0),
            ),
            EncoderDefinition::Mlx(model, _) => self.sources.private_capacity(
                model.assets(),
                resources
                    .mlx
                    .as_ref()
                    .map(|r| r.private_copy_bytes())
                    .transpose()?
                    .unwrap_or(0),
            ),
            _ => Ok(()),
        }
    }

    fn inference_adapter(&self) -> Result<Arc<Adapter>, ModelError> {
        let existing = self
            .adapter
            .lock()
            .map_err(|_| crate::profile::invalid("managed encoder lock poisoned"))?
            .clone();
        if let Some(adapter) = existing
            && adapter.is_prepared()?
        {
            return Ok(adapter);
        }
        let resources = &self.sources.resources;
        let request = match &self.definition {
            EncoderDefinition::FastEmbed(model) => {
                let runtime = resources.onnx.as_ref().ok_or_else(|| {
                    crate::profile::invalid("explicit ONNX runtime preparation required")
                })?;
                Some((model.assets(), runtime.private_copy_bytes()))
            }
            EncoderDefinition::Sentence(model, _) => {
                let runtime = resources.torch.as_ref().ok_or_else(|| {
                    crate::profile::invalid("explicit Torch runtime preparation required")
                })?;
                Some((model.assets(), runtime.private_copy_bytes()?))
            }
            EncoderDefinition::Mlx(model, _) => {
                let runtime = resources.mlx.as_ref().ok_or_else(|| {
                    crate::profile::invalid("explicit MLX runtime preparation required")
                })?;
                Some((model.assets(), runtime.private_copy_bytes()?))
            }
            _ => None,
        };
        if let Some((assets, core_bytes)) = request {
            self.sources.complete_capacity(
                assets,
                crate::model_sources::asset_bytes(assets)?,
                core_bytes,
            )?;
        }
        self.adapter()
    }

    pub fn dim(&self) -> Result<usize, ModelError> {
        if let EncoderDefinition::FastEmbed(model) = &self.definition {
            return Ok(model.dim());
        }
        let adapter = self.inference_adapter()?;
        self.preparation_capacity(&adapter)?;
        match adapter.as_ref() {
            Adapter::Static(encoder) => Ok(encoder.dim()),
            Adapter::Potion(encoder) => Ok(encoder.dim()),
            Adapter::FastEmbed(encoder) => Ok(encoder.dim()),
            Adapter::Sentence(encoder) => encoder.dim(),
            Adapter::Mlx(encoder) => encoder.dim(),
        }
    }

    pub fn token_count(&self, text: &str) -> Result<usize, ModelError> {
        if matches!(&self.definition, EncoderDefinition::FastEmbed(_)) {
            return Err(ModelError::Tokenizer(
                "legacy FastEmbed exposes no raw token-count contract".into(),
            ));
        }
        match self.adapter()?.as_ref() {
            Adapter::Static(encoder) => encoder.token_count(text),
            Adapter::Potion(encoder) => Ok(encoder.token_ids(text, None)?.len()),
            Adapter::Sentence(encoder) => encoder.token_count(text),
            Adapter::Mlx(encoder) => encoder.token_count(text),
            Adapter::FastEmbed(_) => unreachable!("FastEmbed handled before preparation"),
        }
    }

    pub fn embed_query(&self, text: &str) -> Result<Vec<f32>, ModelError> {
        let adapter = self.inference_adapter()?;
        self.preparation_capacity(&adapter)?;
        match adapter.as_ref() {
            Adapter::Static(encoder) => encoder.embed_query(text),
            Adapter::Potion(encoder) => encoder.embed_query(text),
            Adapter::FastEmbed(encoder) => Ok(encoder.embed_queries(&[text])?.remove(0)),
            Adapter::Sentence(encoder) => encoder.embed_query(text),
            Adapter::Mlx(encoder) => encoder.embed_query(text),
        }
    }

    pub fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, ModelError> {
        if texts.is_empty() {
            return Ok(vec![]);
        }
        let adapter = self.inference_adapter()?;
        self.preparation_capacity(&adapter)?;
        match adapter.as_ref() {
            Adapter::Static(encoder) => encoder.embed_passages(texts),
            Adapter::Potion(encoder) => {
                encoder.embed_passages(&texts.iter().map(|s| s.to_string()).collect::<Vec<_>>())
            }
            Adapter::FastEmbed(encoder) => encoder.embed_passages(texts),
            Adapter::Sentence(encoder) => encoder.embed_passages(texts),
            Adapter::Mlx(encoder) => encoder.embed_passages(texts),
        }
    }
}
