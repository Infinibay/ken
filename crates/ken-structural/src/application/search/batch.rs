//! Prepare the entire rule batch before acquiring its single source revision.
use super::super::catalog::SavedRule;
use super::*;
use crate::{AcquiredProject, GraphSnapshot};
use ken_query::{
    execution::{Execution, GraphRead, MemoryGraph},
    legacy::Pattern,
    relational::RelationalQuery,
};
use std::collections::{BTreeMap, BTreeSet};
enum Plan {
    Legacy(Pattern),
    Relational(Arc<RelationalQuery>),
}
struct PreparedRule {
    rule: SavedRule,
    plan: Plan,
}
pub(super) struct PreparedBatch {
    rules: Vec<PreparedRule>,
}
impl PreparedBatch {
    pub fn select(library: &RuleLibrary, request: &SearchRequest) -> Result<Self> {
        let ordinary = library
            .rules()
            .iter()
            .map(|r| r.id.as_str())
            .collect::<BTreeSet<_>>();
        let named = request
            .rules
            .iter()
            .any(|id| !ordinary.contains(id.as_str()));
        if named && (!request.collections.is_empty() || !request.tags.is_empty()) {
            return Err(invalid(
                "named variant selection cannot be combined with collection/tag filters",
            ));
        }
        let selected = if !request.query.is_empty() {
            vec![serde_json::from_value(
                json!({"id":"query","query":request.query}),
            )?]
        } else if named {
            request
                .rules
                .iter()
                .map(|id| {
                    if let Some(rule) = library.rules().iter().find(|r| r.id == *id) {
                        Ok(rule.clone())
                    } else {
                        let selected = library.named(id)?;
                        let roles = selected
                            .exports
                            .items()
                            .iter()
                            .map(|(role, _)| role.as_str())
                            .collect::<Vec<_>>();
                        let bindings = roles
                            .iter()
                            .map(|role| format!("{role}: ${role}"))
                            .collect::<Vec<_>>()
                            .join(", ");
                        let projection = roles
                            .iter()
                            .map(|role| format!("${role}"))
                            .collect::<Vec<_>>()
                            .join(", ");
                        let source = format!(
                            "query selected {{ match {}({bindings}); emit {projection}; }}",
                            serde_json::to_string(id)?
                        );
                        Ok(serde_json::from_value(
                            json!({"id":id,"name":id,"query":source}),
                        )?)
                    }
                })
                .collect::<Result<Vec<SavedRule>>>()?
        } else {
            library.select(&request.rules, &request.collections, &request.tags)?
        };
        let rules = selected
            .into_iter()
            .map(|rule| {
                let plan = if request.query.is_empty() && !ordinary.contains(rule.id.as_str()) {
                    Plan::Relational(library.named(&rule.id)?)
                } else if rule.query.trim_start().starts_with("query ")
                    || rule.query.trim_start().starts_with("language \"kql/2\"")
                {
                    Plan::Relational(library.inline(&rule.query)?)
                } else {
                    let mut pattern = ken_query::legacy::parse_query(&rule.query)?;
                    pattern.name = if rule.name.is_empty() {
                        rule.id.clone()
                    } else {
                        rule.name.clone()
                    };
                    Plan::Legacy(pattern)
                };
                Ok(PreparedRule { rule, plan })
            })
            .collect::<Result<Vec<_>>>()?;
        Ok(Self { rules })
    }
    pub fn validate(&self) -> Result<()> {
        let empty=ken_program::StructuralIr::from_json(&json!({"path":"","language":"","entities":{},"operations":[],"facts":[],"capabilities":[],"diagnostics":[],"version":ken_program::IR_VERSION,"view":"query","relations":[]}).to_string()).map_err(BuildError::from)?;
        let graph = MemoryGraph::new(&empty)?;
        for prepared in &self.rules {
            match &prepared.plan {
                Plan::Legacy(pattern) => {
                    ken_query::legacy::execute(&graph, pattern, Default::default())?;
                }
                Plan::Relational(query) => {
                    Execution::new(Default::default())?.execute(&graph, query)?;
                }
            }
        }
        Ok(())
    }
    pub fn execute(
        self,
        library: &RuleLibrary,
        project: &mut AcquiredProject,
        cache: &mut ArtifactCache,
        options: ExecutionOptions,
        bucket_options: Option<super::BucketOptions>,
    ) -> Result<Value> {
        let graph_key = project.analysis["graph_key"]
            .as_str()
            .unwrap_or("")
            .to_owned();
        let registry = serde_json::to_vec(library.rules())?;
        let mode = serde_json::to_vec(&options.evidence_mode)?;
        let mut legacy = None;
        let mut matches = Vec::new();
        let mut outcomes = BTreeMap::new();
        let mut rules = Vec::new();
        let mut bucket_metrics = super::super::exploration::buckets::BucketMetrics::default();
        for prepared in self.rules {
            let rule = serde_json::to_value(&prepared.rule)?;
            let text = serde_json::to_vec(&rule)?;
            let key = ArtifactCache::key([
                b"native-structural-outcome/1".as_slice(),
                crate::IMPLEMENTATION_FINGERPRINT.as_bytes(),
                graph_key.as_bytes(),
                &registry,
                &mode,
                &text,
            ]);
            let stored = if graph_key.is_empty() || options.cancellation.is_cancelled() {
                None
            } else {
                cache
                    .get_json(&key)
                    .and_then(|raw| serde_json::from_str::<Value>(raw.get()).ok())
                    .filter(|value| usable(value, options.budget.max_matches))
            };
            let outcome = if let Some(stored) = stored {
                stored
            } else {
                let value = match &prepared.plan {
                    Plan::Legacy(pattern) => {
                        if legacy.is_none() {
                            let mut raw = project.source_graph(|| {
                                if options.cancellation.is_cancelled() {
                                    Err(BuildError::Invalid("structural execution cancelled"))
                                } else {
                                    Ok(())
                                }
                            })?;
                            raw.view = "query".into();
                            legacy = Some(MemoryGraph::new(&raw)?);
                        }
                        if let Some(config) = &bucket_options {
                            let graph = super::super::exploration::buckets::CatalogBuckets::new(
                                legacy.as_ref().unwrap(),
                                config.clone(),
                            )?;
                            let outcome =
                                ken_query::legacy::execute(&graph, pattern, options.clone())?;
                            accumulate(&mut bucket_metrics, graph.metrics());
                            serde_json::to_value(outcome)?
                        } else {
                            serde_json::to_value(ken_query::legacy::execute(
                                legacy.as_ref().unwrap(),
                                pattern,
                                options.clone(),
                            )?)?
                        }
                    }
                    Plan::Relational(query) => {
                        let mut index = project.index()?;
                        serde_json::to_value(crate::query::execute_query_with(
                            &mut index,
                            query,
                            options.clone(),
                            |base, execution, query| {
                                if let Some(config) = &bucket_options {
                                    let graph =
                                        super::super::exploration::buckets::CatalogBuckets::new(
                                            base,
                                            config.clone(),
                                        )?;
                                    let outcome = execution.execute(&graph, query)?;
                                    accumulate(&mut bucket_metrics, graph.metrics());
                                    Ok(outcome)
                                } else {
                                    execution.execute(base, query)
                                }
                            },
                        )?)?
                    }
                };
                if !graph_key.is_empty()
                    && value["complete"] == true
                    && !options.cancellation.is_cancelled()
                {
                    cache.put_json(&key, &serde_json::value::to_raw_value(&value)?);
                }
                value
            };
            let mut index = project.index()?;
            let run = Execution::new(Default::default())?;
            let scope = index.execution(|| false).map_err(BuildError::from)?;
            let graph = GraphSnapshot::new(&scope, run.interruption());
            for item in outcome["matches"].as_array().into_iter().flatten() {
                let mut item = item.clone();
                locate(&graph, &mut item)?;
                item["id"] = json!(prepared.rule.id);
                item["rule"] = rule.clone();
                matches.push(item);
            }
            outcomes.insert(prepared.rule.id.clone(),json!({"complete":outcome["complete"],"unknown":outcome["unknown"],"stats":outcome["stats"]}));
            rules.push(rule);
        }
        let complete = outcomes.values().all(|outcome| outcome["complete"] == true);
        let mut response =
            json!({"matches":matches,"outcomes":outcomes,"complete":complete,"rules":rules});
        if bucket_options.is_some() {
            response["pattern_buckets"] = serde_json::to_value(bucket_metrics)?;
        }
        Ok(response)
    }
}
fn usable(value: &Value, limit: Option<u64>) -> bool {
    value["complete"] == true
        && value["stats"].is_object()
        && value["unknown"].is_array()
        && value["matches"].as_array().is_some_and(|rows| {
            limit.is_none_or(|max| rows.len() as u64 <= max)
                && rows.iter().all(|row| {
                    row["bindings"]
                        .as_object()
                        .is_some_and(|bindings| bindings.values().all(Value::is_string))
                })
        })
}
fn locate(graph: &dyn GraphRead, item: &mut Value) -> Result<()> {
    let mut locations = BTreeSet::new();
    let mut unit = None;
    for (key, value) in item["bindings"].as_object().into_iter().flatten() {
        if let Some(id) = value.as_str()
            && let Some(entity) = graph.entity(id)?
        {
            locations.insert((entity.path.clone(), entity.line));
            if key == "$unit" {
                unit = Some(entity);
            }
        }
    }
    let primary = unit
        .as_ref()
        .map(|entity| (entity.path.clone(), entity.line))
        .or_else(|| locations.first().cloned())
        .unwrap_or_default();
    item["path"] = json!(primary.0);
    item["line"] = json!(primary.1);
    item["symbol"] = json!(unit.map(|entity| entity.name.clone()).unwrap_or_default());
    item["locations"] = json!(
        locations
            .into_iter()
            .map(|(path, line)| json!({"path":path,"line":line}))
            .collect::<Vec<_>>()
    );
    Ok(())
}

fn accumulate(
    total: &mut super::super::exploration::buckets::BucketMetrics,
    next: super::super::exploration::buckets::BucketMetrics,
) {
    total.hits += next.hits;
    total.disk_hits += next.disk_hits;
    total.builds += next.builds;
    total.fallback += next.fallback;
    total.loaded_rows += next.loaded_rows;
    total.build_ms += next.build_ms;
    total.evictions += next.evictions;
    total.memory_bytes = total.memory_bytes.max(next.memory_bytes);
    if next.cache_error.is_some() {
        total.cache_error = next.cache_error;
    }
}
