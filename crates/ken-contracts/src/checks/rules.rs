use super::operation::Operation;
use super::{QueryRequest, Result, Rule, Service, execution, invalid};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs,
    time::{Duration, Instant},
};
pub(super) fn validated(record: &Value, version: &str) -> Result<bool> {
    let rule = Rule::read(&record["definition"])?;
    let validation = &record["validation"];
    Ok(validation["passed"] == true
        && validation["revision"] == rule.revision()
        && validation["engine"] == version)
}
pub(super) fn view(record: &Value, full: bool, version: &str) -> Result<Value> {
    let rule = Rule::read(&record["definition"])?;
    let ready = validated(record, version)?;
    let mut out = json!({"id":rule.id,"description":rule.description,"path":rule.path,"expectation":rule.expectation,"state":if ready&&record["enabled"]==true{"enabled"}else if ready{"validated"}else{"draft"},"automatic":ready&&record["enabled"]==true&&record["automatic"]==true,"revision":rule.revision()});
    if full {
        out["definition"] = rule.data();
        out["validation"] = record.get("validation").cloned().unwrap_or(Value::Null);
    }
    Ok(out)
}
impl Service<'_> {
    fn compile_definition(&mut self, mut rule: Rule, operation: &Operation) -> Result<Rule> {
        operation.check(self.engine)?;
        let libraries = self
            .resolver
            .resolve(&self.store.root, &rule.query, &rule.libraries)?;
        operation.check(self.engine)?;
        let entry = ken_query::parse(
            &rule.query,
            "<check-rule>",
            ken_query::ParseLimits::default(),
        )
        .map_err(|e| invalid(e.to_string()))?;
        let mut trees = BTreeMap::new();
        for (module, source) in &libraries {
            operation.check(self.engine)?;
            let tree = ken_query::parse(source, module, ken_query::ParseLimits::default())
                .map_err(|e| invalid(e.to_string()))?;
            if tree.module != *module {
                return Err(invalid(format!(
                    "missing or mismatched library module: {module}"
                )));
            }
            trees.insert(module.clone(), tree);
        }
        operation.check(self.engine)?;
        ken_query::compile(
            &entry,
            None,
            &trees,
            ken_query::BackendPreference::Automatic,
        )
        .map_err(|e| invalid(e.to_string()))?;
        operation.check(self.engine)?;
        rule.libraries = libraries;
        Rule::read(&rule.data())
    }
    pub fn manage(&mut self, input: &Value) -> Result<Value> {
        let started = Instant::now();
        self.engine.checkpoint()?;
        let timeout_ms = input
            .get("timeout_ms")
            .map_or(Some(30000.), Value::as_f64)
            .filter(|v| v.is_finite() && (1.0..=120000.).contains(v))
            .ok_or_else(|| invalid("timeout_ms must be 1..120000"))?;
        let operation = Operation::new(started, Duration::from_secs_f64(timeout_ms / 1000.));
        operation.check(self.engine)?;
        let action = input["action"].as_str().unwrap_or("list");
        let version = operation.identity(self.engine)?;
        let full = input["full"] == true;
        let rule_id = input["rule_id"].as_str().unwrap_or("");
        if action == "list" {
            let result = json!({"rules":self.store.rules_checked(&mut ||operation.check(self.engine))?.iter().map(|r|view(r,full,&version)).collect::<Result<Vec<_>>>()?});
            operation.check(self.engine)?;
            return Ok(result);
        }
        if action == "create" {
            let definition = input
                .get("definition")
                .filter(|v| !v.is_null())
                .ok_or_else(|| invalid("create requires definition"))?;
            let rule = Rule::read(definition)?;
            if !rule_id.is_empty() && rule_id != rule.id {
                return Err(invalid("rule_id conflicts with definition id"));
            }
            let rule = self.compile_definition(rule, &operation)?;
            let record = json!({"version":1,"definition":rule.data(),"enabled":false,"automatic":false,"validation":null});
            let result = view(&record, full, &version)?;
            operation.check(self.engine)?;
            self.store
                .save_rule_checked(&record, None, &mut || operation.check(self.engine))?;
            return Ok(result);
        }
        let previous = self
            .store
            .read_checked("rules", rule_id, &mut || operation.check(self.engine))?;
        let mut record = previous.clone();
        let rule = Rule::read(&record["definition"])?;
        match action {
            "show" => {
                let result = view(&record, full, &version)?;
                operation.check(self.engine)?;
                return Ok(result);
            }
            "update" => {
                let replacement = input
                    .get("definition")
                    .filter(|v| !v.is_null())
                    .ok_or_else(|| invalid("update requires a complete definition"))?;
                let replacement = Rule::read(replacement)?;
                if replacement.id != rule.id {
                    return Err(invalid("update cannot rename a rule"));
                }
                let replacement = self.compile_definition(replacement, &operation)?;
                record["definition"] = replacement.data();
                record["enabled"] = json!(false);
                record["automatic"] = json!(false);
                record["validation"] = Value::Null;
            }
            "validate" => {
                if !["pass", "fail"]
                    .iter()
                    .all(|expected| rule.examples.iter().any(|c| c["expect"] == *expected))
                {
                    return Err(invalid(
                        "validation requires both passing and failing examples",
                    ));
                }
                let mut cases = Vec::new();
                for example in &rule.examples {
                    operation.check(self.engine)?;
                    let temp = tempfile::Builder::new().prefix("ken-rule-").tempdir()?;
                    let files = example["files"]
                        .as_object()
                        .ok_or_else(|| invalid("invalid example source"))?;
                    for (path, source) in files {
                        operation.check(self.engine)?;
                        let file = temp.path().join(path);
                        if let Some(parent) = file.parent() {
                            fs::create_dir_all(parent)?;
                        }
                        fs::write(
                            file,
                            source
                                .as_str()
                                .ok_or_else(|| invalid("invalid example source"))?,
                        )?;
                    }
                    let mut result = match operation.remaining(self.engine) {
                        Ok(left) => {
                            let request = QueryRequest {
                                root: temp.path().to_path_buf(),
                                source: rule.query.clone(),
                                query_name: None,
                                libraries: rule.libraries.clone(),
                                path: rule.path.clone(),
                                source_paths: None,
                                timeout_ms: Some(left.as_secs_f64() * 1000.),
                                max_states: Some(200000),
                                max_rows: Some(100),
                                source_profile: "full".into(),
                            };
                            execution::execute_observation(&request, self.engine, self.inputs)
                        }
                        Err(e) => super::Observation::unknown(e.to_string()),
                    };
                    if result
                        .metadata("check_engine")?
                        .is_some_and(|e| e != json!(version))
                        || operation.identity(self.engine)? != version
                    {
                        result.invalidate("engine_changed_during_validation");
                    }
                    let actual = super::judgment_observation(&result, &rule.expectation);
                    cases.push(json!({"name":example["name"],"expected":example["expect"],"actual":actual,"passed":actual==example["expect"].as_str().unwrap_or(""),"reason":result.metadata("reason")?.unwrap_or(Value::Null)}));
                }
                record["enabled"] = json!(false);
                record["automatic"] = json!(false);
                record["validation"] = json!({"revision":rule.revision(),"engine":version,"passed":operation.identity(self.engine)?==version&&cases.iter().all(|c|c["passed"]==true),"cases":cases});
            }
            "enable" => {
                if !validated(&record, &version)? {
                    return Err(invalid(
                        "validate passing and failing examples against this rule and engine before enabling",
                    ));
                }
                record["enabled"] = json!(true);
                if let Some(automatic) = input.get("automatic").filter(|v| !v.is_null()) {
                    let value = automatic
                        .as_bool()
                        .ok_or_else(|| invalid("automatic must be boolean"))?;
                    record["automatic"] = json!(value);
                }
            }
            "disable" => {
                record["enabled"] = json!(false);
                record["automatic"] = json!(false);
            }
            _ => {
                return Err(invalid(
                    "action must be list/create/show/update/validate/enable/disable",
                ));
            }
        }
        let result = view(&record, full || action == "validate", &version)?;
        operation.check(self.engine)?;
        self.store
            .save_rule_checked(&record, Some(&previous), &mut || {
                operation.check(self.engine)
            })?;
        Ok(result)
    }
}
