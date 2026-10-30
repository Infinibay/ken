//! One selected, lazy project encoder; model selection and inference stay separate.
mod selection;
use crate::{DocumentEncoder, Result, RetrievalError, query_encoder::QueryEncoder};
use ken_models::{EncoderFamily, ManagedEncoder, ModelFactory, TransformerSettings};
use ken_text::PythonText;
pub use selection::{configure_project, resolve_project};
use std::sync::{Arc, Mutex};
/// Raw process inputs are parsed only when their selected backend consumes them.
#[derive(Clone, Debug, Default)]
pub struct TransformerOverrides {
    pub sequence_length: Option<String>,
    pub batch_size: Option<String>,
}
impl TransformerOverrides {
    fn settings(&self) -> Result<TransformerSettings> {
        let parse = |name: &str, value: &Option<String>| {
            value
                .as_ref()
                .map(|value| {
                    value
                        .trim()
                        .parse::<usize>()
                        .ok()
                        .filter(|n| *n > 0)
                        .ok_or_else(|| {
                            RetrievalError::Invalid(format!("{name} must be a positive integer"))
                        })
                })
                .transpose()
        };
        Ok(TransformerSettings {
            dtype: None,
            sequence_length: parse("KEN_EMBED_MAX_SEQ", &self.sequence_length)?,
            batch_size: parse("KEN_EMBED_BATCH", &self.batch_size)?,
        })
    }
    fn present(&self) -> bool {
        self.sequence_length.is_some() || self.batch_size.is_some()
    }
}
pub struct ProjectEmbeddings {
    factory: Arc<ModelFactory>,
    model: String,
    overrides: TransformerOverrides,
    owner: Mutex<Option<Arc<ManagedEncoder>>>,
}
impl ProjectEmbeddings {
    /// The caller has already resolved the project's model with ModelPolicy.
    /// This constructor performs no filesystem, environment or model work.
    pub fn new(
        factory: Arc<ModelFactory>,
        model: impl Into<String>,
        overrides: TransformerOverrides,
    ) -> Self {
        Self {
            factory,
            model: model.into(),
            overrides,
            owner: Mutex::new(None),
        }
    }
    pub fn model(&self) -> &str {
        &self.model
    }
    pub fn managed(&self) -> Result<Arc<ManagedEncoder>> {
        let mut slot = self
            .owner
            .lock()
            .map_err(|_| RetrievalError::Invalid("project encoder owner lock poisoned".into()))?;
        if let Some(owner) = slot.as_ref() {
            return Ok(owner.clone());
        }
        let mut owner = self.factory.legacy_encoder(&self.model)?;
        if self.overrides.present()
            && matches!(
                owner.family(),
                EncoderFamily::SentenceTransformer | EncoderFamily::Mlx
            )
        {
            owner = self
                .factory
                .legacy_encoder_with_settings(&self.model, &self.overrides.settings()?)?;
        }
        *slot = Some(owner.clone());
        Ok(owner)
    }
}
impl QueryEncoder for ProjectEmbeddings {
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>> {
        let text = text.to_utf8().ok_or_else(|| {
            RetrievalError::Invalid("query contains non-scalar Unicode for this encoder".into())
        })?;
        Ok(self.managed()?.embed_query(&text)?)
    }
}
impl DocumentEncoder for ProjectEmbeddings {
    fn dim(&self) -> Result<usize> {
        Ok(self.managed()?.dim()?)
    }
    fn token_count(&self, text: &str) -> Result<usize> {
        Ok(self.managed()?.token_count(text)?)
    }
    fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        if texts.is_empty() {
            return Ok(vec![]);
        }
        Ok(self.managed()?.embed_passages(texts)?)
    }
}
