//! A shared native tool boundary used by the command line and MCP.
mod authored;
mod checks;
mod embeddings;
mod extended_related;
mod find;
mod knowledge;
mod live;
mod presentation;
use crate::{
    args::{ToolCommand, ToolsArgs},
    status::CommandOutput,
};
use extended_related::Related;
use ken_core::{
    project::{DiscoveryContext, ProjectPaths, locate_project},
    tool_output::{Document, render},
};
use ken_search::navigation::{IndexNavigation, ReadRequest};
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use std::path::PathBuf;
pub(crate) fn knowledge_application(
    paths: &ProjectPaths,
    installation: PathBuf,
) -> Result<ken_application::knowledge::KnowledgeApplication, String> {
    let embeddings = std::rc::Rc::new(embeddings::FocusedEmbeddings::new(installation.clone()));
    knowledge::application(paths, installation, embeddings)
}

pub(crate) fn definitions() -> Vec<Value> {
    vec![
        find::definition(),
        json!({"name":"ken_read","description":"Read an indexed file's symbols, imports, documentation, live source and distinguishing-term responsibility profile without model resources.","inputSchema":{"type":"object","additionalProperties":false,"required":["path"],"properties":{
            "path":{"type":"string"},"include":{"anyOf":[{"type":"array","items":{"type":"string","enum":["symbols","imports","docstrings","source","profile"]}},{"type":"null"}],"default":null},
            "qualname":{"type":"string","default":""},"start_line":{"type":"integer","default":0},"end_line":{"type":"integer","default":0},"max_chars":{"type":"integer","default":0},"output_format":{"type":"string","enum":["compact","json"],"default":"compact"}
        }}}),
        json!({"name":"ken_related","description":"Explore index neighbors/imports or live callers, callees and type relationships using prepared grammars without models. Subtypes and supertypes currently both return descendants, matching existing Ken behavior. History, source contracts and scoped impact, role and access observations retain their coverage and uncertainty.","inputSchema":{"type":"object","additionalProperties":false,"required":["target","relation"],"properties":{
            "target":{"type":"string"},"relation":{"type":"string","enum":["neighbors","imports","callers","callees","subtypes","supertypes","cochange","blast_radius","clones","checks","impact","roles","available"]},"path":{"type":"string","default":"."},"from_path":{"type":"string","default":""},"timeout_ms":{"type":"number","default":10000},"limit":{"type":"integer","default":10},"depth":{"type":"integer","default":1},"min_confidence":{"type":"number","default":0.0},"full":{"type":"boolean","default":false},"output_format":{"type":"string","enum":["compact","json"],"default":"compact"}
        }}}),
        json!({"name":"ken_rank","description":"Rank the current work session, explain channel contributions, or orient in project architecture and changes. Session context uses the authenticated native daemon.","inputSchema":{"type":"object","additionalProperties":false,"properties":{
            "scope":{"type":"string","enum":["session","changes","project","architecture"],"default":"session"},"query":{"type":"string","default":""},"verbose":{"type":"integer","default":1},"explain":{"type":"boolean","default":false},"max_chars":{"type":"integer","default":0},"output_format":{"type":"string","enum":["compact","json"],"default":"compact"}
        }}}),
    ].into_iter().chain(authored::definitions()).chain(checks::definitions()).chain(knowledge::definitions()).map(|mut definition| {
        definition["inputSchema"]["properties"]["output_format"] = json!({"type":"string","enum":["compact","json"],"default":"compact"});
        definition
    }).collect()
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
    embeddings: std::rc::Rc<embeddings::FocusedEmbeddings>,
}
#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
struct Rank {
    scope: String,
    #[serde(deserialize_with = "ken_retrieval::query::deserialize_query_text")]
    query: ken_text::PythonText,
    verbose: i64,
    explain: bool,
    max_chars: i64,
}
impl Default for Rank {
    fn default() -> Self {
        Self {
            scope: "session".into(),
            query: "".into(),
            verbose: 1,
            explain: false,
            max_chars: 0,
        }
    }
}
impl ToolService {
    pub(crate) fn new(paths: ProjectPaths, installation: PathBuf) -> Self {
        Self {
            find: find::FindService::new(paths.clone(), installation.clone()),
            embeddings: std::rc::Rc::new(embeddings::FocusedEmbeddings::new(installation.clone())),
            live: live::LiveTools::new(installation),
            paths,
        }
    }
    pub(crate) fn call(&mut self, name: &str, raw: &RawValue) -> Result<ToolReply, String> {
        self.call_with_control(name, raw, Default::default())
    }
    pub(crate) fn call_with_control(
        &mut self,
        name: &str,
        raw: &RawValue,
        cancellation: ken_query::execution::Cancellation,
    ) -> Result<ToolReply, String> {
        if cancellation.is_cancelled() {
            return Err("cancelled".into());
        }
        let response = self.dispatch(name, raw, &cancellation);
        if cancellation.is_cancelled() {
            return Err("cancelled".into());
        }
        response
    }
    fn dispatch(
        &mut self,
        name: &str,
        raw: &RawValue,
        cancellation: &ken_query::execution::Cancellation,
    ) -> Result<ToolReply, String> {
        if knowledge::known(name) {
            return knowledge::call(
                &self.paths,
                &mut self.live,
                self.embeddings.clone(),
                name,
                raw,
            );
        }
        if name == "ken_find" {
            return self.find.call(raw, &mut self.live, cancellation);
        }
        if matches!(name, "ken_query" | "ken_calculate") {
            return authored::call(&self.paths, name, raw);
        }
        if matches!(name, "ken_rule" | "ken_check") {
            return checks::call(&self.paths, &self.live, name, raw, cancellation);
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
        if name == "ken_related" {
            let request: Related = serde_json::from_value(args).map_err(|e| e.to_string())?;
            return extended_related::call(&self.paths, request, &mut self.live, &format);
        }
        if name == "ken_rank"
            && object
                .get("scope")
                .and_then(Value::as_str)
                .unwrap_or("session")
                == "session"
        {
            let request: Rank = serde_json::from_value(args).map_err(|e| e.to_string())?;
            let query = request
                .query
                .to_utf8()
                .ok_or("session query contains non-scalar Unicode")?;
            let value = crate::runtime::session_rank(
                &self.paths,
                self.live.installation(),
                &query,
                request.verbose,
                request.max_chars,
                request.explain,
            )
            .map_err(|e| e.to_string())?;
            let document = Document::parse_json(&value.to_string()).map_err(|e| e.to_string())?;
            return present(&document, name, &format, request.explain);
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
            "ken_rank" => {
                let request: Rank = serde_json::from_value(args).map_err(|e| e.to_string())?;
                let limit = request.verbose.max(1).saturating_mul(10);
                let result = match request.scope.as_str() {
                    "project" => navigation.project_overview(2, limit),
                    "architecture" => navigation.architecture(2, limit),
                    "changes" => navigation.changed_context(),
                    _ => {
                        return Err(
                            "scope must be session, project, architecture or changes".into()
                        );
                    }
                }
                .map_err(|e| e.to_string())?;
                (result, request.explain)
            }
            _ => return Err(format!("Unknown tool: {name}")),
        };
        present(&result, name, &format, full)
    }
}
/// Project arguments are distinct from source selection. A source selector only
/// recovers an old native post-tool project spelling when cwd has no project.
fn project_paths(
    args: &ToolsArgs,
    context: &DiscoveryContext,
) -> Result<ProjectPaths, ken_core::project::ProjectError> {
    if let Some(start) = args
        .path
        .as_deref()
        .or_else(|| args.command.as_ref().and_then(ToolCommand::project_path))
    {
        return match locate_project(start, context)? {
            Some(paths) => Ok(paths),
            None => ProjectPaths::at(start, context),
        };
    }
    let current = std::path::Path::new(".");
    if let Some(paths) = locate_project(current, context)? {
        return Ok(paths);
    }
    if let Some(source) = args
        .command
        .as_ref()
        .and_then(ToolCommand::source_path)
        .filter(|s| !s.is_empty() && *s != ".")
        && let Some(paths) = locate_project(std::path::Path::new(source), context)?
    {
        return Ok(paths);
    }
    ProjectPaths::at(current, context)
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
    let paths = project_paths(&args, context)?;
    if !paths.meta().is_file() {
        return Ok(CommandOutput {
            code: 1,
            stdout: String::new(),
            stderr: format!("error: no .ken project at {}\n", paths.root().display()),
        });
    }
    let (name, mut value) = match args.command.unwrap() {
        ToolCommand::Knowledge(command) => command.request()?,
        ToolCommand::Rule(a) => (
            "ken_rule",
            json!({"action":a.action,"rule_id":a.rule_id,"definition":a.definition.map(|text|serde_json::from_str::<Value>(&text)).transpose()?,"automatic":if a.no_automatic{Some(false)}else{a.automatic},"timeout_ms":a.timeout_ms,"full":a.full,"output_format":a.output_format}),
        ),
        ToolCommand::Check(a) => (
            "ken_check",
            json!({"rules":a.rules,"path":a.source_path,"scope":a.scope,"compare":a.compare,"run_id":a.run_id,"timeout_ms":a.timeout_ms,"max_rows":a.max_rows,"full":a.full,"output_format":a.output_format}),
        ),
        ToolCommand::Query(a) => (
            "ken_query",
            json!({"action":a.action,"module":a.module,"source":a.source,"description":a.description,"expected_revision":a.expected_revision,"prefix":a.prefix,"limit":a.limit,"offset":a.offset,"output_format":a.output_format}),
        ),
        ToolCommand::Calculate(a) => (
            "ken_calculate",
            json!({"expression":a.expression,"output_format":a.output_format}),
        ),
        ToolCommand::Read(a) => (
            "ken_read",
            json!({"path":a.file,"include":a.include,"qualname":a.qualname,"start_line":a.start_line,"end_line":a.end_line,"max_chars":a.max_chars,"output_format":a.output_format}),
        ),
        ToolCommand::Related(a) => (
            "ken_related",
            json!({"target":a.target,"relation":a.relation,"depth":a.depth,"limit":a.limit,"min_confidence":a.min_confidence,"full":a.full,"output_format":a.output_format,"path":a.analysis_path,"from_path":a.from_path,"timeout_ms":a.timeout_ms}),
        ),
        ToolCommand::Find(a) => (
            "ken_find",
            json!({"query":a.query_flag.or(a.query).unwrap_or_default(),"scope":a.scope,"limit":a.limit,"literal":a.literal,"language":a.language,"purpose":a.purpose,"max_chars":a.max_chars,"piece_kind":a.piece_kind,"response_format":a.response_format,"query_language":a.query_language,"full":a.full,"output_format":a.output_format,"path":a.source_path,"cache_mb":a.cache_mb,"timeout_ms":a.timeout_ms,"rules":a.rules,"collections":a.collections,"tags":a.tags,"rule_files":a.rule_files,"evidence_mode":a.evidence_mode,"saved_query":a.saved_query,"query_name":a.query_name,"libraries":a.libraries.map(|text|serde_json::from_str::<Value>(&text)).transpose()?}),
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
                ToolReply::Json(text) if args.compact => ken_text::json::compact(&text)?,
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
