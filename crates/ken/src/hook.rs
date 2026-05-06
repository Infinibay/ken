//! `ken hook <event>` — entry point for every Claude Code hook firing.
//! Six events are wired by `ken install`:
//!
//! * `tool-edit`   (PostToolUse on Edit/Write/MultiEdit) — record `edited`
//! * `tool-read`   (PostToolUse on Read)                 — record `cited`
//! * `prompt`      (UserPromptSubmit)                    — capture user turn,
//!                                                         bump iteration
//! * `stop`        (Stop)                                — capture assistant
//!                                                         reply from transcript
//! * `session-start` (SessionStart)                      — rotate ken session
//! * `session-end`   (SessionEnd)                        — close ken session
//!
//! Hooks must exit fast (Claude Code waits for them before continuing). All
//! of them run a single synchronous HTTP call to the engine; failure is
//! silent on stdout but logged to stderr so a flaky engine never breaks
//! the agent's tool dispatch. State mutation (session_id rotation,
//! iteration bump) goes through `install::save_state` for atomicity.

use anyhow::{anyhow, Context, Result};
use serde_json::Value;
use std::io::Read;
use std::path::{Path, PathBuf};

use crate::client::EngineClient;
use crate::install::{find_state_root, load_state, save_state};

/// Which hook is firing — controls the EventType / ContextKind / state
/// mutation the dispatch performs.
#[derive(Debug, Clone, Copy)]
pub enum HookKind {
    ToolEdit,
    ToolRead,
    SessionStart,
    SessionEnd,
    Prompt,
    Stop,
}

pub fn run(kind: HookKind) -> Result<()> {
    let payload = read_stdin_json();
    let cwd = payload
        .as_ref()
        .ok()
        .and_then(|v| v.get("cwd").and_then(|c| c.as_str()).map(PathBuf::from))
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default());
    let Some(state_root) = find_state_root(&cwd) else {
        // No state installed — silently no-op so the hook doesn't punish a
        // project that hasn't opted in.
        eprintln!(
            "ken: no .claude/ken-state.json under {} — skipping",
            cwd.display()
        );
        return Ok(());
    };

    match kind {
        HookKind::SessionStart => handle_session_start(&state_root),
        HookKind::SessionEnd => handle_session_end(&state_root),
        HookKind::Prompt => handle_prompt(&state_root, payload?),
        HookKind::Stop => handle_stop(&state_root, payload?),
        HookKind::ToolEdit | HookKind::ToolRead => handle_tool(&state_root, payload?, kind),
    }
}

/// SessionStart fires once per Claude Code launch in this project. We mint
/// a fresh ken session, reset iteration to 0, and persist. Future hooks +
/// MCP calls land on the new session id.
fn handle_session_start(state_root: &Path) -> Result<()> {
    let mut state = load_state(state_root).context("load_state for session-start")?;
    let client = EngineClient::new(&state.engine_url);
    let new_id = client
        .create_session(state.workspace_id, &state.agent_id)
        .context("create new session")?;
    state.session_id = new_id;
    state.iteration = 0;
    save_state(state_root, &state)?;
    Ok(())
}

/// SessionEnd fires when Claude Code exits. Closing the ken session is
/// what triggers `infer_coaccessed_edges` (and would trigger
/// `snapshot_session_scores` once the predictive scorer is wired into the
/// close path). Best-effort — log on failure but don't propagate.
fn handle_session_end(state_root: &Path) -> Result<()> {
    let state = load_state(state_root).context("load_state for session-end")?;
    let client = EngineClient::new(&state.engine_url);
    if let Err(err) = client.end_session(state.session_id) {
        eprintln!("ken: session-end failed: {err}");
    }
    Ok(())
}

/// UserPromptSubmit captures one half of the outer dialog (User → AI).
/// Increments iteration first so the new prompt and any tool calls inside
/// this turn share an iteration distinct from the previous turn — the
/// reactive channel uses iteration deltas to decay old activity.
fn handle_prompt(state_root: &Path, payload: Value) -> Result<()> {
    let prompt = payload
        .get("prompt")
        .and_then(|p| p.as_str())
        .unwrap_or("");
    if prompt.trim().is_empty() {
        return Ok(());
    }
    let mut state = load_state(state_root).context("load_state for prompt")?;
    state.iteration = state.iteration.saturating_add(1);
    save_state(state_root, &state)?;
    let client = EngineClient::new(&state.engine_url);
    if let Err(err) = client.append_context(
        state.session_id,
        "user_input",
        prompt,
        state.iteration,
        true,
    ) {
        eprintln!("ken: append user prompt failed: {err}");
    }
    Ok(())
}

