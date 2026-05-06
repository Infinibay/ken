//! HTTP routes. Thin glue between JSON DTOs and `engine::*` calls.
//!
//! No business logic lives here — handlers translate request bodies into
//! engine drafts, dispatch, and serialize the response. Errors flow through
//! `ApiError::into_response` so the error wire format is consistent.

use std::sync::Arc;

use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use engine::annotate::url_edges_for_chunks;
use engine::ingest::{
    default_adapters, pick_adapter, DocumentDraft, EdgeDraft, EdgeEndpoint, IngestContext,
    IngestOutput, MimeHint, RawDocument,
};
use engine::storage::NewEdge;
use engine::rank::{RankRequest, Ranker};
use engine::storage::{NewContext, NewDocument, NewInteraction, NewSource};
use engine::types::{
    Acl, ChunkId, ChunkKind, ChunkPosition, ContentKind, ContextId, ContextKind, DocumentId,
    EmbedKey, EventType, InteractionId, MetadataMap, NodeRef, PlanTier, SessionId, SourceId,
    SourceKind, TenantId, Timestamp, WorkspaceId, WorkspaceSettings,
};
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::error::{ApiError, ApiResult};
use crate::state::AppState;

pub fn router() -> Router<Arc<AppState>> {
    Router::new()
        .route("/health", get(health))
        .route("/tenants", post(create_tenant))
        .route("/workspaces", post(create_workspace))
        .route("/workspaces/resolve", post(resolve_workspace))
        .route("/sources", post(create_source))
        .route("/sessions", post(create_session))
        .route("/sessions/end", post(end_session))
        .route("/sessions/anchor_turn", post(anchor_turn))
        .route("/contexts", post(append_context))
        .route("/ingest", post(ingest_document))
        .route("/ingest_text", post(ingest_text))
        .route("/ingest_blob", post(ingest_blob))
        .route("/ingest_file", post(ingest_file))
        .route("/ingest_url", post(ingest_url))
        .route("/ingest_codebase", post(ingest_codebase))
        .route("/ingest_git", post(ingest_git))
        .route("/rank", post(rank))
        .route("/symbols", post(search_symbols))
        .route("/symbols_in_file", post(list_symbols_in_file))
        .route("/files", post(rank_files))
        .route("/git_history", post(git_history))
        .route("/events", post(record_event))
}

// ============================================================================
// Health
// ============================================================================

async fn health(State(state): State<Arc<AppState>>) -> ApiResult<Json<serde_json::Value>> {
    state.storage.health_check().await?;
    Ok(Json(json!({ "ok": true })))
}

// ============================================================================
// Tenants
// ============================================================================

#[derive(Debug, Deserialize)]
struct CreateTenantBody {
    name: String,
    #[serde(default)]
    plan: PlanTier,
}

#[derive(Debug, Serialize)]
struct CreateTenantResponse {
    id: TenantId,
}

async fn create_tenant(
    State(state): State<Arc<AppState>>,
    Json(body): Json<CreateTenantBody>,
) -> ApiResult<Json<CreateTenantResponse>> {
    let id = state.storage.create_tenant(&body.name, body.plan).await?;
    Ok(Json(CreateTenantResponse { id }))
}

// ============================================================================
// Workspaces
// ============================================================================

#[derive(Debug, Deserialize)]
struct CreateWorkspaceBody {
    tenant_id: TenantId,
    name: String,
    #[serde(default)]
    settings: WorkspaceSettings,
}

#[derive(Debug, Serialize)]
struct CreateWorkspaceResponse {
    id: WorkspaceId,
}

async fn create_workspace(
    State(state): State<Arc<AppState>>,
    Json(body): Json<CreateWorkspaceBody>,
) -> ApiResult<Json<CreateWorkspaceResponse>> {
    let id = state
        .storage
        .create_workspace(body.tenant_id, &body.name, body.settings)
        .await?;
    Ok(Json(CreateWorkspaceResponse { id }))
}

#[derive(Debug, Deserialize)]
struct ResolveWorkspaceBody {
    name: String,
    /// Tenant name; defaults to `"local"` when omitted. Solo-developer
    /// installs all share one tenant.
    #[serde(default = "default_tenant_name")]
    tenant_name: String,
}

fn default_tenant_name() -> String {
    "local".to_string()
}

#[derive(Debug, Serialize)]
struct ResolveWorkspaceResponse {
    id: WorkspaceId,
    tenant_id: TenantId,
    created: bool,
}

async fn resolve_workspace(
    State(state): State<Arc<AppState>>,
    Json(body): Json<ResolveWorkspaceBody>,
) -> ApiResult<Json<ResolveWorkspaceResponse>> {
    let (id, tenant_id, created) = state
        .storage
        .find_or_create_workspace(&body.tenant_name, &body.name)
        .await?;
    Ok(Json(ResolveWorkspaceResponse {
        id,
        tenant_id,
        created,
    }))
}

// ============================================================================
// Sources
// ============================================================================

#[derive(Debug, Deserialize)]
struct CreateSourceBody {
    workspace_id: WorkspaceId,
    kind: SourceKind,
    name: String,
    #[serde(default)]
    config_json: serde_json::Value,
    #[serde(default)]
    keep_history: bool,
    #[serde(default)]
    default_acl: Acl,
}

#[derive(Debug, Serialize)]
struct CreateSourceResponse {
    id: SourceId,
}

async fn create_source(
    State(state): State<Arc<AppState>>,
    Json(body): Json<CreateSourceBody>,
) -> ApiResult<Json<CreateSourceResponse>> {
    let id = state
        .storage
        .create_source(NewSource {
            workspace_id: body.workspace_id,
            kind: body.kind,
            name: body.name,
            config_json: body.config_json,
            keep_history: body.keep_history,
            default_acl: body.default_acl,
        })
        .await?;
    Ok(Json(CreateSourceResponse { id }))
}

// ============================================================================
// Sessions
// ============================================================================

#[derive(Debug, Deserialize)]
struct CreateSessionBody {
    workspace_id: WorkspaceId,
    #[serde(default)]
    agent_id: Option<String>,
}

#[derive(Debug, Serialize)]
struct CreateSessionResponse {
    id: SessionId,
}

async fn create_session(
    State(state): State<Arc<AppState>>,
    Json(body): Json<CreateSessionBody>,
) -> ApiResult<Json<CreateSessionResponse>> {
    let id = state
        .storage
        .create_session(body.workspace_id, body.agent_id.as_deref())
        .await?;
    Ok(Json(CreateSessionResponse { id }))
}

#[derive(Debug, Deserialize)]
struct EndSessionBody {
    session_id: SessionId,
}

#[derive(Debug, Serialize)]
struct EndSessionResponse {
    ok: bool,
}

/// Mark a session as ended. The storage layer's `end_session` also fires the
/// session-close inferences (`snapshot_session_scores` would, if the caller
/// pushed scores; `infer_coaccessed_edges` runs from interactions on the
/// session).
async fn end_session(
    State(state): State<Arc<AppState>>,
    Json(body): Json<EndSessionBody>,
) -> ApiResult<Json<EndSessionResponse>> {
    state.storage.end_session(body.session_id).await?;
    Ok(Json(EndSessionResponse { ok: true }))
}

