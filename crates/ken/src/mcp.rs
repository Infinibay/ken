//! `ken mcp` — minimal stdio JSON-RPC 2.0 MCP server. Exposes
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
const SERVER_NAME: &str = "ken";
const SERVER_VERSION: &str = "0.1.0";

pub fn run() -> Result<()> {
    // Resolve project state once at startup. Without it the MCP can
    // technically still serve `tools/list`, but `query_context` calls
    // would always fail. Better to fail fast.
    let cwd = std::env::current_dir().context("get cwd")?;
    let Some(state_root) = find_state_root(&cwd) else {
        return Err(anyhow!(
            "no .claude/ken-state.json found from {} upward — run `ken install` first",
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
                eprintln!("ken mcp: stdin error: {e}");
                break;
            }
        };
        if line.trim().is_empty() {
            continue;
        }
        let req: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => {
                eprintln!("ken mcp: bad JSON: {e}");
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
            },
            {
                "name": "list_symbols",
                "description": "List the code symbols (functions, methods, classes, structs, \
                                etc.) declared in a single file. Use to get a structural map \
                                BEFORE reading the whole file — much cheaper than Read for \
                                orientation. Returns one entry per symbol with qualified_name \
                                and line range. Set with_docstrings=true to also include each \
                                symbol's signature + first lines of its body (covers the doc \
                                comment / docstring for most languages). Path is repo-relative \
                                — same value the engine ingested.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Repo-relative path. E.g. 'crates/engine/src/rank.rs'."
                        },
                        "with_docstrings": {
                            "type": "boolean",
                            "description": "Include the symbol's signature + first ~10 lines \
                                            of body. Default false.",
                            "default": false
                        },
                        "k": {
                            "type": "integer",
                            "description": "Max symbols. Default 100.",
                            "default": 100
                        }
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "git_history",
                "description": "Commits (from the git-history ingest) that touched a given \
                                file or qualified symbol name. Use to answer 'which commits \
                                modified X?', 'who last touched Y?', 'what's the recent \
                                churn around Z?'. Pass either a path ('src/user.rs') OR a \
                                qualified symbol ('User::validate'); the engine matches both \
                                ChangesFile and ChangesSymbol edges. Returns sha, summary, \
                                author, and ms-since-epoch time, newest-first. matched_kind \
                                tells you whether the hit was on the file or the exact \
                                symbol.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "File path or qualified symbol name."
                        },
                        "since_days": {
                            "type": "integer",
                            "description": "Limit to commits within the last N days. Omit for \
                                            unbounded history."
                        },
                        "k": {
                            "type": "integer",
                            "description": "Max commits. Default 20.",
                            "default": 20
                        }
                    },
                    "required": ["target"]
                }
            },
            {
                "name": "ingest_file",
                "description": "Index a local file's contents into the workspace's KG so \
                                future query_context / list_files calls can surface it. Pass \
                                the file's bytes (base64) plus a stable name. Useful when the \
                                user drops a PDF, doc, or notes file and asks 'use this for \
                                context'. Cap: 8 MiB after decode. Idempotent — re-indexing \
                                the same external_id with identical content returns \
                                outcome=\"unchanged\" without rework.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "external_id": {
                            "type": "string",
                            "description": "Stable name for the document — typically the \
                                            original filename ('report.pdf'). Re-using the \
                                            same external_id updates the existing document."
                        },
                        "bytes_base64": {
                            "type": "string",
                            "description": "Standard base64 encoding of the raw file bytes."
                        },
                        "mime": {
                            "type": "string",
                            "description": "Optional content-type. When omitted, the adapter \
                                            is picked from the file extension on external_id."
                        }
                    },
                    "required": ["external_id", "bytes_base64"]
                }
            },
            {
                "name": "ingest_url",
                "description": "Fetch a URL and index its content into the workspace's KG. \
                                Defaults to a single page (depth=0, max_pages=1). For \
                                documentation sites with cross-linked pages set depth=1 and \
                                a small max_pages. Hard caps: depth ≤ 2, max_pages ≤ 10, \
                                wall ≤ 30s. Returns one entry per fetched page plus a list \
                                of skipped URLs (non-html mime, fetch failure). Idempotent \
                                per URL — re-running on a stable page returns \
                                outcome=\"unchanged\".",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "Absolute http(s) URL to start from."
                        },
                        "depth": {
                            "type": "integer",
                            "description": "Follow-link depth (0 = single page). Capped at 2.",
                            "default": 0
                        },
                        "max_pages": {
                            "type": "integer",
                            "description": "Total pages including the start URL. Capped at 10.",
                            "default": 1
                        },
                        "same_host_only": {
                            "type": "boolean",
                            "description": "Only follow links on the start URL's host. \
                                            Default true.",
                            "default": true
                        }
                    },
                    "required": ["url"]
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
        "list_symbols" => handle_list_symbols(&args, client, state)?,
        "git_history" => handle_git_history(&args, client, state)?,
        "ingest_file" => handle_ingest_file(&args, client, state)?,
        "ingest_url" => handle_ingest_url(&args, client, state)?,
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

