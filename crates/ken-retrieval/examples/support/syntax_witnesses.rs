#[path = "source_catalog.rs"]
mod source_catalog;
use ken_retrieval::syntax_operation_witnesses::SyntaxOperationWitnesses;
use ken_syntax::GrammarCatalog;
use serde_json::{Value, json};
pub use source_catalog::{Physical, ProbeResult, catalog};
use std::{fs, sync::Arc};
pub fn observe(input: Physical, grammars: Arc<GrammarCatalog>) -> ProbeResult<Value> {
    let (directory, catalog) = catalog(input)?;
    let catalog = Arc::new(catalog);
    for path in catalog.snapshots().keys() {
        fs::write(
            directory.path().join(path),
            b"changed after catalog construction\n",
        )?;
    }
    let mut observer = SyntaxOperationWitnesses::new(catalog.clone(), grammars);
    let mut rows = Vec::new();
    for (key, _) in catalog.owners() {
        let cold = observer.for_owner(key)?;
        let warm = observer.for_owner(key)?;
        rows.push(json!({"key":key,"cold":cold,"warm":warm}));
    }
    Ok(json!(rows))
}
