//! ken_find selects the native public application matching its response contract.
mod structural;
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
    cache_mb: Option<f64>,
    timeout_ms: Option<u64>,
    rules: Option<Vec<String>>,
    collections: Option<Vec<String>>,
    tags: Option<Vec<String>>,
    rule_files: Option<Vec<String>>,
    evidence_mode: String,
    libraries: Option<std::collections::BTreeMap<String, String>>,
    saved_query: Option<String>,
    query_name: Option<String>,
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
            cache_mb: None,
            timeout_ms: None,
            rules: None,
            collections: None,
            tags: None,
            rule_files: None,
            evidence_mode: "strict".into(),
            libraries: None,
            saved_query: None,
            query_name: None,
        }
    }
}
pub(super) fn definition() -> Value {
    let mut definition = json!({"name":"ken_find","description":"Find source files/symbols using native search, live text using literal/BM25, likely tests using the index, or route/CLI/environment wiring using prepared grammars. Text, tests and wiring need no model resources. Compact text is the default.","inputSchema":{"type":"object","additionalProperties":false,"properties":{
        "query":{"type":"string","default":""},"scope":{"type":"string","enum":["files","symbols","text","tests","wiring"],"default":"files"},
        "limit":{"anyOf":[{"type":"integer","minimum":1},{"type":"null"}],"default":null},
        "literal":{"type":"boolean","default":false},"query_language":{"type":"string","enum":["kenql/1"],"default":"kenql/1"},
        "language":{"type":"string","default":"","description":"Language filter for scope=text."},
        "path":{"type":"string","default":".","description":"Compatibility parameter for other scopes; file/symbol search covers the configured project."},
        "response_format":{"type":"string","enum":["auto","compact","legacy","evidence"],"default":"auto"},
        "output_format":{"type":"string","enum":["compact","json"],"default":"compact"},
        "purpose":{"type":"string","enum":["auto","implementation","usage","tests","documentation"],"default":"auto"},
        "max_chars":{"type":"integer","minimum":1,"default":12000},"piece_kind":{"type":"string","enum":["auto","class","module","symbol","file"],"default":"auto"},"full":{"type":"boolean","default":false}
    }}});
    let properties = &mut definition["inputSchema"]["properties"];
    properties["scope"]["enum"] = json!([
        "files",
        "symbols",
        "text",
        "tests",
        "wiring",
        "structure",
        "patterns",
        "bugs",
        "intent"
    ]);
    properties["query_language"]["enum"] = json!(["kenql/1", "kql/2"]);
    properties["path"]["description"] =
        json!("Source file or directory within the project for live structural analysis.");
    for key in ["rules", "collections", "tags", "rule_files"] {
        properties[key] = json!({"anyOf":[{"type":"array","items":{"type":"string"}},{"type":"null"}],"default":null});
    }
    for key in ["saved_query", "query_name"] {
        properties[key] = json!({"anyOf":[{"type":"string"},{"type":"null"}],"default":null});
    }
    properties["cache_mb"] =
        json!({"anyOf":[{"type":"number","minimum":0},{"type":"null"}],"default":null});
    properties["timeout_ms"] =
        json!({"anyOf":[{"type":"integer","minimum":1},{"type":"null"}],"default":null});
    properties["evidence_mode"] =
        json!({"type":"string","enum":["strict","possible"],"default":"strict"});
    properties["libraries"] = json!({"anyOf":[{"type":"object","additionalProperties":{"type":"string"}},{"type":"null"}],"default":null});
    definition["description"] = json!(
        "Find source, text, tests and wiring, or execute live structural queries, patterns and bugs with native source capture and explicit coverage and budgets. Files/symbols use best search by default; evidence uses the prepared retrieval profile and verified ranges, while legacy preserves cosine scores and historical shapes."
    );
    definition
}