/// Append one JSON line per tool call to `/tmp/ken-mcp.log` so the
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
        .open("/tmp/ken-mcp.log")
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

fn handle_list_symbols(
    args: &Value,
    client: &EngineClient,
    state: &crate::install::State,
) -> Result<String> {
    let path = args
        .get("path")
        .and_then(|p| p.as_str())
        .context("missing arguments.path")?;
    let with_docstrings = args
        .get("with_docstrings")
        .and_then(|b| b.as_bool())
        .unwrap_or(false);
    let k = args
        .get("k")
        .and_then(|k| k.as_u64())
        .map(|n| n.min(500).max(1) as usize)
        .unwrap_or(100);

    let body = json!({
        "workspace_id": state.workspace_id,
        "path": path,
        "with_docstrings": with_docstrings,
        "limit": k,
    });
    let resp: Value = client.symbols_in_file_raw(body)?;
    log_tool_call(
        state,
        "list_symbols",
        json!({"path": path, "with_docstrings": with_docstrings, "k": k}),
        n_items(&resp),
    );
    Ok(format_list_symbols_response(&resp, path, with_docstrings))
}

fn handle_git_history(
    args: &Value,
    client: &EngineClient,
    state: &crate::install::State,
) -> Result<String> {
    let target = args
        .get("target")
        .and_then(|t| t.as_str())
        .context("missing arguments.target")?;
    let k = args
        .get("k")
        .and_then(|k| k.as_u64())
        .map(|n| n.min(200).max(1) as usize)
        .unwrap_or(20);
    // Convert since_days → since_ms. The engine takes absolute ms so the
    // CLI surface stays "human" (days) while the wire stays portable.
    let since_ms = args
        .get("since_days")
        .and_then(|d| d.as_u64())
        .map(|days| {
            let now_ms = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_millis() as u64)
                .unwrap_or(0);
            now_ms.saturating_sub(days * 24 * 60 * 60 * 1000)
        });

    let mut body = json!({
        "workspace_id": state.workspace_id,
        "target": target,
        "limit": k,
    });
    if let Some(ms) = since_ms {
        body["since_ms"] = json!(ms);
    }
    let resp: Value = client.git_history_raw(body)?;
    log_tool_call(
        state,
        "git_history",
        json!({"target": target, "k": k, "since_ms": since_ms}),
        n_items(&resp),
    );
    Ok(format_git_history_response(&resp, target))
}

fn handle_ingest_file(
    args: &Value,
    client: &EngineClient,
    state: &crate::install::State,
) -> Result<String> {
    let external_id = args
        .get("external_id")
        .and_then(|s| s.as_str())
        .context("missing arguments.external_id")?;
    let bytes_b64 = args
        .get("bytes_base64")
        .and_then(|s| s.as_str())
        .context("missing arguments.bytes_base64")?;
    let mime = args.get("mime").and_then(|s| s.as_str());
    let mut body = json!({
        "workspace": state.workspace_id.to_string(),
        "source_name": "uploads",
        "external_id": external_id,
        "bytes_base64": bytes_b64,
    });
    if let Some(m) = mime {
        body["mime"] = json!(m);
    }
    let resp: Value = client.ingest_file_raw(body)?;
    log_tool_call(
        state,
        "ingest_file",
        json!({"external_id": external_id, "bytes_len_b64": bytes_b64.len(), "mime": mime}),
        resp.get("chunks").and_then(|c| c.as_u64()).unwrap_or(0) as usize,
    );
    Ok(format_ingest_file_response(&resp, external_id))
}

