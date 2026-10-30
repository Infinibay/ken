use super::{Result, invalid};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
pub fn identity(value: &Value) -> String {
    if let Some(object) = value.as_object() {
        object
            .get("local_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned()
    } else if let Some(s) = value.as_str() {
        s.to_owned()
    } else {
        value.to_string()
    }
}
pub fn location(node: &Value) -> Value {
    let mut out = serde_json::Map::new();
    for key in ["path", "line", "name", "kind"] {
        if let Some(v) = node.get(key) {
            out.insert(key.into(), v.clone());
        }
    }
    Value::Object(out)
}
pub fn qualname(node: &Value) -> String {
    let local = node["local_id"].as_str().unwrap_or("");
    local
        .split('/')
        .filter_map(|part| {
            ["CALLABLE:", "CLASS:", "INTERFACE:"]
                .iter()
                .find_map(|prefix| part.strip_prefix(prefix))
        })
        .map(|part| part.split('@').next().unwrap_or(""))
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(".")
}
#[derive(Clone, Debug)]
pub struct Call {
    pub owner: String,
    pub site: Value,
    pub targets: Vec<String>,
    pub resolution: String,
}
#[derive(Clone, Debug)]
pub struct Use {
    pub owner: String,
    pub target: String,
    pub site: String,
    pub usage: Value,
}
pub struct Program {
    pub scope: String,
    pub observations: Value,
    pub nodes: BTreeMap<String, Value>,
    pub calls: Vec<Call>,
    pub uses: Vec<Use>,
    pub snapshot: Option<Value>,
    pub selection: Option<Value>,
    order: Vec<String>,
}
fn rows<'a>(observations: &'a Value, name: &str) -> impl Iterator<Item = &'a Value> {
    observations[name]["rows"].as_array().into_iter().flatten()
}
impl Program {
    pub fn from_batch(scope: &str, batch: &Value) -> Result<Self> {
        let observations = batch["results"].clone();
        if !observations.is_object() {
            return Err(invalid("inspection observations unavailable"));
        }
        let mut nodes = BTreeMap::new();
        let mut order = Vec::new();
        for row in rows(&observations, "definitions") {
            if row[0].is_object() {
                let id = identity(&row[0]);
                if !nodes.contains_key(&id) {
                    order.push(id.clone());
                }
                nodes.insert(id, row[0].clone());
            }
        }
        let mut entities = BTreeMap::new();
        for result in observations.as_object().unwrap().values() {
            if let Some(map) = result["entities"].as_object() {
                entities.extend(map.iter().map(|(k, v)| (k.clone(), v.clone())));
            }
        }
        for (id, node) in &entities {
            if node["kind"] == "CALLABLE" {
                if !nodes.contains_key(id) {
                    order.push(id.clone());
                }
                nodes.insert(id.clone(), node.clone());
            }
        }
        let mut target_map = BTreeMap::<String, Vec<String>>::new();
        let mut possible = BTreeMap::<String, Vec<String>>::new();
        for (name, map) in [
            ("targets", &mut target_map),
            ("possible_targets", &mut possible),
        ] {
            for row in rows(&observations, name) {
                map.entry(identity(&row[0]))
                    .or_default()
                    .push(identity(&row[1]));
            }
        }
        let mut calls = Vec::new();
        for row in rows(&observations, "calls") {
            let owner_id = identity(&row[0]);
            let owner = nodes
                .get(&owner_id)
                .cloned()
                .unwrap_or_else(|| row[0].clone());
            let site_id = identity(&row[1]);
            let site = entities
                .get(&site_id)
                .cloned()
                .unwrap_or_else(|| row[1].clone());
            if !owner.is_object() || !site.is_object() {
                continue;
            }
            if !nodes.contains_key(&owner_id) {
                order.push(owner_id.clone());
                nodes.insert(owner_id.clone(), owner);
            }
            let linked = target_map.get(&site_id).cloned().unwrap_or_default();
            let alternatives = possible.get(&site_id).cloned().unwrap_or_default();
            let resolution = if !linked.is_empty() {
                "resolved"
            } else if !alternatives.is_empty() {
                "ambiguous"
            } else {
                "unresolved"
            };
            calls.push(Call {
                owner: owner_id,
                site,
                targets: if linked.is_empty() {
                    alternatives
                } else {
                    linked
                },
                resolution: resolution.into(),
            });
        }
        let mut uses = Vec::new();
        for row in rows(&observations, "usages") {
            if row[3].is_object() {
                uses.push(Use {
                    owner: identity(&row[0]),
                    target: identity(&row[1]),
                    site: identity(&row[2]),
                    usage: row[3].clone(),
                });
            }
        }
        Ok(Self {
            scope: scope.into(),
            observations,
            nodes,
            calls,
            uses,
            snapshot: batch.get("snapshot").filter(|v| !v.is_null()).cloned(),
            selection: batch.get("selection").filter(|v| !v.is_null()).cloned(),
            order,
        })
    }
    pub fn discard(&mut self, reason: &str) {
        self.nodes.clear();
        self.order.clear();
        self.calls.clear();
        self.uses.clear();
        for result in self
            .observations
            .as_object_mut()
            .into_iter()
            .flatten()
            .map(|(_, r)| r)
        {
            result["complete"] = json!(false);
            result["reason"] = json!(reason);
            result["rows"] = json!([]);
            result["entities"] = json!({});
        }
    }
    pub fn select(&self, target: &str) -> Vec<String> {
        let (path, symbol) = target
            .split_once("::")
            .map_or((target, None), |(p, s)| (p, Some(s)));
        self.order
            .iter()
            .filter(|id| {
                let node = &self.nodes[*id];
                let file = node["path"].as_str().unwrap_or("");
                let path_matches = file == path
                    || file.starts_with(&(path.trim_end_matches('/').to_owned() + "/"));
                if let Some(symbol) = symbol {
                    path_matches && qualname(node) == symbol
                } else {
                    path_matches || qualname(node) == target
                }
            })
            .cloned()
            .collect()
    }
    pub fn coverage(&self) -> Value {
        let mut out = serde_json::Map::new();
        for (name, result) in self.observations.as_object().into_iter().flatten() {
            let mut value = serde_json::Map::new();
            for key in [
                "complete",
                "coverage_complete",
                "unknown_candidates",
                "results_truncated",
                "reason",
            ] {
                if let Some(v) = result.get(key) {
                    value.insert(key.into(), v.clone());
                }
            }
            if let Some(queries) = result["queries"].as_array() {
                value.insert("evaluations".into(), json!(queries.len()));
            }
            out.insert(name.clone(), Value::Object(value));
        }
        Value::Object(out)
    }
    pub fn inventory_complete(&self) -> bool {
        self.observations
            .as_object()
            .into_iter()
            .flatten()
            .filter(|(k, _)| k.as_str() != "usages")
            .all(|(_, r)| {
                super::truth(&r["complete"])
                    && super::truth(&r["coverage_complete"])
                    && !super::truth(&r["results_truncated"])
                    && !super::truth(&r["reason"])
            })
    }
    pub fn connected(&self, seeds: &[String], depth: usize) -> BTreeSet<String> {
        let mut seen = seeds.iter().cloned().collect::<BTreeSet<_>>();
        let mut frontier = seen.clone();
        for _ in 0..depth {
            let mut added = BTreeSet::new();
            for call in &self.calls {
                if frontier.contains(&call.owner)
                    || call.targets.iter().any(|t| frontier.contains(t))
                {
                    added.insert(call.owner.clone());
                    added.extend(call.targets.iter().cloned());
                }
            }
            frontier = added.difference(&seen).cloned().collect();
            seen.extend(added);
        }
        seen
    }
}
