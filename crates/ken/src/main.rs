use std::sync::Arc;

use anyhow::{Context, Result};
use engine::embed::{Embedder, MockEmbedder};
use engine::postgres::PostgresStorage;
use ken::{build_router, hook, install, mcp, AppState};
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        None => run_server(Vec::new()).await,
        Some("serve") => run_server(args.collect()).await,
        Some("ingest-git") => {
            let rest: Vec<String> = args.collect();
            run_ingest_git(rest).await
        }
        Some("ingest-codebase") => {
            let rest: Vec<String> = args.collect();
            run_ingest_codebase(rest).await
        }
        Some("ingest-file") => {
            let rest: Vec<String> = args.collect();
            run_ingest_file(rest).await
        }
        Some("ingest-url") => {
            let rest: Vec<String> = args.collect();
            run_ingest_url(rest).await
        }
        // The remaining subcommands are sync — call them directly. They
        // briefly block the tokio runtime, which is fine because none of
        // them spawn other tasks.
        Some("mcp") => mcp::run(),
        Some("install") => run_install(args.collect()),
        Some("hook") => run_hook(args.collect()),
        Some("--help") | Some("-h") | Some("help") => {
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
        "ken — context engine for coding agents (\"goes beyond your ken\")\n\n\
         USAGE:\n  \
           ken [serve] [--with-pg]                  Run the HTTP API (default).\n  \
                                                    --with-pg auto-starts the\n  \
                                                    pgvector container via docker/podman.\n  \
           ken ingest-git --repo PATH --workspace WS [opts]\n  \
           ken ingest-codebase --root PATH --workspace WS [opts]\n  \
           ken ingest-file --path PATH --workspace WS [opts]\n  \
           ken ingest-url --url URL --workspace WS [opts]\n  \
           ken mcp                                  Run as MCP stdio server\n  \
           ken install --workspace WS [opts]        Install hooks + MCP into Claude Code\n  \
           ken hook tool-edit | tool-read           Run as PostToolUse hook (called by Claude)\n\n\
         INGEST-GIT OPTIONS:\n  \
           --repo PATH           Local repository path (required)\n  \
           --workspace WS_OR_NAME Workspace numeric id, OR a name (find-or-created)\n  \
           --source SOURCE_ID    Existing source id (default: create one)\n  \
           --branch NAME         Branch / ref to walk (default: HEAD)\n  \
           --since YEARS         Only walk commits newer than N years (default: 2)\n  \
           --max NUM             Hard cap on commits processed (default: 0 = unlimited)\n  \
           --mode both|docs|sessions   Which side to populate (default: both)\n  \
           --keep-merges         Don't skip merge commits\n  \
           --keep-whitespace     Don't skip whitespace-only commits\n\n\
         INGEST-CODEBASE OPTIONS:\n  \
           --root PATH           Working tree root (required)\n  \
           --workspace WS_OR_NAME Workspace numeric id, OR a name (find-or-created)\n  \
           --source SOURCE_ID    Existing source id (default: create one)\n  \
           --max-bytes N         Skip files larger than N bytes (default: 1048576)\n  \
           --no-gitignore        Ingest .gitignore'd files too (default: respect)\n  \
           --follow-symlinks     Follow symlinks during walk (default: skip)\n\n\
         INGEST-FILE OPTIONS:\n  \
           --path PATH           File to ingest (required; PDF, MD, HTML, code, txt)\n  \
           --workspace WS_OR_NAME Workspace numeric id, OR a name (find-or-created)\n  \
           --source SOURCE_ID    Existing source id (default: create one)\n  \
           --mime MIME           Override MIME hint (e.g. text/markdown)\n\n\
         INGEST-URL OPTIONS:\n  \
           --url URL             Starting URL (required)\n  \
           --workspace WS_OR_NAME Workspace numeric id, OR a name (find-or-created)\n  \
           --source SOURCE_ID    Existing source id (default: create one)\n  \
           --depth N             BFS crawl depth (default: 0 = single page)\n  \
           --max-pages M         Hard cap on pages fetched (default: 10)\n  \
           --same-host-only      Restrict crawl to the start URL's host (default: on)\n\n\
         INSTALL OPTIONS:\n  \
           --workspace WS_OR_NAME Workspace numeric id, OR a name (find-or-created)\n  \
           --root PATH           Project root (default: current dir)\n  \
           --engine-url URL      Engine HTTP endpoint (default: http://127.0.0.1:8080)\n  \
           --agent-id ID         Agent identifier for the session (default: claude-code)\n\n\
         ENV:\n  \
           DATABASE_URL      Postgres connection string (required for serve / ingest-*)\n  \
           BIND              Address:port the server listens on (default: 0.0.0.0:8080)\n  \
           EMBEDDER=mock     Use deterministic MockEmbedder instead of fastembed\n  \
           KEN_EMBEDDER_MODEL  fastembed model: nomic-q (default, 768d), nomic,\n  \
                             bge-small-q (384d, ~5x faster, needs DB wipe), mini-q\n  \
           KEN_ENGINE_URL    Override engine endpoint for mcp + hook subcommands"
    );
}

