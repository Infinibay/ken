//! Storage support types.
//!
//! `PostgresStorage` (in `crate::postgres`) is the concrete and only storage
//! backend — see `docs/04-storage.md` and the project memory
//! `project_storage_architecture.md`. There is no `Storage` trait abstraction;
//! callers depend on `PostgresStorage` directly.
//!
//! This module owns the input / filter / outcome / error types used by the
//! storage API, plus the `is_visible` ACL helper. They live here (not in
//! `postgres.rs`) so consumers like the ranker and ingest pipeline can use
//! them without pulling in the postgres dependency wall.

use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::types::*;

// ============================================================================
// Errors
// ============================================================================

#[derive(Debug, Error)]
pub enum StorageError {
    #[error("tenant not found: {0}")]
    TenantNotFound(TenantId),
    #[error("workspace not found: {0}")]
    WorkspaceNotFound(WorkspaceId),
    #[error("source not found: {0}")]
    SourceNotFound(SourceId),
    #[error("document not found: {0}")]
    DocumentNotFound(DocumentId),
    #[error("chunk not found: {0}")]
    ChunkNotFound(ChunkId),
    #[error("entity not found: {0}")]
    EntityNotFound(EntityId),
    #[error("session not found: {0}")]
    SessionNotFound(SessionId),
    #[error("context not found: {0}")]
    ContextNotFound(ContextId),
    #[error("interaction not found: {0}")]
    InteractionNotFound(InteractionId),
    #[error("invalid input: {0}")]
    Invalid(String),
}

pub type StorageResult<T> = Result<T, StorageError>;