fn handle_ingest_url(
    args: &Value,
    client: &EngineClient,
    state: &crate::install::State,
) -> Result<String> {
    let url = args
        .get("url")
        .and_then(|s| s.as_str())
        .context("missing arguments.url")?;
    let depth = args
        .get("depth")
        .and_then(|n| n.as_u64())
        .map(|n| n.min(2) as u32)
        .unwrap_or(0);
    let max_pages = args
        .get("max_pages")
        .and_then(|n| n.as_u64())
        .map(|n| n.clamp(1, 10) as u32)
        .unwrap_or(1);
    let same_host = args
        .get("same_host_only")
        .and_then(|b| b.as_bool())
        .unwrap_or(true);
    let body = json!({
        "workspace": state.workspace_id.to_string(),
        "source_name": "web",
        "url": url,
        "depth": depth,
        "max_pages": max_pages,
        "same_host_only": same_host,
    });
    let resp: Value = client.ingest_url_raw(body)?;
    let pages_count = resp
        .get("pages")
        .and_then(|p| p.as_array())
        .map(|a| a.len())
        .unwrap_or(0);
    log_tool_call(
        state,
        "ingest_url",
        json!({"url": url, "depth": depth, "max_pages": max_pages}),
        pages_count,
    );
    Ok(format_ingest_url_response(&resp, url))
}

fn format_ingest_file_response(resp: &Value, external_id: &str) -> String {
    let outcome = resp
        .get("outcome")
        .and_then(|s| s.as_str())
        .unwrap_or("unknown");
    let doc_id = resp
        .get("document_id")
        .map(|v| v.to_string())
        .unwrap_or_else(|| "?".into());
    let chunks = resp.get("chunks").and_then(|c| c.as_u64()).unwrap_or(0);
    let edges = resp.get("edges").and_then(|c| c.as_u64()).unwrap_or(0);
    if outcome == "unchanged" {
        format!("ingest_file: {external_id} unchanged (document {doc_id}). Same hash as the previous version — no re-embed.")
    } else {
        format!(
            "ingest_file: {external_id} {outcome} as document {doc_id} — {chunks} chunks, {edges} edges. Future query_context calls in this workspace can now surface it."
        )
    }
}

fn format_ingest_url_response(resp: &Value, start_url: &str) -> String {
    let pages = resp.get("pages").and_then(|p| p.as_array());
    let skipped = resp.get("skipped").and_then(|s| s.as_array());
    let timed_out = resp
        .get("timed_out")
        .and_then(|b| b.as_bool())
        .unwrap_or(false);
    let pages = pages.cloned().unwrap_or_default();
    let skipped = skipped.cloned().unwrap_or_default();
    if pages.is_empty() && skipped.is_empty() {
        return format!("ingest_url: no pages indexed for {start_url}.");
    }
    let mut out = format!(
        "ingest_url: {} page(s) indexed from {start_url}",
        pages.len()
    );
    if timed_out {
        out.push_str(" (wall-clock cap reached; some queued URLs were not fetched)");
    }
    out.push_str(":\n");
    for p in &pages {
        let url = p.get("url").and_then(|s| s.as_str()).unwrap_or("?");
        let outcome = p.get("outcome").and_then(|s| s.as_str()).unwrap_or("?");
        let chunks = p.get("chunks").and_then(|c| c.as_u64()).unwrap_or(0);
        let doc_id = p
            .get("document_id")
            .map(|v| v.to_string())
            .unwrap_or_else(|| "?".into());
        out.push_str(&format!("- {url}  [{outcome}, doc {doc_id}, {chunks} chunks]\n"));
    }
    if !skipped.is_empty() {
        out.push_str(&format!("Skipped {}:\n", skipped.len()));
        for s in &skipped {
            let url = s.get("url").and_then(|s| s.as_str()).unwrap_or("?");
            let reason = s.get("reason").and_then(|s| s.as_str()).unwrap_or("?");
            out.push_str(&format!("- {url}  ({reason})\n"));
        }
    }
    out
}