fn run_install(rest: Vec<String>) -> Result<()> {
    use ken::client::EngineClient;
    let mut workspace_raw: Option<String> = None;
    let mut root: Option<std::path::PathBuf> = None;
    let mut workdir: Option<std::path::PathBuf> = None;
    let mut engine_url: Option<String> = None;
    let mut agent_id: Option<String> = None;

    let mut it = rest.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--workspace" => workspace_raw = it.next(),
            "--root" => root = it.next().map(std::path::PathBuf::from),
            "--workdir" => workdir = it.next().map(std::path::PathBuf::from),
            "--engine-url" => engine_url = it.next(),
            "--agent-id" => agent_id = it.next(),
            other => anyhow::bail!("unknown install arg: {other}"),
        }
    }

    let workspace_raw = workspace_raw.context("--workspace WS_ID_OR_NAME is required")?;
    let url = engine_url
        .or_else(|| std::env::var("KEN_ENGINE_URL").ok())
        .unwrap_or_else(|| "http://127.0.0.1:8080".into());
    let workspace_id = if let Ok(id) = workspace_raw.parse::<u64>() {
        id
    } else {
        let client = EngineClient::new(&url);
        let id = client
            .resolve_workspace(&workspace_raw)
            .with_context(|| format!("resolve workspace {:?} via engine", workspace_raw))?;
        eprintln!(
            "→ workspace {:?} resolved to id {} (tenant \"local\")",
            workspace_raw, id
        );
        id
    };

    let args = install::InstallArgs {
        root: root.unwrap_or_else(|| std::path::PathBuf::from(".")),
        workdir,
        workspace_id,
        engine_url: url,
        agent_id: agent_id.unwrap_or_else(|| "claude-code".into()),
    };
    install::run(args)
}


fn run_hook(rest: Vec<String>) -> Result<()> {
    let event = rest
        .into_iter()
        .next()
        .context("hook requires an event name (tool-edit | tool-read | session-start | session-end | prompt | stop)")?;
    let kind = match event.as_str() {
        "tool-edit" => hook::HookKind::ToolEdit,
        "tool-read" => hook::HookKind::ToolRead,
        "session-start" => hook::HookKind::SessionStart,
        "session-end" => hook::HookKind::SessionEnd,
        "prompt" => hook::HookKind::Prompt,
        "stop" => hook::HookKind::Stop,
        other => anyhow::bail!("unknown hook event: {other}"),
    };
    hook::run(kind)
}

/// Default connection string used when `--with-pg` is set and `DATABASE_URL`
/// is unset. Mirrors `docker-compose.yml`. Only auto-applied with `--with-pg`
/// so a stray `ken serve` against a wrong DB never silently "works."
const DEFAULT_PG_URL: &str = "postgres://cae:cae_dev@localhost:5432/context_engine";

