//! The implemented ken_find subset delegates to the shared public application.
use ken_core::project::ProjectPaths;
use ken_retrieval::query::{SearchOptions, SearchRequest};
use ken_search::public::SearchApplication;
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json, value::RawValue};
use std::path::PathBuf;

#[derive(Deserialize)]
#[serde(default, deny_unknown_fields)]
struct Arguments {
    #[serde(deserialize_with = "ken_retrieval::query::deserialize_query_text")]
    query: PythonText,
    scope: String,
    limit: Option<isize>,
    literal: bool,
    query_language: String,
    #[serde(rename = "path")]
    _path: String,
    response_format: String,
    output_format: String,
    purpose: String,
    max_chars: isize,
    piece_kind: String,
    full: bool,
}
impl Default for Arguments {
    fn default() -> Self {
        Self {
            query: "".into(),
            scope: "files".into(),
            limit: None,
            literal: false,
            query_language: "kenql/1".into(),
            _path: ".".into(),
            response_format: "auto".into(),
            output_format: "compact".into(),
            purpose: "auto".into(),
            max_chars: 12000,
            piece_kind: "auto".into(),
            full: false,
        }
    }
}
pub(super) fn definition() -> Value {
    json!({"name":"ken_find","description":"Find source files or symbols using the complete native search engine. Search the configured project; compact text is the default. Other Ken scopes are not available in this native binding yet.","inputSchema":{"type":"object","additionalProperties":false,"properties":{
        "query":{"type":"string","default":""},"scope":{"type":"string","enum":["files","symbols"],"default":"files"},
        "limit":{"anyOf":[{"type":"integer","minimum":1},{"type":"null"}],"default":null},
        "literal":{"type":"boolean","default":false},"query_language":{"type":"string","enum":["kenql/1"],"default":"kenql/1"},
        "path":{"type":"string","default":".","description":"Compatibility parameter for other scopes; file/symbol search covers the configured project."},
        "response_format":{"type":"string","enum":["auto","compact"],"default":"auto"},
        "output_format":{"type":"string","enum":["compact","json"],"default":"compact"},
        "purpose":{"type":"string","enum":["auto","implementation","usage","tests","documentation"],"default":"auto"},
        "max_chars":{"type":"integer","minimum":1,"default":12000},"piece_kind":{"type":"string","enum":["auto","class","module","symbol","file"],"default":"auto"},"full":{"type":"boolean","default":false}
    }}})
}
pub(super) struct FindService {
    paths: ProjectPaths,
    application: SearchApplication,
}
impl FindService {
    pub(super) fn new(paths: ProjectPaths, installation: PathBuf) -> Self {
        Self {
            paths,
            application: SearchApplication::new(installation),
        }
    }
    pub(super) fn call(&mut self, raw: &RawValue) -> Result<String, String> {
        let args: Arguments = serde_json::from_str(raw.get()).map_err(|e| e.to_string())?;
        if !matches!(args.scope.as_str(), "files" | "symbols") {
            return Err("native ken_find currently supports scope=files or symbols".into());
        }
        if args.literal || args.query_language != "kenql/1" {
            return Err("semantic search requires nonliteral scope=files or symbols".into());
        }
        if !matches!(args.response_format.as_str(), "auto" | "compact") {
            return Err(
                "this compatibility response mode is not available in native MCP yet".into(),
            );
        }
        if !matches!(args.output_format.as_str(), "compact" | "json") {
            return Err("output_format must be compact or json".into());
        }
        let request: SearchRequest = SearchOptions {
            query: args.query,
            target: if args.scope == "files" {
                "file"
            } else {
                "symbol"
            }
            .into(),
            purpose: args.purpose,
            limit: args.limit.unwrap_or(10),
            max_chars: args.max_chars,
            explain: args.full,
            piece_kind: (args.piece_kind != "auto").then_some(args.piece_kind),
        }
        .try_into()
        .map_err(|e: ken_retrieval::RetrievalError| e.to_string())?;
        let response = self
            .application
            .find(&self.paths, &request)
            .map_err(|e| e.to_string())?;
        if args.output_format == "json" && args.response_format != "compact" {
            serde_json::to_string_pretty(&response).map_err(|e| e.to_string())
        } else {
            Ok(response.render(args.full))
        }
    }
}