fn format_list_symbols_response(resp: &Value, path: &str, with_docstrings: bool) -> String {
    let items = resp.get("items").and_then(|i| i.as_array());
    let Some(items) = items else {
        return format!("list_symbols: malformed response for {path:?}");
    };
    if items.is_empty() {
        return format!(
            "No symbols indexed for {path:?}. The file may not be ingested or has no code-symbol \
             chunks (markdown / pdf / plain text don't produce symbols)."
        );
    }
    let mut out = format!("{} symbols in {path}:\n", items.len());
    for it in items.iter() {
        let qname = it.get("qualified_name").and_then(|q| q.as_str()).unwrap_or("?");
        let ls = it.get("line_start").and_then(|l| l.as_u64()).unwrap_or(0);
        let le = it.get("line_end").and_then(|l| l.as_u64()).unwrap_or(0);
        out.push_str(&format!("- {qname}  L{ls}-{le}\n"));
        if with_docstrings
            && let Some(head) = it.get("head").and_then(|h| h.as_str())
            && !head.is_empty()
        {
            for line in head.lines() {
                out.push_str("    ");
                out.push_str(line);
                out.push('\n');
            }
        }
    }
    out
}

fn format_git_history_response(resp: &Value, target: &str) -> String {
    let items = resp.get("items").and_then(|i| i.as_array());
    let Some(items) = items else {
        return format!("git_history: malformed response for {target:?}");
    };
    if items.is_empty() {
        return format!(
            "No commits found touching {target:?}. The git history may not be ingested, or the \
             target spelling doesn't match any indexed path/symbol."
        );
    }
    let mut out = format!("{} commits touching {target:?} (newest first):\n", items.len());
    for it in items.iter() {
        let sha = it.get("sha").and_then(|s| s.as_str()).unwrap_or("?");
        let short_sha = sha.get(..sha.len().min(10)).unwrap_or(sha);
        let summary = it.get("summary").and_then(|s| s.as_str()).unwrap_or("");
        let author = it.get("author").and_then(|a| a.as_str()).unwrap_or("");
        let kind = it.get("matched_kind").and_then(|k| k.as_str()).unwrap_or("");
        let time_ms = it.get("time_ms").and_then(|t| t.as_u64()).unwrap_or(0);
        let date = format_iso_date(time_ms);
        // `[file]`, `[symbol]`, or `[symbol+file]` — file is the default
        // case (most commits hit at file granularity), so suppress the tag
        // there to save tokens.
        let tag = if kind == "file" {
            String::new()
        } else {
            format!("  [{kind}]")
        };
        let author_tag = if author.is_empty() {
            String::new()
        } else {
            format!("  ({author})")
        };
        out.push_str(&format!(
            "- {short_sha}  {date}  {summary}{tag}{author_tag}\n"
        ));
    }
    out
}

/// Cheap ISO-8601 date renderer (YYYY-MM-DD) for git_history output. We
/// don't need the time-of-day; days is the right granularity for "what
/// commits happened around X". Using `chrono` would pull in a heavy dep
/// for one call site.
fn format_iso_date(ms_since_epoch: u64) -> String {
    if ms_since_epoch == 0 {
        return "????-??-??".to_string();
    }
    // Compute days since 1970-01-01 (a Thursday). Then walk Gregorian.
    let days = (ms_since_epoch / 86_400_000) as i64;
    let (y, m, d) = days_to_ymd(days);
    format!("{y:04}-{m:02}-{d:02}")
}

fn days_to_ymd(mut days: i64) -> (i32, u32, u32) {
    // Algorithm from Howard Hinnant — civil_from_days. Public domain.
    days += 719_468;
    let era = if days >= 0 { days } else { days - 146_096 } / 146_097;
    let doe = (days - era * 146_097) as u64;
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = (if mp < 10 { mp + 3 } else { mp - 9 }) as u32;
    let y = (y + if m <= 2 { 1 } else { 0 }) as i32;
    (y, m, d)
}

fn error_response(id: Option<Value>, code: i32, msg: &str) -> Result<Value> {
    Ok(json!({
        "jsonrpc": "2.0",
        "id": id,
        "error": {"code": code, "message": msg},
    }))
}