async fn run_server(rest: Vec<String>) -> Result<()> {
    let mut with_pg = false;
    let mut it = rest.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--with-pg" => with_pg = true,
            other => anyhow::bail!("unknown serve arg: {other}"),
        }
    }

    if with_pg {
        bring_up_postgres()?;
    }

    let database_url = std::env::var("DATABASE_URL").or_else(|_| {
        if with_pg {
            Ok::<_, std::env::VarError>(DEFAULT_PG_URL.to_string())
        } else {
            Err(std::env::VarError::NotPresent)
        }
    }).map_err(|_| anyhow::anyhow!("DATABASE_URL is required (or pass --with-pg to use the bundled Postgres)"))?;
    tracing::info!("connecting to postgres");
    let storage = PostgresStorage::connect(&database_url).await?;
    storage
        .migrate()
        .await
        .map_err(|e| anyhow::anyhow!("migrate failed: {e}"))?;
    let pgvector = storage.vector_extension_version().await?;
    tracing::info!(?pgvector, "postgres ready");

    let embedder = build_embedder().await?;
    tracing::info!(dim = embedder.dim(), "embedder ready");

    let state = Arc::new(AppState { storage, embedder });
    let app = build_router(state).layer(CorsLayer::permissive()).layer(TraceLayer::new_for_http());

    let bind = std::env::var("BIND").unwrap_or_else(|_| "0.0.0.0:8080".into());
    let listener = tokio::net::TcpListener::bind(&bind).await?;
    tracing::info!(%bind, "listening");
    axum::serve(listener, app).await?;
    Ok(())
}

async fn run_ingest_git(args: Vec<String>) -> Result<()> {
    use ken::client::EngineClient;
    use std::path::PathBuf;

    let mut repo: Option<PathBuf> = None;
    let mut workspace_raw: Option<String> = None;
    let mut branch: Option<String> = None;
    let mut since_years: Option<u64> = Some(2);
    let mut max_commits: u64 = 0;
    let mut mode = "both".to_string();
    let mut keep_merges = false;
    let mut keep_whitespace = false;

    let mut it = args.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--repo" => repo = it.next().map(PathBuf::from),
            "--workspace" => workspace_raw = it.next(),
            "--branch" => branch = it.next(),
            "--since" => since_years = it.next().and_then(|s| s.parse().ok()),
            "--max" => max_commits = it.next().and_then(|s| s.parse().ok()).unwrap_or(0),
            "--mode" => {
                mode = it
                    .next()
                    .filter(|s| matches!(s.as_str(), "docs" | "documents_only" | "sessions" | "sessions_only" | "both"))
                    .unwrap_or_else(|| "both".to_string());
            }
            "--keep-merges" => keep_merges = true,
            "--keep-whitespace" => keep_whitespace = true,
            "--full-history" => since_years = None,
            // `--source` is no longer needed — the server picks/creates one
            // by repo path. Accept it silently for backwards-compat.
            "--source" => {
                let _ = it.next();
            }
            other => anyhow::bail!("unknown ingest-git arg: {other}"),
        }
    }

    let repo = repo.context("--repo PATH is required")?;
    let repo = repo
        .canonicalize()
        .with_context(|| format!("canonicalize {}", repo.display()))?;
    let workspace_raw = workspace_raw.context("--workspace WS_ID_OR_NAME is required")?;

    let url = engine_url();
    let client = EngineClient::new(&url);
    let mut body = serde_json::json!({
        "workspace": workspace_raw,
        "repo": repo.to_string_lossy(),
        "max_commits": max_commits,
        "mode": mode,
        "skip_merges": !keep_merges,
        "skip_whitespace_only": !keep_whitespace,
    });
    if let Some(b) = branch {
        body["branch"] = serde_json::json!(b);
    }
    body["since_years"] = match since_years {
        Some(y) => serde_json::json!(y),
        None => serde_json::Value::Null,
    };

    let started = std::time::Instant::now();
    eprintln!("→ POST {url}/ingest_git");
    let resp = client
        .ingest_git_raw(body)
        .with_context(|| format!("ingest_git via {url}"))?;
    let elapsed = started.elapsed();
    let g = |k: &str| resp.get(k).and_then(|v| v.as_u64()).unwrap_or(0);
    println!(
        "ingest-git complete in {elapsed:?}\n  visited:             {}\n  kept:                {}\n  skipped (merge):     {}\n  skipped (bot):       {}\n  skipped (ws-only):   {}\n  documents written:   {}\n  documents unchanged: {}\n  sessions created:    {}\n  edges written:       {}",
        g("visited"),
        g("kept"),
        g("skipped_merge"),
        g("skipped_bot"),
        g("skipped_whitespace"),
        g("documents_written"),
        g("documents_unchanged"),
        g("sessions_created"),
        g("edges_written"),
    );
    Ok(())
}

