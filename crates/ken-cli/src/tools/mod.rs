//! A shared native tool boundary used by the command line and MCP.
mod find;
use crate::{
    args::{ToolCommand, ToolsArgs},
    status::CommandOutput,
};
use ken_core::{
    project::{DiscoveryContext, ProjectPaths, locate_project},
    tool_output::{Document, render},
};
use ken_search::navigation::{IndexNavigation, ReadRequest};
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use std::path::PathBuf;

pub(crate) fn definitions() -> Vec<Value> {
    vec![
        find::definition(),
        json!({"name":"ken_read","description":"Read an indexed file's symbols, imports, documentation and live source without model resources. File profiles are not available yet.","inputSchema":{"type":"object","additionalProperties":false,"required":["path"],"properties":{
            "path":{"type":"string"},"include":{"anyOf":[{"type":"array","items":{"type":"string","enum":["symbols","imports","docstrings","source"]}},{"type":"null"}],"default":null},
            "qualname":{"type":"string","default":""},"start_line":{"type":"integer","default":0},"end_line":{"type":"integer","default":0},"max_chars":{"type":"integer","default":0},"output_format":{"type":"string","enum":["compact","json"],"default":"compact"}
        }}}),
        json!({"name":"ken_related","description":"Explore indexed neighbors or a bounded import graph. Other relationships are not available in the native binding yet.","inputSchema":{"type":"object","additionalProperties":false,"required":["target","relation"],"properties":{
            "target":{"type":"string"},"relation":{"type":"string","enum":["neighbors","imports"]},"limit":{"type":"integer","default":10},"depth":{"type":"integer","default":1},"full":{"type":"boolean","default":false},"output_format":{"type":"string","enum":["compact","json"],"default":"compact"}
        }}}),
    ]
}
pub(crate) fn present(
    value: &Document,
    name: &str,
    format: &str,
    full: bool,
) -> Result<String, String> {
    match format {
        "json" => serde_json::to_string_pretty(value).map_err(|e| e.to_string()),
        "compact" => Ok(render(value, name, full)),
        _ => Err("output_format must be compact or json".into()),
    }
}
pub(crate) struct ToolService {
    find: find::FindService,
    paths: ProjectPaths,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Related {
    target: String,
    relation: String,
    #[serde(default = "ten")]
    limit: i64,
    #[serde(default = "one")]
    depth: i64,
    #[serde(default)]
    full: bool,
}
fn ten() -> i64 {
    10
}
fn one() -> i64 {
    1
}
impl ToolService {
    pub(crate) fn new(paths: ProjectPaths, installation: PathBuf) -> Self {
        Self {
            find: find::FindService::new(paths.clone(), installation),
            paths,
        }
    }
    pub(crate) fn known(name: &str) -> bool {
        ["ken_find", "ken_read", "ken_related"].contains(&name)
    }
    pub(crate) fn call(&mut self, name: &str, raw: &RawValue) -> Result<String, String> {
        if name == "ken_find" {
            return self.find.call(raw);
        }
        let mut args: Value = serde_json::from_str(raw.get()).map_err(|e| e.to_string())?;
        let object = args
            .as_object_mut()
            .ok_or("tool arguments must be an object")?;
        let format = match object.remove("output_format") {
            None => "compact".to_owned(),
            Some(Value::String(v)) => v,
            _ => return Err("output_format must be compact or json".into()),
        };
        if !matches!(format.as_str(), "compact" | "json") {
            return Err("output_format must be compact or json".into());
        }
        let navigation = IndexNavigation::open(&self.paths).map_err(|e| e.to_string())?;
        let (result, full) = match name {
            "ken_read" => {
                if !object.contains_key("path") {
                    return Err("path is required".into());
                }
                let request: ReadRequest =
                    serde_json::from_value(args).map_err(|e| e.to_string())?;
                (navigation.read(&request).map_err(|e| e.to_string())?, false)
            }
            "ken_related" => {
                let request: Related = serde_json::from_value(args).map_err(|e| e.to_string())?;
                (
                    navigation
                        .related(
                            &request.target,
                            &request.relation,
                            request.depth,
                            request.limit,
                        )
                        .map_err(|e| e.to_string())?,
                    request.full,
                )
            }
            _ => return Err(format!("Unknown tool: {name}")),
        };
        present(&result, name, &format, full)
    }
}
pub fn run(
    args: ToolsArgs,
    installation: PathBuf,
    context: &DiscoveryContext,
) -> Result<CommandOutput, Box<dyn std::error::Error>> {
    if args.list || args.command.is_none() {
        return Ok(CommandOutput {
            code: 0,
            stdout: definitions()
                .iter()
                .map(|v| {
                    format!(
                        "{}  {}",
                        v["name"].as_str().unwrap(),
                        v["description"].as_str().unwrap()
                    )
                })
                .collect::<Vec<_>>()
                .join("\n")
                + "\n",
            stderr: String::new(),
        });
    }
    let paths = match locate_project(&args.path, context)? {
        Some(paths) => paths,
        None => ProjectPaths::at(&args.path, context)?,
    };
    if !paths.meta().is_file() {
        return Ok(CommandOutput {
            code: 1,
            stdout: String::new(),
            stderr: format!("error: no .ken project at {}\n", paths.root().display()),
        });
    }
    let (name, mut value) = match args.command.unwrap() {
        ToolCommand::Read(a) => (
            "ken_read",
            json!({"path":a.file,"include":a.include,"qualname":a.qualname,"start_line":a.start_line,"end_line":a.end_line,"max_chars":a.max_chars,"output_format":a.output_format}),
        ),
        ToolCommand::Related(a) => (
            "ken_related",
            json!({"target":a.target,"relation":a.relation,"depth":a.depth,"limit":a.limit,"full":a.full,"output_format":a.output_format}),
        ),
        ToolCommand::Find(a) => (
            "ken_find",
            json!({"query":a.query,"scope":a.scope,"limit":a.limit,"literal":a.literal,"purpose":a.purpose,"max_chars":a.max_chars,"piece_kind":a.piece_kind,"response_format":a.response_format,"query_language":a.query_language,"full":a.full,"output_format":a.output_format}),
        ),
    };
    if args.json || args.compact {
        value["output_format"] = json!("json");
    }
    let raw = RawValue::from_string(value.to_string())?;
    match ToolService::new(paths, installation).call(name, &raw) {
        Ok(mut stdout) => {
            if args.compact {
                let doc: Document = serde_json::from_str(&stdout)?;
                stdout = serde_json::to_string(&doc)?;
            }
            Ok(CommandOutput {
                code: 0,
                stdout: stdout + "\n",
                stderr: String::new(),
            })
        }
        Err(error) => Ok(CommandOutput {
            code: 1,
            stdout: String::new(),
            stderr: format!("error: {name} failed: {error}\n"),
        }),
    }
}
