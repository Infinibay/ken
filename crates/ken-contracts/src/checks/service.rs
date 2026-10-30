use super::operation::Operation;
use super::{
    CheckObservation, Clock, ModuleResolver, Observation, QueryEngine, QueryRequest, RawReport,
    Receipt, Result, Rule, SourceInputs, Store, compare_receipts, execution, invalid,
    judgment_observation, model::relative, receipt_report, rules, selection,
};
use serde_json::{Value, json};
use std::{
    path::Path,
    time::{Duration, Instant},
};
pub struct Service<'a> {
    pub(super) store: Store,
    pub(super) engine: &'a mut dyn QueryEngine,
    pub(super) inputs: &'a mut dyn SourceInputs,
    pub(super) resolver: &'a mut dyn ModuleResolver,
    pub(super) clock: &'a dyn Clock,
}
impl<'a> Service<'a> {
    pub fn new(
        root: &Path,
        engine: &'a mut dyn QueryEngine,
        inputs: &'a mut dyn SourceInputs,
        resolver: &'a mut dyn ModuleResolver,
        clock: &'a dyn Clock,
    ) -> Result<Self> {
        engine.checkpoint()?;
        inputs.checkpoint()?;
        Ok(Self {
            store: Store::new(root)?,
            engine,
            inputs,
            resolver,
            clock,
        })
    }
    pub fn store(&self) -> &Store {
        &self.store
    }
    pub fn check(&mut self, input: &Value) -> Result<Value> {
        self.check_report(input)?.to_json()
    }
    pub fn check_report(&mut self, input: &Value) -> Result<RawReport> {
        let started = Instant::now();
        self.engine.checkpoint()?;
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
        let operation = Operation::new(started, total);
        operation.check(self.engine)?;
        let path = relative(input["path"].as_str().unwrap_or("."))?;
        let scope = input["scope"].as_str().unwrap_or("project");
        if !["project", "changes"].contains(&scope) {
            return Err(invalid("scope must be project or changes"));
        }
        let full = input["full"] == true;
        if let Some(id) = input["run_id"].as_str().filter(|s| !s.is_empty()) {
            let receipt = self
                .store
                .read_receipt_checked(id, &mut || operation.check(self.engine))?;
            let result = receipt_report(&receipt, full)?;
            operation.check(self.engine)?;
            return Ok(result);
        }
        let records = self
            .store
            .rules_checked(&mut || operation.check(self.engine))?;
        let requested = input
            .get("rules")
            .filter(|v| !v.is_null())
            .map(|v| {
                v.as_array()
                    .filter(|r| (1..=16).contains(&r.len()))
                    .ok_or_else(|| invalid("rules must name 1..16 registered check rules"))?
                    .iter()
                    .map(|v| {
                        v.as_str()
                            .map(str::to_owned)
                            .ok_or_else(|| invalid("rules must name 1..16 registered check rules"))
                    })
                    .collect::<Result<Vec<_>>>()
            })
            .transpose()?;
        if requested.as_ref().is_some_and(|ids| {
            ids.iter()
                .any(|id| !records.iter().any(|r| r["definition"]["id"] == id.as_str()))
        }) {
            return Err(invalid("rules must name 1..16 registered check rules"));
        }
        let version = operation.identity(self.engine)?;
        let automatic = input["automatic"] == true;
        let mut selected = Vec::new();
        let mut unvalidated = Vec::new();
        for record in records {
            operation.check(self.engine)?;
            let valid = rules::validated(&record, &version)?;
            let enabled = record["enabled"] == true;
            let auto = record["automatic"] == true;
            if requested.is_none() && enabled && !valid && (!automatic || auto) {
                unvalidated.push(record.clone());
            }
            let chosen = if let Some(ids) = &requested {
                ids.iter()
                    .any(|id| record["definition"]["id"] == id.as_str())
            } else {
                enabled && valid
            };
            if chosen && (!automatic || (auto && valid && enabled)) {
                selected.push(record);
            }
        }
        operation.check(self.engine)?;
        let changed = if let Some(touched) = input.get("touched").filter(|v| !v.is_null()) {
            Some(
                touched
                    .as_array()
                    .ok_or_else(|| invalid("touched must contain source paths"))?
                    .iter()
                    .map(|p| {
                        p.as_str()
                            .map(str::to_owned)
                            .ok_or_else(|| invalid("touched must contain source paths"))
                    })
                    .collect::<Result<Vec<_>>>()?,
            )
        } else if scope == "changes" {
            Some(self.inputs.changed_paths(&self.store.root)?)
        } else {
            None
        };
        operation.check(self.engine)?;
        let mut evidence = json!({});
        if path != "." {
            let all = selected
                .iter()
                .chain(&unvalidated)
                .cloned()
                .collect::<Vec<_>>();
            let (ids, detail) = selection::affected(
                &self.store.root,
                &all,
                std::slice::from_ref(&path),
                Duration::from_secs_f64((timeout / 4000.).min(1.)),
                false,
                self.inputs,
            )?;
            evidence = detail;
            selected.retain(|r| ids.contains(r["definition"]["id"].as_str().unwrap_or("")));
            unvalidated.retain(|r| ids.contains(r["definition"]["id"].as_str().unwrap_or("")));
        }
        operation.check(self.engine)?;
        if let Some(changed) = changed {
            let all = selected
                .iter()
                .chain(&unvalidated)
                .cloned()
                .collect::<Vec<_>>();
            let (ids, detail) = selection::affected(
                &self.store.root,
                &all,
                &changed,
                Duration::from_secs_f64((timeout / 4000.).min(1.)),
                true,
                self.inputs,
            )?;
            evidence = detail;
            selected.retain(|r| ids.contains(r["definition"]["id"].as_str().unwrap_or("")));
            unvalidated.retain(|r| ids.contains(r["definition"]["id"].as_str().unwrap_or("")));
        }
        operation.check(self.engine)?;
        if selected.len() > 16 {
            return Err(invalid("select at most 16 rules per check"));
        }
        let compare = input["compare"].as_str().unwrap_or("");
        let baseline = if compare == "last" {
            self.store
                .run_ids_checked(&mut || operation.check(self.engine))?
                .first()
                .map(|id| {
                    self.store
                        .read_receipt_checked(id, &mut || operation.check(self.engine))
                })
                .transpose()?
        } else if !compare.is_empty() {
            Some(
                self.store
                    .read_receipt_checked(compare, &mut || operation.check(self.engine))?,
            )
        } else {
            None
        };
        let mut observations = Vec::new();
        for record in selected {
            operation.check(self.engine)?;
            let rule = Rule::read(&record["definition"])?;
            let mut result = match execution::remaining(started, total) {
                Ok(left) => {
                    let request = QueryRequest {
                        root: self.store.root.clone(),
                        source: rule.query.clone(),
                        query_name: None,
                        libraries: rule.libraries.clone(),
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
            operation.check(self.engine)?;
            let current = self
                .store
                .read("rules", &rule.id)
                .ok()
                .and_then(|r| Rule::read(&r["definition"]).ok())
                .map(|r| r.revision());
            if current.as_deref() != Some(rule.revision().as_str()) {
                result.invalidate("rule_changed_during_check");
            }
            if result
                .metadata("check_engine")?
                .is_some_and(|v| v != json!(version))
            {
                result.invalidate("engine_changed_after_rule_selection");
            }
            let status = judgment_observation(&result, &rule.expectation);
            let engine = result
                .metadata("check_engine")?
                .and_then(|v| v.as_str().map(str::to_owned))
                .unwrap_or_else(|| version.clone());
            let revision = rule.revision();
            observations.push(CheckObservation {
                rule: rule.id,
                description: rule.description,
                revision,
                path: rule.path,
                query: rule.query,
                libraries: rule.libraries,
                expectation: rule.expectation,
                status,
                engine,
                result,
                extra: Default::default(),
            });
        }
        let status = if observations.iter().any(|o| o.status == "fail") {
            "fail"
        } else if !unvalidated.is_empty() || observations.iter().any(|o| o.status == "unknown") {
            "unknown"
        } else if observations.is_empty() {
            "not_applicable"
        } else {
            "pass"
        };
        let mut receipt = Receipt {
            version: 1,
            run_id: self.clock.run_id(),
            created_at: self.clock.now(),
            scope: scope.into(),
            selection: path,
            status: status.into(),
            checks: observations,
            selection_evidence: Some(evidence),
            comparison: None,
            skipped_rules: None,
            extra: Default::default(),
        };
        if !unvalidated.is_empty() {
            receipt.skipped_rules=Some(unvalidated.iter().map(|r|json!({"rule":r["definition"]["id"],"reason":"rule or engine changed; validate again"})).collect());
        }
        if let Some(before) = baseline {
            receipt.comparison = Some(compare_receipts(&before, &receipt));
        }
        let result = receipt_report(&receipt, full)?;
        operation.check(self.engine)?;
        if !receipt.checks.is_empty() || !unvalidated.is_empty() {
            self.store
                .write_receipt_checked(&receipt, &mut || operation.check(self.engine))?;
        }
        Ok(result)
    }
}