pub(super) struct FindService {
    paths: ProjectPaths,
    application: SearchApplication,
    embeddings: super::embeddings::FocusedEmbeddings,
    compatibility: std::rc::Rc<crate::search::CompatibilityResources>,
}
impl FindService {
    pub(super) fn new(paths: ProjectPaths, installation: PathBuf) -> Self {
        Self {
            paths,
            embeddings: super::embeddings::FocusedEmbeddings::new(installation.clone()),
            compatibility: crate::search::CompatibilityResources::new(installation.clone()),
            application: SearchApplication::new(installation),
        }
    }
    pub(super) fn call(
        &mut self,
        raw: &RawValue,
        live: &mut super::live::LiveTools,
        cancellation: &ken_query::execution::Cancellation,
    ) -> Result<ToolReply, String> {
        let args: Arguments = serde_json::from_str(raw.get()).map_err(|e| e.to_string())?;
        if !matches!(args.output_format.as_str(), "compact" | "json") {
            return Err("output_format must be compact or json".into());
        }
        if !matches!(
            args.response_format.as_str(),
            "auto" | "compact" | "evidence" | "legacy"
        ) {
            return Err("response_format must be auto, compact, evidence or legacy".into());
        }
        if matches!(args.response_format.as_str(), "evidence" | "legacy")
            && args.piece_kind != "auto"
        {
            return Err("piece_kind requires the default or compact files/symbols search".into());
        }
        if args.response_format == "evidence" {
            if args.literal
                || !matches!(args.scope.as_str(), "files" | "symbols")
                || args.query_language != "kenql/1"
            {
                return Err("evidence responses require nonliteral scope=files or symbols".into());
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
                piece_kind: None,
            }
            .try_into()
            .map_err(|e: ken_retrieval::RetrievalError| e.to_string())?;
            let store = ken_store::ProjectStore::open(&self.paths).map_err(|e| e.to_string())?;
            let response =
                match ken_application::search_compat::SearchCompatibility::evidence_requirement(
                    store.database().connection(),
                )
                .map_err(|e| e.to_string())?
                {
                    Some(required) => required,
                    None => self
                        .compatibility
                        .owner()
                        .map_err(|e| e.to_string())?
                        .evidence(store.database().connection(), &self.paths, &request)
                        .map_err(|e| e.to_string())?,
                };
            // Explicit evidence retains its structure even when output_format
            // is the presentation boundary's default compact value.
            return serde_json::to_string_pretty(&response)
                .map(ToolReply::Json)
                .map_err(|e| e.to_string());
        }
        if args.response_format == "legacy" && args.purpose != "auto" {
            return Err("purpose requires response_format=evidence or compact".into());
        }
        if args.scope == "intent" {
            let query = args
                .query
                .to_utf8()
                .ok_or("intent query contains non-scalar Unicode")?;
            let store = ken_store::ProjectStore::open(&self.paths).map_err(|e| e.to_string())?;
            let query_owner = std::rc::Rc::new(super::embeddings::IntentQuery {
                embeddings: &self.embeddings,
                db: store.database().connection(),
            });
            let mut vectors = ken_application::embedding::IntentVectorAdapter::new(query_owner);
            let value = ken_history::intent::intent_history(
                store.database().connection(),
                &query,
                12,
                args.limit.unwrap_or(15) as i64,
                Some(self.paths.root()),
                &mut vectors,
            )
            .map_err(|e| e.to_string())?;
            let document = ken_core::tool_output::Document::parse_json(&value.to_string())
                .map_err(|e| e.to_string())?;
            return super::present(
                &document,
                "ken_find",
                if args.response_format == "legacy" {
                    "json"
                } else {
                    &args.output_format
                },
                args.full,
            );
        }
        if args.query_language == "kql/2"
            || matches!(args.scope.as_str(), "structure" | "patterns" | "bugs")
        {
            return structural::call(&self.paths, &args, live, cancellation);
        }
        if args.libraries.is_some() || args.saved_query.is_some() || args.query_name.is_some() {
            return Err(
                "libraries, saved_query and query_name require query_language=kql/2".into(),
            );
        }
        if [&args.rules, &args.collections, &args.tags, &args.rule_files]
            .iter()
            .any(|values| values.as_ref().is_some_and(|v| !v.is_empty()))
        {
            return Err("saved rule selectors require scope=structure".into());
        }
        if args.scope == "wiring" {
            if args.piece_kind != "auto"
                || args.purpose != "auto"
                || args.query_language != "kenql/1"
                || !matches!(args.response_format.as_str(), "auto" | "legacy")
            {
                return Err("native wiring search requires default purpose, piece kind and query_language=kenql/1, with response_format=auto or legacy".into());
            }
            let query = args
                .query
                .to_utf8()
                .ok_or("wiring query contains non-scalar Unicode")?;
            let nav = ken_search::navigation::IndexNavigation::open(&self.paths)
                .map_err(|e| e.to_string())?;
            let result = live.wiring(&nav, &query, args.limit.unwrap_or(10) as i64)?;
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
                || !matches!(args.response_format.as_str(), "auto" | "legacy")
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
        if !matches!(args.scope.as_str(), "files" | "symbols") {
            return Err("native ken_find currently supports scope=files or symbols".into());
        }
        if args.response_format == "legacy" {
            let store = ken_store::ProjectStore::open(&self.paths).map_err(|e| e.to_string())?;
            let response = self
                .compatibility
                .owner()
                .map_err(|e| e.to_string())?
                .legacy(
                    store.database().connection(),
                    Some(self.paths.root()),
                    &args.query,
                    &args.scope,
                    args.limit.unwrap_or(10),
                )
                .map_err(|e| e.to_string())?;
            return serde_json::to_string_pretty(&response)
                .map(ToolReply::Json)
                .map_err(|e| e.to_string());
        }
        if args.literal || args.query_language != "kenql/1" {
            return Err("semantic search requires nonliteral scope=files or symbols".into());
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
