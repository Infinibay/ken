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
            #[cfg(feature = "git")]
            {
                let rest: Vec<String> = args.collect();
                run_ingest_git(rest).await
            }
            #[cfg(not(feature = "git"))]
            {
                let _ = args;
                anyhow::bail!("`ingest-git` requires the `git` feature at build time");
            }
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

/// Shared between every `ingest-*` subcommand: resolve `--workspace VALUE`
/// to a `WorkspaceId`. Numeric → use as id; otherwise find-or-create
/// the named workspace under tenant `"local"`.
async fn resolve_workspace_arg(
    storage: &engine::postgres::PostgresStorage,
    value: &str,
) -> Result<engine::types::WorkspaceId> {
    use engine::types::WorkspaceId;
    if let Ok(id) = value.parse::<u64>() {
        return Ok(WorkspaceId(id));
    }
    let (id, _, created) = storage
        .find_or_create_workspace("local", value)
        .await
        .with_context(|| format!("find-or-create workspace {value:?}"))?;
    if created {
        eprintln!("→ created workspace {value:?} under tenant \"local\" (id {})", id.0);
    } else {
        eprintln!("→ workspace {value:?} resolved to id {}", id.0);
    }
    Ok(id)
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

#[cfg(feature = "git")]
async fn run_ingest_git(args: Vec<String>) -> Result<()> {
    use engine::ingest_git::{ensure_source, ingest_repo, IngestGitConfig, IngestMode};
    use engine::types::SourceId;
    use std::path::PathBuf;

    let mut repo: Option<PathBuf> = None;
    let mut workspace_raw: Option<String> = None;
    let mut source: Option<u64> = None;
    let mut branch: Option<String> = None;
    let mut since_years: Option<u64> = Some(2);
    let mut max_commits: u64 = 0;
    let mut mode = IngestMode::Both;
    let mut keep_merges = false;
    let mut keep_whitespace = false;

    let mut it = args.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--repo" => repo = it.next().map(PathBuf::from),
            "--workspace" => workspace_raw = it.next(),
            "--source" => source = it.next().and_then(|s| s.parse().ok()),
            "--branch" => branch = it.next(),
            "--since" => since_years = it.next().and_then(|s| s.parse().ok()),
            "--max" => max_commits = it.next().and_then(|s| s.parse().ok()).unwrap_or(0),
            "--mode" => {
                mode = match it.next().as_deref() {
                    Some("docs") | Some("documents_only") => IngestMode::DocumentsOnly,
                    Some("sessions") | Some("sessions_only") => IngestMode::SessionsOnly,
                    Some("both") | None => IngestMode::Both,
                    Some(other) => anyhow::bail!("unknown --mode: {other}"),
                }
            }
            "--keep-merges" => keep_merges = true,
            "--keep-whitespace" => keep_whitespace = true,
            "--full-history" => since_years = None,
            other => anyhow::bail!("unknown ingest-git arg: {other}"),
        }
    }

    let repo = repo.context("--repo PATH is required")?;
    let workspace_raw = workspace_raw.context("--workspace WS_ID_OR_NAME is required")?;

    let database_url =
        std::env::var("DATABASE_URL").map_err(|_| anyhow::anyhow!("DATABASE_URL is required"))?;
    let storage = PostgresStorage::connect(&database_url).await?;
    storage
        .migrate()
        .await
        .map_err(|e| anyhow::anyhow!("migrate failed: {e}"))?;
    let workspace_id = resolve_workspace_arg(&storage, &workspace_raw).await?;

    let source_id = match source {
        Some(s) => SourceId(s),
        None => {
            let name = format!("git:{}", repo.display());
            ensure_source(&storage, workspace_id, &name, &repo).await?
        }
    };

    let mut cfg = IngestGitConfig::new(&repo, workspace_id, source_id);
    cfg.branch = branch;
    cfg.skip_merges = !keep_merges;
    cfg.skip_whitespace_only = !keep_whitespace;
    cfg.max_commits = max_commits;
    cfg.mode = mode;
    if let Some(y) = since_years {
        cfg = cfg.since_years(y);
    }

    let embedder = build_embedder().await?;

    let started = std::time::Instant::now();
    tracing::info!(
        repo = %repo.display(),
        ?workspace_id,
        ?source_id,
        ?cfg.branch,
        ?cfg.since_seconds_unix,
        "starting git ingest"
    );
    let stats = ingest_repo(&storage, embedder, &cfg)
        .await
        .map_err(|e| anyhow::anyhow!("ingest failed: {e}"))?;
    let elapsed = started.elapsed();
    println!(
        "ingest-git complete in {elapsed:?}\n  visited:           {visited}\n  kept:              {kept}\n  skipped (merge):   {sm}\n  skipped (bot):     {sb}\n  skipped (ws-only): {sw}\n  documents written:   {dw}\n  documents unchanged: {du}\n  sessions created:    {sc}\n  edges written:       {ew}",
        visited = stats.walk.visited,
        kept = stats.walk.kept,
        sm = stats.walk.skipped_merge,
        sb = stats.walk.skipped_bot,
        sw = stats.walk.skipped_whitespace,
        dw = stats.documents_written,
        du = stats.documents_unchanged,
        sc = stats.sessions_created,
        ew = stats.edges_written,
    );
    Ok(())
}