fn engine_url() -> String {
    std::env::var("KEN_ENGINE_URL").unwrap_or_else(|_| "http://127.0.0.1:8080".into())
}

async fn run_ingest_codebase(args: Vec<String>) -> Result<()> {
    use std::path::PathBuf;

    let mut root: Option<PathBuf> = None;
    let mut workspace_raw: Option<String> = None;
    let mut max_bytes: u64 = 1024 * 1024;
    let mut respect_gitignore = true;
    let mut follow_symlinks = false;

    let mut it = args.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--root" => root = it.next().map(PathBuf::from),
            "--workspace" => workspace_raw = it.next(),
            "--max-bytes" => {
                max_bytes = it.next().and_then(|s| s.parse().ok()).unwrap_or(max_bytes);
            }
            "--no-gitignore" => respect_gitignore = false,
            "--follow-symlinks" => follow_symlinks = true,
            // `--source` is no longer needed — the server picks/creates one
            // by root path. Accept it silently for backwards-compat.
            "--source" => {
                let _ = it.next();
            }
            other => anyhow::bail!("unknown ingest-codebase arg: {other}"),
        }
    }

    let root = root.context("--root PATH is required")?;
    let root = root
        .canonicalize()
        .with_context(|| format!("canonicalize {}", root.display()))?;
    let workspace_raw = workspace_raw.context("--workspace WS_ID_OR_NAME is required")?;

    let url = engine_url();
    let client = ken::client::EngineClient::new(&url);
    let body = serde_json::json!({
        "workspace": workspace_raw,
        "root": root.to_string_lossy(),
        "max_bytes": max_bytes,
        "respect_gitignore": respect_gitignore,
        "follow_symlinks": follow_symlinks,
    });

    let started = std::time::Instant::now();
    eprintln!("→ POST {url}/ingest_codebase");
    let resp = client
        .ingest_codebase_raw(body)
        .with_context(|| format!("ingest_codebase via {url}"))?;
    let elapsed = started.elapsed();
    let g = |k: &str| resp.get(k).and_then(|v| v.as_u64()).unwrap_or(0);
    println!(
        "ingest-codebase complete in {elapsed:?}\n  files visited:         {}\n  documents written:     {}\n  documents unchanged:   {}\n  skipped (no adapter):  {}\n  skipped (too large):   {}\n  skipped (adapter err): {}\n  skipped (io err):      {}\n  chunks written:        {}\n  edges written:         {}",
        g("files_visited"),
        g("documents_written"),
        g("documents_unchanged"),
        g("files_skipped_no_adapter"),
        g("files_skipped_too_large"),
        g("files_skipped_adapter_error"),
        g("files_skipped_io_error"),
        g("chunks_written"),
        g("edges_written"),
    );
    Ok(())
}

