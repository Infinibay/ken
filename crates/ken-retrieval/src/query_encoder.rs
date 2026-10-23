//! Query-side model use is separate from document indexing.
use crate::{Result, RetrievalError};
use ken_models::ManagedEncoder;
use ken_text::PythonText;
use std::{rc::Rc, sync::Arc};
pub trait QueryEncoder {
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>>;
}
pub struct QueryEncoders {
    pub identity: Rc<dyn QueryEncoder>,
    pub behavior: Rc<dyn QueryEncoder>,
}
pub struct ManagedQueryEncoder(pub Arc<ManagedEncoder>);
impl QueryEncoder for ManagedQueryEncoder {
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>> {
        let scalar = text.to_utf8().ok_or_else(|| {
            RetrievalError::Invalid("query contains non-scalar Unicode for this encoder".into())
        })?;
        Ok(self.0.embed_query(&scalar)?)
    }
}