async fn run_ingest_codebase(args: Vec<String>) -> Result<()> {
    use engine::ingest_fs::{ensure_source, ingest_codebase, IngestCodebaseConfig};
    use engine::types::SourceId;
    use std::path::PathBuf;

    let mut root: Option<PathBuf> = None;
    let mut workspace_raw: Option<String> = None;
    let mut source: Option<u64> = None;
    let mut max_bytes: u64 = 1024 * 1024;
    let mut respect_gitignore = true;
    let mut follow_symlinks = false;

    let mut it = args.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--root" => root = it.next().map(PathBuf::from),
            "--workspace" => workspace_raw = it.next(),
            "--source" => source = it.next().and_then(|s| s.parse().ok()),
            "--max-bytes" => {
                max_bytes = it.next().and_then(|s| s.parse().ok()).unwrap_or(max_bytes);
            }
            "--no-gitignore" => respect_gitignore = false,
            "--follow-symlinks" => follow_symlinks = true,
            other => anyhow::bail!("unknown ingest-codebase arg: {other}"),
        }
    }

    let root = root.context("--root PATH is required")?;
    let workspace_raw = workspace_raw.context("--workspace WS_ID_OR_NAME is required")?;

    let database_url =
        std::env::var("DATABASE_URL").map_err(|_| anyhow::anyhow!("DATABASE_URL is required"))?;
    let storage = PostgresStorage::connect(&database_url).await?;
    storage
        .migrate()
        .await
        .map_err(|e| anyhow::anyhow!("migrate failed: {e}"))?;
    let workspace_id = resolve_workspace_arg(&storage, &workspace_raw).await?;

    let source_id = match source {
        Some(s) => SourceId(s),
        None => {
            let name = format!("codebase:{}", root.display());
            ensure_source(&storage, workspace_id, &name, &root).await?
        }
    };

    let mut cfg = IngestCodebaseConfig::new(&root, workspace_id, source_id);
    cfg.max_file_bytes = max_bytes;
    cfg.respect_gitignore = respect_gitignore;
    cfg.follow_symlinks = follow_symlinks;

    let embedder = build_embedder().await?;

    tracing::info!(
        root = %root.display(),
        ?workspace_id,
        ?source_id,
        "starting codebase ingest"
    );
    let stats = ingest_codebase(&storage, embedder, &cfg)
        .await
        .map_err(|e| anyhow::anyhow!("ingest failed: {e}"))?;
    println!(
        "ingest-codebase complete in {elapsed:?}\n  files visited:        {visited}\n  documents written:    {dw}\n  documents unchanged:  {du}\n  skipped (no adapter): {snm}\n  skipped (too large):  {stl}\n  skipped (adapter err):{sae}\n  skipped (io err):     {sio}\n  chunks written:       {cw}\n  edges written:        {ew}",
        elapsed = stats.elapsed,
        visited = stats.files_visited,
        dw = stats.documents_written,
        du = stats.documents_unchanged,
        snm = stats.files_skipped_no_adapter,
        stl = stats.files_skipped_too_large,
        sae = stats.files_skipped_adapter_error,
        sio = stats.files_skipped_io_error,
        cw = stats.chunks_written,
        ew = stats.edges_written,
    );
    Ok(())
}

