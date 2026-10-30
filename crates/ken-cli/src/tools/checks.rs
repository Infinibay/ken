//! Source-contract transport composes the native process supervisor on demand.
use super::{ToolReply, live::LiveTools};
use ken_checks_application::{ChecksApplication, Resources, WorkerProgram};
use ken_core::project::ProjectPaths;
use serde_json::{Value, json, value::RawValue};
pub(super) fn application(
    paths: &ProjectPaths,
    live: &LiveTools,
) -> Result<ChecksApplication, String> {
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let worker = executable
        .parent()
        .ok_or("native executable has no parent")?
        .join("ken-check-worker");
    let resources = Resources::prepared(&live.grammar_manifest()?, WorkerProgram::new(worker))
        .map_err(|e| e.to_string())?;
    ChecksApplication::new(paths.root(), resources).map_err(|e| e.to_string())
}
pub(super) fn definitions() -> Vec<Value> {
    vec![
        json!({"name":"ken_rule","description":"Create, validate and enable KQL2 source contracts. Passing and failing source examples are parsed in isolated native workers; project code is never executed.","inputSchema":{"type":"object","additionalProperties":false,"properties":{
        "action":{"type":"string","enum":["list","create","show","update","validate","enable","disable"],"default":"list"},"rule_id":{"type":"string","default":""},"definition":{"anyOf":[{"type":"object"},{"type":"null"}],"default":null},"automatic":{"anyOf":[{"type":"boolean"},{"type":"null"}],"default":null},"timeout_ms":{"type":"integer","default":30000},"full":{"type":"boolean","default":false}
        }}}),
        json!({"name":"ken_check","description":"Run source contracts and retain immutable receipts. Coverage gaps, truncation, timeouts and uncertainty cannot certify success. Retrieve with run_id or compare to an earlier run.","inputSchema":{"type":"object","additionalProperties":false,"properties":{
        "rules":{"anyOf":[{"type":"array","items":{"type":"string"}},{"type":"null"}],"default":null},"path":{"type":"string","default":"."},"scope":{"type":"string","enum":["project","changes"],"default":"project"},"compare":{"type":"string","default":""},"run_id":{"type":"string","default":""},"timeout_ms":{"type":"integer","default":10000},"max_rows":{"type":"integer","default":100},"full":{"type":"boolean","default":false}
        }}}),
    ]
}
pub(super) fn call(
    paths: &ProjectPaths,
    live: &LiveTools,
    name: &str,
    raw: &RawValue,
    cancellation: &ken_query::execution::Cancellation,
) -> Result<ToolReply, String> {
    let mut input: Value = serde_json::from_str(raw.get()).map_err(|e| e.to_string())?;
    let object = input
        .as_object_mut()
        .ok_or("tool arguments must be an object")?;
    let format = object
        .remove("output_format")
        .unwrap_or_else(|| json!("compact"));
    let format = format
        .as_str()
        .filter(|format| matches!(*format, "compact" | "json"))
        .ok_or("output_format must be compact or json")?;
    let full = object.get("full").and_then(Value::as_bool).unwrap_or(false);
    let allowed = if name == "ken_rule" {
        &[
            "action",
            "rule_id",
            "definition",
            "automatic",
            "timeout_ms",
            "full",
        ][..]
    } else {
        &[
            "rules",
            "path",
            "scope",
            "compare",
            "run_id",
            "timeout_ms",
            "max_rows",
            "full",
        ][..]
    };
    if let Some(key) = object.keys().find(|key| !allowed.contains(&key.as_str())) {
        return Err(format!("unknown tool argument: {key}"));
    }
    let application = application(paths, live)?;
    let control = ken_checks_application::WorkerControl {
        cancellation: cancellation.clone(),
        ..Default::default()
    };
    if name == "ken_rule" {
        let value = application
            .manage_with_control(&input, &control)
            .map_err(|e| e.to_string())?;
        super::presentation::raw_json(
            serde_json::to_string(&value).map_err(|e| e.to_string())?,
            name,
            format,
            full,
        )
    } else {
        let report = application
            .check_with_control(&input, &control)
            .map_err(|e| e.to_string())?;
        super::presentation::raw_json(report.json().into(), name, format, full)
    }
}
