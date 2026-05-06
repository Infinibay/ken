//! Filesystem-based codebase ingest. Walks a working tree, dispatches
//! each file to the existing `ContentAdapter` registry (Code / Markdown /
//! PDF / PlainText), and persists Documents + Chunks + Embeddings via
//! the same path `/ingest_text` uses internally. The agent-facing
//! contract: after this runs, `/rank "<query>"` returns chunks with
//! `path_or_url = "<relative_path>"` so the agent can locate code by
//! file:line directly without any extra search step.
//!
//! Respects `.gitignore` / `.ignore` by default (via the `ignore` crate),
//! so generated files, build outputs, and `node_modules` don't pollute
//! the index. Hidden directories are skipped unless explicitly included.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use crate::annotate::url_edges_for_chunks;
use crate::embed::Embedder;
use crate::ingest::{
    default_adapters, pick_adapter, ContentAdapter, EdgeDraft, EdgeEndpoint, IngestContext,
    IngestOutput, MimeHint, RawDocument,
};
use crate::postgres::PostgresStorage;
use crate::storage::{NewChunk, NewDocument, NewEdge, NewSource, StorageResult, UpsertOutcome};
use crate::types::{
    Acl, ChunkId, DocumentId, MetadataMap, NodeRef, SourceId, SourceKind, WorkspaceId,
};

/// Configuration for `ingest_codebase`.
#[derive(Debug, Clone)]
pub struct IngestCodebaseConfig {
    pub root: PathBuf,
    pub workspace_id: WorkspaceId,
    pub source_id: SourceId,
    /// Skip files larger than this many bytes. Default 1 MiB. Code files
    /// past this are usually generated, vendored, or minified — embedding
    /// them rarely helps the ranker and inflates storage.
    pub max_file_bytes: u64,
    /// Respect `.gitignore` / `.ignore` / global ignore. Default `true`.
    pub respect_gitignore: bool,
    /// Follow symlinks during the walk. Default `false` to avoid cycles.
    pub follow_symlinks: bool,
}

impl IngestCodebaseConfig {
    pub fn new(
        root: impl Into<PathBuf>,
        workspace_id: WorkspaceId,
        source_id: SourceId,
    ) -> Self {
        Self {
            root: root.into(),
            workspace_id,
            source_id,
            max_file_bytes: 1024 * 1024,
            respect_gitignore: true,
            follow_symlinks: false,
        }
    }
}

#[derive(Debug, Default, Clone)]
pub struct IngestCodebaseStats {
    pub files_visited: u64,
    pub documents_written: u64,
    pub documents_unchanged: u64,
    pub files_skipped_no_adapter: u64,
    pub files_skipped_too_large: u64,
    pub files_skipped_adapter_error: u64,
    pub files_skipped_io_error: u64,
    pub chunks_written: u64,
    pub edges_written: u64,
    pub elapsed: Duration,
}

/// Create (or reuse) a Source row tagged as a filesystem codebase. Find-or-
/// create on `(workspace_id, name)` so re-running an ingest command without
/// `--source` doesn't pile up duplicate Source rows — the second run reuses
/// the first, and document idempotency via `(source_id, external_id)` keeps
/// re-ingestion cheap.
pub async fn ensure_source(
    storage: &PostgresStorage,
    workspace_id: WorkspaceId,
    name: &str,
    repo_path: &Path,
) -> StorageResult<SourceId> {
    if let Some(id) = storage.find_source_by_name(workspace_id, name).await {
        return Ok(id);
    }
    storage
        .create_source(NewSource {
            workspace_id,
            kind: SourceKind::Custom("codebase".into()),
            name: name.to_string(),
            config_json: serde_json::json!({
                "kind": "codebase",
                "root": repo_path.to_string_lossy(),
            }),
            keep_history: false,
            default_acl: Acl::default(),
        })
        .await
}

