//! Admit original observation inputs without synthesizing any expected result.
#[path = "source_catalog.rs"]
mod source_catalog;
use serde_json::Value;
pub use source_catalog::{Physical, ProbeResult, catalog};
/// Original synthetic owners have no display fields. These five empty strings
/// represent that empty metadata in the native fixed-field Passage schema;
/// source bytes, entity keys, spans and source hashes are preserved verbatim.
pub fn physical(mut input: Value) -> ProbeResult<Physical> {
    if let Some(owners) = input.get_mut("owners").and_then(Value::as_array_mut) {
        for owner in owners {
            if let Some(passages) = owner.get_mut("passages").and_then(Value::as_array_mut) {
                for passage in passages {
                    if passage
                        .get("fields")
                        .and_then(Value::as_object)
                        .is_some_and(|fields| fields.is_empty())
                    {
                        passage["fields"] = serde_json::json!({"identity":"","signature":"","documentation":"","body":"","path":""});
                    }
                }
            }
        }
    }
    Ok(serde_json::from_value(input)?)
}

use ken_retrieval::operation_witnesses::OperationWitnesses;
use ken_syntax::GrammarCatalog;
use serde_json::json;
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
    let mut observer = OperationWitnesses::new(catalog.clone(), grammars);
    let mut rows = Vec::new();
    for (key, _) in catalog.owners() {
        let cold = observer.for_owner(key)?;
        let warm = observer.for_owner(key)?;
        rows.push(json!({"key":key,"cold":cold,"warm":warm}));
    }
    Ok(json!(rows))
}
