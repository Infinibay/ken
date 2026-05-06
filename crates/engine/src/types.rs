use std::str::FromStr;

use serde::{Deserialize, Deserializer, Serialize, Serializer};
use thiserror::Error;

pub type Timestamp = u64;

// ============================================================================
// IDs
// ============================================================================

macro_rules! id_type {
    ($name:ident) => {
        #[derive(
            Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize,
        )]
        #[serde(transparent)]
        pub struct $name(pub u64);

        impl std::fmt::Display for $name {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                self.0.fmt(f)
            }
        }
    };
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(transparent)]
pub struct TenantId(pub ulid::Ulid);

impl TenantId {
    pub fn new() -> Self {
        Self(ulid::Ulid::new())
    }
}

impl std::fmt::Display for TenantId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.0.fmt(f)
    }
}

id_type!(WorkspaceId);
id_type!(SourceId);
id_type!(DocumentId);
id_type!(ChunkId);
id_type!(EntityId);
id_type!(EdgeId);
id_type!(SessionId);
id_type!(ContextId);
id_type!(InteractionId);
id_type!(EmbeddingId);

// ============================================================================
// Identity & origin
// ============================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum PlanTier {
    #[default]
    Free,
    Team,
    Enterprise,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tenant {
    pub id: TenantId,
    pub name: String,
    pub plan: PlanTier,
    pub created_at: Timestamp,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct WorkspaceSettings {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub embedder_model: Option<String>,
    #[serde(default, skip_serializing_if = "serde_json::Value::is_null")]
    pub config: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Workspace {
    pub id: WorkspaceId,
    pub tenant_id: TenantId,
    pub name: String,
    pub settings: WorkspaceSettings,
    pub created_at: Timestamp,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceKind {
    LocalFs,
    Http,
    GitHub,
    Slack,
    Confluence,
    Gmail,
    S3,
    Manual,
    Custom(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Source {
    pub id: SourceId,
    pub workspace_id: WorkspaceId,
    pub kind: SourceKind,
    pub name: String,
    #[serde(default, skip_serializing_if = "serde_json::Value::is_null")]
    pub config_json: serde_json::Value,
    pub keep_history: bool,
    pub default_acl: Acl,
    pub last_sync_at: Option<Timestamp>,
    pub created_at: Timestamp,
}

// ============================================================================
// ACL
// ============================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum Visibility {
    #[default]
    Public,
    Restricted,
    Private,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PrincipalKind {
    User,
    Group,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct Principal {
    pub kind: PrincipalKind,
    pub id: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Acl {
    pub visibility: Visibility,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub principals: Vec<Principal>,
}

// ============================================================================
// Content kinds & metadata
// ============================================================================

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContentKind {
    CodeFile,
    Markdown,
    PlainText,
    Pdf,
    Docx,
    Html,
    Email,
    SlackMessage,
    JiraTicket,
    ConfluencePage,
    Notebook,
    Spreadsheet,
    Other(String),
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChunkKind {
    Paragraph,
    TokenWindow,
    Heading,
    CodeSymbol,
    PdfSection,
    EmailMessage,
    TableRow,
    Other(String),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ChunkPosition {
    ByteRange { start: u64, end: u64 },
    LineRange { start: u32, end: u32 },
    SymbolRange { qualified_name: String, line_start: u32, line_end: u32 },
    PageRange { page: u32, char_start: u32, char_end: u32 },
    Custom(serde_json::Value),
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Language {
    Rust,
    Python,
    TypeScript,
    JavaScript,
    Go,
    Java,
    Cpp,
    C,
    Ruby,
    English,
    Spanish,
    Portuguese,
    French,
    German,
    Other(String),
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct MetadataMap {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub language: Option<Language>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub author: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub size_bytes: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub word_count: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_modified_at: Option<Timestamp>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tags: Vec<String>,
    #[serde(default, skip_serializing_if = "serde_json::Value::is_null")]
    pub extra: serde_json::Value,
}

// ============================================================================
// Documents, Chunks, Entities
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Document {
    pub id: DocumentId,
    pub workspace_id: WorkspaceId,
    pub source_id: SourceId,
    pub external_id: Option<String>,
    pub kind: ContentKind,
    pub mime: String,
    pub title: Option<String>,
    pub path_or_url: Option<String>,
    pub content_hash: [u8; 32],
    pub version: u64,
    pub current: bool,
    pub replaced_by: Option<DocumentId>,
    pub acl: Acl,
    pub metadata: MetadataMap,
    pub ingested_at: Timestamp,
    pub source_modified_at: Option<Timestamp>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Chunk {
    pub id: ChunkId,
    pub document_id: DocumentId,
    pub workspace_id: WorkspaceId,
    pub kind: ChunkKind,
    pub position: ChunkPosition,
    pub text: String,
    pub embedding_id: Option<EmbeddingId>,
    pub metadata: MetadataMap,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EntityKind {
    Person,
    Organization,
    Product,
    Function,
    Project,
    Date,
    Other(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Entity {
    pub id: EntityId,
    pub workspace_id: WorkspaceId,
    pub kind: EntityKind,
    pub canonical_name: String,
    pub aliases: Vec<String>,
    pub embedding_id: Option<EmbeddingId>,
    pub metadata: MetadataMap,
}

// ============================================================================
// Knowledge graph: Edges & NodeRefs
// ============================================================================

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum NodeRef {
    Document(DocumentId),
    Chunk(ChunkId),
    Entity(EntityId),
    External(String),
}

#[derive(Debug, Error)]
pub enum NodeRefParseError {
    #[error("missing ':' separator in node ref")]
    MissingSeparator,
    #[error("unknown node ref prefix '{0}' (expected doc|chunk|ent|ext)")]
    UnknownPrefix(String),
    #[error("invalid id '{0}': {1}")]
    InvalidId(String, std::num::ParseIntError),
}

impl std::fmt::Display for NodeRef {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            NodeRef::Document(id) => write!(f, "doc:{}", id.0),
            NodeRef::Chunk(id) => write!(f, "chunk:{}", id.0),
            NodeRef::Entity(id) => write!(f, "ent:{}", id.0),
            NodeRef::External(uri) => write!(f, "ext:{uri}"),
        }
    }
}

impl FromStr for NodeRef {
    type Err = NodeRefParseError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let (prefix, rest) = s.split_once(':').ok_or(NodeRefParseError::MissingSeparator)?;
        match prefix {
            "doc" => rest
                .parse::<u64>()
                .map(|n| NodeRef::Document(DocumentId(n)))
                .map_err(|e| NodeRefParseError::InvalidId(rest.to_string(), e)),
            "chunk" => rest
                .parse::<u64>()
                .map(|n| NodeRef::Chunk(ChunkId(n)))
                .map_err(|e| NodeRefParseError::InvalidId(rest.to_string(), e)),
            "ent" => rest
                .parse::<u64>()
                .map(|n| NodeRef::Entity(EntityId(n)))
                .map_err(|e| NodeRefParseError::InvalidId(rest.to_string(), e)),
            "ext" => Ok(NodeRef::External(rest.to_string())),
            other => Err(NodeRefParseError::UnknownPrefix(other.to_string())),
        }
    }
}

impl Serialize for NodeRef {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for NodeRef {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let s = String::deserialize(deserializer)?;
        s.parse().map_err(serde::de::Error::custom)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EdgeKind {
    Imports,
    Cites,
    Replies,
    Authored,
    Mentions,
    DerivedFrom,
    SimilarTo,
    Defines,
    References,
    /// Git commit-message linkage: this commit fixes the bug introduced by
    /// the target. Populated by the `Fixes:` trailer parser in
    /// `ingest_git::linkage`. The target is `External("git+sha:<sha>")`,
    /// possibly dangling if we haven't ingested that commit yet.
    Fixes,
    /// Git commit-message linkage: this commit reverts the target.
    Reverts,
    /// Git commit-message linkage: this commit was cherry-picked from the
    /// target (`(cherry picked from commit <sha>)`).
    CherryPickedFrom,
    /// Git diff: this commit modified / created / deleted the target file.
    /// More specific than `References`; the edge metadata carries a
    /// `status` ∈ {added, modified, removed, renamed}.
    ChangesFile,
    /// File-identity bridge: target was the previous path of source after
    /// a libgit2-detected rename. Emitted commit-side: a single rename
    /// produces one edge (ON CONFLICT collapses if multiple commits do
    /// the same rename — rare but possible across cherry-picks).
    RenamedFrom,
    /// Like `ChangesFile` but resolved to the enclosing code symbol via
    /// tree-sitter on the post-state file content. Target is
    /// `External("git+symbol:<ws>:<path>:<qualified_name>")`. A future
    /// sweep can rewrite these to `Chunk(id)` once a `CodeAdapter` has
    /// ingested the same file through the regular pipeline.
    ChangesSymbol,
    /// Inferred at session-close: both endpoints were productively
    /// co-accessed during the same session (productivity > 1.0 — Cited,
    /// ReadEdit, or EditOnly). Symmetric — both directions are emitted.
    /// The ranker can use this as a 1-hop expansion signal once we wire
    /// edge-following into the predictive channel. Metadata carries the
    /// session id and both endpoints' patterns for forensics.
    CoAccessed,
    /// Inferred at turn-close (`Stop` hook): connects the user's prompt
    /// context for that turn to every tool target the agent touched while
    /// answering it. Weight decays linearly by position — the FIRST tool
    /// in the turn is most strongly anchored to the prompt (it's
    /// "answering" it most directly); later tools earn lower weight.
    /// `from` is the user-input SessionContext encoded as
    /// `External("ctx:<id>")`; `to` is the tool target.
    PromptAnchored,
    /// Mirror of `PromptAnchored` but anchored on the agent's final reply
    /// SessionContext. Weight *grows* by position — the LAST tool is most
    /// strongly anchored to the reply (the reply summarizes the work
    /// closest to it). Together with `PromptAnchored` these two edges
    /// give the ranker a way to retrieve "which files did I touch when
    /// I asked X last week?" by semantically matching the prompt context
    /// and following its outgoing edges.
    ReplyAnchored,
    Other(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EdgeOrigin {
    Adapter,
    UrlResolver,
    Annotator,
    Background,
    User,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Edge {
    pub id: EdgeId,
    pub workspace_id: WorkspaceId,
    pub from: NodeRef,
    pub to: NodeRef,
    pub kind: EdgeKind,
    pub weight: f32,
    pub metadata: MetadataMap,
    pub created_by: EdgeOrigin,
    pub created_at: Timestamp,
}

// ============================================================================
// Sessions & interactions (agent-first)
// ============================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum SessionKind {
    /// A live agent session — created via `create_session`. The default.
    #[default]
    Real,
    /// A reconstructed session — created via `record_synthetic_session`
    /// (git history replay, imports, etc). The ranker is free to weight
    /// these lower than live sessions; see `docs/11-git-history-plan.md`
    /// §6 risk register.
    Synthetic,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
    pub id: SessionId,
    pub workspace_id: WorkspaceId,
    pub agent_id: Option<String>,
    #[serde(default)]
    pub kind: SessionKind,
    pub created_at: Timestamp,
    pub ended_at: Option<Timestamp>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContextKind {
    /// What the user typed at the start of a turn. Captured by the
    /// `UserPromptSubmit` hook in Claude Code. Embedded so the predictive
    /// channel can compare future queries against past intent.
    UserInput,
    /// The result returned by a tool call (Read, Bash, …). Reserved for
    /// future fine-grained capture; not currently emitted by hooks.
    ToolResult,
    /// One step in a planned breakdown of work — e.g. "I'll first survey
    /// the auth code, then refactor the middleware."
    StepDescription,
    /// The agent's internal reflection — thinking, deliberation. Not
    /// captured by default (intentionally — see `AssistantReply`).
    Reflection,
    /// The agent's final user-facing reply at the end of a turn. Captured
    /// by the `Stop` hook reading the transcript. Carries the
    /// conclusions / explanations / answers the user actually sees, which
    /// makes it high-signal for the predictive channel — much higher than
    /// inner deliberation that never lands.
    AssistantReply,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionContext {
    pub id: ContextId,
    pub session_id: SessionId,
    pub kind: ContextKind,
    pub content: String,
    pub iteration: u32,
    pub embedding_id: Option<EmbeddingId>,
    pub created_at: Timestamp,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EventType {
    Retrieved,
    Read,
    Edited,
    Cited,
    Dismissed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionInteraction {
    pub id: InteractionId,
    pub session_id: SessionId,
    pub context_id: Option<ContextId>,
    pub iteration: u32,
    pub event_type: EventType,
    pub target: NodeRef,
    pub weight: f32,
    pub was_useful: Option<bool>,
    /// Forensics / telemetry only — the ranker never reads this. Lets
    /// callers preserve their own tool name (`gmail.search`, `file.read`, …)
    /// for later debugging and future per-tool weight learning. The engine's
    /// ranking contract is `(event_type, weight)`; see
    /// `docs/03-ranking.md` and the project memory `project_tool_event_boundary.md`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_name: Option<String>,
    pub created_at: Timestamp,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum Pattern {
    Cited,
    ReadEdit,
    EditOnly,
    #[default]
    Neutral,
    ReadRepeated,
    /// Read 1–2× and never edited, *while the same session edited a
    /// different target*. The agent looked at the file and moved on —
    /// a softer-but-real form of rejection that historically aliased
    /// into `Neutral`. Damped to 0.3× so the file still ranks (it's
    /// the first time the agent saw it) but loses cleanly to the
    /// target that was actually edited.
    ReadSkipped,
    Dismissed,
}

impl Pattern {
    pub fn multiplier(self) -> f32 {
        match self {
            Pattern::Cited => 2.5,
            Pattern::ReadEdit => 2.0,
            Pattern::EditOnly => 1.5,
            Pattern::Neutral => 1.0,
            Pattern::ReadRepeated => 0.7,
            Pattern::ReadSkipped => 0.3,
            Pattern::Dismissed => 0.3,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionScore {
    pub session_id: SessionId,
    pub target: NodeRef,
    pub score: f32,
    pub access_count: u32,
    pub productivity: f32,
    pub pattern: Pattern,
    pub was_edited: bool,
    pub created_at: Timestamp,
}

// ============================================================================
// Embeddings — owner registry
// ============================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EmbedOwner {
    Chunk,
    Entity,
    SessionContext,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct EmbedKey {
    pub owner: EmbedOwner,
    pub id: u64,
}

impl EmbedKey {
    pub fn chunk(id: ChunkId) -> Self {
        Self { owner: EmbedOwner::Chunk, id: id.0 }
    }
    pub fn entity(id: EntityId) -> Self {
        Self { owner: EmbedOwner::Entity, id: id.0 }
    }
    pub fn context(id: ContextId) -> Self {
        Self { owner: EmbedOwner::SessionContext, id: id.0 }
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pattern_multipliers() {
        assert_eq!(Pattern::Cited.multiplier(), 2.5);
        assert_eq!(Pattern::ReadEdit.multiplier(), 2.0);
        assert_eq!(Pattern::EditOnly.multiplier(), 1.5);
        assert_eq!(Pattern::Neutral.multiplier(), 1.0);
        assert_eq!(Pattern::ReadRepeated.multiplier(), 0.7);
        assert_eq!(Pattern::ReadSkipped.multiplier(), 0.3);
        assert_eq!(Pattern::Dismissed.multiplier(), 0.3);
    }

    #[test]
    fn nodref_display_roundtrip() {
        let cases = vec![
            NodeRef::Document(DocumentId(42)),
            NodeRef::Chunk(ChunkId(0)),
            NodeRef::Entity(EntityId(u64::MAX)),
            NodeRef::External("https://example.com/page#anchor".into()),
            NodeRef::External("ABC-1234".into()),
        ];
        for r in cases {
            let s = r.to_string();
            let parsed: NodeRef = s.parse().expect("parse roundtrip");
            assert_eq!(parsed, r);
        }
    }

    #[test]
    fn nodref_format_examples() {
        assert_eq!(NodeRef::Document(DocumentId(7)).to_string(), "doc:7");
        assert_eq!(NodeRef::Chunk(ChunkId(123)).to_string(), "chunk:123");
        assert_eq!(NodeRef::Entity(EntityId(9)).to_string(), "ent:9");
        assert_eq!(
            NodeRef::External("https://x.com".into()).to_string(),
            "ext:https://x.com"
        );
    }

    #[test]
    fn nodref_parse_errors() {
        assert!("nope".parse::<NodeRef>().is_err());
        assert!("foo:1".parse::<NodeRef>().is_err());
        assert!("doc:notanumber".parse::<NodeRef>().is_err());
    }

    #[test]
    fn nodref_serde_json_roundtrip() {
        let r = NodeRef::Chunk(ChunkId(99));
        let s = serde_json::to_string(&r).unwrap();
        assert_eq!(s, "\"chunk:99\"");
        let back: NodeRef = serde_json::from_str(&s).unwrap();
        assert_eq!(back, r);
    }

    #[test]
    fn tenant_id_is_ulid() {
        let t = TenantId::new();
        let s = t.to_string();
        assert_eq!(s.len(), 26);
        let parsed = serde_json::to_string(&t).unwrap();
        assert!(parsed.contains(&s));
    }

    #[test]
    fn document_serde_roundtrip() {
        let d = Document {
            id: DocumentId(1),
            workspace_id: WorkspaceId(1),
            source_id: SourceId(1),
            external_id: Some("sha-abc".into()),
            kind: ContentKind::CodeFile,
            mime: "text/x-rust".into(),
            title: Some("lib.rs".into()),
            path_or_url: Some("crates/engine/src/lib.rs".into()),
            content_hash: [0u8; 32],
            version: 1,
            current: true,
            replaced_by: None,
            acl: Acl::default(),
            metadata: MetadataMap {
                language: Some(Language::Rust),
                tags: vec!["core".into()],
                ..Default::default()
            },
            ingested_at: 1700000000000,
            source_modified_at: None,
        };
        let s = serde_json::to_string(&d).unwrap();
        let back: Document = serde_json::from_str(&s).unwrap();
        assert_eq!(back.id, d.id);
        assert_eq!(back.metadata.language, Some(Language::Rust));
    }

    #[test]
    fn embed_key_construction() {
        assert_eq!(
            EmbedKey::chunk(ChunkId(5)),
            EmbedKey { owner: EmbedOwner::Chunk, id: 5 }
        );
        assert_eq!(
            EmbedKey::entity(EntityId(7)),
            EmbedKey { owner: EmbedOwner::Entity, id: 7 }
        );
        assert_eq!(
            EmbedKey::context(ContextId(9)),
            EmbedKey { owner: EmbedOwner::SessionContext, id: 9 }
        );
    }

    #[test]
    fn content_kind_other_serde() {
        let k = ContentKind::Other("CustomFormat".into());
        let s = serde_json::to_string(&k).unwrap();
        let back: ContentKind = serde_json::from_str(&s).unwrap();
        assert_eq!(back, k);
    }
}
