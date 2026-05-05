use anyhow::{Context, Result};

mod client;
mod hook;
mod install;
mod mcp;

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("install") => run_install(args.collect()),
        Some("mcp") => mcp::run(),
        Some("hook") => run_hook(args.collect()),
        Some("--help") | Some("-h") | Some("help") | None => {
            print_usage();
            Ok(())
        }
        Some(other) => {
            eprintln!("unknown subcommand: {other}");
            print_usage();
            std::process::exit(2);
        }
    }
}

fn print_usage() {
    eprintln!(
        "cae-claude — wire Claude Code to the context-ai-engine\n\n\
         USAGE:\n  \
           cae-claude install --workspace WS [--root .] [--engine-url URL] [--agent-id ID]\n  \
           cae-claude mcp                                              (run as MCP stdio server)\n  \
           cae-claude hook tool-edit | tool-read                       (run as PostToolUse hook)\n\n\
         INSTALL OPTIONS:\n  \
           --workspace WS_ID     Engine workspace id (required, integer)\n  \
           --root PATH           Project root (default: current dir)\n  \
           --engine-url URL      Engine HTTP endpoint (default: http://127.0.0.1:8080)\n  \
           --agent-id ID         Agent identifier for the session (default: claude-code)\n\n\
         ENV (read by mcp + hook):\n  \
           CAE_ENGINE_URL    Override the engine endpoint\n\n\
         The `install` command writes <root>/.claude/settings.local.json\n\
         (hooks + mcp server entry) and <root>/.claude/cae-state.json\n\
         (workspace_id + session_id sentinel that the hooks read)."
    );
}

fn run_install(rest: Vec<String>) -> Result<()> {
    let mut workspace: Option<u64> = None;
    let mut root: Option<std::path::PathBuf> = None;
    let mut workdir: Option<std::path::PathBuf> = None;
    let mut engine_url: Option<String> = None;
    let mut agent_id: Option<String> = None;

    let mut it = rest.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--workspace" => workspace = it.next().and_then(|s| s.parse().ok()),
            "--root" => root = it.next().map(std::path::PathBuf::from),
            "--workdir" => workdir = it.next().map(std::path::PathBuf::from),
            "--engine-url" => engine_url = it.next(),
            "--agent-id" => agent_id = it.next(),
            other => anyhow::bail!("unknown install arg: {other}"),
        }
    }

    let args = install::InstallArgs {
        root: root.unwrap_or_else(|| std::path::PathBuf::from(".")),
        workdir,
        workspace_id: workspace.context("--workspace WS_ID is required")?,
        engine_url: engine_url
            .or_else(|| std::env::var("CAE_ENGINE_URL").ok())
            .unwrap_or_else(|| "http://127.0.0.1:8080".into()),
        agent_id: agent_id.unwrap_or_else(|| "claude-code".into()),
    };
    install::run(args)
}

fn run_hook(rest: Vec<String>) -> Result<()> {
    let event = rest
        .into_iter()
        .next()
        .context("hook requires an event name (tool-edit | tool-read)")?;
    let kind = match event.as_str() {
        "tool-edit" => hook::HookKind::ToolEdit,
        "tool-read" => hook::HookKind::ToolRead,
        other => anyhow::bail!("unknown hook event: {other}"),
    };
    hook::run(kind)
}
