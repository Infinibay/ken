use super::scenario::{Physical, Scenario};
use super::{Observation, finish_source, raw};
use ken_retrieval::source_catalog::{PieceIdentity, SourceCatalog, entity_id};
use serde_json::{Value, json};
use std::collections::BTreeMap;
fn projection(catalog: &SourceCatalog) -> ken_retrieval::source_snapshot::SourceResult<Value> {
    let mut projections = Vec::new();
    for (key, _) in catalog.owners() {
        let mut primary = BTreeMap::new();
        for kind in ["class", "module", "symbol", "file"] {
            primary.insert(
                kind,
                catalog.primary(key, kind)?.map(|p| match p {
                    PieceIdentity::Entity(k) => entity_id(&k),
                    PieceIdentity::Path(p) => p,
                }),
            );
        }
        projections.push(json!({"identity":entity_id(key),"extent":catalog.extent(key)?,"owned_ranges":catalog.owned_ranges(key,false)?,"implementation_ranges":catalog.owned_ranges(key,true)?,"scope_members":catalog.scope_members(key)?.map(|keys|keys.iter().map(entity_id).collect::<Vec<_>>()),"enclosing_callable":catalog.enclosing_callable(key)?.as_ref().map(entity_id),"primary":primary}));
    }
    let lines: BTreeMap<_, _> = catalog
        .snapshots()
        .iter()
        .map(|(p, s)| (p, s.lines()))
        .collect();
    let hashes: BTreeMap<_, _> = catalog
        .snapshots()
        .iter()
        .map(|(p, s)| (p, s.hash()))
        .collect();
    Ok(
        json!({"inventory":catalog.source_inventory()?,"projections":projections,"lines":lines,"hashes":hashes}),
    )
}
pub fn run(text: &str) -> Observation {
    let value = (|| {
        let physical: Physical = serde_json::from_str(text)
            .map_err(|e| ken_retrieval::source_snapshot::SourceError::Invalid(e.to_string()))?;
        let scenario = Scenario::new(&physical)?;
        let catalog = scenario.catalog(physical.owners)?;
        raw(&projection(&catalog)?)
            .map_err(|e| ken_retrieval::source_snapshot::SourceError::Invalid(e.to_string()))
    })();
    finish_source(value, Observation::new())
}
