//! A shared native tool boundary used by the command line and MCP.
mod find;
mod live;
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
        json!({"name":"ken_read","description":"Read an indexed file's symbols, imports, documentation, live source and distinguishing-term responsibility profile without model resources.","inputSchema":{"type":"object","additionalProperties":false,"required":["path"],"properties":{
            "path":{"type":"string"},"include":{"anyOf":[{"type":"array","items":{"type":"string","enum":["symbols","imports","docstrings","source","profile"]}},{"type":"null"}],"default":null},
            "qualname":{"type":"string","default":""},"start_line":{"type":"integer","default":0},"end_line":{"type":"integer","default":0},"max_chars":{"type":"integer","default":0},"output_format":{"type":"string","enum":["compact","json"],"default":"compact"}
        }}}),
        json!({"name":"ken_related","description":"Explore index neighbors/imports or live callers, callees and type relationships using prepared grammars without models. Subtypes and supertypes currently both return descendants, matching existing Ken behavior. Other relationships are pending.","inputSchema":{"type":"object","additionalProperties":false,"required":["target","relation"],"properties":{
            "target":{"type":"string"},"relation":{"type":"string","enum":["neighbors","imports","callers","callees","subtypes","supertypes"]},"limit":{"type":"integer","default":10},"depth":{"type":"integer","default":1},"min_confidence":{"type":"number","default":0.0},"full":{"type":"boolean","default":false},"output_format":{"type":"string","enum":["compact","json"],"default":"compact"}
        }}}),
        json!({"name":"ken_rank","description":"Orient in the indexed project: scopes project, architecture and changes run without model resources. Session ranking is not available in this native binding yet; choose an implemented scope explicitly.","inputSchema":{"type":"object","additionalProperties":false,"properties":{
            "scope":{"type":"string","enum":["session","changes","project","architecture"],"default":"session"},"query":{"type":"string","default":""},"verbose":{"type":"integer","default":1},"explain":{"type":"boolean","default":false},"max_chars":{"type":"integer","default":0},"output_format":{"type":"string","enum":["compact","json"],"default":"compact"}
        }}}),
    ]
}
pub(crate) enum ToolReply {
    Json(String),
    Text(String),
}
impl ToolReply {
    pub(crate) fn into_text(self) -> String {
        match self {
            Self::Json(value) | Self::Text(value) => value,
        }
    }
}
pub(crate) fn present(
    value: &Document,
    name: &str,
    format: &str,
    full: bool,
) -> Result<ToolReply, String> {
    match format {
        "json" => serde_json::to_string_pretty(value)
            .map(ToolReply::Json)
            .map_err(|e| e.to_string()),
        "compact" => Ok(ToolReply::Text(render(value, name, full))),
        _ => Err("output_format must be compact or json".into()),
    }
}
pub(crate) struct ToolService {
    find: find::FindService,
    live: live::LiveTools,
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
    #[serde(default)]
    min_confidence: f64,
}
#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
struct Rank {
    scope: String,
    #[serde(
        rename = "query",
        deserialize_with = "ken_retrieval::query::deserialize_query_text"
    )]
    _query: ken_text::PythonText,
    verbose: i64,
    explain: bool,
    #[serde(rename = "max_chars")]
    _max_chars: i64,
}
impl Default for Rank {
    fn default() -> Self {
        Self {
            scope: "session".into(),
            _query: "".into(),
            verbose: 1,
            explain: false,
            _max_chars: 0,
        }
    }
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
            find: find::FindService::new(paths.clone(), installation.clone()),
            live: live::LiveTools::new(installation),
            paths,
        }
    }
    pub(crate) fn known(name: &str) -> bool {
        ["ken_find", "ken_read", "ken_related", "ken_rank"].contains(&name)
    }
    pub(crate) fn call(&mut self, name: &str, raw: &RawValue) -> Result<ToolReply, String> {
        if name == "ken_find" {
            return self.find.call(raw, &mut self.live);
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
                if matches!(
                    request.relation.as_str(),
                    "callers" | "callees" | "subtypes" | "supertypes"
                ) {
                    let result = self.live.related(
                        &navigation,
                        &request.target,
                        &request.relation,
                        request.min_confidence,
                        request.limit,
                    )?;
                    return present(&result, name, &format, request.full);
                }
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
            "ken_rank" => {
                let request: Rank = serde_json::from_value(args).map_err(|e| e.to_string())?;
                let limit = request.verbose.max(1).saturating_mul(10);
                let result = match request.scope.as_str() {
                    "project" => navigation.project_overview(2, limit),
                    "architecture" => navigation.architecture(2, limit),
                    "changes" => navigation.changed_context(),
                    _ => return Err("native ken_rank supports scope=project, architecture or changes; session ranking is not available yet".into()),
                }.map_err(|e| e.to_string())?;
                (result, request.explain)
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
            json!({"target":a.target,"relation":a.relation,"depth":a.depth,"limit":a.limit,"min_confidence":a.min_confidence,"full":a.full,"output_format":a.output_format}),
        ),
        ToolCommand::Find(a) => (
            "ken_find",
            json!({"query":a.query,"scope":a.scope,"limit":a.limit,"literal":a.literal,"language":a.language,"purpose":a.purpose,"max_chars":a.max_chars,"piece_kind":a.piece_kind,"response_format":a.response_format,"query_language":a.query_language,"full":a.full,"output_format":a.output_format}),
        ),
        ToolCommand::Rank(a) => (
            "ken_rank",
            json!({"scope":a.scope,"query":a.query,"verbose":a.verbose,"explain":a.explain,"max_chars":a.max_chars,"output_format":a.output_format}),
        ),
    };
    if args.json || args.compact {
        value["output_format"] = json!("json");
    }
    let raw = RawValue::from_string(value.to_string())?;
    match ToolService::new(paths, installation).call(name, &raw) {
        Ok(reply) => {
            let stdout = match reply {
                ToolReply::Text(text) if args.compact => serde_json::to_string(&text)?,
                ToolReply::Json(text) if args.compact => {
                    let doc: Document = serde_json::from_str(&text)?;
                    serde_json::to_string(&doc)?
                }
                reply => reply.into_text(),
            };
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