async fn run_ingest_file(args: Vec<String>) -> Result<()> {
    use engine::ingest::{default_adapters, pick_adapter, MimeHint};
    use engine::ingest_fs::{ensure_source, ingest_uri, FileOutcome, IngestFileError};
    use engine::types::{MetadataMap, SourceId};
    use std::path::PathBuf;

    let mut path: Option<PathBuf> = None;
    let mut workspace_raw: Option<String> = None;
    let mut source: Option<u64> = None;
    let mut mime_override: Option<String> = None;

    let mut it = args.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--path" => path = it.next().map(PathBuf::from),
            "--workspace" => workspace_raw = it.next(),
            "--source" => source = it.next().and_then(|s| s.parse().ok()),
            "--mime" => mime_override = it.next(),
            other => anyhow::bail!("unknown ingest-file arg: {other}"),
        }
    }
    let path = path.context("--path PATH is required")?;
    let workspace_raw = workspace_raw.context("--workspace WS_ID_OR_NAME is required")?;

    let database_url =
        std::env::var("DATABASE_URL").map_err(|_| anyhow::anyhow!("DATABASE_URL is required"))?;
    let storage = PostgresStorage::connect(&database_url).await?;
    storage
        .migrate()
        .await
        .map_err(|e| anyhow::anyhow!("migrate failed: {e}"))?;
    let workspace_id = resolve_workspace_arg(&storage, &workspace_raw).await?;

    let source_id = match source {
        Some(s) => SourceId(s),
        None => {
            // Reuse `ensure_source` from ingest_fs (codebase tag is the closest
            // match for one-off filesystem uploads). For a true "manual upload"
            // tag we'd add a new helper, but the engine doesn't dispatch on
            // SourceKind anywhere — it's purely descriptive.
            let name = format!("file:{}", path.display());
            ensure_source(&storage, workspace_id, &name, &path).await?
        }
    };

    let bytes = std::fs::read(&path)
        .with_context(|| format!("read {}", path.display()))?;
    let uri = path.to_string_lossy().to_string();
    let extension = path
        .extension()
        .and_then(|e| e.to_str())
        .map(|s| s.to_ascii_lowercase());
    let hint = MimeHint {
        mime: mime_override.clone(),
        extension,
    };
    let adapters = default_adapters();
    let adapter = pick_adapter(&adapters, &hint)
        .with_context(|| format!("no adapter accepts mime={:?} ext={:?}", hint.mime, hint.extension))?;

    let embedder = build_embedder().await?;
    tracing::info!(path = %path.display(), ?workspace_id, ?source_id, "ingesting one file");

    let started = std::time::Instant::now();
    let outcome = ingest_uri(
        &storage,
        &embedder,
        workspace_id,
        source_id,
        adapter,
        &uri,
        bytes,
        mime_override,
        MetadataMap::default(),
    )
    .await
    .map_err(|e| match e {
        IngestFileError::Adapter(err) => anyhow::anyhow!("adapter rejected: {err}"),
        IngestFileError::Storage(err) => anyhow::anyhow!("storage error: {err}"),
    })?;
    let elapsed = started.elapsed();

    match outcome {
        FileOutcome::Written { chunks, edges, document_id, outcome } => println!(
            "ingest-file complete in {elapsed:?}\n  {outcome}: doc {document_id:?}, {chunks} chunks, {edges} edges"
        ),
        FileOutcome::Unchanged { document_id } => println!("ingest-file complete in {elapsed:?} — unchanged (doc {document_id:?})"),
    }
    Ok(())
}

