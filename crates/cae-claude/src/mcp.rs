//! `cae-claude mcp` — minimal stdio JSON-RPC 2.0 MCP server. Exposes
//! one tool, `query_context`, that calls the engine's `/rank` endpoint
//! with `include_text=true` and formats the chunks as a single text
//! block ready to drop into a model prompt.
//!
//! The MCP transport is line-delimited JSON: each request is one
//! object on stdin, each response one object on stdout. We hand-roll
//! the protocol (vs. pulling in a SDK) because the surface we need is
//! tiny — three methods (`initialize`, `tools/list`, `tools/call`) and
//! one notification (`notifications/initialized`). Using a SDK would
//! drag in async runtimes we don't need here.

use anyhow::{anyhow, Context, Result};
use serde_json::{json, Value};
use std::io::{BufRead, Write};

use crate::client::EngineClient;
use crate::install::{find_state_root, load_state};

const PROTOCOL_VERSION: &str = "2024-11-05";
const SERVER_NAME: &str = "cae";
const SERVER_VERSION: &str = "0.1.0";

pub fn run() -> Result<()> {
    // Resolve project state once at startup. Without it the MCP can
    // technically still serve `tools/list`, but `query_context` calls
    // would always fail. Better to fail fast.
    let cwd = std::env::current_dir().context("get cwd")?;
    let Some(state_root) = find_state_root(&cwd) else {
        return Err(anyhow!(
            "no .claude/cae-state.json found from {} upward — run `cae-claude install` first",
            cwd.display()
        ));
    };
    let state = load_state(&state_root)?;
    let client = EngineClient::new(&state.engine_url);

    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(e) => {
                eprintln!("cae-claude mcp: stdin error: {e}");
                break;
            }
        };
        if line.trim().is_empty() {
            continue;
        }
        let req: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("cae-claude mcp: bad JSON: {e}");
                continue;
            }
        };
        let id = req.get("id").cloned();
        let method = req.get("method").and_then(|m| m.as_str()).unwrap_or("");

        // Notifications carry no `id` and expect no response.
        let is_notification = id.is_none();

        let response = match method {
            "initialize" => handle_initialize(),
            "tools/list" => handle_tools_list(),
            "tools/call" => handle_tools_call(&req, &client, &state),
            "notifications/initialized" | "notifications/cancelled" => {
                // No response for notifications.
                if is_notification {
                    continue;
                }
                error_response(id.clone(), -32601, "method not found")
            }
            "ping" => Ok(json!({})),
            _ => Err(anyhow!("method not found: {method}")),
        };

        if is_notification {
            continue;
        }

        let envelope = match response {
            Ok(result) => json!({
                "jsonrpc": "2.0",
                "id": id,
                "result": result,
            }),
            Err(e) => json!({
                "jsonrpc": "2.0",
                "id": id,
                "error": {"code": -32603, "message": e.to_string()},
            }),
        };
        let line = serde_json::to_string(&envelope)?;
        stdout.write_all(line.as_bytes())?;
        stdout.write_all(b"\n")?;
        stdout.flush()?;
    }
    Ok(())
}

fn handle_initialize() -> Result<Value> {
    Ok(json!({
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {
            "tools": {}
        },
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        }
    }))
}

fn handle_tools_list() -> Result<Value> {
    Ok(json!({
        "tools": [
            {
                "name": "query_context",
                "description": "Semantic search over the indexed codebase. Returns ranked \
                                citations (path:line + qualified_name) — NOT the chunk text \
                                by default. Use for natural-language queries when you don't \
                                know the symbol name (e.g. 'JWT validation middleware', \
                                'how the linter handles vowel sounds'). Combines semantic \
                                similarity, prior access patterns in this session, and graph \
                                proximity. Then Read the 1-3 citations that look most relevant. \
                                Set include_text=true only when you specifically need the \
                                snippet and don't want to Read the file.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural-language description of what you're looking for."
                        },
                        "k": {
                            "type": "integer",
                            "description": "Max citations. Default 5. Cap 10.",
                            "default": 5
                        },
                        "include_text": {
                            "type": "boolean",
                            "description": "If true, include chunk text. Default false.",
                            "default": false
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "search_symbols",
                "description": "Exact / fuzzy lookup of a symbol by name (function, class, \
                                method, struct, trait, etc.). Use this when you ALREADY KNOW \
                                the symbol name and want to jump to it — much cheaper and \
                                more precise than semantic search. Substring + last-segment \
                                match: 'validate' matches 'User::validate' and 'Form::validate'. \
                                Returns citations sorted by closeness (exact → last-segment → \
                                substring). No chunk text — Read the citation if you need it.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Symbol name or fragment. E.g. 'AnA', 'validate', \
                                            'starts_with_vowel'."
                        },
                        "k": {
                            "type": "integer",
                            "description": "Max matches. Default 10.",
                            "default": 10
                        }
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "list_files",
                "description": "Rank FILE PATHS (not chunks) by relevance to a natural-language \
                                query. Aggregates chunk-level scores per file, so a file with \
                                several relevant sections wins over one with a single hit. Use \
                                instead of Glob/find when you want orientation at the file \
                                level — 'which files implement linting?' → ranked list of \
                                paths. Returns no text, no line numbers — just paths and a \
                                relative score.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural-language description of what the files \
                                            should be about."
                        },
                        "k": {
                            "type": "integer",
                            "description": "Max paths. Default 10.",
                            "default": 10
                        }
                    },
                    "required": ["query"]
                }
            }
        ]
    }))
}

