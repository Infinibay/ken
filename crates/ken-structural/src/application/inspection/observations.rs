use super::{Result, invalid};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
const NAMES: [&str; 5] = [
    "definitions",
    "calls",
    "targets",
    "possible_targets",
    "usages",
];
pub struct ObservationLog {
    pub results: Value,
    pub manifest: BTreeMap<String, String>,
    pub paths: BTreeSet<String>,
    pub invalidated: bool,
    seen: BTreeMap<String, BTreeSet<String>>,
}
impl Default for ObservationLog {
    fn default() -> Self {
        Self::new()
    }
}
impl ObservationLog {
    pub fn new() -> Self {
        Self{results:json!(NAMES.into_iter().map(|name|(name,json!({"rows":[],"entities":{},"complete":true,"coverage_complete":true,"unknown_candidates":0,"results_truncated":false,"reason":null,"queries":[]}))).collect::<BTreeMap<_,_>>()),manifest:BTreeMap::new(),paths:BTreeSet::new(),invalidated:false,seen:NAMES.into_iter().map(|name|(name.into(),BTreeSet::new())).collect()}
    }
    pub fn add(&mut self, name: &str, query: &str, result: &Value) -> Result<()> {
        let combined = self
            .results
            .get_mut(name)
            .ok_or_else(|| invalid("unknown inspection observation"))?;
        if let Some(entities) = result["entities"].as_object() {
            combined["entities"]
                .as_object_mut()
                .unwrap()
                .extend(entities.iter().map(|(k, v)| (k.clone(), v.clone())));
        }
        for row in result["rows"].as_array().into_iter().flatten() {
            let key = serde_json::to_string(row)?;
            if self.seen.get_mut(name).unwrap().insert(key) {
                combined["rows"].as_array_mut().unwrap().push(row.clone());
            }
        }
        for key in ["complete", "coverage_complete"] {
            combined[key] = json!(super::truth(&combined[key]) && super::truth(&result[key]));
        }
        combined["results_truncated"] = json!(
            super::truth(&combined["results_truncated"])
                || super::truth(&result["results_truncated"])
        );
        combined["unknown_candidates"] = json!(
            combined["unknown_candidates"]
                .as_u64()
                .unwrap_or(0)
                .saturating_add(result["unknown_candidates"].as_u64().unwrap_or(0))
        );
        let mut reasons = Vec::new();
        for reason in [&combined["reason"], &result["reason"]] {
            if let Some(s) = reason.as_str().filter(|s| !s.is_empty())
                && !reasons.iter().any(|reason: &String| reason == s)
            {
                reasons.push(s.to_owned());
            }
        }
        combined["reason"] = if reasons.is_empty() {
            Value::Null
        } else {
            json!(reasons.join("; "))
        };
        let mut analysis = serde_json::Map::new();
        for key in [
            "parsed_units",
            "reused_units",
            "scanned_nodes",
            "states",
            "build_ms",
            "query_ms",
            "total_ms",
            "result_cache",
        ] {
            if let Some(v) = result["analysis"].get(key) {
                analysis.insert(key.into(), v.clone());
            }
        }
        combined["queries"].as_array_mut().unwrap().push(json!({"query":query,"source_scope":result.get("source_scope").cloned().unwrap_or(Value::Null),"analysis":analysis}));
        let mut changed = false;
        for item in result["analysis"]["manifest"]
            .as_array()
            .into_iter()
            .flatten()
        {
            let path = item[0]
                .as_str()
                .ok_or_else(|| invalid("invalid query source manifest"))?;
            let fingerprint = item[1]
                .as_str()
                .ok_or_else(|| invalid("invalid query source manifest"))?;
            if self
                .manifest
                .get(path)
                .is_some_and(|previous| previous != fingerprint)
            {
                changed = true;
            }
            self.manifest.insert(path.into(), fingerprint.into());
            self.paths.insert(path.into());
        }
        if changed {
            self.fail("source_changed_during_inspection", true);
        }
        Ok(())
    }
    pub fn fail(&mut self, reason: &str, discard: bool) {
        self.invalidated |= discard;
        for result in self.results.as_object_mut().unwrap().values_mut() {
            result["complete"] = json!(false);
            result["reason"] = json!(reason);
            if discard {
                result["rows"] = json!([]);
                result["entities"] = json!({});
            }
        }
    }
    pub fn batch(&mut self, snapshot: &Value, engine: &str, selection: &Value) -> Value {
        if self.invalidated {
            self.fail("source_changed_during_inspection", true);
        }
        for result in self.results.as_object_mut().unwrap().values_mut() {
            result["check_snapshot"] = snapshot.clone();
            result["check_engine"] = json!(engine);
        }
        json!({"results":self.results,"snapshot":snapshot,"engine":engine,"selection":selection})
    }
}
