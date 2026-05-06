//! `ken install` — wires Claude Code into a project so every
//! Edit/Write/Read tool call publishes an event to the engine, and the
//! agent can call `query_context` via MCP.
//!
//! Writes (or merges into) `<root>/.claude/settings.local.json`. We pick
//! `settings.local.json` over `settings.json` because the latter is
//! checked-in shared config and the former is gitignored per-developer
//! state — perfect fit for "this dev's instance has the engine plugged
//! in." We also write a sentinel under `.claude/ken-state.json` with
//! the workspace + session ids so the hooks can find them without
//! re-reading the agent's environment.

use anyhow::{Context, Result};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

use crate::client::EngineClient;

pub struct InstallArgs {
    /// Where Claude Code reads `.claude/settings.local.json` from — i.e.
    /// the directory you launch Claude Code in. Both `settings.local.json`
    /// and `ken-state.json` are written under `<root>/.claude/`.
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

    // Mint an initial session so the MCP server has a valid id even if
    // Claude Code is opened without firing `SessionStart` for some reason.
    // The `SessionStart` hook rotates `session_id` on every Claude Code
    // launch (see `hook::handle_session_start`), so this initial value is
    // a transient bootstrap, not the long-lived ranker session.
    let client = EngineClient::new(&args.engine_url);
    let session_id = client
        .create_session(args.workspace_id, &args.agent_id)
        .context("create session against engine")?;

    let workdir = args.workdir.clone().unwrap_or_else(|| args.root.clone());
    let state = State {
        workspace_id: args.workspace_id,
        session_id,
        engine_url: args.engine_url.clone(),
        agent_id: args.agent_id.clone(),
        root: workdir
            .canonicalize()
            .unwrap_or_else(|_| workdir.clone())
            .to_string_lossy()
            .into_owned(),
        iteration: 0,
    };
    let state_path = claude_dir.join("ken-state.json");
    save_state(&args.root, &state).context("write initial ken-state.json")?;

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

    // Drop any prior entries we'd overwrite — match by `ken hook` (or
    // legacy `cae-claude`) in the hook command. Anything else stays.
    arr.retain(|entry| {
        !entry
            .get("hooks")
            .and_then(|h| h.as_array())
            .map(|hs| {
                hs.iter().any(|hh| {
                    hh.get("command")
                        .and_then(|c| c.as_str())
                        .is_some_and(|c| c.contains("ken hook") || c.contains("cae-claude"))
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

    // Session-lifecycle + dialog-capture hooks. SessionStart rotates the
    // ken session_id (so each Claude Code launch is a separate rank
    // session). UserPromptSubmit captures the user's message + bumps
    // iteration. Stop captures the agent's final user-facing reply by
    // reading the transcript. SessionEnd closes the session and triggers
    // co-access edge inference.
    let single_hooks: &[(&str, &str)] = &[
        ("SessionStart", "session-start"),
        ("UserPromptSubmit", "prompt"),
        ("Stop", "stop"),
        ("SessionEnd", "session-end"),
    ];
    for (event, sub) in single_hooks {
        let bucket = hooks_obj
            .entry((*event).to_string())
            .or_insert_with(|| json!([]));
        let arr = bucket
            .as_array_mut()
            .with_context(|| format!("settings.hooks.{event} is not an array"))?;
        // Drop our prior entry for this event (idempotent re-install).
        arr.retain(|entry| {
            !entry
                .get("hooks")
                .and_then(|h| h.as_array())
                .map(|hs| {
                    hs.iter().any(|hh| {
                        hh.get("command")
                            .and_then(|c| c.as_str())
                            .is_some_and(|c| c.contains(&format!("ken hook {sub}")))
                    })
                })
                .unwrap_or(false)
        });
        arr.push(json!({
            "hooks": [{
                "type": "command",
                "command": format!("{exe} hook {sub}")
            }]
        }));
    }

    Ok(())
}

/// Register the `ken` MCP server. Existing entries with the same key are
/// overwritten (idempotent re-install). The legacy `cae` entry from older
/// installs is removed if present so we don't end up with two MCP rows.
fn merge_mcp(settings: &mut Value, exe: &str) -> Result<()> {
    let mcp = settings
        .as_object_mut()
        .context("settings is not a JSON object")?
        .entry("mcpServers")
        .or_insert_with(|| json!({}));
    let obj = mcp
        .as_object_mut()
        .context("settings.mcpServers is not a JSON object")?;
    obj.remove("cae");
    obj.insert(
        "ken".into(),
        json!({
            "command": exe,
            "args": ["mcp"]
        }),
    );
    Ok(())
}

/// Read `<root>/.claude/ken-state.json` (the sentinel `install` writes).
/// Hooks + MCP need workspace_id + session_id + engine_url; rather than
/// read them from env each time we keep them in a tiny per-project
/// sidecar so the hook command stays a clean one-liner.
pub fn load_state(root: &Path) -> Result<State> {
    let path = root.join(".claude/ken-state.json");
    let bytes = std::fs::read(&path)
        .with_context(|| format!("read {}", path.display()))?;
    let state: State = serde_json::from_slice(&bytes)
        .with_context(|| format!("parse {}", path.display()))?;
    Ok(state)
}

/// Atomically write `<root>/.claude/ken-state.json`. Writes to a sibling
/// temp file then renames so concurrent readers either see the previous
/// state or the new one — never a half-written truncation. The
/// `SessionStart` and `UserPromptSubmit` hooks both mutate state, so
/// atomicity matters.
pub fn save_state(root: &Path, state: &State) -> Result<()> {
    let path = root.join(".claude/ken-state.json");
    let tmp = root.join(".claude/.ken-state.json.tmp");
    let json = serde_json::to_string_pretty(state).context("serialize ken state")?;
    std::fs::write(&tmp, json)
        .with_context(|| format!("write {}", tmp.display()))?;
    std::fs::rename(&tmp, &path)
        .with_context(|| format!("rename to {}", path.display()))?;
    Ok(())
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct State {
    pub workspace_id: u64,
    pub session_id: u64,
    pub engine_url: String,
    pub agent_id: String,
    pub root: String,
    /// Monotonic counter advanced by the `UserPromptSubmit` hook. Hooks +
    /// MCP read this when recording interactions so the reactive channel
    /// can decay older turns. Starts at 0 (no prompts yet) and bumps to 1
    /// on the first user message of the session. Defaulted to 0 so old
    /// state files that predate this field still parse.
    #[serde(default)]
    pub iteration: u32,
}

/// Walk up from `start` looking for a directory containing `.claude/`.
/// Hooks run with `cwd` set to wherever Claude Code was launched, but
/// the user might have installed the engine state at the project root —
/// we need to find it.
pub fn find_state_root(start: &Path) -> Option<PathBuf> {
    let mut cur = start.to_path_buf();
    loop {
        if cur.join(".claude/ken-state.json").is_file() {
            return Some(cur);
        }
        if !cur.pop() {
            return None;
        }
    }
}
