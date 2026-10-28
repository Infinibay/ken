//! One immutable catalog owns the synthesis and reuse of its descriptions.
use crate::{
    EntityKey, Result, RetrievalError,
    description::{OwnerDescription, describe_owner},
    source_catalog::SourceCatalog,
};
use std::{collections::HashMap, sync::Arc};
pub struct OwnerDescriptions {
    catalog: Arc<SourceCatalog>,
    lookup: HashMap<EntityKey, usize>,
    values: Vec<Arc<OwnerDescription>>,
}
impl OwnerDescriptions {
    pub fn new(catalog: Arc<SourceCatalog>) -> Self {
        Self {
            catalog,
            lookup: HashMap::new(),
            values: Vec::new(),
        }
    }
    pub fn belongs_to(&self, catalog: &SourceCatalog) -> bool {
        std::ptr::eq(self.catalog.as_ref(), catalog)
    }
    pub fn len(&self) -> usize {
        self.values.len()
    }
    pub fn is_empty(&self) -> bool {
        self.values.is_empty()
    }
    pub fn iter(&self) -> impl Iterator<Item = &Arc<OwnerDescription>> {
        self.values.iter()
    }
    pub fn get(&mut self, key: &EntityKey) -> Result<Arc<OwnerDescription>> {
        let passages = self
            .catalog
            .passages(key)
            .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
        if let Some(&index) = self.lookup.get(key) {
            return Ok(self.values[index].clone());
        }
        let description = Arc::new(describe_owner(passages)?);
        self.lookup.insert(key.clone(), self.values.len());
        self.values.push(description.clone());
        Ok(description)
    }
}