// ============================================================================
// Draft / input types
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewSource {
    pub workspace_id: WorkspaceId,
    pub kind: SourceKind,
    pub name: String,
    pub config_json: serde_json::Value,
    pub keep_history: bool,
    pub default_acl: Acl,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewDocument {
    pub workspace_id: WorkspaceId,
    pub source_id: SourceId,
    pub external_id: Option<String>,
    pub kind: ContentKind,
    pub mime: String,
    pub title: Option<String>,
    pub path_or_url: Option<String>,
    pub content_hash: [u8; 32],
    pub acl: Acl,
    pub metadata: MetadataMap,
    pub source_modified_at: Option<Timestamp>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewChunk {
    pub kind: ChunkKind,
    pub position: ChunkPosition,
    pub text: String,
    pub metadata: MetadataMap,
    /// Optional pre-computed embedding. When present, written inline with
    /// the chunk row in a single SQL statement — saves one round-trip per
    /// chunk vs. calling `put_embedding` afterwards.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub embedding: Option<Vec<f32>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewEntity {
    pub workspace_id: WorkspaceId,
    pub kind: EntityKind,
    pub canonical_name: String,
    pub aliases: Vec<String>,
    pub metadata: MetadataMap,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewEdge {
    pub workspace_id: WorkspaceId,
    pub from: NodeRef,
    pub to: NodeRef,
    pub kind: EdgeKind,
    pub weight: f32,
    pub metadata: MetadataMap,
    pub created_by: EdgeOrigin,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewContext {
    pub session_id: SessionId,
    pub kind: ContextKind,
    pub content: String,
    pub iteration: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewInteraction {
    pub session_id: SessionId,
    pub context_id: Option<ContextId>,
    pub iteration: u32,
    pub event_type: EventType,
    pub target: NodeRef,
    pub weight: f32,
    /// Optional client-side tool name (e.g. `"gmail.search"`). Forensics only —
    /// the ranker ignores it. See `docs/03-ranking.md` for the tool→EventType
    /// mapping contract.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_name: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewSessionScore {
    pub target: NodeRef,
    pub score: f32,
    pub access_count: u32,
    pub productivity: f32,
    pub pattern: Pattern,
    pub was_edited: bool,
}

/// One interaction to attach to a synthetic session. No `session_id`,
/// `context_id`, or `created_at` because they're filled in by
/// `record_synthetic_session` (the session it's being attached to and the
/// session's backdated created_at, respectively).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyntheticInteraction {
    pub iteration: u32,
    pub event_type: EventType,
    pub target: NodeRef,
    pub weight: f32,
}

/// All-in-one payload for `PostgresStorage::record_synthetic_session`. Used
/// by the git-history ingest path (`ingest_git`) — a real session that
/// happened in the past gets reconstructed from a commit and persisted with
/// backdated timestamps so the predictive ranker's time-decay math sees it
/// at the *commit's* age, not at ingest time.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyntheticSessionWrite {
    pub workspace_id: WorkspaceId,
    pub agent_id: String,
    /// Historical timestamp (commit's committer time, millis since epoch).
    /// Applied to `sessions.created_at`, `session_contexts.created_at`, and
    /// every `session_interactions.created_at` written by this call.
    pub created_at: Timestamp,
    pub context_kind: ContextKind,
    pub context_content: String,
    /// Pre-computed embedding for the context. Required for the synthetic
    /// session to participate in the predictive channel — the channel reads
    /// `session_contexts.embedding` to find similar past sessions.
    pub context_embedding: Option<Vec<f32>>,
    pub interactions: Vec<SyntheticInteraction>,
    pub scores: Vec<NewSessionScore>,
}

// ============================================================================
// Query result types
// ============================================================================

/// A commit that touched a particular file or symbol. Returned by
/// `git_history_for_target`. Carries enough metadata to render a citation
/// without a follow-up document fetch — the route would otherwise N+1.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommitTouch {
    pub document_id: DocumentId,
    /// Hex commit sha (extracted from the commit Document's `external_id`).
    pub sha: String,
    /// First line of the commit message.
    pub summary: String,
    /// `Name <email>` if known, else `None`.
    pub author: Option<String>,
    /// Committer time in milliseconds since epoch.
    pub time_ms: u64,
    /// Which edge kind matched: `"file"` for `ChangesFile`, `"symbol"` for
    /// `ChangesSymbol`. When both match the same commit the edge with the
    /// higher weight wins (symbol-level edges have weight 1.0; file-level
    /// edges weight depends on FileStatus).
    pub matched_kind: String,
}

/// One symbol declared in a file. Returned by `list_symbols_in_file`. The
/// `head` field carries the first lines of the chunk's text (signature +
/// adjacent doc-comment / docstring) only when the caller asked for it —
/// otherwise it stays `None` to keep the response cheap.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileSymbol {
    pub chunk_id: ChunkId,
    pub qualified_name: String,
    pub line_start: u32,
    pub line_end: u32,
    /// First N lines of the symbol's chunk text — covers the signature and
    /// (for adapters that include them) the leading doc comment / docstring.
    /// Cross-language heuristic; works because every code adapter starts the
    /// chunk at the symbol's signature.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub head: Option<String>,
}

// ============================================================================
// Filter / outcome types
// ============================================================================

#[derive(Debug, Clone, Default)]
pub struct ChunkFilter {
    pub kinds: Option<Vec<ChunkKind>>,
    pub sources: Option<Vec<SourceId>>,
    pub languages: Option<Vec<Language>>,
    pub tags: Option<Vec<String>>,
    pub current_only: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UpsertOutcome {
    Created(DocumentId),
    Updated(DocumentId),
    Versioned { new: DocumentId, replaced: DocumentId },
    Unchanged(DocumentId),
}

impl UpsertOutcome {
    pub fn current_id(&self) -> DocumentId {
        match self {
            UpsertOutcome::Created(id)
            | UpsertOutcome::Updated(id)
            | UpsertOutcome::Unchanged(id) => *id,
            UpsertOutcome::Versioned { new, .. } => *new,
        }
    }

    pub fn is_unchanged(&self) -> bool {
        matches!(self, UpsertOutcome::Unchanged(_))
    }
}

// ============================================================================
// Helpers
// ============================================================================

pub fn is_visible(acl: &Acl, principals: &[Principal]) -> bool {
    match acl.visibility {
        Visibility::Public => true,
        Visibility::Private => false,
        Visibility::Restricted => acl
            .principals
            .iter()
            .any(|p| principals.iter().any(|q| p == q)),
    }
}

pub fn now_millis() -> Timestamp {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn acl_visibility_rules() {
        let public = Acl { visibility: Visibility::Public, principals: vec![] };
        let private = Acl { visibility: Visibility::Private, principals: vec![] };
        let restricted = Acl {
            visibility: Visibility::Restricted,
            principals: vec![Principal { kind: PrincipalKind::User, id: "alice".into() }],
        };

        let alice = Principal { kind: PrincipalKind::User, id: "alice".into() };
        let bob = Principal { kind: PrincipalKind::User, id: "bob".into() };

        assert!(is_visible(&public, std::slice::from_ref(&bob)));
        assert!(!is_visible(&private, std::slice::from_ref(&alice)));
        assert!(is_visible(&restricted, std::slice::from_ref(&alice)));
        assert!(!is_visible(&restricted, std::slice::from_ref(&bob)));
    }

    #[test]
    fn upsert_outcome_helpers() {
        let id = DocumentId(7);
        assert_eq!(UpsertOutcome::Created(id).current_id(), id);
        assert_eq!(UpsertOutcome::Updated(id).current_id(), id);
        assert_eq!(UpsertOutcome::Unchanged(id).current_id(), id);
        assert_eq!(
            UpsertOutcome::Versioned { new: DocumentId(8), replaced: id }.current_id(),
            DocumentId(8),
        );
        assert!(UpsertOutcome::Unchanged(id).is_unchanged());
        assert!(!UpsertOutcome::Created(id).is_unchanged());
    }
}