async fn run_ingest_file(args: Vec<String>) -> Result<()> {
    use base64::Engine;
    use std::path::PathBuf;

    let mut path: Option<PathBuf> = None;
    let mut workspace_raw: Option<String> = None;
    let mut mime_override: Option<String> = None;

    let mut it = args.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--path" => path = it.next().map(PathBuf::from),
            "--workspace" => workspace_raw = it.next(),
            "--mime" => mime_override = it.next(),
            "--source" => {
                let _ = it.next();
            }
            other => anyhow::bail!("unknown ingest-file arg: {other}"),
        }
    }
    let path = path.context("--path PATH is required")?;
    let workspace_raw = workspace_raw.context("--workspace WS_ID_OR_NAME is required")?;
    let bytes = std::fs::read(&path).with_context(|| format!("read {}", path.display()))?;
    let bytes_b64 = base64::engine::general_purpose::STANDARD.encode(&bytes);
    let external_id = path
        .file_name()
        .and_then(|n| n.to_str())
        .map(str::to_string)
        .unwrap_or_else(|| path.to_string_lossy().into_owned());
    let mut body = serde_json::json!({
        "workspace": workspace_raw,
        "source_name": "uploads",
        "external_id": external_id,
        "bytes_base64": bytes_b64,
    });
    if let Some(m) = mime_override {
        body["mime"] = serde_json::json!(m);
    }

    let url = engine_url();
    let client = ken::client::EngineClient::new(&url);
    let started = std::time::Instant::now();
    eprintln!("→ POST {url}/ingest_file ({} bytes)", bytes.len());
    let resp = client
        .ingest_file_raw(body)
        .with_context(|| format!("ingest_file via {url}"))?;
    let elapsed = started.elapsed();
    let outcome = resp.get("outcome").and_then(|v| v.as_str()).unwrap_or("?");
    let doc = resp.get("document_id").map(|v| v.to_string()).unwrap_or_else(|| "?".into());
    let chunks = resp.get("chunks").and_then(|v| v.as_u64()).unwrap_or(0);
    let edges = resp.get("edges").and_then(|v| v.as_u64()).unwrap_or(0);
    println!("ingest-file complete in {elapsed:?}\n  {outcome}: doc {doc}, {chunks} chunks, {edges} edges");
    Ok(())
}

async fn run_ingest_url(args: Vec<String>) -> Result<()> {
    let mut url_arg: Option<String> = None;
    let mut workspace_raw: Option<String> = None;
    let mut depth: u32 = 0;
    let mut max_pages: u32 = 1;
    let mut same_host_only = true;

    let mut it = args.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--url" => url_arg = it.next(),
            "--workspace" => workspace_raw = it.next(),
            "--depth" => depth = it.next().and_then(|s| s.parse().ok()).unwrap_or(0),
            "--max-pages" => max_pages = it.next().and_then(|s| s.parse().ok()).unwrap_or(1),
            "--same-host-only" => same_host_only = true,
            "--no-same-host" => same_host_only = false,
            "--source" => {
                let _ = it.next();
            }
            other => anyhow::bail!("unknown ingest-url arg: {other}"),
        }
    }
    let start_url = url_arg.context("--url URL is required")?;
    let workspace_raw = workspace_raw.context("--workspace WS_ID_OR_NAME is required")?;

    let url = engine_url();
    let client = ken::client::EngineClient::new(&url);
    let body = serde_json::json!({
        "workspace": workspace_raw,
        "source_name": "web",
        "url": start_url,
        "depth": depth,
        "max_pages": max_pages,
        "same_host_only": same_host_only,
    });

    let started = std::time::Instant::now();
    eprintln!("→ POST {url}/ingest_url (depth={depth}, max_pages={max_pages})");
    let resp = client
        .ingest_url_raw(body)
        .with_context(|| format!("ingest_url via {url}"))?;
    let elapsed = started.elapsed();

    let pages = resp.get("pages").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let skipped = resp.get("skipped").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let timed_out = resp.get("timed_out").and_then(|v| v.as_bool()).unwrap_or(false);
    println!(
        "ingest-url complete in {elapsed:?}\n  pages indexed: {}\n  skipped:       {}\n  timed_out:     {}",
        pages.len(),
        skipped.len(),
        timed_out,
    );
    for p in &pages {
        let pu = p.get("url").and_then(|v| v.as_str()).unwrap_or("?");
        let outcome = p.get("outcome").and_then(|v| v.as_str()).unwrap_or("?");
        let chunks = p.get("chunks").and_then(|v| v.as_u64()).unwrap_or(0);
        println!("  - {pu}  [{outcome}, {chunks} chunks]");
    }
    for s in &skipped {
        let su = s.get("url").and_then(|v| v.as_str()).unwrap_or("?");
        let r = s.get("reason").and_then(|v| v.as_str()).unwrap_or("?");
        println!("  ! {su}  ({r})");
    }
    Ok(())
}

