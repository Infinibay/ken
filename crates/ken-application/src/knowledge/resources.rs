//! A focused encoder is selected only when a domain-approved operation needs it.
use super::FindingEmbeddings;
use ken_maintenance::UserConfig;
use ken_models::{ModelFactory, model_policy::ModelPolicy};
use ken_retrieval::{
    RetrievalError,
    project_embeddings::{ProjectEmbeddings, TransformerOverrides, configure_project},
    query_encoder::QueryEncoder,
};
use ken_text::PythonText;
use rusqlite::Connection;
use std::{rc::Rc, sync::Arc};
#[derive(Clone)]
pub struct EmbeddingResources {
    factory: Arc<ModelFactory>,
    config: UserConfig,
    environment_model: Option<String>,
    overrides: TransformerOverrides,
}
impl EmbeddingResources {
    /// Capture explicit inputs. No model selection, metadata pin or inference here.
    pub fn new(
        factory: Arc<ModelFactory>,
        config: UserConfig,
        environment_model: Option<String>,
        overrides: TransformerOverrides,
    ) -> Self {
        Self {
            factory,
            config,
            environment_model,
            overrides,
        }
    }
    pub fn project(&self, db: &Connection) -> ken_retrieval::Result<Arc<ProjectEmbeddings>> {
        let default = self
            .config
            .default_model()
            .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
        let selected = configure_project(
            db,
            &ModelPolicy::new(default.as_deref()),
            self.environment_model.as_deref(),
        )?;
        Ok(Arc::new(ProjectEmbeddings::new(
            self.factory.clone(),
            selected.model,
            self.overrides.clone(),
        )))
    }
    /// History's adapter uses Rc while the native responsibility owner uses Arc.
    pub fn query_encoder(&self, db: &Connection) -> ken_retrieval::Result<Rc<dyn QueryEncoder>> {
        Ok(Rc::new(QueryOwner(self.project(db)?)))
    }
}
struct QueryOwner(Arc<ProjectEmbeddings>);
impl QueryEncoder for QueryOwner {
    fn embed_query(&self, text: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
        self.0.embed_query(text)
    }
}
impl FindingEmbeddings for EmbeddingResources {
    fn embed_finding(&self, db: &Connection, topic: &str, content: &str) -> Option<Vec<f32>> {
        crate::embedding::finding_embedding(self.project(db).ok()?.as_ref(), topic, content)
    }
    fn embed_query(&self, db: &Connection, query: &str) -> ken_knowledge::Result<Vec<f32>> {
        self.project(db)
            .and_then(|owner| owner.embed_query(&query.into()))
            .map_err(super::error)
    }
}
