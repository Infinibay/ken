//! `cae-claude install` — wires Claude Code into a project so every
//! Edit/Write/Read tool call publishes an event to the engine, and the
//! agent can call `query_context` via MCP.
//!
//! Writes (or merges into) `<root>/.claude/settings.local.json`. We pick
//! `settings.local.json` over `settings.json` because the latter is
//! checked-in shared config and the former is gitignored per-developer
//! state — perfect fit for "this dev's instance has the engine plugged
//! in." We also write a sentinel under `.claude/cae-state.json` with
//! the workspace + session ids so the hooks can find them without
//! re-reading the agent's environment.

use anyhow::{Context, Result};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

use crate::client::EngineClient;

pub struct InstallArgs {
    /// Where Claude Code reads `.claude/settings.local.json` from — i.e.
    /// the directory you launch Claude Code in. Both `settings.local.json`
    /// and `cae-state.json` are written under `<root>/.claude/`.
    pub root: PathBuf,
    /// The project the agent is actually working on. Path-relativization
    /// in hooks strips this prefix (so events land as `<rel-path>` not
    /// `/abs/path/...`). Defaults to `root` when not specified — useful
    /// when you want hooks to fire on a different repo than where Claude
    /// Code was launched.
    pub workdir: Option<PathBuf>,
    pub workspace_id: u64,
    pub engine_url: String,
    pub agent_id: String,
}

pub fn run(args: InstallArgs) -> Result<()> {
    let claude_dir = args.root.join(".claude");
    std::fs::create_dir_all(&claude_dir).context("create .claude dir")?;

    // Resolve our own absolute path. Claude Code spawns hooks via the
    // login shell's PATH, which may or may not include `~/.cargo/bin`
    // depending on how the user's shell was started. Writing the
    // absolute path to `settings.local.json` removes that ambiguity.
    let exe = std::env::current_exe()
        .context("locate own executable")?
        .to_string_lossy()
        .into_owned();

    // Mint a session up front so every hook + every MCP rank call lands
    // on the same session row. A single session per project install is
    // the right granularity for the demo: the ranker's reactive channel
    // depends on co-occurrences within a session.
    let client = EngineClient::new(&args.engine_url);
    let session_id = client
        .create_session(args.workspace_id, &args.agent_id)
        .context("create session against engine")?;

    let workdir = args.workdir.clone().unwrap_or_else(|| args.root.clone());
    let state = json!({
        "workspace_id": args.workspace_id,
        "session_id": session_id,
        "engine_url": args.engine_url,
        "agent_id": args.agent_id,
        "root": workdir.canonicalize()
            .unwrap_or_else(|_| workdir.clone())
            .to_string_lossy(),
    });
    let state_path = claude_dir.join("cae-state.json");
    std::fs::write(&state_path, serde_json::to_string_pretty(&state)?)
        .with_context(|| format!("write {}", state_path.display()))?;

    let settings_path = claude_dir.join("settings.local.json");
    let mut settings: Value = if settings_path.exists() {
        serde_json::from_slice(&std::fs::read(&settings_path)?)
            .unwrap_or_else(|_| json!({}))
    } else {
        json!({})
    };

    merge_hooks(&mut settings, &exe)?;
    merge_mcp(&mut settings, &exe)?;

    std::fs::write(&settings_path, serde_json::to_string_pretty(&settings)?)
        .with_context(|| format!("write {}", settings_path.display()))?;

    println!("✓ wrote {}", state_path.display());
    println!("✓ wrote {}", settings_path.display());
    println!("  workspace_id = {}", args.workspace_id);
    println!("  session_id   = {session_id}");
    println!("  engine_url   = {}", args.engine_url);
    println!();
    println!("Restart Claude Code in this directory for hooks + MCP to pick up.");
    Ok(())
}

/// Insert the PostToolUse hooks for Edit/Write/Read into the settings
/// document. Existing hooks for other matchers are preserved; existing
/// hooks for our matchers are overwritten so re-running `install` is
/// idempotent.
fn merge_hooks(settings: &mut Value, exe: &str) -> Result<()> {
    let hooks = settings
        .as_object_mut()
        .context("settings is not a JSON object")?
        .entry("hooks")
        .or_insert_with(|| json!({}));
    let hooks_obj = hooks
        .as_object_mut()
        .context("settings.hooks is not a JSON object")?;

    let post_tool_use = hooks_obj
        .entry("PostToolUse")
        .or_insert_with(|| json!([]));
    let arr = post_tool_use
        .as_array_mut()
        .context("settings.hooks.PostToolUse is not an array")?;

    // Drop any prior entries we'd overwrite — match by `cae-claude` in
    // the hook command. Anything else stays.
    arr.retain(|entry| {
        !entry
            .get("hooks")
            .and_then(|h| h.as_array())
            .map(|hs| {
                hs.iter().any(|hh| {
                    hh.get("command")
                        .and_then(|c| c.as_str())
                        .is_some_and(|c| c.contains("cae-claude"))
                })
            })
            .unwrap_or(false)
    });

    arr.push(json!({
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [{
            "type": "command",
            "command": format!("{exe} hook tool-edit")
        }]
    }));
    arr.push(json!({
        "matcher": "Read",
        "hooks": [{
            "type": "command",
            "command": format!("{exe} hook tool-read")
        }]
    }));
    Ok(())
}

/// Register the `cae` MCP server. Existing entries with the same key are
/// overwritten (idempotent re-install).
fn merge_mcp(settings: &mut Value, exe: &str) -> Result<()> {
    let mcp = settings
        .as_object_mut()
        .context("settings is not a JSON object")?
        .entry("mcpServers")
        .or_insert_with(|| json!({}));
    let obj = mcp
        .as_object_mut()
        .context("settings.mcpServers is not a JSON object")?;
    obj.insert(
        "cae".into(),
        json!({
            "command": exe,
            "args": ["mcp"]
        }),
    );
    Ok(())
}

/// Read `<root>/.claude/cae-state.json` (the sentinel `install` writes).
/// Hooks + MCP need workspace_id + session_id + engine_url; rather than
/// read them from env each time we keep them in a tiny per-project
/// sidecar so the hook command stays a clean one-liner.
pub fn load_state(root: &Path) -> Result<State> {
    let path = root.join(".claude/cae-state.json");
    let bytes = std::fs::read(&path)
        .with_context(|| format!("read {}", path.display()))?;
    let state: State = serde_json::from_slice(&bytes)
        .with_context(|| format!("parse {}", path.display()))?;
    Ok(state)
}

#[derive(Debug, serde::Deserialize)]
pub struct State {
    pub workspace_id: u64,
    pub session_id: u64,
    pub engine_url: String,
    #[allow(dead_code)]
    pub agent_id: String,
    #[allow(dead_code)]
    pub root: String,
}

/// Walk up from `start` looking for a directory containing `.claude/`.
/// Hooks run with `cwd` set to wherever Claude Code was launched, but
/// the user might have installed the engine state at the project root —
/// we need to find it.
pub fn find_state_root(start: &Path) -> Option<PathBuf> {
    let mut cur = start.to_path_buf();
    loop {
        if cur.join(".claude/cae-state.json").is_file() {
            return Some(cur);
        }
        if !cur.pop() {
            return None;
        }
    }
}