/// Stop fires when the agent finishes its reply. Captures the other half of
/// the outer dialog (AI → User) by reading the transcript and pulling the
/// last assistant message's text blocks (skips tool_use, tool_result, and
/// thinking blocks per the user's intent — only the final reply lands in
/// the KG).
fn handle_stop(state_root: &Path, payload: Value) -> Result<()> {
    let Some(transcript) = payload
        .get("transcript_path")
        .and_then(|t| t.as_str())
        .map(PathBuf::from)
    else {
        eprintln!("ken: stop payload missing transcript_path — skipping");
        return Ok(());
    };
    let text = match extract_last_assistant_text(&transcript) {
        Ok(Some(t)) => t,
        Ok(None) => return Ok(()),
        Err(err) => {
            eprintln!("ken: stop transcript read failed: {err}");
            return Ok(());
        }
    };
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Ok(());
    }
    let state = load_state(state_root).context("load_state for stop")?;
    let client = EngineClient::new(&state.engine_url);
    if let Err(err) = client.append_context(
        state.session_id,
        "assistant_reply",
        trimmed,
        state.iteration,
        true,
    ) {
        eprintln!("ken: append assistant reply failed: {err}");
        return Ok(());
    }
    // The reply context is now persisted — fire the per-turn anchor pass so
    // every tool the agent touched gets `PromptAnchored` + `ReplyAnchored`
    // edges to the turn's dialog endpoints. Best-effort; failure here
    // doesn't break the hook.
    if let Err(err) = client.anchor_turn(state.session_id, state.iteration) {
        eprintln!("ken: anchor_turn failed: {err}");
    }
    Ok(())
}

/// PostToolUse for Edit/Write/MultiEdit/Read: record an interaction
/// targeting the file's relative path under the project. This is the
/// reactive ranker's main signal — recently-edited files boost their
/// neighbors in the next `query_context`.
fn handle_tool(state_root: &Path, payload: Value, kind: HookKind) -> Result<()> {
    let state = load_state(state_root).context("load_state for tool hook")?;
    let tool_name = payload
        .get("tool_name")
        .and_then(|t| t.as_str())
        .unwrap_or("unknown");
    let file_path = payload
        .get("tool_input")
        .and_then(|i| i.get("file_path"))
        .and_then(|p| p.as_str())
        .ok_or_else(|| anyhow!("hook payload missing tool_input.file_path"))?;

    let rel = relativize(file_path, &state.root);
    let target = format!("ext:codebase:{}:{}", state.workspace_id, rel);

    let (event_type, weight) = match kind {
        HookKind::ToolEdit => ("edited", 1.5),
        HookKind::ToolRead => ("cited", 1.0),
        _ => unreachable!("handle_tool only called for tool-edit/tool-read"),
    };

    let client = EngineClient::new(&state.engine_url);
    let _ = client.record_event(
        state.session_id,
        &target,
        event_type,
        weight,
        state.iteration,
        Some(tool_name),
    );
    Ok(())
}

/// Read the entire JSON object Claude Code piped to the hook on stdin. An
/// empty body parses to `{}` so the no-payload path doesn't error out.
fn read_stdin_json() -> Result<Value> {
    let mut buf = String::new();
    std::io::stdin().read_to_string(&mut buf).context("read stdin")?;
    if buf.trim().is_empty() {
        return Ok(Value::Object(Default::default()));
    }
    serde_json::from_str(&buf).context("parse hook JSON")
}

/// Walk the JSONL transcript backward, find the most recent message
/// authored by the assistant, and concatenate its `text`-typed content
/// blocks. Returns `None` if no such message has any text. Skips
/// `tool_use`, `tool_result`, and `thinking` blocks — the user explicitly
/// wants only the outer dialog persisted, not internal AI reasoning.
fn extract_last_assistant_text(transcript_path: &Path) -> Result<Option<String>> {
    let bytes = std::fs::read(transcript_path)
        .with_context(|| format!("read {}", transcript_path.display()))?;
    let text = std::str::from_utf8(&bytes).context("transcript not utf-8")?;
    let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();

    for line in lines.iter().rev() {
        let v: Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if !is_assistant(&v) {
            continue;
        }
        let content = v.get("content").or_else(|| v.pointer("/message/content"));
        let Some(content) = content else { continue };
        let extracted = extract_text_blocks(content);
        if !extracted.trim().is_empty() {
            return Ok(Some(extracted));
        }
    }
    Ok(None)
}

fn is_assistant(v: &Value) -> bool {
    let direct = v.get("type").and_then(|t| t.as_str()) == Some("assistant")
        || v.get("role").and_then(|r| r.as_str()) == Some("assistant");
    let nested = v.pointer("/message/role").and_then(|r| r.as_str()) == Some("assistant");
    direct || nested
}

/// Extract concatenated text from a Claude content field. Supports both
/// the "string content" shape (older / simpler messages) and the typed-
/// blocks array (`[{type: text, text: ...}, {type: tool_use, ...}, ...]`).
fn extract_text_blocks(content: &Value) -> String {
    if let Some(s) = content.as_str() {
        return s.to_string();
    }
    if let Some(arr) = content.as_array() {
        return arr
            .iter()
            .filter_map(|block| {
                let block_type = block.get("type").and_then(|t| t.as_str())?;
                if block_type != "text" {
                    return None;
                }
                block.get("text").and_then(|t| t.as_str()).map(str::to_string)
            })
            .collect::<Vec<_>>()
            .join("\n");
    }
    String::new()
}

/// Strip the project root prefix so paths in the engine match what
/// `ingest-codebase` recorded. Falls back to the original string if the
/// path isn't under the root (rare; we record the absolute path).
fn relativize(file_path: &str, root: &str) -> String {
    let trimmed_root = root.trim_end_matches('/');
    if let Some(rest) = file_path.strip_prefix(trimmed_root) {
        rest.trim_start_matches('/').to_string()
    } else {
        file_path.to_string()
    }
}