/// Pick the embedder. `EMBEDDER=mock` forces the deterministic 768-dim
/// `MockEmbedder` (used in CI / tests / dev with no internet); otherwise the
/// production `FastEmbedder` is built — the model is selected by
/// `KEN_EMBEDDER_MODEL` (defaults to `nomic-q`, the quantized 768-dim
/// nomic-embed-text-v1.5 — same schema as `nomic` but ~2× faster on CPU).
/// Construction triggers a one-time model download to the fastembed cache
/// and is heavy enough that we run it on a blocking thread.
async fn build_embedder() -> Result<Arc<dyn Embedder>> {
    let mode = std::env::var("EMBEDDER").unwrap_or_default();
    if mode.eq_ignore_ascii_case("mock") {
        tracing::warn!("EMBEDDER=mock — using deterministic MockEmbedder (development only)");
        return Ok(Arc::new(MockEmbedder::new(768)));
    }

    #[cfg(feature = "fastembed")]
    {
        tracing::info!("loading FastEmbedder (model picked by KEN_EMBEDDER_MODEL — default nomic-q)…");
        let embedder = tokio::task::spawn_blocking(engine::embed_fast::FastEmbedder::from_env)
            .await
            .map_err(|e| anyhow::anyhow!("fastembed init task panicked: {e}"))?
            .map_err(|e| anyhow::anyhow!("fastembed init failed: {e}"))?;
        Ok(Arc::new(embedder))
    }

    #[cfg(not(feature = "fastembed"))]
    {
        tracing::warn!("compiled without `fastembed` feature — falling back to MockEmbedder");
        Ok(Arc::new(MockEmbedder::new(768)))
    }
}

// ============================================================================
// --with-pg : auto-bringup of Postgres+pgvector via docker/podman
// ============================================================================

/// Container name used by both compose-driven and `ken serve --with-pg`
/// driven setups. Matches `docker-compose.yml` so users who already ran
/// `docker-compose up -d` see the same row.
const PG_CONTAINER: &str = "cae-postgres";
/// Named volume holding the data dir. Same name as docker-compose.yml so
/// existing data survives switching between compose and --with-pg.
const PG_VOLUME: &str = "cae-pg-data";
const PG_IMAGE: &str = "docker.io/pgvector/pgvector:pg16";

/// Detect docker or podman, then start (or create) the Postgres container
/// and wait for the healthcheck to report `healthy`. Idempotent — re-running
/// when the container is already healthy is a no-op.
fn bring_up_postgres() -> Result<()> {
    let runtime = detect_container_runtime()
        .context("--with-pg needs `docker` or `podman` on PATH")?;
    eprintln!("→ {runtime}: bringing up {PG_CONTAINER}");

    match container_state(runtime, PG_CONTAINER)? {
        ContainerState::Running => {
            eprintln!("  already running");
        }
        ContainerState::Stopped => {
            eprintln!("  starting existing container");
            run_quiet(runtime, &["start", PG_CONTAINER])?;
        }
        ContainerState::Missing => {
            eprintln!("  creating container (pulling image if needed)");
            create_pg_container(runtime)?;
        }
    }

    wait_for_healthy(runtime, PG_CONTAINER)?;
    eprintln!("  ✓ {PG_CONTAINER} healthy on :5432");
    Ok(())
}

