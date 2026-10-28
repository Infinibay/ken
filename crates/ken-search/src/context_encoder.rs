//! Adapt the registered contextual model to source and query retrieval boundaries.
use ken_models::{ContextEncoder, ContextModel, EncoderSpec};
use ken_retrieval::{
    Result, RetrievalError, context_preparation::ContextSourceEncoder, query_encoder::QueryEncoder,
    source_views::SOURCE_VIEW_PROJECTION,
};
use ken_text::PythonText;
use std::sync::Arc;
pub(crate) struct NativeContext {
    owner: Arc<ContextEncoder>,
    spec: EncoderSpec,
    view: EncoderSpec,
}
impl NativeContext {
    pub fn new(owner: Arc<ContextEncoder>) -> Result<Self> {
        let mut registration: serde_json::Value = serde_json::from_str(include_str!(
            "../../ken-models/resources/code-context-int8.json"
        ))?;
        let identity = ContextModel::from_json(&registration.to_string())?.compatible_identity();
        let spec = serde_json::from_value(identity["spec"].clone())?;
        registration["document_projection"] = SOURCE_VIEW_PROJECTION.into();
        let identity = ContextModel::from_json(&registration.to_string())?.compatible_identity();
        let view = serde_json::from_value(identity["spec"].clone())?;
        Ok(Self { owner, spec, view })
    }
}
fn scalar(text: &PythonText) -> Result<String> {
    text.to_utf8()
        .ok_or_else(|| RetrievalError::Invalid("context input contains non-scalar Unicode".into()))
}
impl QueryEncoder for NativeContext {
    fn embed_query(&self, text: &PythonText) -> Result<Vec<f32>> {
        Ok(self.owner.embed_query(&scalar(text)?)?)
    }
}
impl ContextSourceEncoder for NativeContext {
    fn spec(&self) -> &EncoderSpec {
        &self.spec
    }
    fn view_spec(&self) -> &EncoderSpec {
        &self.view
    }
    fn embed_passages(&self, texts: &[PythonText]) -> Result<Vec<Vec<f32>>> {
        let texts = texts.iter().map(scalar).collect::<Result<Vec<_>>>()?;
        Ok(self
            .owner
            .embed_passages(&texts.iter().map(String::as_str).collect::<Vec<_>>())?)
    }
}
