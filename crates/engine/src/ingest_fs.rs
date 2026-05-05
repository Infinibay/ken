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

/// Create (or reuse) a Source row tagged as a filesystem codebase.
/// Mirrors `ingest_git::ensure_source` — same shape, different `kind`.
pub async fn ensure_source(
    storage: &PostgresStorage,
    workspace_id: WorkspaceId,
    name: &str,
    repo_path: &Path,
) -> StorageResult<SourceId> {
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
pub async fn ingest_codebase(
    storage: &PostgresStorage,
    embedder: Arc<dyn Embedder>,
    cfg: &IngestCodebaseConfig,
) -> StorageResult<IngestCodebaseStats> {
    let started = Instant::now();
    let mut stats = IngestCodebaseStats::default();
    let adapters = default_adapters();

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

        match ingest_one_file(storage, &embedder, cfg, adapter, &rel, bytes).await {
            Ok(FileOutcome::Written { chunks, edges }) => {
                stats.documents_written += 1;
                stats.chunks_written += chunks as u64;
                stats.edges_written += edges as u64;
            }
            Ok(FileOutcome::Unchanged) => stats.documents_unchanged += 1,
            Err(IngestFileError::Adapter(err)) => {
                tracing::debug!(path = %rel, error = %err, "adapter rejected file");
                stats.files_skipped_adapter_error += 1;
            }
            Err(IngestFileError::Storage(err)) => return Err(err),
        }
    }

    stats.elapsed = started.elapsed();
    Ok(stats)
}

enum FileOutcome {
    Written { chunks: usize, edges: usize },
    Unchanged,
}

enum IngestFileError {
    Adapter(crate::ingest::IngestError),
    Storage(crate::storage::StorageError),
}

impl From<crate::storage::StorageError> for IngestFileError {
    fn from(e: crate::storage::StorageError) -> Self {
        IngestFileError::Storage(e)
    }
}

async fn ingest_one_file(
    storage: &PostgresStorage,
    embedder: &Arc<dyn Embedder>,
    cfg: &IngestCodebaseConfig,
    adapter: &dyn ContentAdapter,
    rel_path: &str,
    bytes: Vec<u8>,
) -> Result<FileOutcome, IngestFileError> {
    let raw = RawDocument {
        bytes,
        source_uri: rel_path.to_string(),
        mime_hint: None,
        external_id: Some(rel_path.to_string()),
        hint_metadata: MetadataMap::default(),
        source_modified_at: None,
    };
    let ctx = IngestContext {
        workspace_id: cfg.workspace_id,
        source_id: cfg.source_id,
    };
    let IngestOutput { document, chunks, edges: edge_drafts, .. } =
        adapter.ingest(raw, &ctx).map_err(IngestFileError::Adapter)?;

    let new_doc = NewDocument {
        workspace_id: cfg.workspace_id,
        source_id: cfg.source_id,
        external_id: document.external_id,
        kind: document.kind,
        mime: document.mime,
        title: document.title,
        path_or_url: document.path_or_url.or_else(|| Some(rel_path.to_string())),
        content_hash: document.content_hash,
        acl: document.acl,
        metadata: document.metadata,
        source_modified_at: document.source_modified_at,
    };
    let outcome = storage.upsert_document(new_doc).await?;
    if outcome.is_unchanged() {
        return Ok(FileOutcome::Unchanged);
    }
    let doc_id = outcome.current_id();

    // Embed all chunks in one batch on a blocking thread (matches the
    // /ingest_text path), then write chunks + embeddings inline.
    let texts: Vec<String> = chunks.iter().map(|c| c.text.clone()).collect();
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
        if let Some(new_edge) = resolve_edge(&edge, cfg.workspace_id, doc_id, &chunk_ids) {
            all_edges.push(new_edge);
        }
    }
    let url_pairs: Vec<(ChunkId, String)> = chunk_ids
        .iter()
        .zip(chunks.iter())
        .map(|(cid, c)| (*cid, c.text.clone()))
        .collect();
    all_edges.extend(url_edges_for_chunks(cfg.workspace_id, &url_pairs));
    let edges_count = all_edges.len();
    if !all_edges.is_empty() {
        let _ = storage.add_edges(all_edges).await;
    }

    Ok(FileOutcome::Written { chunks: chunk_ids.len(), edges: edges_count })
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