#[derive(Debug, Deserialize)]
struct AnchorTurnBody {
    session_id: SessionId,
    iteration: u32,
}

#[derive(Debug, Serialize)]
struct AnchorTurnResponse {
    edges: usize,
}

/// Emit `PromptAnchored` + `ReplyAnchored` edges for a finished turn. The
/// `Stop` hook calls this after appending the assistant reply so all the
/// turn's tool interactions are anchored to both dialog endpoints in a
/// single batched insert.
async fn anchor_turn(
    State(state): State<Arc<AppState>>,
    Json(body): Json<AnchorTurnBody>,
) -> ApiResult<Json<AnchorTurnResponse>> {
    let edges = state
        .storage
        .anchor_turn(body.session_id, body.iteration)
        .await?;
    Ok(Json(AnchorTurnResponse { edges }))
}

// ============================================================================
// Contexts (user_request, tool_result, ...)
// ============================================================================

#[derive(Debug, Deserialize)]
struct AppendContextBody {
    session_id: SessionId,
    kind: ContextKind,
    content: String,
    iteration: u32,
    #[serde(default)]
    embed: bool,
}

#[derive(Debug, Serialize)]
struct AppendContextResponse {
    id: ContextId,
    embedded: bool,
}

async fn append_context(
    State(state): State<Arc<AppState>>,
    Json(body): Json<AppendContextBody>,
) -> ApiResult<Json<AppendContextResponse>> {
    let id = state
        .storage
        .append_context(NewContext {
            session_id: body.session_id,
            kind: body.kind,
            content: body.content.clone(),
            iteration: body.iteration,
        })
        .await?;
    let embedded = if body.embed {
        let embedder = state.embedder.clone();
        let content = body.content.clone();
        let v = tokio::task::spawn_blocking(move || embedder.embed_passage(&content))
            .await
            .map_err(|e| ApiError::Invalid(format!("embed task panicked: {e}")))?;
        state.storage.put_embedding(EmbedKey::context(id), v).await?;
        true
    } else {
        false
    };
    Ok(Json(AppendContextResponse { id, embedded }))
}

// ============================================================================
// Ingest (structured: document + chunks)
// ============================================================================

#[derive(Debug, Deserialize)]
struct IngestDocumentBody {
    workspace_id: WorkspaceId,
    source_id: SourceId,
    #[serde(default)]
    external_id: Option<String>,
    kind: ContentKind,
    mime: String,
    #[serde(default)]
    title: Option<String>,
    #[serde(default)]
    path_or_url: Option<String>,
    #[serde(default)]
    acl: Acl,
    #[serde(default)]
    metadata: MetadataMap,
    #[serde(default)]
    source_modified_at: Option<Timestamp>,
    chunks: Vec<ChunkInput>,
}

#[derive(Debug, Deserialize)]
struct ChunkInput {
    kind: ChunkKind,
    position: ChunkPosition,
    text: String,
    #[serde(default)]
    metadata: MetadataMap,
}

#[derive(Debug, Serialize)]
struct IngestResponse {
    outcome: &'static str,
    document_id: DocumentId,
    chunks: Vec<ChunkId>,
}

async fn ingest_document(
    State(state): State<Arc<AppState>>,
    Json(body): Json<IngestDocumentBody>,
) -> ApiResult<Json<IngestResponse>> {
    if body.chunks.is_empty() {
        return Err(ApiError::Invalid("chunks must not be empty".into()));
    }

    // Hash the concatenated chunk texts so re-uploads of the same content are
    // detected as `Unchanged`.
    let concat: String = body.chunks.iter().map(|c| c.text.as_str()).collect::<Vec<_>>().join("\n");
    let content_hash = *blake3::hash(concat.as_bytes()).as_bytes();

    let outcome = state
        .storage
        .upsert_document(NewDocument {
            workspace_id: body.workspace_id,
            source_id: body.source_id,
            external_id: body.external_id,
            kind: body.kind,
            mime: body.mime,
            title: body.title,
            path_or_url: body.path_or_url,
            content_hash,
            acl: body.acl,
            metadata: body.metadata,
            source_modified_at: body.source_modified_at,
        })
        .await?;

    let doc_id = outcome.current_id();
    let outcome_label = match outcome {
        engine::storage::UpsertOutcome::Created(_) => "created",
        engine::storage::UpsertOutcome::Updated(_) => "updated",
        engine::storage::UpsertOutcome::Versioned { .. } => "versioned",
        engine::storage::UpsertOutcome::Unchanged(_) => "unchanged",
    };

    if outcome.is_unchanged() {
        let existing = state.storage.chunks_in_document(doc_id).await;
        return Ok(Json(IngestResponse {
            outcome: outcome_label,
            document_id: doc_id,
            chunks: existing,
        }));
    }

    // Convert ChunkInput → ChunkDraft so we can route through the shared
    // `persist_chunks_and_edges` helper. No adapter edges here — manual
    // ingest is the "I already chunked this for you" path.
    let drafts: Vec<engine::ingest::ChunkDraft> = body
        .chunks
        .iter()
        .map(|c| engine::ingest::ChunkDraft {
            kind: c.kind.clone(),
            position: c.position.clone(),
            text: c.text.clone(),
            metadata: c.metadata.clone(),
        })
        .collect();
    let chunk_ids =
        persist_chunks_and_edges(&state, body.workspace_id, doc_id, drafts, Vec::new()).await?;

    Ok(Json(IngestResponse {
        outcome: outcome_label,
        document_id: doc_id,
        chunks: chunk_ids,
    }))
}

/// One-shot post-upsert pipeline: embed all chunk texts in a single batched
/// call, write chunks + embeddings inline (one statement), then batch-upsert
/// adapter edges + URL annotator edges in two more statements. Replaces what
/// used to be a per-chunk + per-edge round-trip storm (~150 RT for a 50-chunk
/// doc) with ~5 round-trips (upsert_doc + replace_chunks + add_edges + commit).
async fn persist_chunks_and_edges(
    state: &AppState,
    workspace_id: WorkspaceId,
    doc_id: DocumentId,
    chunks: Vec<engine::ingest::ChunkDraft>,
    edge_drafts: Vec<engine::ingest::EdgeDraft>,
) -> ApiResult<Vec<ChunkId>> {
    let texts: Vec<String> = chunks.iter().map(|c| c.text.clone()).collect();
    let embedder = state.embedder.clone();
    let vectors = tokio::task::spawn_blocking(move || {
        let refs: Vec<&str> = texts.iter().map(|s| s.as_str()).collect();
        embedder.embed_passages(&refs)
    })
    .await
    .map_err(|e| ApiError::Invalid(format!("embed task panicked: {e}")))?;
    if vectors.len() != chunks.len() {
        return Err(ApiError::Invalid(format!(
            "embedder returned {} vectors for {} chunks",
            vectors.len(),
            chunks.len()
        )));
    }

    // Pair chunks with their freshly-computed embeddings — one shot to the
    // DB, no separate UPDATE-per-row.
    let new_chunks: Vec<engine::storage::NewChunk> = chunks
        .iter()
        .zip(vectors.into_iter())
        .map(|(c, v)| engine::storage::NewChunk {
            kind: c.kind.clone(),
            position: c.position.clone(),
            text: c.text.clone(),
            metadata: c.metadata.clone(),
            embedding: Some(v),
        })
        .collect();
    let chunk_ids = state.storage.replace_chunks(doc_id, new_chunks).await?;

    // Adapter-emitted edges + URL annotator edges merged into one batch.
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
    if !all_edges.is_empty() {
        // Best-effort: edge persistence shouldn't fail the ingest.
        let _ = state.storage.add_edges(all_edges).await;
    }

    Ok(chunk_ids)
}

