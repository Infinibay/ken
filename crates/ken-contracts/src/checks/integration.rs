//! Native application consumers share the same typed receipt and report policy.
use super::operation::Operation;
use super::{
    Observation, QueryRequest, RawReport, Receipt, Result, Rule, Service, execution, invalid,
    observation::{Fields, raw},
    observation_report, query_report, rules, selection,
};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    time::{Duration, Instant},
};
fn manifest(value: &Value) -> Result<BTreeMap<String, String>> {
    value["manifest"]
        .as_array()
        .ok_or_else(|| invalid("receipt has no source manifest"))?
        .iter()
        .map(|p| {
            Ok((
                p[0].as_str()
                    .ok_or_else(|| invalid("invalid source manifest"))?
                    .to_owned(),
                p[1].as_str()
                    .ok_or_else(|| invalid("invalid source manifest"))?
                    .to_owned(),
            ))
        })
        .collect()
}
fn changed(old: &Value, new: &Value) -> Result<BTreeSet<String>> {
    let old = manifest(old)?;
    let new = manifest(new)?;
    Ok(old
        .keys()
        .chain(new.keys())
        .filter(|p| old.get(*p) != new.get(*p))
        .cloned()
        .collect())
}
impl Service<'_> {
    pub fn search(&mut self, input: &Value) -> Result<Value> {
        self.search_report(input)?.to_json()
    }
    pub fn search_report(&mut self, input: &Value) -> Result<RawReport> {
        let start = Instant::now();
        self.engine.checkpoint()?;
        let ids = input["ids"]
            .as_array()
            .or_else(|| input["rules"].as_array())
            .ok_or_else(|| invalid("registered rule ids are required"))?;
        let path = super::relative(input["path"].as_str().unwrap_or("."))?;
        let timeout = input
            .get("timeout_ms")
            .map_or(Some(10000.), Value::as_f64)
            .filter(|v| v.is_finite() && (1.0..=120000.).contains(v))
            .ok_or_else(|| invalid("invalid execution budget"))?;
        let max_rows = input
            .get("max_rows")
            .map_or(Some(100), Value::as_u64)
            .filter(|v| (1..=1000).contains(v))
            .ok_or_else(|| invalid("invalid execution budget"))?;
        let total = Duration::from_secs_f64(timeout / 1000.);
        let operation = Operation::new(start, total);
        operation.check(self.engine)?;
        let mut seen = BTreeSet::new();
        let mut results = Vec::new();
        let mut complete = true;
        for id in ids {
            operation.check(self.engine)?;
            let id = id
                .as_str()
                .ok_or_else(|| invalid("invalid check reference"))?;
            if !seen.insert(id) {
                continue;
            }
            let rule = Rule::read(
                &self
                    .store
                    .read_checked("rules", id, &mut || operation.check(self.engine))?["definition"],
            )?;
            if !selection::overlaps(&rule.path, &path)? {
                continue;
            }
            let result = match execution::remaining(start, total) {
                Ok(left) => {
                    let request = QueryRequest {
                        root: self.store.root.clone(),
                        source: rule.query,
                        query_name: None,
                        libraries: rule.libraries,
                        path: rule.path.clone(),
                        source_paths: None,
                        timeout_ms: Some(left.as_secs_f64() * 1000.),
                        max_states: Some(200000),
                        max_rows: Some(max_rows),
                        source_profile: "full".into(),
                    };
                    execution::execute_observation(&request, self.engine, self.inputs)
                }
                Err(e) => Observation::unknown(e.to_string()),
            };
            complete &= result.admission().complete == Some(true);
            let mut item = Fields::new();
            item.insert("rule".into(), raw(id)?);
            item.insert("path".into(), raw(&rule.path)?);
            item.insert(
                "result".into(),
                raw(&query_report(&result, input["full"] == true)?)?,
            );
            results.push(item);
        }
        operation.check(self.engine)?;
        let report = RawReport::new(&BTreeMap::from([
            ("results", raw(&results)?),
            ("complete", raw(&complete)?),
        ]))?;
        operation.check(self.engine)?;
        Ok(report)
    }
    pub fn freshness(&mut self, receipt: &Value, budget: Duration) -> Result<Value> {
        self.freshness_receipt(&Receipt::from_json(receipt)?, budget)
    }
    pub fn freshness_receipt(&mut self, receipt: &Receipt, budget: Duration) -> Result<Value> {
        let start = Instant::now();
        let operation = Operation::new(start, budget);
        let version = operation.identity(self.engine)?;
        let mut issues = Vec::new();
        let mut states = Vec::new();
        let mut observations = Vec::new();
        let mut snapshots = BTreeMap::new();
        for check in &receipt.checks {
            operation.check(self.engine)?;
            let mut detail = json!({"rule":check.rule,"path":check.path,"status":check.status});
            let result = (|| -> Result<(String, Vec<String>)> {
                let rule = Rule::read(
                    &self
                        .store
                        .read_checked("rules", &check.rule, &mut || operation.check(self.engine))?
                        ["definition"],
                )?;
                if check.revision != rule.revision() || check.engine != version {
                    issues.push(format!("{}: rule or engine changed", rule.id));
                    return Ok(("stale".into(), Vec::new()));
                }
                let scope = &check.path;
                if !snapshots.contains_key(scope) {
                    let remaining = operation.remaining(self.engine)?;
                    snapshots.insert(
                        scope.clone(),
                        self.inputs.capture(&self.store.root, scope, remaining)?,
                    );
                }
                let snapshot = &snapshots[scope];
                let before = check
                    .result
                    .metadata("check_snapshot")?
                    .filter(|v| !v.is_null())
                    .ok_or_else(|| invalid("receipt has no source snapshot"))?;
                let mut state = if snapshot == &before {
                    "unchanged"
                } else {
                    "stale"
                };
                let mut paths = changed(&before, snapshot)?;
                if state == "unchanged"
                    && let Some(old_deps) = check.result.metadata("check_dependencies")?
                {
                    let remaining = operation.remaining(self.engine)?;
                    let live = self
                        .inputs
                        .dependencies(&self.store.root, snapshot, remaining)?;
                    if live != old_deps {
                        state = "stale";
                        paths.extend(changed(&old_deps, &live)?);
                    }
                }
                if state != "unchanged" {
                    issues.push(format!("{}: source inventory or contents changed", rule.id));
                }
                Ok((state.into(), paths.into_iter().collect()))
            })();
            match result {
                Ok((state, paths)) => {
                    detail["validity"] = json!(state);
                    if !(state == "stale"
                        && issues
                            .last()
                            .is_some_and(|s| s.ends_with(": rule or engine changed")))
                    {
                        detail["changed_files"] = json!(paths);
                    }
                    states.push(state);
                }
                Err(e) => {
                    let reason = e.to_string();
                    states.push("unknown".into());
                    issues.push(format!("{}: {reason}", check.rule));
                    detail["validity"] = json!("unknown");
                    detail["reason"] = json!(reason);
                }
            }
            observations.push(detail);
        }
        operation.check(self.engine)?;
        let state = if states.iter().any(|s| s == "stale") {
            "stale"
        } else if states.is_empty() || states.iter().any(|s| s == "unknown") {
            "unknown"
        } else {
            "unchanged"
        };
        Ok(
            json!({"state":state,"issues":issues,"checks":observations,"scope":"Recorded check inputs; the memory's prose is not independently proved."}),
        )
    }
    pub fn related(&mut self, path: &str, limit: usize) -> Result<Value> {
        self.related_report(path, limit)?.to_json()
    }
    pub fn related_report(&mut self, path: &str, limit: usize) -> Result<RawReport> {
        let operation = Operation::new(Instant::now(), Duration::from_secs(1));
        operation.check(self.engine)?;
        let path = super::relative(path)?;
        if !(1..=100).contains(&limit) {
            return Err(invalid("limit must be 1..100"));
        }
        let records = self
            .store
            .rules_checked(&mut || operation.check(self.engine))?;
        let (selected, evidence) = selection::affected(
            &self.store.root,
            &records,
            &[path],
            operation.remaining(self.engine)?,
            true,
            self.inputs,
        )?;
        let records = records
            .into_iter()
            .filter(|r| selected.contains(r["definition"]["id"].as_str().unwrap_or("")))
            .collect::<Vec<_>>();
        operation.check(self.engine)?;
        if records.is_empty() {
            return RawReport::new(&json!({"rules":[],"checks":[]}));
        }
        let version = operation.identity(self.engine)?;
        let ids = self
            .store
            .run_ids_checked(&mut || operation.check(self.engine))?;
        let mut seen = BTreeSet::new();
        let mut checks = Vec::new();
        for run_id in ids.into_iter().take(100) {
            operation.check(self.engine)?;
            let run = self
                .store
                .read_receipt_checked(&run_id, &mut || operation.check(self.engine))?;
            for observation in &run.checks {
                if seen.contains(&observation.rule) || !selected.contains(&observation.rule) {
                    continue;
                }
                seen.insert(observation.rule.clone());
                let mut one = run.clone();
                one.checks = vec![observation.clone()];
                let validity = self.freshness_receipt(
                    &one,
                    operation
                        .remaining(self.engine)?
                        .min(Duration::from_millis(500)),
                )?;
                let mut out: Fields =
                    serde_json::from_str(observation_report(observation)?.json())?;
                out.insert("run_id".into(), raw(&run.run_id)?);
                out.insert("validity".into(), raw(&validity)?);
                checks.push(out);
                if checks.len() >= limit {
                    break;
                }
            }
            if checks.len() >= limit {
                break;
            }
        }
        let mut out = Fields::new();
        out.insert(
            "rules".into(),
            raw(&records
                .iter()
                .take(limit)
                .map(|r| rules::view(r, false, &version))
                .collect::<Result<Vec<_>>>()?)?,
        );
        out.insert("checks".into(), raw(&checks)?);
        out.insert(
            "omitted_rules".into(),
            raw(&records.len().saturating_sub(limit))?,
        );
        out.insert("selection_evidence".into(), raw(&evidence)?);
        let report = RawReport::new(&out)?;
        operation.check(self.engine)?;
        Ok(report)
    }
    pub fn justification(&mut self, run_id: &str, data: Option<&Value>) -> Result<Value> {
        let operation = Operation::new(Instant::now(), Duration::from_secs(2));
        operation.check(self.engine)?;
        let receipt = self
            .store
            .read_receipt_checked(run_id, &mut || operation.check(self.engine))?;
        let live = self.freshness_receipt(&receipt, operation.remaining(self.engine)?)?;
        if live["state"] != "unchanged" {
            return Err(invalid(
                "check inputs changed or cannot be verified; rerun ken_check before recording",
            ));
        }
        let mut out = data.cloned().unwrap_or(json!({}));
        let map = out
            .as_object_mut()
            .ok_or_else(|| invalid("justification must be an object"))?;
        map.entry("kind").or_insert(json!("observation"));
        map.entry("rationale").or_insert(json!("This note references the selected KQL2 source-contract checks; retain their scope and uncertainty."));
        map.entry("recheck").or_insert(json!("ken_check with the referenced rules; update this note only after reviewing the new result."));
        let mut runs = map
            .get("check_runs")
            .cloned()
            .unwrap_or(json!([]))
            .as_array()
            .cloned()
            .ok_or_else(|| invalid("check_runs must contain receipt ids"))?;
        if !runs.iter().any(|r| r == run_id) {
            runs.push(json!(run_id));
        }
        let mut seen = BTreeSet::new();
        runs.retain(|r| seen.insert(r.as_str().unwrap_or("").to_owned()));
        map.insert("check_runs".into(), json!(runs));
        operation.check(self.engine)?;
        Ok(out)
    }
    pub fn resume(&mut self) -> Result<String> {
        let operation = Operation::new(Instant::now(), Duration::from_millis(500));
        operation.check(self.engine)?;
        let receipt = self
            .store
            .run_ids_checked(&mut || operation.check(self.engine))?
            .first()
            .map(|id| {
                self.store
                    .read_receipt_checked(id, &mut || operation.check(self.engine))
            })
            .transpose()?;
        let Some(receipt) = receipt else {
            return Ok(String::new());
        };
        let live = self.freshness_receipt(&receipt, operation.remaining(self.engine)?)?;
        Ok(format!(
            "<ken-checks>\nLast source-contract check: {}; input validity: {}. Inspect: ken_check(run_id=\"{}\"). Recheck if inputs changed.\n</ken-checks>",
            receipt.status,
            live["state"].as_str().unwrap_or("unknown"),
            receipt.run_id
        ))
    }
}
