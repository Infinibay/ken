//! Initializer roots and evaluated-value uses preserve occurrence identity.
use super::{
    ExecutionError, OperationProbe, Result,
    engine::Engine,
    evidence::{Proof, Row},
    source::{SourceRuntime, attr, string},
    source_operators::bound,
};
use ken_program::{Operation, value::GraphValue as V};
use serde_json::json;
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
};
pub(super) struct Initializer {
    pub assignment: String,
    pub expression: String,
    pub call: Option<String>,
    pub unknown: BTreeSet<String>,
}
pub(super) fn unknown(reason: &str) -> BTreeSet<String> {
    BTreeSet::from([reason.into()])
}
pub(super) fn integer(v: V) -> Option<i64> {
    if let V::Int(v) = v {
        v.parse().ok()
    } else {
        None
    }
}
impl Engine<'_> {
    pub fn source_initializer(
        &mut self,
        row: &Row,
        binding_role: &str,
        construct: bool,
        target_role: &str,
        output: Option<&str>,
        out: &mut Vec<Row>,
    ) -> Result<()> {
        let binding = bound(row, binding_role)?;
        let target = bound(row, target_role)?;
        let regions = self.with_source(|s| s.initializers(binding))?;
        for region in regions {
            self.tick()?;
            let mut missing = row.unknown.clone();
            missing.extend(region.unknown.iter().cloned());
            if let Some(call) = &region.call {
                if construct {
                    let allocations =
                        self.with_source(|s| s.rows("ALLOCATES_TYPE", Some(call), None))?;
                    let matching = allocations
                        .iter()
                        .filter(|f| f.object == target)
                        .collect::<Vec<_>>();
                    if !matching.is_empty() {
                        let mut all_may = true;
                        for f in matching {
                            all_may &= string(&f.attrs, "modality")?.as_deref() == Some("may");
                        }
                        if all_may {
                            missing.insert("initializer_allocation_may".into());
                        }
                    } else if !allocations.is_empty() {
                        continue;
                    } else if self.graph.entity(call)?.is_some_and(|e| {
                        attr(&e.attrs, "construction")
                            .map(|v| v.truthy())
                            .unwrap_or(false)
                    }) {
                        missing.insert("initializer_allocation_missing".into());
                    } else {
                        continue;
                    }
                } else if call != target {
                    continue;
                }
                if output.is_some_and(|role| row.bindings.get(role).is_some_and(|v| v != call)) {
                    continue;
                }
            } else if region.unknown.is_empty() {
                continue;
            }
            let mut bindings = row.bindings.clone();
            if let Some(output) = output {
                bindings.entry(output.into()).or_insert_with(|| {
                    region
                        .call
                        .clone()
                        .unwrap_or_else(|| format!("@unknown:initializer:{binding}"))
                });
            }
            let proof = json!({"subject":region.assignment,"relation":"source_initializer","object":region.expression});
            out.push(Row {
                bindings,
                evidence: row.append(Proof::Source(Arc::new(proof))),
                unknown: missing,
            });
        }
        Ok(())
    }
    pub fn source_usages(
        &mut self,
        row: &Row,
        value_role: &str,
        usage_role: &str,
        filters: &[(String, String, String)],
        out: &mut Vec<Row>,
    ) -> Result<()> {
        let value = bound(row, value_role)?;
        let uses = self.with_source(|s| s.usages(value))?;
        for usage in uses {
            self.tick()?;
            if row.bindings.get(usage_role).is_some_and(|v| v != &usage.id) {
                continue;
            }
            let mut metadata_unknown = false;
            let mut rejected = false;
            for (name, mode, text) in filters {
                let actual = usage.attrs.get(name).cloned().unwrap_or(V::Null);
                if actual == V::Null && name != "position" {
                    metadata_unknown = true;
                } else if !(if mode == "role" {
                    actual.string().as_deref() == Some(bound(row, text)?)
                } else {
                    self.comparisons.compare(&actual, mode, text)?
                }) {
                    rejected = true;
                    break;
                }
            }
            if rejected {
                continue;
            }
            let mut proof = serde_json::Map::new();
            for (k, v) in &usage.attrs {
                proof.insert(
                    k.clone(),
                    serde_json::from_str(v.to_raw()?.get())
                        .map_err(|e| ExecutionError::Invalid(e.to_string()))?,
                );
            }
            proof.insert("usage".into(), json!(usage.id));
            proof.insert("value".into(), json!(value));
            proof.insert("relation".into(), json!(usage.fact.relation));
            proof.insert("source".into(), json!(usage.fact.evidence));
            proof.insert("inventory".into(), json!("open"));
            self.source
                .usage_metadata
                .insert(usage.id.clone(), usage.attrs);
            let mut bindings = row.bindings.clone();
            bindings.insert(usage_role.into(), usage.id);
            let mut missing = row.unknown.clone();
            if usage.uncertain {
                missing.insert("usage_origin_may".into());
            }
            if metadata_unknown {
                missing.insert("usage_metadata_unknown".into());
            }
            out.push(Row {
                bindings,
                evidence: row.append(Proof::Source(Arc::new(proof.into()))),
                unknown: missing,
            });
        }
        if row
            .bindings
            .get(usage_role)
            .is_none_or(|v| v.starts_with("@unknown:"))
        {
            let id = format!("@unknown:usage:{value}");
            self.source
                .usage_metadata
                .insert(id.clone(), BTreeMap::new());
            let mut bindings = row.bindings.clone();
            bindings.insert(usage_role.into(), id);
            let mut missing = row.unknown.clone();
            missing.insert("usage_inventory_open".into());
            out.push(Row {
                bindings,
                evidence: row.append(Proof::Source(Arc::new(
                    json!({"value":value,"usage_inventory":"open"}),
                ))),
                unknown: missing,
            });
        }
        Ok(())
    }
}
impl SourceRuntime<'_> {
    pub(super) fn children(&mut self, parent: &Operation) -> Result<Vec<Arc<Operation>>> {
        Ok(self
            .operations(&OperationProbe {
                region: Some(parent.id.clone()),
                ..Default::default()
            })?
            .into_iter()
            .filter(|op| op.parent.as_deref() == Some(parent.id.as_str()))
            .collect())
    }
}