/// Walk `cfg.root`, ingest every file an adapter accepts, and persist
/// Documents + Chunks + embeddings. Idempotent: re-running keeps existing
/// Documents whose content hash hasn't changed (`UpsertOutcome::Unchanged`).
///
/// Emits a `tracing::info!` summary every `KEN_INGEST_PROGRESS_EVERY` files
/// (default 25) so a long ingest is observable in the server log. Per-file
/// outcomes log at DEBUG.
pub async fn ingest_codebase(
    storage: &PostgresStorage,
    embedder: Arc<dyn Embedder>,
    cfg: &IngestCodebaseConfig,
) -> StorageResult<IngestCodebaseStats> {
    let started = Instant::now();
    let mut stats = IngestCodebaseStats::default();
    let adapters = default_adapters();

    let progress_every: u64 = std::env::var("KEN_INGEST_PROGRESS_EVERY")
        .ok()
        .and_then(|v| v.parse().ok())
        .filter(|n: &u64| *n > 0)
        .unwrap_or(25);

    // The ONNX runtime under fastembed accumulates internal state across
    // inferences (per-batch quant buffers, arena pages) that Rust can't
    // reclaim — RSS climbs unbounded on long ingests. We periodically drop
    // and rebuild the embedder to release that state. 0 disables.
    let reload_every: u64 = std::env::var("KEN_EMBEDDER_RELOAD_EVERY")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(500);

    tracing::info!(
        root = %cfg.root.display(),
        max_file_bytes = cfg.max_file_bytes,
        respect_gitignore = cfg.respect_gitignore,
        progress_every,
        "starting codebase ingest",
    );

    // Drop the chunks HNSW index for the duration of the walk. pgvector
    // maintains HNSW per-row on INSERT, which on a large ingest is both
    // the dominant write cost and the main source of PG memory pressure
    // (in extreme cases triggering the OOM killer mid-ingest). We rebuild
    // the index in one shot at the end. Side effect: semantic search via
    // the chunks vector is unindexed during the walk — bulk ingests are
    // expected to be off-peak operations, so this is acceptable.
    if let Err(err) = storage.drop_chunks_embedding_index().await {
        tracing::warn!(error = %err, "could not drop chunks embedding index; continuing");
    } else {
        tracing::info!("dropped chunks HNSW index for bulk ingest");
    }

    let mut builder = ignore::WalkBuilder::new(&cfg.root);
    builder
        .standard_filters(cfg.respect_gitignore)
        .hidden(true)
        .follow_links(cfg.follow_symlinks);
    let walker = builder.build();

    for entry in walker {
        let entry = match entry {
            Ok(e) => e,
            Err(err) => {
                tracing::debug!(error = %err, "walk error");
                stats.files_skipped_io_error += 1;
                continue;
            }
        };
        if !entry.file_type().is_some_and(|ft| ft.is_file()) {
            continue;
        }
        stats.files_visited += 1;
        let abs = entry.path();
        let rel = abs
            .strip_prefix(&cfg.root)
            .unwrap_or(abs)
            .to_string_lossy()
            .to_string();

        // Cheap stat-based size check before reading the file.
        if let Ok(meta) = entry.metadata() {
            if meta.len() > cfg.max_file_bytes {
                stats.files_skipped_too_large += 1;
                tracing::debug!(path = %rel, size = meta.len(), "skip: too large");
                continue;
            }
        }

        let bytes = match std::fs::read(abs) {
            Ok(b) => b,
            Err(err) => {
                tracing::debug!(path = %rel, error = %err, "read failed");
                stats.files_skipped_io_error += 1;
                continue;
            }
        };

        let hint = MimeHint::from_uri(&rel);
        let Some(adapter) = pick_adapter(&adapters, &hint) else {
            stats.files_skipped_no_adapter += 1;
            continue;
        };

        let file_t0 = Instant::now();
        match ingest_uri(
            storage,
            &embedder,
            cfg.workspace_id,
            cfg.source_id,
            adapter,
            &rel,
            bytes,
            None,
            MetadataMap::default(),
        )
        .await
        {
            Ok(FileOutcome::Written { chunks, edges, .. }) => {
                stats.documents_written += 1;
                stats.chunks_written += chunks as u64;
                stats.edges_written += edges as u64;
                tracing::debug!(
                    path = %rel,
                    chunks,
                    edges,
                    took_ms = file_t0.elapsed().as_millis() as u64,
                    "ingested",
                );
            }
            Ok(FileOutcome::Unchanged { .. }) => {
                stats.documents_unchanged += 1;
                tracing::debug!(path = %rel, "unchanged");
            }
            Err(IngestFileError::Adapter(err)) => {
                tracing::debug!(path = %rel, error = %err, "adapter rejected file");
                stats.files_skipped_adapter_error += 1;
            }
            Err(IngestFileError::Storage(err)) => return Err(err),
        }

        if reload_every > 0 && stats.files_visited > 0 && stats.files_visited % reload_every == 0 {
            let t0 = Instant::now();
            match embedder.reset() {
                Ok(()) => tracing::info!(
                    after_files = stats.files_visited,
                    took_ms = t0.elapsed().as_millis() as u64,
                    rss_mb = current_rss_mb().map(|m| format!("{m:.0}")).unwrap_or_else(|| "?".into()),
                    "reloaded embedder (releases ORT state)",
                ),
                Err(e) => tracing::warn!(
                    error = %e,
                    "embedder reset failed; continuing with existing session",
                ),
            }
        }

        if stats.files_visited % progress_every == 0 {
            let elapsed = started.elapsed();
            let rate = stats.files_visited as f64 / elapsed.as_secs_f64().max(1e-3);
            tracing::info!(
                visited = stats.files_visited,
                written = stats.documents_written,
                unchanged = stats.documents_unchanged,
                skipped_adapter = stats.files_skipped_no_adapter,
                skipped_too_large = stats.files_skipped_too_large,
                skipped_error = stats.files_skipped_adapter_error + stats.files_skipped_io_error,
                chunks = stats.chunks_written,
                elapsed_s = elapsed.as_secs(),
                rate_per_s = format!("{rate:.1}"),
                rss_mb = current_rss_mb().map(|m| format!("{m:.0}")).unwrap_or_else(|| "?".into()),
                "ingest progress",
            );
        }
    }

    // Rebuild the HNSW index in one shot now that all rows are inserted.
    // pgvector builds the whole graph from scratch which is far faster (and
    // bounded in memory) than per-row maintenance during INSERT. Logged at
    // INFO so the user knows the post-ingest pause is the index build.
    let index_t0 = Instant::now();
    tracing::info!("rebuilding chunks HNSW index (this can take a minute on large corpora)…");
    match storage.rebuild_chunks_embedding_index().await {
        Ok(()) => tracing::info!(took_s = index_t0.elapsed().as_secs(), "chunks HNSW index rebuilt"),
        Err(err) => tracing::error!(error = %err, "rebuild HNSW index failed; semantic search will fall back to seq scan until manual rebuild"),
    }

    stats.elapsed = started.elapsed();
    tracing::info!(
        visited = stats.files_visited,
        written = stats.documents_written,
        unchanged = stats.documents_unchanged,
        skipped = stats.files_skipped_no_adapter
            + stats.files_skipped_too_large
            + stats.files_skipped_adapter_error
            + stats.files_skipped_io_error,
        chunks = stats.chunks_written,
        edges = stats.edges_written,
        elapsed_s = stats.elapsed.as_secs(),
        "codebase ingest done",
    );
    Ok(stats)
}