async fn run_ingest_url(args: Vec<String>) -> Result<()> {
    use ken::url_crawl::{build_agent, canonical_url, extract_links, fetch_url};
    use engine::ingest::{default_adapters, pick_adapter, MimeHint};
    use engine::ingest_fs::{ingest_uri, FileOutcome, IngestFileError};
    use engine::storage::NewSource;
    use engine::types::{Acl, MetadataMap, SourceId, SourceKind};
    use std::collections::{HashSet, VecDeque};

    let mut url_arg: Option<String> = None;
    let mut workspace_raw: Option<String> = None;
    let mut source: Option<u64> = None;
    let mut depth: u32 = 0;
    let mut max_pages: u32 = 10;
    let mut same_host_only = true;

    let mut it = args.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--url" => url_arg = it.next(),
            "--workspace" => workspace_raw = it.next(),
            "--source" => source = it.next().and_then(|s| s.parse().ok()),
            "--depth" => depth = it.next().and_then(|s| s.parse().ok()).unwrap_or(0),
            "--max-pages" => max_pages = it.next().and_then(|s| s.parse().ok()).unwrap_or(10),
            "--same-host-only" => same_host_only = true,
            "--no-same-host" => same_host_only = false,
            other => anyhow::bail!("unknown ingest-url arg: {other}"),
        }
    }
    let start_url = url_arg.context("--url URL is required")?;
    let workspace_raw = workspace_raw.context("--workspace WS_ID_OR_NAME is required")?;
    let start = url::Url::parse(&start_url).context("invalid --url")?;
    let start_host = start.host_str().map(|s| s.to_string());

    let database_url =
        std::env::var("DATABASE_URL").map_err(|_| anyhow::anyhow!("DATABASE_URL is required"))?;
    let storage = PostgresStorage::connect(&database_url).await?;
    storage
        .migrate()
        .await
        .map_err(|e| anyhow::anyhow!("migrate failed: {e}"))?;
    let workspace_id = resolve_workspace_arg(&storage, &workspace_raw).await?;

    let source_id = match source {
        Some(s) => SourceId(s),
        None => {
            let name = match &start_host {
                Some(h) => format!("url:{h}"),
                None => format!("url:{start_url}"),
            };
            if let Some(existing) = storage.find_source_by_name(workspace_id, &name).await {
                existing
            } else {
                storage
                    .create_source(NewSource {
                        workspace_id,
                        kind: SourceKind::Http,
                        name,
                        config_json: serde_json::json!({
                            "kind": "url",
                            "start": start_url,
                            "depth": depth,
                            "max_pages": max_pages,
                            "same_host_only": same_host_only,
                        }),
                        keep_history: false,
                        default_acl: Acl::default(),
                    })
                    .await?
            }
        }
    };

    let embedder = build_embedder().await?;
    let adapters = default_adapters();
    // ureq is sync. Each fetch runs on a blocking thread so the tokio
    // runtime stays free for embedding tasks.
    let agent = build_agent(20);

    let mut queue: VecDeque<(url::Url, u32)> = VecDeque::new();
    let mut visited: HashSet<String> = HashSet::new();
    queue.push_back((start.clone(), 0));
    visited.insert(canonical_url(&start));

    let mut pages_fetched = 0u32;
    let mut pages_written = 0u32;
    let mut pages_unchanged = 0u32;
    let mut pages_failed = 0u32;
    let mut chunks_total = 0u64;

    let started = std::time::Instant::now();
    while let Some((url, d)) = queue.pop_front() {
        if pages_fetched >= max_pages {
            break;
        }
        pages_fetched += 1;
        let url_string = url.to_string();
        tracing::info!(url = %url_string, depth = d, "fetching");
        let agent_clone = agent.clone();
        let fetched = tokio::task::spawn_blocking(move || fetch_url(&agent_clone, &url_string))
            .await
            .map_err(|e| anyhow::anyhow!("fetch task panicked: {e}"))?;
        let (mime, bytes) = match fetched {
            Ok(v) => v,
            Err(err) => {
                tracing::warn!(url = %url, error = %err, "fetch failed");
                pages_failed += 1;
                continue;
            }
        };

        let extension = url
            .path_segments()
            .and_then(|mut s| s.next_back())
            .and_then(|name| name.rsplit_once('.'))
            .map(|(_, ext)| ext.to_ascii_lowercase());
        let hint = MimeHint {
            mime: Some(mime.clone()),
            extension,
        };
        let Some(adapter) = pick_adapter(&adapters, &hint) else {
            tracing::warn!(url = %url, mime = %mime, "no adapter for this content type");
            pages_failed += 1;
            continue;
        };

        // For HTML: extract links BEFORE bytes are moved into ingest_uri.
        let next_links: Vec<url::Url> = if d < depth && mime.starts_with("text/html") {
            extract_links(&url, std::str::from_utf8(&bytes).unwrap_or(""))
        } else {
            Vec::new()
        };

        let result = ingest_uri(
            &storage,
            &embedder,
            workspace_id,
            source_id,
            adapter,
            url.as_str(),
            bytes,
            Some(mime.clone()),
            MetadataMap::default(),
        )
        .await;
        match result {
            Ok(FileOutcome::Written { chunks, .. }) => {
                pages_written += 1;
                chunks_total += chunks as u64;
            }
            Ok(FileOutcome::Unchanged { .. }) => pages_unchanged += 1,
            Err(IngestFileError::Adapter(err)) => {
                tracing::warn!(url = %url, error = %err, "adapter rejected");
                pages_failed += 1;
                continue;
            }
            Err(IngestFileError::Storage(err)) => {
                anyhow::bail!("storage error on {url}: {err}");
            }
        }

        // Enqueue next-hop links once the page is persisted, applying the
        // same-host filter and dedup against `visited`.
        for link in next_links {
            if same_host_only && link.host_str() != start_host.as_deref() {
                continue;
            }
            let canon = canonical_url(&link);
            if visited.insert(canon) {
                queue.push_back((link, d + 1));
            }
        }
    }
    let elapsed = started.elapsed();
    println!(
        "ingest-url complete in {elapsed:?}\n  pages fetched:  {pf}\n  written:        {pw}\n  unchanged:      {pu}\n  failed:         {ff}\n  chunks written: {ct}",
        pf = pages_fetched,
        pw = pages_written,
        pu = pages_unchanged,
        ff = pages_failed,
        ct = chunks_total,
    );
    Ok(())
}

/// Pick the embedder. `EMBEDDER=mock` forces the deterministic 768-dim
/// `MockEmbedder` (used in CI / tests / dev with no internet); otherwise the
/// production `FastEmbedder` (nomic-embed-text-v1.5) is built. Construction
/// of `FastEmbedder` triggers a one-time model download to the fastembed
/// cache and is heavy enough that we run it on a blocking thread.
async fn build_embedder() -> Result<Arc<dyn Embedder>> {
    let mode = std::env::var("EMBEDDER").unwrap_or_default();
    if mode.eq_ignore_ascii_case("mock") {
        tracing::warn!("EMBEDDER=mock — using deterministic MockEmbedder (development only)");
        return Ok(Arc::new(MockEmbedder::new(768)));
    }

    #[cfg(feature = "fastembed")]
    {
        tracing::info!("loading FastEmbedder (nomic-embed-text-v1.5)…");
        let embedder = tokio::task::spawn_blocking(engine::embed_fast::FastEmbedder::nomic_v15)
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