// ============================================================================
// Ingest text (let the PlainTextAdapter do the chunking)
// ============================================================================

#[derive(Debug, Deserialize)]
struct IngestTextBody {
    workspace_id: WorkspaceId,
    source_id: SourceId,
    source_uri: String,
    text: String,
    #[serde(default)]
    external_id: Option<String>,
    #[serde(default)]
    mime: Option<String>,
    #[serde(default)]
    metadata: MetadataMap,
    #[serde(default)]
    acl: Acl,
}

async fn ingest_text(
    State(state): State<Arc<AppState>>,
    Json(body): Json<IngestTextBody>,
) -> ApiResult<Json<IngestResponse>> {
    // Pick the adapter from the registry — Markdown wins over PlainText for
    // `text/markdown` mime or `.md` URIs; PlainText is the fallback.
    let extension = uri_extension(&body.source_uri);
    let hint = MimeHint {
        mime: body.mime.clone(),
        extension,
    };
    let adapters = default_adapters();
    let adapter = pick_adapter(&adapters, &hint).ok_or_else(|| {
        ApiError::Invalid(format!(
            "no adapter accepts mime={:?} extension={:?}",
            hint.mime, hint.extension
        ))
    })?;

    let raw = RawDocument {
        bytes: body.text.into_bytes(),
        source_uri: body.source_uri,
        mime_hint: body.mime.clone(),
        external_id: body.external_id.clone(),
        hint_metadata: body.metadata.clone(),
        source_modified_at: None,
    };
    let ctx = IngestContext {
        workspace_id: body.workspace_id,
        source_id: body.source_id,
    };
    let IngestOutput { document, chunks, edges: edge_drafts, .. } = adapter.ingest(raw, &ctx)?;
    let DocumentDraft {
        external_id,
        kind,
        mime,
        title,
        path_or_url,
        content_hash,
        acl: draft_acl,
        metadata: draft_meta,
        source_modified_at,
    } = document;

    let acl = if draft_acl == Acl::default() { body.acl } else { draft_acl };
    let outcome = state
        .storage
        .upsert_document(NewDocument {
            workspace_id: body.workspace_id,
            source_id: body.source_id,
            external_id,
            kind,
            mime,
            title,
            path_or_url,
            content_hash,
            acl,
            metadata: draft_meta,
            source_modified_at,
        })
        .await?;

    let doc_id = outcome.current_id();
    let outcome_label = match outcome {
        engine::storage::UpsertOutcome::Created(_) => "created",
        engine::storage::UpsertOutcome::Updated(_) => "updated",
        engine::storage::UpsertOutcome::Versioned { .. } => "versioned",
        engine::storage::UpsertOutcome::Unchanged(_) => "unchanged",
    };

    if outcome.is_unchanged() {
        let existing = state.storage.chunks_in_document(doc_id).await;
        return Ok(Json(IngestResponse {
            outcome: outcome_label,
            document_id: doc_id,
            chunks: existing,
        }));
    }

    let chunk_ids =
        persist_chunks_and_edges(&state, body.workspace_id, doc_id, chunks, edge_drafts).await?;
    Ok(Json(IngestResponse {
        outcome: outcome_label,
        document_id: doc_id,
        chunks: chunk_ids,
    }))
}