/// Best-effort current resident-set in MB for the calling process. Linux-only;
/// other platforms return `None`. Used purely for progress logs — a bad
/// reading is logged as `?`, never propagated.
#[cfg(target_os = "linux")]
fn current_rss_mb() -> Option<f64> {
    let s = std::fs::read_to_string("/proc/self/status").ok()?;
    for line in s.lines() {
        if let Some(rest) = line.strip_prefix("VmRSS:") {
            let kb: f64 = rest.trim().split_whitespace().next()?.parse().ok()?;
            return Some(kb / 1024.0);
        }
    }
    None
}

#[cfg(not(target_os = "linux"))]
fn current_rss_mb() -> Option<f64> {
    None
}

/// Outcome of `ingest_uri`. Both variants carry the resolved `DocumentId`
/// so callers (HTTP routes, MCP tools) can echo it back regardless of
/// whether the content was already up-to-date.
///
/// A re-ingest of the same content (same hash) short-circuits to
/// `Unchanged`; otherwise the chunk and edge counts are
/// what was actually persisted.
pub enum FileOutcome {
    Written {
        document_id: DocumentId,
        chunks: usize,
        edges: usize,
        /// `"created"`, `"updated"`, or `"versioned"` — mirrors the
        /// `UpsertOutcome` variant. Useful for HTTP responses that want to
        /// distinguish between a fresh upload and an update.
        outcome: &'static str,
    },
    Unchanged {
        document_id: DocumentId,
    },
}