fn handle_tools_call(
    req: &Value,
    client: &EngineClient,
    state: &crate::install::State,
) -> Result<Value> {
    let params = req.get("params").context("missing params")?;
    let name = params
        .get("name")
        .and_then(|n| n.as_str())
        .context("missing params.name")?;
    let args = params
        .get("arguments")
        .cloned()
        .unwrap_or_else(|| json!({}));

    let text = match name {
        "query_context" => handle_query_context(&args, client, state)?,
        "search_symbols" => handle_search_symbols(&args, client, state)?,
        "list_files" => handle_list_files(&args, client, state)?,
        other => return Err(anyhow!("unknown tool: {other}")),
    };

    Ok(json!({
        "content": [{
            "type": "text",
            "text": text,
        }]
    }))
}

fn handle_query_context(
    args: &Value,
    client: &EngineClient,
    state: &crate::install::State,
) -> Result<String> {
    let query = args
        .get("query")
        .and_then(|q| q.as_str())
        .context("missing arguments.query")?;
    let k = args
        .get("k")
        .and_then(|k| k.as_u64())
        .map(|n| n.min(10).max(1) as usize)
        .unwrap_or(5);
    let include_text = args
        .get("include_text")
        .and_then(|b| b.as_bool())
        .unwrap_or(false);

    let body = json!({
        "workspace_id": state.workspace_id,
        "session_id": state.session_id,
        "query": query,
        "iteration": 0,
        "include_text": include_text,
        "limit": k,
    });
    let resp: Value = client.rank_raw(body)?;
    log_tool_call(
        state,
        "query_context",
        json!({"query": query, "k": k, "include_text": include_text}),
        n_items(&resp),
    );
    Ok(format_rank_response(&resp, query))
}

fn handle_search_symbols(
    args: &Value,
    client: &EngineClient,
    state: &crate::install::State,
) -> Result<String> {
    let name_query = args
        .get("name")
        .and_then(|q| q.as_str())
        .context("missing arguments.name")?;
    let k = args
        .get("k")
        .and_then(|k| k.as_u64())
        .map(|n| n.min(50).max(1) as usize)
        .unwrap_or(10);

    let body = json!({
        "workspace_id": state.workspace_id,
        "query": name_query,
        "limit": k,
    });
    let resp: Value = client.search_symbols_raw(body)?;
    log_tool_call(
        state,
        "search_symbols",
        json!({"name": name_query, "k": k}),
        n_items(&resp),
    );
    Ok(format_symbols_response(&resp, name_query))
}

fn handle_list_files(
    args: &Value,
    client: &EngineClient,
    state: &crate::install::State,
) -> Result<String> {
    let query = args
        .get("query")
        .and_then(|q| q.as_str())
        .context("missing arguments.query")?;
    let k = args
        .get("k")
        .and_then(|k| k.as_u64())
        .map(|n| n.min(50).max(1) as usize)
        .unwrap_or(10);

    let body = json!({
        "workspace_id": state.workspace_id,
        "session_id": state.session_id,
        "query": query,
        "iteration": 0,
        "limit": k,
    });
    let resp: Value = client.rank_files_raw(body)?;
    log_tool_call(
        state,
        "list_files",
        json!({"query": query, "k": k}),
        n_items(&resp),
    );
    Ok(format_files_response(&resp, query))
}

fn n_items(resp: &Value) -> usize {
    resp.get("items")
        .and_then(|i| i.as_array())
        .map(|a| a.len())
        .unwrap_or(0)
}

