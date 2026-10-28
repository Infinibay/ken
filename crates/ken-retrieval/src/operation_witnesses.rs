//! Dispatch source-operation evidence to its language's semantic backend.
use crate::{
    EntityKey, python_operation_witnesses::PythonOperationWitnesses, source_catalog::SourceCatalog,
    source_snapshot::SourceResult, syntax_operation_witnesses::SyntaxOperationWitnesses,
};
use ken_syntax::GrammarCatalog;
use std::{collections::BTreeSet, sync::Arc};
pub struct OperationWitnesses {
    catalog: Arc<SourceCatalog>,
    python: PythonOperationWitnesses,
    syntax: SyntaxOperationWitnesses,
}
impl OperationWitnesses {
    pub fn new(catalog: Arc<SourceCatalog>, grammars: Arc<GrammarCatalog>) -> Self {
        Self {
            python: PythonOperationWitnesses::new(catalog.clone()),
            syntax: SyntaxOperationWitnesses::new(catalog.clone(), grammars),
            catalog,
        }
    }
    pub fn for_owner(&mut self, key: &EntityKey) -> SourceResult<BTreeSet<String>> {
        self.catalog.passages(key)?;
        if PythonOperationWitnesses::supports(&key.path) {
            self.python.for_owner(key)
        } else if SyntaxOperationWitnesses::supports(&key.path) {
            self.syntax.for_owner(key)
        } else {
            Ok(BTreeSet::new())
        }
    }
}
