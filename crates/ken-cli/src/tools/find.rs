//! The implemented ken_find subset delegates to the shared public application.
use super::ToolReply;
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
    language: String,
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
            language: String::new(),
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
    json!({"name":"ken_find","description":"Find source files or symbols using the native search engine, live text using literal or BM25 search, or likely tests using the index. Text and test search need no model resources. Compact text is the default.","inputSchema":{"type":"object","additionalProperties":false,"properties":{
        "query":{"type":"string","default":""},"scope":{"type":"string","enum":["files","symbols","text","tests"],"default":"files"},
        "limit":{"anyOf":[{"type":"integer","minimum":1},{"type":"null"}],"default":null},
        "literal":{"type":"boolean","default":false},"query_language":{"type":"string","enum":["kenql/1"],"default":"kenql/1"},
        "language":{"type":"string","default":"","description":"Language filter for scope=text."},
        "path":{"type":"string","default":".","description":"Compatibility parameter for other scopes; file/symbol search covers the configured project."},
        "response_format":{"type":"string","enum":["auto","compact","legacy"],"default":"auto"},
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
    pub(super) fn call(&mut self, raw: &RawValue) -> Result<ToolReply, String> {
        let args: Arguments = serde_json::from_str(raw.get()).map_err(|e| e.to_string())?;
        if !matches!(args.output_format.as_str(), "compact" | "json") {
            return Err("output_format must be compact or json".into());
        }
        if args.scope == "text" {
            if args.piece_kind != "auto"
                || args.purpose != "auto"
                || args.query_language != "kenql/1"
                || !matches!(args.response_format.as_str(), "auto" | "legacy")
            {
                return Err("native text search requires default purpose, piece kind and query_language=kenql/1, with response_format=auto or legacy".into());
            }
            let query = args
                .query
                .to_utf8()
                .ok_or("text query contains non-scalar Unicode")?;
            let result = ken_search::text_search::WorktreeTextSearch::new(self.paths.clone())
                .find(
                    &query,
                    args.literal,
                    &args.language,
                    args.limit.unwrap_or(10) as i64,
                )
                .map_err(|e| e.to_string())?;
            return super::present(
                &result,
                "ken_find",
                if args.response_format == "legacy" {
                    "json"
                } else {
                    &args.output_format
                },
                args.full,
            );
        }
        if args.scope == "tests" {
            if args.piece_kind != "auto"
                || args.purpose != "auto"
                || args.response_format != "auto"
                || args.query_language != "kenql/1"
            {
                return Err("native test discovery requires the default response, purpose and piece kind and query_language=kenql/1".into());
            }
            let query = args
                .query
                .to_utf8()
                .ok_or("test target contains non-scalar Unicode")?;
            let navigation = ken_search::navigation::IndexNavigation::open(&self.paths)
                .map_err(|e| e.to_string())?;
            let result = navigation
                .test_search(&query, args.limit.unwrap_or(10) as i64)
                .map_err(|e| e.to_string())?;
            return super::present(&result, "ken_find", &args.output_format, args.full);
        }
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
            serde_json::to_string_pretty(&response)
                .map(ToolReply::Json)
                .map_err(|e| e.to_string())
        } else {
            Ok(ToolReply::Text(response.render(args.full)))
        }
    }
}
