//! One registered owner supplies both sentence and individual term vectors.
use crate::{
    Result, RetrievalError,
    query_encoder::{ManagedQueryEncoder, QueryEncoder},
};
use ken_models::{EncoderSpec, ManagedEncoder};
use ken_text::PythonText;
use std::sync::Arc;
pub trait WordEncoder {
    fn spec(&self) -> &EncoderSpec;
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>>;
    fn embed_passages(&self, texts: &[PythonText]) -> Result<Vec<Vec<f32>>>;
}
pub struct ManagedWordEncoder {
    encoder: Arc<ManagedEncoder>,
    spec: EncoderSpec,
}
impl ManagedWordEncoder {
    pub fn new(encoder: Arc<ManagedEncoder>, spec: EncoderSpec) -> Self {
        Self { encoder, spec }
    }
}
impl WordEncoder for ManagedWordEncoder {
    fn spec(&self) -> &EncoderSpec {
        &self.spec
    }
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>> {
        ManagedQueryEncoder(self.encoder.clone()).embed_query(text)
    }
    fn embed_passages(&self, texts: &[PythonText]) -> Result<Vec<Vec<f32>>> {
        let scalar: Vec<_> = texts
            .iter()
            .map(|t| {
                t.to_utf8().ok_or_else(|| {
                    RetrievalError::Invalid(
                        "word contains non-scalar Unicode for this encoder".into(),
                    )
                })
            })
            .collect::<Result<_>>()?;
        Ok(self
            .encoder
            .embed_passages(&scalar.iter().map(String::as_str).collect::<Vec<_>>())?)
    }
}