/// Append one JSON line per tool call to `/tmp/cae-claude-mcp.log` so the
/// demo can verify post-hoc which tools the agent actually used. Best-
/// effort — never let a logging failure break the tool call.
fn log_tool_call(
    state: &crate::install::State,
    tool: &str,
    args: Value,
    n_results: usize,
) {
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open("/tmp/cae-claude-mcp.log")
    {
        let _ = writeln!(
            f,
            "{}",
            json!({
                "ts_ms": std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|d| d.as_millis() as u64)
                    .unwrap_or(0),
                "workspace_id": state.workspace_id,
                "session_id": state.session_id,
                "tool": tool,
                "args": args,
                "n_results": n_results,
            })
        );
    }
}

fn format_rank_response(resp: &Value, query: &str) -> String {
    let items = resp.get("items").and_then(|i| i.as_array());
    let Some(items) = items else {
        return format!("query_context: malformed response for {query:?}");
    };
    if items.is_empty() {
        return format!("No matches for {query:?}. Try different phrasing or direct file search.");
    }
    let mut out = format!("{} results for {query:?}:\n", items.len());
    for (i, it) in items.iter().enumerate() {
        // Prefer the citation (path:line-line). Fall back to the bare path or
        // the opaque target only if nothing else is available.
        let citation = it
            .get("citation")
            .and_then(|c| c.as_str())
            .or_else(|| it.get("target").and_then(|t| t.as_str()))
            .unwrap_or("?");
        let qname = it.get("qualified_name").and_then(|q| q.as_str());
        let kind = it.get("kind").and_then(|k| k.as_str());
        let text = it.get("text").and_then(|t| t.as_str()).unwrap_or("");

        let mut suffix = String::new();
        if let Some(q) = qname {
            suffix.push_str(&format!("  ({q})"));
        }
        // Only render `kind` when it's NOT plain code — code is the default
        // case and the file extension already conveys it. Markdown / pdf /
        // jira / etc. are signal worth the tokens.
        if let Some(k) = kind.filter(|k| *k != "code_file") {
            suffix.push_str(&format!("  [{k}]"));
        }

        out.push_str(&format!("{}. {citation}{suffix}\n", i + 1));
        if !text.is_empty() {
            out.push('\n');
            out.push_str(text);
            out.push_str("\n\n");
        }
    }
    out
}

/// `search_symbols` shares the RankItemDto shape so reuse the same
/// renderer logic, but skip semantic-similarity affordances we don't
/// surface (the underlying score is always 1.0 for name matches).
fn format_symbols_response(resp: &Value, name: &str) -> String {
    let items = resp.get("items").and_then(|i| i.as_array());
    let Some(items) = items else {
        return format!("search_symbols: malformed response for {name:?}");
    };
    if items.is_empty() {
        return format!("No symbols match {name:?}. Try a shorter/longer fragment.");
    }
    let mut out = format!("{} symbols match {name:?}:\n", items.len());
    for (i, it) in items.iter().enumerate() {
        let citation = it
            .get("citation")
            .and_then(|c| c.as_str())
            .or_else(|| it.get("target").and_then(|t| t.as_str()))
            .unwrap_or("?");
        let qname = it
            .get("qualified_name")
            .and_then(|q| q.as_str())
            .unwrap_or("?");
        let kind = it.get("kind").and_then(|k| k.as_str());
        let kind_tag = kind
            .filter(|k| *k != "code_file")
            .map(|k| format!("  [{k}]"))
            .unwrap_or_default();
        out.push_str(&format!("{}. {qname}  →  {citation}{kind_tag}\n", i + 1));
    }
    out
}

/// `list_files` returns `{path, score, chunks}` per item — different shape
/// from RankItemDto, so its own renderer.
fn format_files_response(resp: &Value, query: &str) -> String {
    let items = resp.get("items").and_then(|i| i.as_array());
    let Some(items) = items else {
        return format!("list_files: malformed response for {query:?}");
    };
    if items.is_empty() {
        return format!("No files match {query:?}.");
    }
    let mut out = format!("{} files for {query:?}:\n", items.len());
    for (i, it) in items.iter().enumerate() {
        let path = it.get("path").and_then(|p| p.as_str()).unwrap_or("?");
        let chunks = it.get("chunks").and_then(|c| c.as_u64()).unwrap_or(0);
        // Show the chunk count as a "concentration" cue — a file with 5
        // hits is qualitatively different from one with 1.
        out.push_str(&format!("{}. {path}  ({chunks} relevant)\n", i + 1));
    }
    out
}

fn error_response(id: Option<Value>, code: i32, msg: &str) -> Result<Value> {
    Ok(json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": {"code": code, "message": msg},
    }))
}