#[derive(Debug, Clone, Copy)]
enum ContainerState {
    Running,
    Stopped,
    Missing,
}

/// Try `docker` first (works on Linux/Mac/Windows); fall back to `podman`
/// (the rootless default on many recent Linux distros). Returns the
/// argv[0] string the rest of the helpers should invoke.
fn detect_container_runtime() -> Option<&'static str> {
    for rt in ["docker", "podman"] {
        if std::process::Command::new(rt)
            .arg("--version")
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .ok()
            .filter(|s| s.success())
            .is_some()
        {
            return Some(rt);
        }
    }
    None
}

fn container_state(runtime: &str, name: &str) -> Result<ContainerState> {
    let out = std::process::Command::new(runtime)
        .args(["inspect", "--format", "{{.State.Status}}", name])
        .output()
        .with_context(|| format!("run {runtime} inspect"))?;
    if !out.status.success() {
        return Ok(ContainerState::Missing);
    }
    let status = String::from_utf8_lossy(&out.stdout).trim().to_string();
    Ok(match status.as_str() {
        "running" => ContainerState::Running,
        // "exited", "created", "paused", "dead" — anything else is a stopped
        // container we can `start` rather than re-creating.
        _ => ContainerState::Stopped,
    })
}

fn create_pg_container(runtime: &str) -> Result<()> {
    let args = [
        "run",
        "-d",
        "--name",
        PG_CONTAINER,
        "--restart",
        "unless-stopped",
        "-e",
        "POSTGRES_USER=cae",
        "-e",
        "POSTGRES_PASSWORD=cae_dev",
        "-e",
        "POSTGRES_DB=context_engine",
        "-e",
        "POSTGRES_INITDB_ARGS=--encoding=UTF-8",
        "-p",
        "5432:5432",
        "-v",
        &format!("{PG_VOLUME}:/var/lib/postgresql/data"),
        "--health-cmd",
        "pg_isready -U cae -d context_engine",
        "--health-interval",
        "5s",
        "--health-timeout",
        "3s",
        "--health-retries",
        "10",
        PG_IMAGE,
    ];
    let status = std::process::Command::new(runtime)
        .args(args)
        .status()
        .with_context(|| format!("run {runtime} run"))?;
    if !status.success() {
        anyhow::bail!("{runtime} run failed (exit {:?})", status.code());
    }
    Ok(())
}

fn wait_for_healthy(runtime: &str, name: &str) -> Result<()> {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(60);
    loop {
        let out = std::process::Command::new(runtime)
            .args(["inspect", "--format", "{{.State.Health.Status}}", name])
            .output()
            .with_context(|| format!("run {runtime} inspect for health"))?;
        if out.status.success() {
            let status = String::from_utf8_lossy(&out.stdout).trim().to_string();
            // Some runtimes (older podman) return "<no value>" when no
            // healthcheck is configured — treat that as healthy after a
            // few connection attempts.
            if status == "healthy" || status == "<no value>" {
                return Ok(());
            }
        }
        if std::time::Instant::now() >= deadline {
            anyhow::bail!("{name} did not become healthy within 60s");
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
}

fn run_quiet(runtime: &str, args: &[&str]) -> Result<()> {
    let status = std::process::Command::new(runtime)
        .args(args)
        .stdout(std::process::Stdio::null())
        .status()
        .with_context(|| format!("run {runtime} {}", args.join(" ")))?;
    if !status.success() {
        anyhow::bail!("{runtime} {} failed (exit {:?})", args.join(" "), status.code());
    }
    Ok(())
}
