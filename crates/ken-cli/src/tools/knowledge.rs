//! Public memory, reasoning and responsibility calls compose application owners.
use super::{ToolReply, embeddings::FocusedEmbeddings, live::LiveTools};
use ken_application::knowledge::{KnowledgeApplication, SessionSignals};
use ken_core::{project::ProjectPaths, tool_output::Document};
use serde_json::{Value, json, value::RawValue};
use std::{path::PathBuf, rc::Rc};
fn definition(name: &str, description: &str, required: &[&str], properties: Value) -> Value {
    json!({"name":name,"description":description,"inputSchema":{"type":"object","additionalProperties":false,"required":required,"properties":properties}})
}
pub(super) fn definitions() -> Vec<Value> {
    let mut remember = json!({"topic":{"type":"string"},"content":{"type":"string","default":""},"action":{"type":"string","enum":["save","forget","dismiss"],"default":"save"},"tags":{"anyOf":[{"type":"array","items":{"type":"string"}},{"type":"null"}],"default":null},"reason":{"type":"string","default":""},"justification":{"anyOf":[{"type":"object"},{"type":"null"}],"default":null},"check_run":{"type":"string","default":""}});
    let mut recall = json!({"query":{"type":"string","default":""},"path":{"type":"string","default":""},"topic":{"type":"string","default":""},"tag":{"type":"string","default":""},"limit":{"type":"integer","default":5},"min_score":{"type":"number","default":0.},"detail":{"type":"string","enum":["full","summary","answer"],"default":"full"},"max_chars":{"type":"integer","default":3000}});
    for key in [
        "anchor_file",
        "anchor_symbol",
        "anchor_tool",
        "anchor_error",
    ] {
        remember[key] = json!({"type":"string","default":""});
        recall[key] = json!({"type":"string","default":""});
    }
    vec![
        definition(
            "ken_remember",
            "Persist reusable findings with anchors and live dependency justification; forget by topic or dismiss a path in the active daemon session.",
            &["topic"],
            remember,
        ),
        definition(
            "ken_recall",
            "Recall findings by anchors, exact topic, path, semantic query or tag, retaining source validity and check receipt freshness.",
            &[],
            recall,
        ),
        definition(
            "ken_reason_record",
            "Persist or retract an attributed premise bundle in an explicit reasoning context.",
            &["source"],
            json!({"source":{"type":"string"},"facts":{"anyOf":[{"type":"array","items":{"type":"object"}},{"type":"null"}],"default":null},"rules":{"anyOf":[{"type":"array","items":{"type":"object"}},{"type":"null"}],"default":null},"evidence":{"type":"string","default":""},"context":{"type":"string","default":"main"},"retract":{"type":"boolean","default":false}}),
        ),
        definition(
            "ken_reason",
            "Ask persistent scoped reasoning with resumable bounded inference, support, opposition, proof links and conditional assumptions.",
            &["question"],
            json!({"question":{"type":"string"},"goal":{"anyOf":[{"type":"object"},{"type":"null"}],"default":null},"context":{"type":"string","default":"main"},"budget":{"type":"integer","default":1000},"seed":{"type":"integer","default":7},"assumptions":{"anyOf":[{"type":"array","items":{"type":"object"}},{"type":"null"}],"default":null}}),
        ),
        definition(
            "ken_who",
            "Find responsibility hypotheses in current documentation, with counterevidence, explicit assumptions and optional bounded structural observations. Scores are uncalibrated, not probabilities or proof.",
            &["question"],
            json!({"question":{"type":"string"},"path":{"type":"string","default":"."},"hypotheses":{"anyOf":[{"type":"array","items":{"type":"string"}},{"type":"null"}],"default":null},"limit":{"type":"integer","default":3},"include_tests":{"type":"boolean","default":false},"full":{"type":"boolean","default":false},"verify":{"type":"boolean","default":true},"timeout_ms":{"type":"number","default":3000}}),
        ),
    ]
}
pub(super) fn known(name: &str) -> bool {
    matches!(
        name,
        "ken_remember" | "ken_recall" | "ken_reason_record" | "ken_reason" | "ken_who"
    )
}
struct DaemonSignals {
    paths: ProjectPaths,
    installation: PathBuf,
}
impl SessionSignals for DaemonSignals {
    fn dismiss(&self, target: &str, reason: &str) -> ken_knowledge::Result<Value> {
        let client = crate::runtime::client(&self.paths, &self.installation).map_err(error)?;
        if client
            .health()
            .as_ref()
            .and_then(|v| v["sessions_active"].as_u64())
            .unwrap_or(0)
            == 0
        {
            return Ok(
                json!({"ok":false,"error":"no active session — open a coding agent inside the project and try again"}),
            );
        }
        Ok(client
            .post(
                "/interactions/dismiss",
                &json!({"target":target,"reason":reason}),
            )
            .map_err(error)?
            .unwrap_or_else(|| json!({"ok":false,"error":"daemon unreachable"})))
    }
}
fn error(e: impl std::fmt::Display) -> ken_knowledge::Error {
    ken_knowledge::Error::Invalid(e.to_string())
}
fn valid(value: &Value, schema: &Value) -> bool {
    if let Some(options) = schema["anyOf"].as_array() {
        return options.iter().any(|s| valid(value, s));
    }
    let typed = match schema["type"].as_str() {
        Some("string") => value.is_string(),
        Some("boolean") => value.is_boolean(),
        Some("object") => value.is_object(),
        Some("array") => value.is_array(),
        Some("integer") => value.as_i64().is_some() || value.as_u64().is_some(),
        Some("number") => value.is_number(),
        Some("null") => value.is_null(),
        _ => true,
    };
    typed
        && schema["enum"]
            .as_array()
            .is_none_or(|options| options.contains(value))
        && value
            .as_array()
            .is_none_or(|items| items.iter().all(|v| valid(v, &schema["items"])))
}
fn checked(name: &str, raw: &RawValue) -> Result<(Value, String), String> {
    let mut input: Value = serde_json::from_str(raw.get()).map_err(|e| e.to_string())?;
    let object = input
        .as_object_mut()
        .ok_or("tool arguments must be an object")?;
    let format = match object.remove("output_format") {
        None => "compact".to_owned(),
        Some(Value::String(s)) if matches!(s.as_str(), "compact" | "json") => s,
        _ => return Err("output_format must be compact or json".into()),
    };
    let schema = definitions()
        .into_iter()
        .find(|v| v["name"] == name)
        .ok_or("unknown knowledge tool")?;
    for (key, value) in object.iter() {
        let property = &schema["inputSchema"]["properties"][key];
        if property.is_null() {
            return Err(format!("unknown tool argument: {key}"));
        }
        if !valid(value, property) {
            return Err(format!("invalid {key} argument"));
        }
    }
    for key in schema["inputSchema"]["required"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
    {
        if !object.contains_key(key) {
            return Err(format!("{key} is required"));
        }
    }
    Ok((input, format))
}
fn present(raw: String, name: &str, format: &str, full: bool) -> Result<ToolReply, String> {
    if format == "json" {
        return Ok(ToolReply::Json(raw));
    }
    match Document::parse_json(&raw) {
        Ok(document) => super::present(&document, name, format, full),
        Err(_) => Ok(ToolReply::Json(raw)),
    }
}
fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .try_into()
        .unwrap_or(i64::MAX)
}
pub(super) fn application(
    paths: &ProjectPaths,
    installation: PathBuf,
    embeddings: Rc<FocusedEmbeddings>,
) -> Result<KnowledgeApplication, String> {
    let signals = Rc::new(DaemonSignals {
        paths: paths.clone(),
        installation: installation.clone(),
    });
    let check_paths = paths.clone();
    Ok(
        KnowledgeApplication::new(paths.root(), embeddings, signals, None)
            .map_err(|e| e.to_string())?
            .with_checks_provider(move || {
                super::checks::application(&check_paths, &LiveTools::new(installation.clone()))
                    .map_err(error)
            }),
    )
}
pub(super) fn call(
    paths: &ProjectPaths,
    live: &mut LiveTools,
    embeddings: Rc<FocusedEmbeddings>,
    name: &str,
    raw: &RawValue,
) -> Result<ToolReply, String> {
    let (mut input, format) = checked(name, raw)?;
    let application = application(paths, live.installation().into(), embeddings.clone())?;
    if name == "ken_reason_record" {
        let connection = rusqlite::Connection::open(paths.root().join(".ken/reasoning.sqlite"))
            .map_err(|e| e.to_string())?;
        let value = application
            .reason_record(&connection, &input)
            .map_err(|e| e.to_string())?;
        return present(value.to_string(), name, &format, false);
    }
    let store = ken_store::ProjectStore::open(paths).map_err(|e| e.to_string())?;
    let connection = store.database().connection();
    if name == "ken_who" {
        let full = input.get("full").and_then(Value::as_bool).unwrap_or(false);
        let options = ken_application::responsibility::WhoOptions {
            full,
            verify: input.get("verify").and_then(Value::as_bool).unwrap_or(true),
            timeout_ms: input
                .get("timeout_ms")
                .and_then(Value::as_f64)
                .unwrap_or(3000.),
        };
        for key in ["full", "verify", "timeout_ms"] {
            input.as_object_mut().unwrap().remove(key);
        }
        if input["hypotheses"].is_null() {
            input.as_object_mut().unwrap().remove("hypotheses");
        }
        let request = serde_json::from_value(input).map_err(|e| e.to_string())?;
        let resources = embeddings.resources().map_err(|e| e.to_string())?;
        let catalog =
            ken_structural::application::catalog::Catalog::packaged().map_err(|e| e.to_string())?;
        let application = ken_application::responsibility::WhoApplication::new(
            paths.root(),
            resources.as_ref().clone(),
            live.shared_catalog()?,
            catalog.libraries().clone(),
        )
        .map_err(|e| e.to_string())?;
        let result = application
            .who(connection, &request, &options)
            .map_err(|e| e.to_string())?;
        return present(
            result.to_json_string().map_err(|e| e.to_string())?,
            name,
            &format,
            full,
        );
    }
    let value = match name {
        "ken_remember" => application.remember(connection, &input, now()),
        "ken_recall" => application.recall(connection, &input, now()),
        "ken_reason" => {
            let reasoning = rusqlite::Connection::open(paths.root().join(".ken/reasoning.sqlite"))
                .map_err(|e| e.to_string())?;
            application.reason(connection, &reasoning, &input, now())
        }
        _ => return Err(format!("Unknown tool: {name}")),
    }
    .map_err(|e| e.to_string())?;
    present(value.to_string(), name, &format, false)
}
