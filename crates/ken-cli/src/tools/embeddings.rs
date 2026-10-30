//! Optional tool embeddings stay cold until a domain actually requests a vector.
use ken_application::knowledge::{EmbeddingResources, FindingEmbeddings};
use ken_retrieval::{project_embeddings::TransformerOverrides, query_encoder::QueryEncoder};
use ken_text::PythonText;
use rusqlite::Connection;
use std::{cell::RefCell, collections::BTreeMap, path::PathBuf, rc::Rc};
pub(super) struct FocusedEmbeddings {
    installation: PathBuf,
    environment: BTreeMap<String, String>,
    resource: RefCell<Option<Rc<EmbeddingResources>>>,
}
impl FocusedEmbeddings {
    pub(super) fn new(installation: PathBuf) -> Self {
        Self {
            installation,
            environment: crate::runtime::environment(),
            resource: RefCell::new(None),
        }
    }
    pub(super) fn resources(&self) -> ken_knowledge::Result<Rc<EmbeddingResources>> {
        if let Some(resources) = self.resource.borrow().as_ref() {
            return Ok(resources.clone());
        }
        let factory = crate::runtime::model_factory(&self.installation, &self.environment)
            .map_err(|e| ken_knowledge::Error::Invalid(e.to_string()))?;
        let resources = Rc::new(EmbeddingResources::new(
            factory,
            crate::runtime::user_config(&self.environment),
            self.environment.get("KEN_EMBED_MODEL").cloned(),
            TransformerOverrides {
                sequence_length: self.environment.get("KEN_EMBED_MAX_SEQ").cloned(),
                batch_size: self.environment.get("KEN_EMBED_BATCH").cloned(),
            },
        ));
        self.resource.replace(Some(resources.clone()));
        Ok(resources)
    }
}
impl FindingEmbeddings for FocusedEmbeddings {
    fn embed_finding(&self, db: &Connection, topic: &str, content: &str) -> Option<Vec<f32>> {
        self.resources().ok()?.embed_finding(db, topic, content)
    }
    fn embed_query(&self, db: &Connection, query: &str) -> ken_knowledge::Result<Vec<f32>> {
        self.resources()?.embed_query(db, query)
    }
}
pub(super) struct IntentQuery<'a> {
    pub embeddings: &'a FocusedEmbeddings,
    pub db: &'a Connection,
}
impl QueryEncoder for IntentQuery<'_> {
    fn embed_query(&self, query: &PythonText) -> ken_retrieval::Result<Vec<f32>> {
        let resources = self
            .embeddings
            .resources()
            .map_err(|e| ken_retrieval::RetrievalError::Invalid(e.to_string()))?;
        resources.project(self.db)?.embed_query(query)
    }
}
