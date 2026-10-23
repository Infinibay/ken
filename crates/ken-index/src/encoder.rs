//! Adapt accepted lazy model owners to the document-only indexing boundary.
use ken_models::{EncoderSpec, LegacyRuntimeIdentity, ManagedEncoder, ModelFactory};
use ken_retrieval::{DocumentEncoder, Result, encoder::EncoderLoader};
use std::{rc::Rc, sync::Arc};
pub struct ManagedDocumentEncoder(pub Arc<ManagedEncoder>);
impl DocumentEncoder for ManagedDocumentEncoder {
    fn dim(&self) -> Result<usize> {
        Ok(self.0.dim()?)
    }
    fn token_count(&self, text: &str) -> Result<usize> {
        Ok(self.0.token_count(text)?)
    }
    fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        Ok(self.0.embed_passages(texts)?)
    }
}
pub struct ModelEncoderLoader {
    pub factory: Arc<ModelFactory>,
    pub legacy: LegacyRuntimeIdentity,
}
impl EncoderLoader for ModelEncoderLoader {
    fn load(&self, spec: &EncoderSpec) -> Result<Rc<dyn DocumentEncoder>> {
        Ok(Rc::new(ManagedDocumentEncoder(
            self.factory.encoder(spec, &self.legacy)?,
        )))
    }
}