/// Either the adapter rejected the bytes (corrupt PDF, non-utf8 plaintext,
/// etc.) or the storage call failed. Adapter errors are recoverable per
/// document; storage errors are usually fatal for the run.
pub enum IngestFileError {
    Adapter(crate::ingest::IngestError),
    Storage(crate::storage::StorageError),
}

impl From<crate::storage::StorageError> for IngestFileError {
    fn from(e: crate::storage::StorageError) -> Self {
        IngestFileError::Storage(e)
    }
}

/// Public, generic version of the per-document ingest path. Used by:
///   * `ingest_codebase` (one call per file under a root)
///   * `ken ingest-file` (one shot for a single file)
///   * `ken ingest-url` (one shot per fetched URL)
///
/// Caller picks the adapter (usually via `pick_adapter(&adapters, &hint)`).
/// `source_uri` becomes the document's `path_or_url` and `external_id` —
/// re-ingesting the same URI updates the existing Document via the upsert's
/// content-hash check.
pub async fn ingest_uri(
    storage: &PostgresStorage,
    embedder: &Arc<dyn Embedder>,
    workspace_id: WorkspaceId,
    source_id: SourceId,
    adapter: &dyn ContentAdapter,
    source_uri: &str,
    bytes: Vec<u8>,
    mime_hint: Option<String>,
    hint_metadata: MetadataMap,
) -> Result<FileOutcome, IngestFileError> {
    let raw = RawDocument {
        bytes,
        source_uri: source_uri.to_string(),
        mime_hint,
        external_id: Some(source_uri.to_string()),
        hint_metadata,
        source_modified_at: None,
    };
    let ctx = IngestContext {
        workspace_id,
        source_id,
    };
    let IngestOutput { document, chunks, edges: edge_drafts, .. } =
        adapter.ingest(raw, &ctx).map_err(IngestFileError::Adapter)?;

    // Safety cap: pathological files (auto-generated, vendored, gigantic
    // notebooks) can produce thousands of chunks and dominate ingest memory
    // / time. KEN_MAX_CHUNKS_PER_FILE (default 200) gates this — files past
    // the cap surface as adapter errors so the walker's stats reflect them.
    // 200 chunks ≈ a 1 MiB code file's real content; files exceeding this
    // are almost always machine-generated or vendored.
    let chunks_cap = std::env::var("KEN_MAX_CHUNKS_PER_FILE")
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
        .filter(|n| *n > 0)
        .unwrap_or(200);
    if chunks.len() > chunks_cap {
        return Err(IngestFileError::Adapter(
            crate::ingest::IngestError::Invalid(format!(
                "{} chunks exceeds cap {} (raise KEN_MAX_CHUNKS_PER_FILE if intentional)",
                chunks.len(),
                chunks_cap,
            )),
        ));
    }

    let new_doc = NewDocument {
        workspace_id,
        source_id,
        external_id: document.external_id,
        kind: document.kind,
        mime: document.mime,
        title: document.title,
        path_or_url: document.path_or_url.or_else(|| Some(source_uri.to_string())),
        content_hash: document.content_hash,
        acl: document.acl,
        metadata: document.metadata,
        source_modified_at: document.source_modified_at,
    };
    let outcome = storage.upsert_document(new_doc).await?;
    if outcome.is_unchanged() {
        return Ok(FileOutcome::Unchanged {
            document_id: outcome.current_id(),
        });
    }
    let doc_id = outcome.current_id();
    let outcome_label = match outcome {
        UpsertOutcome::Created(_) => "created",
        UpsertOutcome::Updated(_) => "updated",
        UpsertOutcome::Versioned { .. } => "versioned",
        UpsertOutcome::Unchanged(_) => "unchanged", // unreachable per the early return above
    };

    // Embed all chunks in one batch on a blocking thread (matches the
    // /ingest_text path), then write chunks + embeddings inline.
    let texts: Vec<String> = chunks.iter().map(|c| c.text.clone()).collect();
    let expected = texts.len();
    let embedder_clone = embedder.clone();
    let vectors = tokio::task::spawn_blocking(move || {
        let refs: Vec<&str> = texts.iter().map(|s| s.as_str()).collect();
        embedder_clone.embed_passages(&refs)
    })
    .await
    .map_err(|e| {
        IngestFileError::Adapter(crate::ingest::IngestError::Invalid(format!(
            "embed task panicked: {e}"
        )))
    })?;

    // The Embedder trait is infallible at the type level — a fallible call
    // (fastembed inference error) surfaces here as a length mismatch. Bail
    // out rather than zip-and-pad: zero or default vectors silently corrupt
    // retrieval calibration, and re-running the ingest is cheap.
    if vectors.len() != expected {
        return Err(IngestFileError::Adapter(
            crate::ingest::IngestError::Invalid(format!(
                "embedder returned {} vectors for {} chunks (likely inference failure)",
                vectors.len(),
                expected,
            )),
        ));
    }

    let new_chunks: Vec<NewChunk> = chunks
        .iter()
        .zip(vectors.into_iter())
        .map(|(c, v)| NewChunk {
            kind: c.kind.clone(),
            position: c.position.clone(),
            text: c.text.clone(),
            metadata: c.metadata.clone(),
            embedding: Some(v),
        })
        .collect();
    let chunk_ids = storage.replace_chunks(doc_id, new_chunks).await?;

    // Adapter edges + URL annotator edges, batched.
    let mut all_edges: Vec<NewEdge> = Vec::new();
    for edge in edge_drafts {
        if let Some(new_edge) = resolve_edge(&edge, workspace_id, doc_id, &chunk_ids) {
            all_edges.push(new_edge);
        }
    }
    let url_pairs: Vec<(ChunkId, String)> = chunk_ids
        .iter()
        .zip(chunks.iter())
        .map(|(cid, c)| (*cid, c.text.clone()))
        .collect();
    all_edges.extend(url_edges_for_chunks(workspace_id, &url_pairs));
    let edges_count = all_edges.len();
    if !all_edges.is_empty() {
        let _ = storage.add_edges(all_edges).await;
    }

    Ok(FileOutcome::Written {
        document_id: doc_id,
        chunks: chunk_ids.len(),
        edges: edges_count,
        outcome: outcome_label,
    })
}

