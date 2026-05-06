//! `ken hook <event>` — Claude Code calls this on every
//! PostToolUse(Edit|Write|MultiEdit|Read) per the settings written by
//! `install`. We read the JSON event off stdin, look up the per-project
//! state under `.claude/ken-state.json`, and POST a `/events` interaction
//! to the engine. Events drive the reactive ranker channel: chunks
//! whose Document the agent is editing right now get their session
//! score boosted, so a later `/rank` call surfaces neighbors first.
//!
//! Hooks must exit fast. We open one synchronous HTTP request and exit;
//! no tokio runtime, no threads. Failure is silent — a flaky engine
//! shouldn't break the agent's tool dispatch. We log diagnostic info to
//! stderr (Claude Code captures it for logs).

use anyhow::{anyhow, Context, Result};
use serde_json::Value;
use std::io::Read;
use std::path::PathBuf;

use crate::client::EngineClient;
use crate::install::{find_state_root, load_state};

/// Which hook is firing — controls the EventType we record.
#[derive(Debug, Clone, Copy)]
pub enum HookKind {
    /// PostToolUse for Edit/Write/MultiEdit — the agent committed to
    /// changing this file. Strongest signal.
    ToolEdit,
    /// PostToolUse for Read — the agent looked at the file. Weaker
    /// signal but still useful for the reactive channel.
    ToolRead,
}

impl HookKind {
    fn event_type(&self) -> &'static str {
        match self {
            HookKind::ToolEdit => "edited",
            HookKind::ToolRead => "cited",
        }
    }
    fn weight(&self) -> f32 {
        match self {
            HookKind::ToolEdit => 1.5,
            HookKind::ToolRead => 1.0,
        }
    }
}

pub fn run(kind: HookKind) -> Result<()> {
    let mut buf = String::new();
    std::io::stdin().read_to_string(&mut buf).context("read stdin")?;
    let event: Value = if buf.trim().is_empty() {
        Value::Object(Default::default())
    } else {
        serde_json::from_str(&buf).context("parse hook JSON")?
    };

    let cwd = event
        .get("cwd")
        .and_then(|c| c.as_str())
        .map(PathBuf::from)
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default());
    let Some(state_root) = find_state_root(&cwd) else {
        // No state installed in this tree — silently no-op so the hook
        // doesn't punish a project that hasn't opted in.
        eprintln!("ken: no .claude/ken-state.json under {} — skipping", cwd.display());
        return Ok(());
    };
    let state = load_state(&state_root)?;

    let tool_name = event
        .get("tool_name")
        .and_then(|t| t.as_str())
        .unwrap_or("unknown");
    let file_path = event
        .get("tool_input")
        .and_then(|i| i.get("file_path"))
        .and_then(|p| p.as_str())
        .ok_or_else(|| anyhow!("hook payload missing tool_input.file_path"))?;

    // Use `ext:` URI namespace targeting the file path relative to the
    // project root. This lines up with the `path_or_url` we wrote during
    // ingest-codebase, so /events recorded here can correlate with
    // chunks ingested earlier (via the document's path → external
    // pointer the ranker fans out from).
    let rel = relativize(file_path, &state.root);
    let target = format!("ext:codebase:{}:{}", state.workspace_id, rel);

    let client = EngineClient::new(&state.engine_url);
    let _ = client.record_event(
        state.session_id,
        &target,
        kind.event_type(),
        kind.weight(),
        0,
        Some(tool_name),
    );
    Ok(())
}

/// Strip the project root prefix so paths in the engine match what
/// `ingest-codebase` recorded. Falls back to the original string if the
/// path isn't under the root (which would mean the agent edited
/// something outside the project — rare; we record the absolute path).
fn relativize(file_path: &str, root: &str) -> String {
    let trimmed_root = root.trim_end_matches('/');
    if let Some(rest) = file_path.strip_prefix(trimmed_root) {
        rest.trim_start_matches('/').to_string()
    } else {
        file_path.to_string()
    }
}
