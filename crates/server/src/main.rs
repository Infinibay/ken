use std::sync::Arc;

use anyhow::{Context, Result};
use cae_server::{build_router, AppState};
use engine::embed::{Embedder, MockEmbedder};
use engine::postgres::PostgresStorage;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        None | Some("serve") => run_server().await,
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
        "context-engine — embedding + KG service\n\n\
         USAGE:\n  \
           context-engine [serve]                       Run the HTTP API (default)\n  \
           context-engine ingest-git --repo PATH --workspace WS [opts]\n  \
           context-engine ingest-codebase --root PATH --workspace WS [opts]\n\n\
         INGEST-GIT OPTIONS:\n  \
           --repo PATH           Local repository path (required)\n  \
           --workspace WS_ID     Workspace id (required, integer)\n  \
           --source SOURCE_ID    Existing source id (default: create one)\n  \
           --branch NAME         Branch / ref to walk (default: HEAD)\n  \
           --since YEARS         Only walk commits newer than N years (default: 2)\n  \
           --max NUM             Hard cap on commits processed (default: 0 = unlimited)\n  \
           --mode both|docs|sessions   Which side to populate (default: both)\n  \
           --keep-merges         Don't skip merge commits\n  \
           --keep-whitespace     Don't skip whitespace-only commits\n\n\
         INGEST-CODEBASE OPTIONS:\n  \
           --root PATH           Working tree root (required)\n  \
           --workspace WS_ID     Workspace id (required, integer)\n  \
           --source SOURCE_ID    Existing source id (default: create one)\n  \
           --max-bytes N         Skip files larger than N bytes (default: 1048576)\n  \
           --no-gitignore        Ingest .gitignore'd files too (default: respect)\n  \
           --follow-symlinks     Follow symlinks during walk (default: skip)\n\n\
         ENV:\n  \
           DATABASE_URL    Postgres connection string (required)\n  \
           EMBEDDER=mock   Use deterministic MockEmbedder instead of fastembed"
    );
}

async fn run_server() -> Result<()> {
    let database_url =
        std::env::var("DATABASE_URL").map_err(|_| anyhow::anyhow!("DATABASE_URL is required"))?;
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
    use engine::types::{SourceId, WorkspaceId};
    use std::path::PathBuf;

    let mut repo: Option<PathBuf> = None;
    let mut workspace: Option<u64> = None;
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
            "--workspace" => workspace = it.next().and_then(|s| s.parse().ok()),
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
    let workspace_id = WorkspaceId(workspace.context("--workspace WS_ID is required")?);

    let database_url =
        std::env::var("DATABASE_URL").map_err(|_| anyhow::anyhow!("DATABASE_URL is required"))?;
    let storage = PostgresStorage::connect(&database_url).await?;
    storage
        .migrate()
        .await
        .map_err(|e| anyhow::anyhow!("migrate failed: {e}"))?;

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
    use engine::types::{SourceId, WorkspaceId};
    use std::path::PathBuf;

    let mut root: Option<PathBuf> = None;
    let mut workspace: Option<u64> = None;
    let mut source: Option<u64> = None;
    let mut max_bytes: u64 = 1024 * 1024;
    let mut respect_gitignore = true;
    let mut follow_symlinks = false;

    let mut it = args.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--root" => root = it.next().map(PathBuf::from),
            "--workspace" => workspace = it.next().and_then(|s| s.parse().ok()),
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
    let workspace_id = WorkspaceId(workspace.context("--workspace WS_ID is required")?);

    let database_url =
        std::env::var("DATABASE_URL").map_err(|_| anyhow::anyhow!("DATABASE_URL is required"))?;
    let storage = PostgresStorage::connect(&database_url).await?;
    storage
        .migrate()
        .await
        .map_err(|e| anyhow::anyhow!("migrate failed: {e}"))?;

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
