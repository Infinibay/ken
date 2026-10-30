//! One request-local cache owns source preparation and library closure selection.
use super::*;
use ken_query::{BackendPreference, File, compile, relational::RelationalQuery};
use std::{collections::BTreeSet, sync::Arc};
pub(super) fn block(source: &str) -> bool {
    let source = source.trim_start();
    source.starts_with("query ") || source.starts_with("language \"kql/2\"")
}
pub(super) struct Compilation<'a> {
    catalog: &'a Catalog,
    queries: BTreeMap<String, Arc<RelationalQuery>>,
    libraries: BTreeMap<String, File>,
}
impl<'a> Compilation<'a> {
    pub fn new(catalog: &'a Catalog) -> Self {
        Self {
            catalog,
            queries: Default::default(),
            libraries: Default::default(),
        }
    }
    pub fn query(&mut self, source: &str) -> Result<Arc<RelationalQuery>> {
        if let Some(q) = self.queries.get(source) {
            return Ok(q.clone());
        }
        let query = if source.trim_start().starts_with("language \"kql/2\"") {
            let tree = ken_query::parse(source, "<catalog-query>", Default::default())?;
            let mut pending = tree.imports.clone();
            let mut seen = BTreeSet::new();
            let mut selected = BTreeMap::new();
            while let Some(name) = pending.pop() {
                if !seen.insert(name.clone()) || name == "ken.core" {
                    continue;
                }
                if !self.libraries.contains_key(&name)
                    && let Some(source) = self.catalog.libraries.get(&name)
                {
                    self.libraries.insert(
                        name.clone(),
                        ken_query::parse(source, &name, Default::default())?,
                    );
                }
                if let Some(file) = self.libraries.get(&name) {
                    pending.extend(file.imports.iter().cloned());
                    selected.insert(name, file.clone());
                }
            }
            compile(&tree, None, &selected, BackendPreference::Relational)?
                .relational
                .ok_or_else(|| invalid("catalog query has no relational plan"))?
        } else if block(source) {
            Arc::new(ken_query::legacy_blocks::parse(source)?)
        } else {
            Arc::new(ken_query::legacy_blocks::legacy_query(source, "query")?)
        };
        self.queries.insert(source.into(), query.clone());
        Ok(query)
    }
}