fn resolve_endpoint(
    ep: &EdgeEndpoint,
    doc_id: DocumentId,
    chunks: &[ChunkId],
) -> Option<NodeRef> {
    match ep {
        EdgeEndpoint::Document => Some(NodeRef::Document(doc_id)),
        EdgeEndpoint::LocalChunk(idx) => chunks.get(*idx).copied().map(NodeRef::Chunk),
        EdgeEndpoint::LocalEntity(_) => None,
        EdgeEndpoint::Known(node) => Some(node.clone()),
        EdgeEndpoint::External(uri) => Some(NodeRef::External(uri.clone())),
    }
}

fn resolve_edge(
    draft: &EdgeDraft,
    workspace_id: WorkspaceId,
    doc_id: DocumentId,
    chunks: &[ChunkId],
) -> Option<NewEdge> {
    let from = resolve_endpoint(&draft.from, doc_id, chunks)?;
    let to = resolve_endpoint(&draft.to, doc_id, chunks)?;
    Some(NewEdge {
        workspace_id,
        from,
        to,
        kind: draft.kind.clone(),
        weight: draft.weight,
        metadata: draft.metadata.clone(),
        created_by: draft.created_by,
    })
}

// Suppress unused warning when `UpsertOutcome` enum variants change.
#[allow(dead_code)]
fn _outcome_assertion(o: UpsertOutcome) -> DocumentId {
    o.current_id()
}