fn resolve_endpoint(
    ep: &EdgeEndpoint,
    doc_id: DocumentId,
    chunks: &[ChunkId],
) -> Option<engine::types::NodeRef> {
    use engine::types::NodeRef;
    match ep {
        EdgeEndpoint::Document => Some(NodeRef::Document(doc_id)),
        EdgeEndpoint::LocalChunk(idx) => chunks.get(*idx).copied().map(NodeRef::Chunk),
        EdgeEndpoint::LocalEntity(_) => None, // entities not yet persisted by this route
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

/// Extract a lower-case extension from a URI/path. `"docs/README.md"` →
/// `Some("md")`. Used by `/ingest_text` to feed adapter selection.
fn uri_extension(uri: &str) -> Option<String> {
    uri.rsplit('/')
        .next()
        .and_then(|name| name.rsplit_once('.'))
        .map(|(_, ext)| ext.to_ascii_lowercase())
}

// ============================================================================
// Ingest blob (binary content — base64-encoded)
// ============================================================================

#[derive(Debug, Deserialize)]
struct IngestBlobBody {
    workspace_id: WorkspaceId,
    source_id: SourceId,
    source_uri: String,
    /// Base64-encoded raw bytes. Required for binary formats (PDF, DOCX,
    /// images). UTF-8 text formats can keep using `/ingest_text`.
    bytes_base64: String,
    #[serde(default)]
    external_id: Option<String>,
    #[serde(default)]
    mime: Option<String>,
    #[serde(default)]
    metadata: MetadataMap,
    #[serde(default)]
    acl: Acl,
}

async fn ingest_blob(
    State(state): State<Arc<AppState>>,
    Json(body): Json<IngestBlobBody>,
) -> ApiResult<Json<IngestResponse>> {
    use base64::Engine;
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(body.bytes_base64.as_bytes())
        .map_err(|e| ApiError::Invalid(format!("bytes_base64 decode: {e}")))?;

    let extension = uri_extension(&body.source_uri);
    let hint = MimeHint {
        mime: body.mime.clone(),
        extension,
    };
    let adapters = default_adapters();
    let adapter = pick_adapter(&adapters, &hint).ok_or_else(|| {
        ApiError::Invalid(format!(
            "no adapter accepts mime={:?} extension={:?}",
            hint.mime, hint.extension
        ))
    })?;

    let raw = RawDocument {
        bytes,
        source_uri: body.source_uri,
        mime_hint: body.mime.clone(),
        external_id: body.external_id.clone(),
        hint_metadata: body.metadata.clone(),
        source_modified_at: None,
    };
    let ctx = IngestContext {
        workspace_id: body.workspace_id,
        source_id: body.source_id,
    };
    let IngestOutput { document, chunks, edges: edge_drafts, .. } = adapter.ingest(raw, &ctx)?;
    let DocumentDraft {
        external_id,
        kind,
        mime,
        title,
        path_or_url,
        content_hash,
        acl: draft_acl,
        metadata: draft_meta,
        source_modified_at,
    } = document;

    let acl = if draft_acl == Acl::default() { body.acl } else { draft_acl };
    let outcome = state
        .storage
        .upsert_document(NewDocument {
            workspace_id: body.workspace_id,
            source_id: body.source_id,
            external_id,
            kind,
            mime,
            title,
            path_or_url,
            content_hash,
            acl,
            metadata: draft_meta,
            source_modified_at,
        })
        .await?;

    let doc_id = outcome.current_id();
    let outcome_label = match outcome {
        engine::storage::UpsertOutcome::Created(_) => "created",
        engine::storage::UpsertOutcome::Updated(_) => "updated",
        engine::storage::UpsertOutcome::Versioned { .. } => "versioned",
        engine::storage::UpsertOutcome::Unchanged(_) => "unchanged",
    };
    if outcome.is_unchanged() {
        let existing = state.storage.chunks_in_document(doc_id).await;
        return Ok(Json(IngestResponse {
            outcome: outcome_label,
            document_id: doc_id,
            chunks: existing,
        }));
    }

    let chunk_ids =
        persist_chunks_and_edges(&state, body.workspace_id, doc_id, chunks, edge_drafts).await?;
    Ok(Json(IngestResponse {
        outcome: outcome_label,
        document_id: doc_id,
        chunks: chunk_ids,
    }))
}

// ============================================================================
// Ingest file (upload-style: bytes + mime, find-or-create source by name)
// ============================================================================

/// Hard cap on decoded bytes the route accepts. MCP-over-stdio has no
/// streaming, so a runaway upload would block the agent — this keeps the
/// failure mode "obvious" rather than "hung".
const INGEST_FILE_MAX_BYTES: usize = 8 * 1024 * 1024;

#[derive(Debug, Deserialize)]
struct IngestFileBody {
    /// Workspace numeric id OR a name (find-or-created under tenant `"local"`).
    workspace: String,
    /// Used to find-or-create the `Source` row. Stable identifier for the
    /// uploader — typically `"uploads"` (manual MCP) or `"http"` (URL crawl).
    source_name: String,
    /// Canonical reference for this document. Becomes both `external_id` and
    /// `path_or_url`. Typically the original filename (`report.pdf`) or a
    /// URL when the same document is also web-fetched.
    external_id: String,
    /// Optional explicit content-type. When absent the adapter is picked
    /// from the extension on `external_id` (`*.pdf` → PDF, `*.html` → HTML).
    #[serde(default)]
    mime: Option<String>,
    /// Standard base64-encoded bytes. Capped at 8 MiB after decode.
    bytes_base64: String,
}

#[derive(Debug, Serialize)]
struct IngestFileResponse {
    outcome: String,
    document_id: DocumentId,
    chunks: usize,
    edges: usize,
}

async fn ingest_file(
    State(state): State<Arc<AppState>>,
    Json(body): Json<IngestFileBody>,
) -> ApiResult<Json<IngestFileResponse>> {
    use base64::Engine;
    use engine::ingest_fs::{ingest_uri, FileOutcome, IngestFileError};
    use engine::storage::NewSource;
    use engine::types::{Acl, MetadataMap, SourceKind};

    let bytes = base64::engine::general_purpose::STANDARD
        .decode(body.bytes_base64.as_bytes())
        .map_err(|e| ApiError::Invalid(format!("bytes_base64 decode: {e}")))?;
    if bytes.len() > INGEST_FILE_MAX_BYTES {
        return Err(ApiError::Invalid(format!(
            "decoded body {} bytes exceeds {} MiB cap",
            bytes.len(),
            INGEST_FILE_MAX_BYTES / (1024 * 1024)
        )));
    }

    let workspace_id = resolve_workspace_input(&state.storage, &body.workspace).await?;
    let source_id = match state
        .storage
        .find_source_by_name(workspace_id, &body.source_name)
        .await
    {
        Some(id) => id,
        None => {
            state
                .storage
                .create_source(NewSource {
                    workspace_id,
                    kind: SourceKind::Manual,
                    name: body.source_name.clone(),
                    config_json: serde_json::json!({"kind": "manual_upload"}),
                    keep_history: false,
                    default_acl: Acl::default(),
                })
                .await?
        }
    };

    let extension = uri_extension(&body.external_id);
    let hint = MimeHint {
        mime: body.mime.clone(),
        extension,
    };
    let adapters = default_adapters();
    let adapter = pick_adapter(&adapters, &hint).ok_or_else(|| {
        ApiError::Invalid(format!(
            "no adapter accepts mime={:?} extension={:?}",
            hint.mime, hint.extension
        ))
    })?;

    let outcome = ingest_uri(
        &state.storage,
        &state.embedder,
        workspace_id,
        source_id,
        adapter,
        &body.external_id,
        bytes,
        body.mime.clone(),
        MetadataMap::default(),
    )
    .await
    .map_err(|e| match e {
        IngestFileError::Adapter(err) => ApiError::Invalid(format!("adapter rejected: {err}")),
        IngestFileError::Storage(err) => ApiError::Storage(err),
    })?;

    let response = match outcome {
        FileOutcome::Written {
            document_id,
            chunks,
            edges,
            outcome,
        } => IngestFileResponse {
            outcome: outcome.to_string(),
            document_id,
            chunks,
            edges,
        },
        FileOutcome::Unchanged { document_id } => IngestFileResponse {
            outcome: "unchanged".to_string(),
            document_id,
            chunks: 0,
            edges: 0,
        },
    };
    Ok(Json(response))
}

// ============================================================================
// Ingest URL (single page or shallow BFS crawl)
// ============================================================================

/// Hard ceilings on the crawl. MCP stdio has no streaming so the route
/// blocks until done — these caps bound how long the agent can wait.
const INGEST_URL_MAX_DEPTH: u32 = 2;
const INGEST_URL_MAX_PAGES: u32 = 10;
const INGEST_URL_WALL_SECS: u64 = 30;

#[derive(Debug, Deserialize)]
struct IngestUrlBody {
    /// Workspace numeric id OR a name (find-or-created under tenant `"local"`).
    workspace: String,
    /// Find-or-create source name; defaults to `"web"` if omitted.
    #[serde(default = "default_url_source")]
    source_name: String,
    url: String,
    /// Depth of follow-link expansion (0 = single page only). Clamped to
    /// `INGEST_URL_MAX_DEPTH`.
    #[serde(default)]
    depth: u32,
    /// Total pages to fetch, including the start URL. Clamped to
    /// `INGEST_URL_MAX_PAGES`.
    #[serde(default = "default_url_max_pages")]
    max_pages: u32,
    #[serde(default = "default_true")]
    same_host_only: bool,
}

fn default_url_source() -> String {
    "web".to_string()
}
fn default_url_max_pages() -> u32 {
    1
}
fn default_true() -> bool {
    true
}

#[derive(Debug, Serialize)]
struct IngestUrlPage {
    url: String,
    outcome: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    document_id: Option<DocumentId>,
    chunks: usize,
}

#[derive(Debug, Serialize)]
struct IngestUrlSkipped {
    url: String,
    reason: String,
}

#[derive(Debug, Serialize)]
struct IngestUrlResponse {
    pages: Vec<IngestUrlPage>,
    skipped: Vec<IngestUrlSkipped>,
    /// `true` when the wall-clock cap fired and the queue still had items.
    /// Useful for the agent to know whether retrying with a higher depth is
    /// worth it.
    timed_out: bool,
}

async fn ingest_url(
    State(state): State<Arc<AppState>>,
    Json(body): Json<IngestUrlBody>,
) -> ApiResult<Json<IngestUrlResponse>> {
    use crate::url_crawl::{build_agent, canonical_url, extract_links, fetch_url};
    use engine::ingest_fs::{ingest_uri, FileOutcome, IngestFileError};
    use engine::storage::NewSource;
    use engine::types::{Acl, MetadataMap, SourceKind};
    use std::collections::{HashSet, VecDeque};

    let depth = body.depth.min(INGEST_URL_MAX_DEPTH);
    let max_pages = body.max_pages.clamp(1, INGEST_URL_MAX_PAGES);

    let start = url::Url::parse(&body.url)
        .map_err(|e| ApiError::Invalid(format!("invalid url: {e}")))?;
    let start_host = start.host_str().map(|s| s.to_string());

    let workspace_id = resolve_workspace_input(&state.storage, &body.workspace).await?;
    let source_id = match state
        .storage
        .find_source_by_name(workspace_id, &body.source_name)
        .await
    {
        Some(id) => id,
        None => {
            state
                .storage
                .create_source(NewSource {
                    workspace_id,
                    kind: SourceKind::Http,
                    name: body.source_name.clone(),
                    config_json: serde_json::json!({"kind": "url_crawl"}),
                    keep_history: false,
                    default_acl: Acl::default(),
                })
                .await?
        }
    };

    let adapters = default_adapters();
    let agent = build_agent(20);
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(INGEST_URL_WALL_SECS);

    let mut queue: VecDeque<(url::Url, u32)> = VecDeque::new();
    let mut visited: HashSet<String> = HashSet::new();
    queue.push_back((start.clone(), 0));
    visited.insert(canonical_url(&start));

    let mut pages: Vec<IngestUrlPage> = Vec::new();
    let mut skipped: Vec<IngestUrlSkipped> = Vec::new();
    let mut fetched = 0u32;
    let mut timed_out = false;

    while let Some((url, d)) = queue.pop_front() {
        if fetched >= max_pages {
            break;
        }
        if std::time::Instant::now() >= deadline {
            timed_out = true;
            break;
        }
        fetched += 1;
        let url_str = url.to_string();
        let agent_clone = agent.clone();
        let url_for_task = url_str.clone();
        let fetched_res = tokio::task::spawn_blocking(move || fetch_url(&agent_clone, &url_for_task))
            .await
            .map_err(|e| ApiError::Invalid(format!("fetch task panicked: {e}")))?;
        let (mime, bytes) = match fetched_res {
            Ok(v) => v,
            Err(err) => {
                skipped.push(IngestUrlSkipped {
                    url: url_str,
                    reason: format!("fetch: {err}"),
                });
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
            skipped.push(IngestUrlSkipped {
                url: url_str,
                reason: format!("no adapter for mime={mime}"),
            });
            continue;
        };

        let next_links: Vec<url::Url> = if d < depth && mime.starts_with("text/html") {
            extract_links(&url, std::str::from_utf8(&bytes).unwrap_or(""))
        } else {
            Vec::new()
        };

        let result = ingest_uri(
            &state.storage,
            &state.embedder,
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
            Ok(FileOutcome::Written {
                document_id,
                chunks,
                outcome,
                ..
            }) => pages.push(IngestUrlPage {
                url: url_str,
                outcome: outcome.to_string(),
                document_id: Some(document_id),
                chunks,
            }),
            Ok(FileOutcome::Unchanged { document_id }) => pages.push(IngestUrlPage {
                url: url_str,
                outcome: "unchanged".to_string(),
                document_id: Some(document_id),
                chunks: 0,
            }),
            Err(IngestFileError::Adapter(err)) => skipped.push(IngestUrlSkipped {
                url: url_str,
                reason: format!("adapter: {err}"),
            }),
            Err(IngestFileError::Storage(err)) => return Err(ApiError::Storage(err)),
        }

        for link in next_links {
            if body.same_host_only && link.host_str() != start_host.as_deref() {
                continue;
            }
            let canon = canonical_url(&link);
            if visited.insert(canon) {
                queue.push_back((link, d + 1));
            }
        }
    }

    Ok(Json(IngestUrlResponse {
        pages,
        skipped,
        timed_out,
    }))
}

// ============================================================================
// Ingest codebase (full filesystem walk — server reads the path directly)
// ============================================================================

/// Resolve `--workspace VALUE` server-side: numeric -> use as id, otherwise
/// find-or-create under tenant `"local"`. Mirrors the CLI helper so the
/// HTTP route accepts the same flexible argument.
async fn resolve_workspace_input(
    storage: &engine::postgres::PostgresStorage,
    value: &str,
) -> ApiResult<WorkspaceId> {
    if let Ok(id) = value.parse::<u64>() {
        return Ok(WorkspaceId(id));
    }
    let (id, _, _) = storage
        .find_or_create_workspace("local", value)
        .await?;
    Ok(id)
}

#[derive(Debug, Deserialize)]
struct IngestCodebaseBody {
    /// Workspace numeric id OR a name (find-or-created under tenant `"local"`).
    workspace: String,
    /// Absolute path on the SERVER's filesystem. The CLI canonicalizes
    /// before sending so a relative `.` becomes `/abs/path`. For local
    /// dev this is fine; if `ken serve` ever runs on a different host
    /// from the CLI, the path must be reachable there.
    root: String,
    #[serde(default = "default_codebase_max_bytes")]
    max_bytes: u64,
    #[serde(default = "default_true_bool")]
    respect_gitignore: bool,
    #[serde(default)]
    follow_symlinks: bool,
}

fn default_codebase_max_bytes() -> u64 {
    1024 * 1024
}
fn default_true_bool() -> bool {
    true
}

#[derive(Debug, Serialize)]
struct IngestCodebaseResult {
    files_visited: u64,
    documents_written: u64,
    documents_unchanged: u64,
    files_skipped_no_adapter: u64,
    files_skipped_too_large: u64,
    files_skipped_adapter_error: u64,
    files_skipped_io_error: u64,
    chunks_written: u64,
    edges_written: u64,
    elapsed_ms: u64,
}

async fn ingest_codebase(
    State(state): State<Arc<AppState>>,
    Json(body): Json<IngestCodebaseBody>,
) -> ApiResult<Json<IngestCodebaseResult>> {
    use engine::ingest_fs::{ensure_source, ingest_codebase as ingest_fn, IngestCodebaseConfig};
    use std::path::PathBuf;

    let workspace_id = resolve_workspace_input(&state.storage, &body.workspace).await?;

    let root = PathBuf::from(&body.root);
    if !root.exists() {
        return Err(ApiError::Invalid(format!("root path does not exist: {}", body.root)));
    }
    let source_name = format!("codebase:{}", root.display());
    let source_id = ensure_source(&state.storage, workspace_id, &source_name, &root).await?;

    let mut cfg = IngestCodebaseConfig::new(&root, workspace_id, source_id);
    cfg.max_file_bytes = body.max_bytes;
    cfg.respect_gitignore = body.respect_gitignore;
    cfg.follow_symlinks = body.follow_symlinks;

    let stats = ingest_fn(&state.storage, state.embedder.clone(), &cfg)
        .await
        .map_err(|e| ApiError::Invalid(format!("ingest_codebase: {e}")))?;

    Ok(Json(IngestCodebaseResult {
        files_visited: stats.files_visited,
        documents_written: stats.documents_written,
        documents_unchanged: stats.documents_unchanged,
        files_skipped_no_adapter: stats.files_skipped_no_adapter,
        files_skipped_too_large: stats.files_skipped_too_large,
        files_skipped_adapter_error: stats.files_skipped_adapter_error,
        files_skipped_io_error: stats.files_skipped_io_error,
        chunks_written: stats.chunks_written,
        edges_written: stats.edges_written,
        elapsed_ms: stats.elapsed.as_millis() as u64,
    }))
}

// ============================================================================
// Ingest git (full repo history walk — server reads the .git directly)
// ============================================================================

#[derive(Debug, Deserialize)]
struct IngestGitBody {
    workspace: String,
    /// Absolute repository path on the server.
    repo: String,
    #[serde(default)]
    branch: Option<String>,
    /// Limit history to commits within the last N years. `null` (omitted)
    /// means full history. Default 2.
    #[serde(default = "default_since_years")]
    since_years: Option<u64>,
    #[serde(default)]
    max_commits: u64,
    #[serde(default = "default_git_mode")]
    mode: String,
    #[serde(default = "default_true_bool")]
    skip_merges: bool,
    #[serde(default = "default_true_bool")]
    skip_whitespace_only: bool,
}

fn default_since_years() -> Option<u64> {
    Some(2)
}
fn default_git_mode() -> String {
    "both".to_string()
}

#[derive(Debug, Serialize)]
struct IngestGitResult {
    visited: u64,
    kept: u64,
    skipped_merge: u64,
    skipped_bot: u64,
    skipped_whitespace: u64,
    documents_written: u64,
    documents_unchanged: u64,
    sessions_created: u64,
    edges_written: u64,
}

#[cfg(feature = "git")]
async fn ingest_git(
    State(state): State<Arc<AppState>>,
    Json(body): Json<IngestGitBody>,
) -> ApiResult<Json<IngestGitResult>> {
    use engine::ingest_git::{ensure_source, ingest_repo, IngestGitConfig, IngestMode};
    use std::path::PathBuf;

    let workspace_id = resolve_workspace_input(&state.storage, &body.workspace).await?;

    let repo = PathBuf::from(&body.repo);
    if !repo.exists() {
        return Err(ApiError::Invalid(format!("repo path does not exist: {}", body.repo)));
    }

    let mode = match body.mode.as_str() {
        "docs" | "documents_only" => IngestMode::DocumentsOnly,
        "sessions" | "sessions_only" => IngestMode::SessionsOnly,
        "both" => IngestMode::Both,
        other => return Err(ApiError::Invalid(format!("unknown mode: {other}"))),
    };

    let source_name = format!("git:{}", repo.display());
    let source_id = ensure_source(&state.storage, workspace_id, &source_name, &repo)
        .await
        .map_err(|e| ApiError::Invalid(format!("ensure_source: {e}")))?;

    let mut cfg = IngestGitConfig::new(&repo, workspace_id, source_id);
    cfg.branch = body.branch;
    cfg.skip_merges = body.skip_merges;
    cfg.skip_whitespace_only = body.skip_whitespace_only;
    cfg.max_commits = body.max_commits;
    cfg.mode = mode;
    if let Some(y) = body.since_years {
        cfg = cfg.since_years(y);
    }

    let stats = ingest_repo(&state.storage, state.embedder.clone(), &cfg)
        .await
        .map_err(|e| ApiError::Invalid(format!("ingest_repo: {e}")))?;

    Ok(Json(IngestGitResult {
        visited: stats.walk.visited,
        kept: stats.walk.kept,
        skipped_merge: stats.walk.skipped_merge,
        skipped_bot: stats.walk.skipped_bot,
        skipped_whitespace: stats.walk.skipped_whitespace,
        documents_written: stats.documents_written,
        documents_unchanged: stats.documents_unchanged,
        sessions_created: stats.sessions_created,
        edges_written: stats.edges_written,
    }))
}

#[cfg(not(feature = "git"))]
async fn ingest_git(
    State(_state): State<Arc<AppState>>,
    Json(_body): Json<IngestGitBody>,
) -> ApiResult<Json<IngestGitResult>> {
    Err(ApiError::Invalid(
        "server compiled without the `git` feature".into(),
    ))
}

// ============================================================================
// Rank
// ============================================================================

#[derive(Debug, Deserialize)]
struct RankBody {
    workspace_id: WorkspaceId,
    session_id: SessionId,
    query: String,
    #[serde(default)]
    iteration: u32,
    /// When `true`, the response includes the chunk text and a citation
    /// (`<path_or_url>:<line_start>-<line_end>`) for every Chunk/Document
    /// target. Costs one extra DB roundtrip per item but saves a follow-
    /// up call for clients that always need the text (MCP, CLI demos).
    #[serde(default)]
    include_text: bool,
    /// Cap on items returned. The ranker itself is already top-K capped
    /// internally; this is a second cap for when the caller wants fewer.
    #[serde(default)]
    limit: Option<usize>,
    /// Override the confidence gate threshold. Default `None` keeps the
    /// engine's default (0.5). Lower it for cold-start workspaces where
    /// no session history exists yet (the gate is calibrated for blended
    /// channels — when only the semantic channel fires, raw scores are
    /// naturally lower).
    #[serde(default)]
    min_score: Option<f32>,
    /// Override the semantic-channel `min_similarity` floor. Chunks
    /// whose cosine similarity to the query is below this are dropped
    /// before scoring. Default `None` keeps the engine's default (0.4).
    #[serde(default)]
    min_similarity: Option<f32>,
}

#[derive(Debug, Serialize)]
struct RankItemDto {
    target: NodeRef,
    score: f32,
    reason: String,
    /// `<path_or_url>:<line_start>-<line_end>` (or page anchor for PDFs).
    /// Always populated when the target is a Chunk/Document with a known
    /// path. Independent of `include_text` — clients that just need
    /// citations don't have to also pull text.
    #[serde(skip_serializing_if = "Option::is_none")]
    citation: Option<String>,
    /// Qualified symbol name (`User::validate`) when the chunk is a code
    /// `SymbolRange`. Lets the caller display "what function" without
    /// reading the file.
    #[serde(skip_serializing_if = "Option::is_none")]
    qualified_name: Option<String>,
    /// Document content kind in `snake_case` (`code_file`, `markdown`, …).
    /// Useful for callers that want to filter or render differently.
    #[serde(skip_serializing_if = "Option::is_none")]
    kind: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    text: Option<String>,
}

#[derive(Debug, Serialize)]
struct RankResponse {
    items: Vec<RankItemDto>,
}

async fn rank(
    State(state): State<Arc<AppState>>,
    Json(body): Json<RankBody>,
) -> ApiResult<Json<RankResponse>> {
    // Pre-embed the query off the executor — for FastEmbedder this is the
    // single hot operation in the rank path (~30ms).
    let embedder = state.embedder.clone();
    let query = body.query.clone();
    let query_embedding = tokio::task::spawn_blocking(move || embedder.embed_query(&query))
        .await
        .map_err(|e| ApiError::Invalid(format!("embed task panicked: {e}")))?;
    let ranker = if body.min_score.is_some() || body.min_similarity.is_some() {
        let mut cfg = engine::rank::RankerConfig::default();
        if let Some(min) = body.min_score {
            cfg.merge.confidence_gate = min;
        }
        if let Some(ms) = body.min_similarity {
            cfg.semantic.min_similarity = ms;
        }
        Ranker::new(&state.storage).with_config(cfg)
    } else {
        Ranker::new(&state.storage)
    };
    let result = ranker
        .rank(RankRequest {
            workspace: body.workspace_id,
            session: body.session_id,
            query_embedding,
            iteration: body.iteration,
        })
        .await;

    let mut items = Vec::with_capacity(result.items.len());
    let limit = body.limit.unwrap_or(usize::MAX);
    for it in result.items.into_iter().take(limit) {
        let meta = resolve_target_meta(&state, &it.target, body.include_text).await;
        items.push(RankItemDto {
            target: it.target,
            score: it.score,
            reason: it.reason,
            citation: meta.citation,
            qualified_name: meta.qualified_name,
            kind: meta.kind,
            text: meta.text,
        });
    }
    Ok(Json(RankResponse { items }))
}

#[derive(Default)]
struct TargetMeta {
    text: Option<String>,
    citation: Option<String>,
    qualified_name: Option<String>,
    kind: Option<String>,
}

/// Best-effort lookup of metadata for a rank target. `citation`,
/// `qualified_name`, and `kind` are extracted regardless of `include_text` —
/// the only DB cost they add over the bare ranker output is the lookups for
/// chunk + document, which we'd do anyway when text is requested.
async fn resolve_target_meta(
    state: &AppState,
    target: &NodeRef,
    include_text: bool,
) -> TargetMeta {
    use engine::types::{ChunkPosition, NodeRef};
    match target {
        NodeRef::Chunk(id) => {
            let Some(chunk) = state.storage.get_chunk(*id).await else {
                return TargetMeta::default();
            };
            let doc = state.storage.get_document(chunk.document_id).await;
            let path = doc.as_ref().and_then(|d| d.path_or_url.clone());
            let kind = doc.as_ref().map(|d| {
                serde_json::to_value(&d.kind)
                    .ok()
                    .and_then(|v| v.as_str().map(str::to_string))
                    .unwrap_or_else(|| format!("{:?}", d.kind).to_lowercase())
            });
            let (citation, qualified_name) = match (&path, &chunk.position) {
                (Some(p), ChunkPosition::LineRange { start, end }) => {
                    (Some(format!("{p}:{start}-{end}")), None)
                }
                (Some(p), ChunkPosition::SymbolRange { line_start, line_end, qualified_name }) => {
                    (
                        Some(format!("{p}:{line_start}-{line_end}")),
                        Some(qualified_name.clone()),
                    )
                }
                (Some(p), ChunkPosition::PageRange { page, .. }) => {
                    (Some(format!("{p}#page={page}")), None)
                }
                (Some(p), _) => (Some(p.clone()), None),
                _ => (None, None),
            };
            TargetMeta {
                text: include_text.then_some(chunk.text),
                citation,
                qualified_name,
                kind,
            }
        }
        NodeRef::Document(id) => {
            let doc = state.storage.get_document(*id).await;
            let path = doc.as_ref().and_then(|d| d.path_or_url.clone());
            let kind = doc.as_ref().map(|d| {
                serde_json::to_value(&d.kind)
                    .ok()
                    .and_then(|v| v.as_str().map(str::to_string))
                    .unwrap_or_else(|| format!("{:?}", d.kind).to_lowercase())
            });
            let text = if include_text {
                let chunk_ids = state.storage.chunks_in_document(*id).await;
                if let Some(first) = chunk_ids.first() {
                    state.storage.get_chunk(*first).await.map(|c| c.text)
                } else {
                    None
                }
            } else {
                None
            };
            TargetMeta {
                text,
                citation: path,
                qualified_name: None,
                kind,
            }
        }
        NodeRef::Entity(_) | NodeRef::External(_) => TargetMeta::default(),
    }
}

// ============================================================================
// Symbol search (name-based, complements semantic /rank)
// ============================================================================

#[derive(Debug, Deserialize)]
struct SearchSymbolsBody {
    workspace_id: WorkspaceId,
    /// Substring/prefix to match against `qualified_name`. Case-insensitive.
    /// "AnA" matches `AnA::lint`, `AnA::new`, etc. "validate" matches
    /// `User::validate`. Exact and last-segment matches outrank substrings.
    query: String,
    /// Cap on items returned. Default 10.
    #[serde(default)]
    limit: Option<usize>,
}

async fn search_symbols(
    State(state): State<Arc<AppState>>,
    Json(body): Json<SearchSymbolsBody>,
) -> ApiResult<Json<RankResponse>> {
    let limit = body.limit.unwrap_or(10).max(1);
    let chunk_ids = state
        .storage
        .search_symbols_by_name(body.workspace_id, &body.query, limit)
        .await;

    let mut items = Vec::with_capacity(chunk_ids.len());
    for cid in chunk_ids {
        let target = NodeRef::Chunk(cid);
        let meta = resolve_target_meta(&state, &target, false).await;
        items.push(RankItemDto {
            target,
            // No semantic score for name-based hits — surface as 1.0 so the
            // client sees them as "exact answers", and let ordering carry
            // the tiered ranking from the SQL CASE.
            score: 1.0,
            reason: "name match".to_string(),
            citation: meta.citation,
            qualified_name: meta.qualified_name,
            kind: meta.kind,
            text: None,
        });
    }
    Ok(Json(RankResponse { items }))
}

// ============================================================================
// File ranking (group chunk hits by path → top-k files)
// ============================================================================

#[derive(Debug, Deserialize)]
struct RankFilesBody {
    workspace_id: WorkspaceId,
    session_id: SessionId,
    query: String,
    #[serde(default)]
    iteration: u32,
    /// Cap on file paths returned. Default 10.
    #[serde(default)]
    limit: Option<usize>,
}

#[derive(Debug, Serialize)]
struct FileRankItem {
    path: String,
    /// Sum of chunk scores from this path. A file with several relevant
    /// chunks aggregates higher than one with a single hit, which is the
    /// "concentration of relevance" signal we want when answering "which
    /// files are most relevant" rather than "which symbol is closest".
    score: f32,
    chunks: usize,
}

#[derive(Debug, Serialize)]
struct RankFilesResponse {
    items: Vec<FileRankItem>,
}

async fn rank_files(
    State(state): State<Arc<AppState>>,
    Json(body): Json<RankFilesBody>,
) -> ApiResult<Json<RankFilesResponse>> {
    // Embed off the executor — same path as /rank.
    let embedder = state.embedder.clone();
    let query = body.query.clone();
    let query_embedding = tokio::task::spawn_blocking(move || embedder.embed_query(&query))
        .await
        .map_err(|e| ApiError::Invalid(format!("embed task panicked: {e}")))?;
    let result = Ranker::new(&state.storage)
        .rank(RankRequest {
            workspace: body.workspace_id,
            session: body.session_id,
            query_embedding,
            iteration: body.iteration,
        })
        .await;

    // Aggregate scores per file path. A file with 3 hits (0.6, 0.5, 0.4) wins
    // over one with a single 0.7 — concentration matters more than peak.
    let mut by_path: std::collections::HashMap<String, (f32, usize)> =
        std::collections::HashMap::new();
    for it in result.items.into_iter() {
        let meta = resolve_target_meta(&state, &it.target, false).await;
        if let Some(citation) = meta.citation {
            // Strip line range suffix if present: `path:N-M` → `path`.
            let path = citation
                .rsplit_once(':')
                .map(|(p, _)| p.to_string())
                .unwrap_or(citation);
            let entry = by_path.entry(path).or_insert((0.0, 0));
            entry.0 += it.score;
            entry.1 += 1;
        }
    }
    let mut items: Vec<FileRankItem> = by_path
        .into_iter()
        .map(|(path, (score, chunks))| FileRankItem {
            path,
            score,
            chunks,
        })
        .collect();
    items.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let limit = body.limit.unwrap_or(10);
    items.truncate(limit);

    Ok(Json(RankFilesResponse { items }))
}

// ============================================================================
// Git history (commits that touched a file or symbol)
// ============================================================================

#[derive(Debug, Deserialize)]
struct GitHistoryBody {
    workspace_id: WorkspaceId,
    /// File path (e.g. `src/user.rs`) or qualified symbol name (e.g.
    /// `User::validate`). The query tries both at once — exact-path match
    /// for `ChangesFile`, prefix-of-symbol match for "any symbol in this
    /// file", and suffix-match for "this symbol in any file".
    target: String,
    /// Optional lower bound on committer time (ms since epoch). Commits
    /// older than this are dropped.
    #[serde(default)]
    since_ms: Option<u64>,
    /// Cap on commits returned. Default 20.
    #[serde(default)]
    limit: Option<usize>,
}

#[derive(Debug, Serialize)]
struct GitHistoryItem {
    sha: String,
    summary: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    author: Option<String>,
    time_ms: u64,
    /// `"file"`, `"symbol"`, or `"symbol+file"` — which edge kind matched.
    /// Useful for the agent to know whether a commit hit the exact symbol
    /// or just touched the surrounding file.
    matched_kind: String,
}

#[derive(Debug, Serialize)]
struct GitHistoryResponse {
    items: Vec<GitHistoryItem>,
}

async fn git_history(
    State(state): State<Arc<AppState>>,
    Json(body): Json<GitHistoryBody>,
) -> ApiResult<Json<GitHistoryResponse>> {
    let limit = body.limit.unwrap_or(20).clamp(1, 200);
    let touches = state
        .storage
        .git_history_for_target(body.workspace_id, &body.target, body.since_ms, limit)
        .await;
    let items = touches
        .into_iter()
        .map(|t| GitHistoryItem {
            sha: t.sha,
            summary: t.summary,
            author: t.author,
            time_ms: t.time_ms,
            matched_kind: t.matched_kind,
        })
        .collect();
    Ok(Json(GitHistoryResponse { items }))
}

// ============================================================================
// List symbols in file (cheap structural overview, no embedder)
// ============================================================================

#[derive(Debug, Deserialize)]
struct ListSymbolsInFileBody {
    workspace_id: WorkspaceId,
    /// Repo-relative path (matches `documents.path_or_url`). Must equal what
    /// the ingest pipeline stored — usually relative to the repo root.
    path: String,
    /// When true, include the first ~10 lines of each symbol's chunk text
    /// (signature + adjacent doc comment / docstring). Default false to
    /// keep responses small for the common "give me a map of this file"
    /// use case.
    #[serde(default)]
    with_docstrings: bool,
    /// Cap on symbols returned. Default 100.
    #[serde(default)]
    limit: Option<usize>,
}

#[derive(Debug, Serialize)]
struct ListSymbolsItem {
    qualified_name: String,
    line_start: u32,
    line_end: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    head: Option<String>,
}

#[derive(Debug, Serialize)]
struct ListSymbolsResponse {
    items: Vec<ListSymbolsItem>,
}

async fn list_symbols_in_file(
    State(state): State<Arc<AppState>>,
    Json(body): Json<ListSymbolsInFileBody>,
) -> ApiResult<Json<ListSymbolsResponse>> {
    let limit = body.limit.unwrap_or(100).clamp(1, 500);
    let symbols = state
        .storage
        .list_symbols_in_file(body.workspace_id, &body.path, body.with_docstrings, limit)
        .await;
    let items = symbols
        .into_iter()
        .map(|s| ListSymbolsItem {
            qualified_name: s.qualified_name,
            line_start: s.line_start,
            line_end: s.line_end,
            head: s.head,
        })
        .collect();
    Ok(Json(ListSymbolsResponse { items }))
}

// ============================================================================
// Events (interactions)
// ============================================================================

#[derive(Debug, Deserialize)]
struct RecordEventBody {
    session_id: SessionId,
    target: NodeRef,
    event_type: EventType,
    weight: f32,
    iteration: u32,
    #[serde(default)]
    context_id: Option<ContextId>,
    #[serde(default)]
    tool_name: Option<String>,
}

#[derive(Debug, Serialize)]
struct RecordEventResponse {
    id: InteractionId,
}

async fn record_event(
    State(state): State<Arc<AppState>>,
    Json(body): Json<RecordEventBody>,
) -> ApiResult<Json<RecordEventResponse>> {
    let id = state
        .storage
        .append_interaction(NewInteraction {
            session_id: body.session_id,
            context_id: body.context_id,
            iteration: body.iteration,
            event_type: body.event_type,
            target: body.target,
            weight: body.weight,
            tool_name: body.tool_name,
        })
        .await?;
    Ok(Json(RecordEventResponse { id }))
}
