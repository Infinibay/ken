//! Transport adapters for native authored queries and exact calculations.
use super::{ToolReply, present};
use ken_core::{project::ProjectPaths, tool_output::Document};
use ken_structural::application::{
    catalog::Catalog,
    modules::{ModuleRegistry, module_tree},
};
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
struct QueryArgs {
    action: String,
    module: String,
    source: String,
    description: Option<String>,
    expected_revision: Option<String>,
    prefix: String,
    limit: i64,
    offset: i64,
}
impl Default for QueryArgs {
    fn default() -> Self {
        Self {
            action: "list".into(),
            module: String::new(),
            source: String::new(),
            description: None,
            expected_revision: None,
            prefix: String::new(),
            limit: 50,
            offset: 0,
        }
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Calculate {
    expression: String,
}
pub(super) fn definitions() -> Vec<Value> {
    vec![
        json!({"name":"ken_query","description":"Save, list, show or delete reusable KQL2 modules. Updates require the current revision; imported modules cannot be deleted.","inputSchema":{"type":"object","additionalProperties":false,"properties":{
        "action":{"type":"string","enum":["save","list","show","delete"],"default":"list"},"module":{"type":"string","default":""},"source":{"type":"string","default":""},"description":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null},"expected_revision":{"anyOf":[{"type":"string"},{"type":"null"}],"default":null},"prefix":{"type":"string","default":""},"limit":{"type":"integer","default":50},"offset":{"type":"integer","default":0}
        }}}),
        json!({"name":"ken_calculate","description":"Calculate exact rational arithmetic with + - * / ** and parentheses. No names, code, tools or units; results are not stored as premises.","inputSchema":{"type":"object","additionalProperties":false,"required":["expression"],"properties":{"expression":{"type":"string"}}}}),
    ]
}
pub(super) fn call(paths: &ProjectPaths, name: &str, raw: &RawValue) -> Result<ToolReply, String> {
    // Keep format handling outside domain arguments; MCP defaults to compact text.
    let mut args: Value = serde_json::from_str(raw.get()).map_err(|e| e.to_string())?;
    let object = args
        .as_object_mut()
        .ok_or("tool arguments must be an object")?;
    let format = match object.remove("output_format") {
        None => "compact".into(),
        Some(Value::String(value)) => value,
        _ => return Err("output_format must be compact or json".into()),
    };
    if !matches!(format.as_str(), "compact" | "json") {
        return Err("output_format must be compact or json".into());
    }
    let response = if name == "ken_calculate" {
        let input: Calculate = serde_json::from_value(args).map_err(|e| e.to_string())?;
        match ken_knowledge::arithmetic::calculate(&input.expression) {
            Ok(value) => value,
            Err(error) => json!({"ok":false,"error":error.to_string()}),
        }
    } else {
        let args: QueryArgs = serde_json::from_value(args).map_err(|e| e.to_string())?;
        let packaged = Catalog::packaged().map_err(|e| e.to_string())?;
        let registry = ModuleRegistry::with_packaged(paths.root(), packaged.libraries().clone())
            .map_err(|e| e.to_string())?;
        match args.action.as_str() {
            "save" => {
                if !args.module.is_empty()
                    && module_tree(&args.source).map_err(|e| e.to_string())?.module != args.module
                {
                    return Err("module conflicts with source declaration".into());
                }
                registry
                    .save(
                        &args.source,
                        args.description.as_deref(),
                        args.expected_revision.as_deref(),
                    )
                    .map_err(|e| e.to_string())?
                    .to_value(false)
            }
            "list" => {
                if !(1..=200).contains(&args.limit) || args.offset < 0 {
                    return Err("limit must be 1..200 and offset must be nonnegative".into());
                }
                let records = registry
                    .list_modules()
                    .map_err(|e| e.to_string())?
                    .into_iter()
                    .filter(|record| record.module.starts_with(&args.prefix))
                    .collect::<Vec<_>>();
                let offset = usize::try_from(args.offset).unwrap_or(usize::MAX);
                json!({"modules":records.iter().skip(offset).take(args.limit as usize).map(|record|record.to_value(false)).collect::<Vec<_>>(),"total":records.len(),"offset":args.offset,"limit":args.limit})
            }
            "show" | "delete" if args.module.is_empty() => {
                return Err("show/delete requires module".into());
            }
            "show" => registry
                .get(&args.module)
                .map_err(|e| e.to_string())?
                .to_value(true),
            "delete" => {
                registry
                    .delete(&args.module, args.expected_revision.as_deref())
                    .map_err(|e| e.to_string())?;
                json!({"deleted":args.module})
            }
            _ => return Err("action must be save/list/show/delete".into()),
        }
    };
    let document: Document =
        Document::parse_json(&response.to_string()).map_err(|e| e.to_string())?;
    present(&document, name, &format, false)
}
