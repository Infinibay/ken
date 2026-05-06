//! PostgreSQL backend.
//!
//! Per D-019 (`docs/06-decisions.md`) and `docs/04-storage.md`, the production
//! `Storage` backend is PostgreSQL + `pgvector`. Schema is defined in
//! `crates/engine/migrations/0001_initial.sql`.
//!
//! ## Design notes
//! - Numeric IDs (`WorkspaceId`, `DocumentId`, …) are `u64` in Rust and `BIGINT`
//!   (i64) in Postgres. They come from `BIGSERIAL` so they always fit positive
//!   i64 — `as` cast preserves the bit pattern.
//! - `TenantId` (`ulid::Ulid`) is stored as 26-char Crockford32 TEXT.
//! - `NodeRef` is split across `(kind TEXT, id BIGINT NULL, uri TEXT NULL)`.
//! - Embeddings live on the owning row (`chunks.embedding`, `entities.embedding`,
//!   `session_contexts.embedding`). The `EmbeddingId` returned by
//!   `put_embedding` is a synthetic value that tags `(owner, owner_id)` into a
//!   single `u64` — top 2 bits = owner kind, low 62 bits = owner row id.
//! - JSONB fields (`kind`, `metadata`, `acl`, …) round-trip via
//!   `sqlx::types::Json<T>` against the existing serde derives in `types.rs`.
//! - Multi-step writes (`upsert_document`, `replace_chunks`, `delete_document`,
//!   `add_edge`, `upsert_entity`, `snapshot_session_scores`) run inside a
//!   single `BEGIN` / `COMMIT` for atomicity (D-018).

use std::str::FromStr;

use pgvector::Vector;
use sqlx::postgres::{PgPool, PgPoolOptions};
use sqlx::types::Json;
use sqlx::Row;
use thiserror::Error;

use crate::storage::{
    now_millis, ChunkFilter, CommitTouch, FileSymbol, NewChunk, NewContext, NewDocument, NewEdge,
    NewEntity, NewInteraction, NewSessionScore, NewSource, StorageError, StorageResult,
    SyntheticSessionWrite, UpsertOutcome,
};
use crate::types::*;

#[derive(Debug, Error)]
pub enum PgStorageError {
    #[error("postgres error: {0}")]
    Sqlx(#[from] sqlx::Error),
    #[error("migration error: {0}")]
    Migrate(#[from] sqlx::migrate::MigrateError),
}

pub type PgStorageResult<T> = Result<T, PgStorageError>;

#[derive(Debug, Clone)]
pub struct PostgresConfig {
    pub database_url: String,
    pub max_connections: u32,
    pub min_connections: u32,
    pub connect_timeout_seconds: u64,
}

impl PostgresConfig {
    pub fn from_url(database_url: impl Into<String>) -> Self {
        Self {
            database_url: database_url.into(),
            max_connections: 20,
            min_connections: 1,
            connect_timeout_seconds: 10,
        }
    }
}

pub struct PostgresStorage {
    pool: PgPool,
}

impl PostgresStorage {
    /// Connect using a `DATABASE_URL`-style libpq connection string and the
    /// default pool settings.
    pub async fn connect(database_url: &str) -> PgStorageResult<Self> {
        Self::connect_with(PostgresConfig::from_url(database_url)).await
    }

    pub async fn connect_with(cfg: PostgresConfig) -> PgStorageResult<Self> {
        let pool = PgPoolOptions::new()
            .max_connections(cfg.max_connections)
            .min_connections(cfg.min_connections)
            .acquire_timeout(std::time::Duration::from_secs(cfg.connect_timeout_seconds))
            .connect(&cfg.database_url)
            .await?;
        Ok(Self { pool })
    }

    /// Apply embedded migrations (`crates/engine/migrations/`).
    pub async fn migrate(&self) -> PgStorageResult<()> {
        sqlx::migrate!("./migrations").run(&self.pool).await?;
        Ok(())
    }

    /// `SELECT 1` round-trip — confirms the pool is usable.
    pub async fn health_check(&self) -> PgStorageResult<()> {
        sqlx::query("SELECT 1").execute(&self.pool).await?;
        Ok(())
    }

    /// Confirms the `vector` extension is loaded (returns extension version).
    pub async fn vector_extension_version(&self) -> PgStorageResult<Option<String>> {
        let row: Option<(String,)> =
            sqlx::query_as("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
                .fetch_optional(&self.pool)
                .await?;
        Ok(row.map(|r| r.0))
    }

    pub fn pool(&self) -> &PgPool {
        &self.pool
    }
}

// ============================================================================
// Helpers
// ============================================================================

fn map_sqlx(e: sqlx::Error) -> StorageError {
    StorageError::Invalid(format!("postgres: {e}"))
}

/// Decompose a `NodeRef` into the `(kind, id, uri)` triple stored in the edge /
/// interaction / score tables.
fn pg_ref(node: &NodeRef) -> (&'static str, Option<i64>, Option<&str>) {
    match node {
        NodeRef::Document(id) => ("doc", Some(id.0 as i64), None),
        NodeRef::Chunk(id) => ("chunk", Some(id.0 as i64), None),
        NodeRef::Entity(id) => ("ent", Some(id.0 as i64), None),
        NodeRef::External(uri) => ("ext", None, Some(uri.as_str())),
    }
}

fn from_pg_ref(kind: &str, id: Option<i64>, uri: Option<String>) -> Option<NodeRef> {
    match kind {
        "doc" => id.map(|i| NodeRef::Document(DocumentId(i as u64))),
        "chunk" => id.map(|i| NodeRef::Chunk(ChunkId(i as u64))),
        "ent" => id.map(|i| NodeRef::Entity(EntityId(i as u64))),
        "ext" => uri.map(NodeRef::External),
        _ => None,
    }
}

/// Pack `(EmbedOwner, owner_row_id)` into a single `u64` so we can return it
/// as an opaque `EmbeddingId` to callers. Top 2 bits tag the owner; low 62 bits
/// hold the row id (BIGSERIAL ids never approach 2^62 in practice).
fn encode_embedding_id(owner: EmbedOwner, id: u64) -> EmbeddingId {
    debug_assert!(id < (1u64 << 62), "row id exceeds 62-bit budget");
    let tag: u64 = match owner {
        EmbedOwner::Chunk => 0,
        EmbedOwner::Entity => 1,
        EmbedOwner::SessionContext => 2,
    };
    EmbeddingId((tag << 62) | id)
}

fn decode_embedding_id(eid: EmbeddingId) -> Option<(EmbedOwner, u64)> {
    let tag = eid.0 >> 62;
    let id = eid.0 & ((1u64 << 62) - 1);
    let owner = match tag {
        0 => EmbedOwner::Chunk,
        1 => EmbedOwner::Entity,
        2 => EmbedOwner::SessionContext,
        _ => return None,
    };
    Some((owner, id))
}

fn embed_target_table(owner: EmbedOwner) -> &'static str {
    match owner {
        EmbedOwner::Chunk => "chunks",
        EmbedOwner::Entity => "entities",
        EmbedOwner::SessionContext => "session_contexts",
    }
}

fn event_type_str(e: EventType) -> &'static str {
    match e {
        EventType::Retrieved => "retrieved",
        EventType::Read => "read",
        EventType::Edited => "edited",
        EventType::Cited => "cited",
        EventType::Dismissed => "dismissed",
    }
}

fn event_type_from_str(s: &str) -> Option<EventType> {
    Some(match s {
        "retrieved" => EventType::Retrieved,
        "read" => EventType::Read,
        "edited" => EventType::Edited,
        "cited" => EventType::Cited,
        "dismissed" => EventType::Dismissed,
        _ => return None,
    })
}

fn context_kind_str(k: ContextKind) -> &'static str {
    match k {
        ContextKind::UserInput => "user_input",
        ContextKind::ToolResult => "tool_result",
        ContextKind::StepDescription => "step_description",
        ContextKind::Reflection => "reflection",
    }
}

fn context_kind_from_str(s: &str) -> Option<ContextKind> {
    Some(match s {
        "user_input" => ContextKind::UserInput,
        "tool_result" => ContextKind::ToolResult,
        "step_description" => ContextKind::StepDescription,
        "reflection" => ContextKind::Reflection,
        _ => return None,
    })
}

fn pattern_str(p: Pattern) -> &'static str {
    match p {
        Pattern::Cited => "cited",
        Pattern::ReadEdit => "read_edit",
        Pattern::EditOnly => "edit_only",
        Pattern::Neutral => "neutral",
        Pattern::ReadRepeated => "read_repeated",
        Pattern::Dismissed => "dismissed",
    }
}

fn pattern_from_str(s: &str) -> Option<Pattern> {
    Some(match s {
        "cited" => Pattern::Cited,
        "read_edit" => Pattern::ReadEdit,
        "edit_only" => Pattern::EditOnly,
        "neutral" => Pattern::Neutral,
        "read_repeated" => Pattern::ReadRepeated,
        "dismissed" => Pattern::Dismissed,
        _ => return None,
    })
}

fn plan_tier_str(p: PlanTier) -> &'static str {
    match p {
        PlanTier::Free => "free",
        PlanTier::Team => "team",
        PlanTier::Enterprise => "enterprise",
    }
}

fn plan_tier_from_str(s: &str) -> PlanTier {
    match s {
        "team" => PlanTier::Team,
        "enterprise" => PlanTier::Enterprise,
        _ => PlanTier::Free,
    }
}

// ============================================================================
// Storage operations (inherent impl — no trait abstraction; Postgres is the
// only backend, see `project_storage_architecture.md`).
// ============================================================================

impl PostgresStorage {
    // ---------- Tenants ----------

    pub async fn create_tenant(&self, name: &str, plan: PlanTier) -> StorageResult<TenantId> {
        let id = TenantId::new();
        sqlx::query(
            "INSERT INTO tenants (id, name, plan, created_at) VALUES ($1, $2, $3, $4)",
        )
        .bind(id.to_string())
        .bind(name)
        .bind(plan_tier_str(plan))
        .bind(now_millis() as i64)
        .execute(&self.pool)
        .await
        .map_err(map_sqlx)?;
        Ok(id)
    }

    pub async fn get_tenant(&self, id: TenantId) -> Option<Tenant> {
        let row = sqlx::query("SELECT id, name, plan, created_at FROM tenants WHERE id = $1")
            .bind(id.to_string())
            .fetch_optional(&self.pool)
            .await
            .ok()??;
        let id_str: String = row.get(0);
        let parsed = ulid::Ulid::from_str(&id_str).ok()?;
        Some(Tenant {
            id: TenantId(parsed),
            name: row.get(1),
            plan: plan_tier_from_str(row.get::<&str, _>(2)),
            created_at: row.get::<i64, _>(3) as u64,
        })
    }

    // ---------- Workspaces ----------

    pub async fn create_workspace(
        &self,
        tenant_id: TenantId,
        name: &str,
        settings: WorkspaceSettings,
    ) -> StorageResult<WorkspaceId> {
        let id: i64 = sqlx::query_scalar(
            "INSERT INTO workspaces (tenant_id, name, settings, created_at)
             VALUES ($1, $2, $3, $4) RETURNING id",
        )
        .bind(tenant_id.to_string())
        .bind(name)
        .bind(Json(settings))
        .bind(now_millis() as i64)
        .fetch_one(&self.pool)
        .await
        .map_err(map_sqlx)?;
        Ok(WorkspaceId(id as u64))
    }

    pub async fn get_workspace(&self, id: WorkspaceId) -> Option<Workspace> {
        let row = sqlx::query(
            "SELECT id, tenant_id, name, settings, created_at FROM workspaces WHERE id = $1",
        )
        .bind(id.0 as i64)
        .fetch_optional(&self.pool)
        .await
        .ok()??;
        let tid_str: String = row.get(1);
        let tid = ulid::Ulid::from_str(&tid_str).ok()?;
        let settings: Json<WorkspaceSettings> = row.get(3);
        Some(Workspace {
            id: WorkspaceId(row.get::<i64, _>(0) as u64),
            tenant_id: TenantId(tid),
            name: row.get(2),
            settings: settings.0,
            created_at: row.get::<i64, _>(4) as u64,
        })
    }

    // ---------- Sources ----------

    pub async fn create_source(&self, src: NewSource) -> StorageResult<SourceId> {
        let id: i64 = sqlx::query_scalar(
            "INSERT INTO sources (workspace_id, kind, name, config_json, keep_history, default_acl, created_at)
             VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
        )
        .bind(src.workspace_id.0 as i64)
        .bind(Json(&src.kind))
        .bind(&src.name)
        .bind(Json(&src.config_json))
        .bind(src.keep_history)
        .bind(Json(&src.default_acl))
        .bind(now_millis() as i64)
        .fetch_one(&self.pool)
        .await
        .map_err(map_sqlx)?;
        Ok(SourceId(id as u64))
    }

    pub async fn get_source(&self, id: SourceId) -> Option<Source> {
        let row = sqlx::query(
            "SELECT id, workspace_id, kind, name, config_json, keep_history, default_acl, last_sync_at, created_at
             FROM sources WHERE id = $1",
        )
        .bind(id.0 as i64)
        .fetch_optional(&self.pool)
        .await
        .ok()??;
        let kind: Json<SourceKind> = row.get(2);
        let acl: Json<Acl> = row.get(6);
        let cfg: Option<Json<serde_json::Value>> = row.get(4);
        Some(Source {
            id: SourceId(row.get::<i64, _>(0) as u64),
            workspace_id: WorkspaceId(row.get::<i64, _>(1) as u64),
            kind: kind.0,
            name: row.get(3),
            config_json: cfg.map(|j| j.0).unwrap_or(serde_json::Value::Null),
            keep_history: row.get(5),
            default_acl: acl.0,
            last_sync_at: row.get::<Option<i64>, _>(7).map(|t| t as u64),
            created_at: row.get::<i64, _>(8) as u64,
        })
    }

    /// Lookup a source by name within a workspace. Returns `None` if absent
    /// or the workspace doesn't exist. Used by the `ensure_source` helpers
    /// to make re-running ingest commands idempotent without forcing the
    /// caller to remember a `--source` id.
    pub async fn find_source_by_name(
        &self,
        workspace_id: WorkspaceId,
        name: &str,
    ) -> Option<SourceId> {
        let id: Option<i64> = sqlx::query_scalar(
            "SELECT id FROM sources WHERE workspace_id = $1 AND name = $2 LIMIT 1",
        )
        .bind(workspace_id.0 as i64)
        .bind(name)
        .fetch_optional(&self.pool)
        .await
        .ok()
        .flatten();
        id.map(|i| SourceId(i as u64))
    }

    pub async fn touch_source_synced(&self, id: SourceId, ts: Timestamp) -> StorageResult<()> {
        let res = sqlx::query("UPDATE sources SET last_sync_at = $1 WHERE id = $2")
            .bind(ts as i64)
            .bind(id.0 as i64)
            .execute(&self.pool)
            .await
            .map_err(map_sqlx)?;
        if res.rows_affected() == 0 {
            return Err(StorageError::SourceNotFound(id));
        }
        Ok(())
    }

    // ---------- Documents ----------

    pub async fn upsert_document(&self, draft: NewDocument) -> StorageResult<UpsertOutcome> {
        let mut tx = self.pool.begin().await.map_err(map_sqlx)?;

        // Single round-trip preflight: source.keep_history + workspace
        // existence + existing-document lookup, all in one CTE'd query.
        // Returns four nullable cols: (source_keep_history, ws_id, doc_id,
        // doc_content_hash, doc_version). Source-not-found surfaces as a
        // NULL keep_history and we map it to the SourceNotFound error;
        // same for workspace.
        let row: (Option<bool>, Option<i64>, Option<i64>, Option<Vec<u8>>, Option<i64>) =
            sqlx::query_as(
                "SELECT
                    (SELECT keep_history FROM sources WHERE id = $1),
                    (SELECT id FROM workspaces WHERE id = $2),
                    d.id, d.content_hash, d.version
                 FROM (SELECT 1) AS _
                 LEFT JOIN documents d
                   ON d.source_id = $1
                  AND ($3::text IS NOT NULL AND d.external_id = $3)
                  AND d.current = TRUE",
            )
            .bind(draft.source_id.0 as i64)
            .bind(draft.workspace_id.0 as i64)
            .bind(draft.external_id.as_deref())
            .fetch_one(&mut *tx)
            .await
            .map_err(map_sqlx)?;
        let keep_history = row
            .0
            .ok_or(StorageError::SourceNotFound(draft.source_id))?;
        if row.1.is_none() {
            return Err(StorageError::WorkspaceNotFound(draft.workspace_id));
        }
        let existing: Option<(i64, Vec<u8>, i64)> = match (row.2, row.3, row.4) {
            (Some(id), Some(hash), Some(version)) => Some((id, hash, version)),
            _ => None,
        };

        let now = now_millis();
        let outcome = if let Some((existing_id, existing_hash, existing_version)) = existing {
            if existing_hash.as_slice() == draft.content_hash.as_slice() {
                tx.commit().await.map_err(map_sqlx)?;
                return Ok(UpsertOutcome::Unchanged(DocumentId(existing_id as u64)));
            }
            if !keep_history {
                sqlx::query(
                    "UPDATE documents SET kind = $1, mime = $2, title = $3, path_or_url = $4,
                       content_hash = $5, version = version + 1, acl = $6, metadata = $7,
                       ingested_at = $8, source_modified_at = $9
                     WHERE id = $10",
                )
                .bind(Json(&draft.kind))
                .bind(&draft.mime)
                .bind(&draft.title)
                .bind(&draft.path_or_url)
                .bind(draft.content_hash.as_slice())
                .bind(Json(&draft.acl))
                .bind(Json(&draft.metadata))
                .bind(now as i64)
                .bind(draft.source_modified_at.map(|t| t as i64))
                .bind(existing_id)
                .execute(&mut *tx)
                .await
                .map_err(map_sqlx)?;
                UpsertOutcome::Updated(DocumentId(existing_id as u64))
            } else {
                // Mark the old row as historical. The partial unique index on
                // (source_id, external_id) WHERE current is what frees the slot
                // for the replacement insert below.
                sqlx::query("UPDATE documents SET current = FALSE WHERE id = $1")
                    .bind(existing_id)
                    .execute(&mut *tx)
                    .await
                    .map_err(map_sqlx)?;
                let new_id: i64 = sqlx::query_scalar(
                    "INSERT INTO documents (workspace_id, source_id, external_id, kind, mime,
                       title, path_or_url, content_hash, version, current, replaced_by, acl,
                       metadata, ingested_at, source_modified_at)
                     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, TRUE, NULL, $10, $11, $12, $13)
                     RETURNING id",
                )
                .bind(draft.workspace_id.0 as i64)
                .bind(draft.source_id.0 as i64)
                .bind(&draft.external_id)
                .bind(Json(&draft.kind))
                .bind(&draft.mime)
                .bind(&draft.title)
                .bind(&draft.path_or_url)
                .bind(draft.content_hash.as_slice())
                .bind(existing_version + 1)
                .bind(Json(&draft.acl))
                .bind(Json(&draft.metadata))
                .bind(now as i64)
                .bind(draft.source_modified_at.map(|t| t as i64))
                .fetch_one(&mut *tx)
                .await
                .map_err(map_sqlx)?;
                sqlx::query("UPDATE documents SET replaced_by = $1 WHERE id = $2")
                    .bind(new_id)
                    .bind(existing_id)
                    .execute(&mut *tx)
                    .await
                    .map_err(map_sqlx)?;
                UpsertOutcome::Versioned {
                    new: DocumentId(new_id as u64),
                    replaced: DocumentId(existing_id as u64),
                }
            }
        } else {
            let new_id: i64 = sqlx::query_scalar(
                "INSERT INTO documents (workspace_id, source_id, external_id, kind, mime, title,
                   path_or_url, content_hash, version, current, replaced_by, acl, metadata,
                   ingested_at, source_modified_at)
                 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 1, TRUE, NULL, $9, $10, $11, $12)
                 RETURNING id",
            )
            .bind(draft.workspace_id.0 as i64)
            .bind(draft.source_id.0 as i64)
            .bind(&draft.external_id)
            .bind(Json(&draft.kind))
            .bind(&draft.mime)
            .bind(&draft.title)
            .bind(&draft.path_or_url)
            .bind(draft.content_hash.as_slice())
            .bind(Json(&draft.acl))
            .bind(Json(&draft.metadata))
            .bind(now as i64)
            .bind(draft.source_modified_at.map(|t| t as i64))
            .fetch_one(&mut *tx)
            .await
            .map_err(map_sqlx)?;
            UpsertOutcome::Created(DocumentId(new_id as u64))
        };

        tx.commit().await.map_err(map_sqlx)?;
        Ok(outcome)
    }

    pub async fn get_document(&self, id: DocumentId) -> Option<Document> {
        let row = sqlx::query(
            "SELECT id, workspace_id, source_id, external_id, kind, mime, title, path_or_url,
                    content_hash, version, current, replaced_by, acl, metadata, ingested_at,
                    source_modified_at
             FROM documents WHERE id = $1",
        )
        .bind(id.0 as i64)
        .fetch_optional(&self.pool)
        .await
        .ok()??;
        let kind: Json<ContentKind> = row.get(4);
        let acl: Json<Acl> = row.get(12);
        let metadata: Json<MetadataMap> = row.get(13);
        let hash_bytes: Vec<u8> = row.get(8);
        let mut content_hash = [0u8; 32];
        if hash_bytes.len() == 32 {
            content_hash.copy_from_slice(&hash_bytes);
        }
        Some(Document {
            id: DocumentId(row.get::<i64, _>(0) as u64),
            workspace_id: WorkspaceId(row.get::<i64, _>(1) as u64),
            source_id: SourceId(row.get::<i64, _>(2) as u64),
            external_id: row.get(3),
            kind: kind.0,
            mime: row.get(5),
            title: row.get(6),
            path_or_url: row.get(7),
            content_hash,
            version: row.get::<i64, _>(9) as u64,
            current: row.get(10),
            replaced_by: row
                .get::<Option<i64>, _>(11)
                .map(|i| DocumentId(i as u64)),
            acl: acl.0,
            metadata: metadata.0,
            ingested_at: row.get::<i64, _>(14) as u64,
            source_modified_at: row.get::<Option<i64>, _>(15).map(|t| t as u64),
        })
    }

    pub async fn find_document_by_external(
        &self,
        source_id: SourceId,
        external_id: &str,
    ) -> Option<DocumentId> {
        let id: Option<i64> = sqlx::query_scalar(
            "SELECT id FROM documents WHERE source_id = $1 AND external_id = $2 AND current = TRUE",
        )
        .bind(source_id.0 as i64)
        .bind(external_id)
        .fetch_optional(&self.pool)
        .await
        .ok()
        .flatten();
        id.map(|i| DocumentId(i as u64))
    }

    pub async fn delete_document(&self, id: DocumentId) -> StorageResult<()> {
        let mut tx = self.pool.begin().await.map_err(map_sqlx)?;
        // Drop edges that reference the document or its chunks. ON DELETE
        // CASCADE will not catch these because edges store NodeRefs as
        // (kind, id, uri) without FKs.
        sqlx::query(
            "DELETE FROM edges WHERE
               (from_kind = 'doc' AND from_id = $1) OR
               (to_kind   = 'doc' AND to_id   = $1) OR
               (from_kind = 'chunk' AND from_id IN (SELECT id FROM chunks WHERE document_id = $1)) OR
               (to_kind   = 'chunk' AND to_id   IN (SELECT id FROM chunks WHERE document_id = $1))",
        )
        .bind(id.0 as i64)
        .execute(&mut *tx)
        .await
        .map_err(map_sqlx)?;

        let res = sqlx::query("DELETE FROM documents WHERE id = $1")
            .bind(id.0 as i64)
            .execute(&mut *tx)
            .await
            .map_err(map_sqlx)?;
        if res.rows_affected() == 0 {
            return Err(StorageError::DocumentNotFound(id));
        }
        tx.commit().await.map_err(map_sqlx)?;
        Ok(())
    }

    // ---------- Chunks ----------

    pub async fn replace_chunks(
        &self,
        doc_id: DocumentId,
        chunks: Vec<NewChunk>,
    ) -> StorageResult<Vec<ChunkId>> {
        let mut tx = self.pool.begin().await.map_err(map_sqlx)?;
        let workspace_id: Option<i64> =
            sqlx::query_scalar("SELECT workspace_id FROM documents WHERE id = $1")
                .bind(doc_id.0 as i64)
                .fetch_optional(&mut *tx)
                .await
                .map_err(map_sqlx)?;
        let workspace_id = workspace_id.ok_or(StorageError::DocumentNotFound(doc_id))?;

        // Drop edges that reference any chunk of this document, then the chunks.
        // CTE so the (SELECT id FROM chunks WHERE document_id = $1) is
        // materialized once instead of twice.
        sqlx::query(
            "WITH cids AS (SELECT id FROM chunks WHERE document_id = $1)
             DELETE FROM edges
             WHERE (from_kind = 'chunk' AND from_id IN (SELECT id FROM cids))
                OR (to_kind   = 'chunk' AND to_id   IN (SELECT id FROM cids))",
        )
        .bind(doc_id.0 as i64)
        .execute(&mut *tx)
        .await
        .map_err(map_sqlx)?;
        sqlx::query("DELETE FROM chunks WHERE document_id = $1")
            .bind(doc_id.0 as i64)
            .execute(&mut *tx)
            .await
            .map_err(map_sqlx)?;

        if chunks.is_empty() {
            tx.commit().await.map_err(map_sqlx)?;
            return Ok(Vec::new());
        }

        // One INSERT for the whole batch via UNNEST. ORDER BY ord_tmp on the
        // input keeps `RETURNING id` aligned with input order — Postgres
        // assigns sequence values in scan order, so the ids come back in
        // ord_tmp order. We then ORDER BY ord_tmp on the result for safety.
        let n = chunks.len();
        let mut kinds: Vec<serde_json::Value> = Vec::with_capacity(n);
        let mut positions: Vec<serde_json::Value> = Vec::with_capacity(n);
        let mut texts: Vec<String> = Vec::with_capacity(n);
        let mut metas: Vec<serde_json::Value> = Vec::with_capacity(n);
        let mut embeddings: Vec<Option<Vector>> = Vec::with_capacity(n);
        for c in chunks {
            kinds.push(serde_json::to_value(&c.kind).map_err(|e| {
                StorageError::Invalid(format!("chunk kind json: {e}"))
            })?);
            positions.push(serde_json::to_value(&c.position).map_err(|e| {
                StorageError::Invalid(format!("chunk position json: {e}"))
            })?);
            texts.push(c.text);
            metas.push(serde_json::to_value(&c.metadata).map_err(|e| {
                StorageError::Invalid(format!("chunk metadata json: {e}"))
            })?);
            embeddings.push(c.embedding.map(Vector::from));
        }

        let rows: Vec<(i64, i32)> = sqlx::query_as(
            "INSERT INTO chunks (document_id, workspace_id, kind, position, text, metadata, embedding)
             SELECT $1, $2, t.kind, t.position, t.text, t.metadata, t.emb
             FROM UNNEST($3::jsonb[], $4::jsonb[], $5::text[], $6::jsonb[], $7::vector(768)[])
                  WITH ORDINALITY AS t(kind, position, text, metadata, emb, ord)
             ORDER BY t.ord
             RETURNING id, 0::int AS ord_dummy",
        )
        .bind(doc_id.0 as i64)
        .bind(workspace_id)
        .bind(&kinds)
        .bind(&positions)
        .bind(&texts)
        .bind(&metas)
        .bind(&embeddings)
        .fetch_all(&mut *tx)
        .await
        .map_err(map_sqlx)?;
        let new_ids: Vec<ChunkId> = rows.into_iter().map(|(id, _)| ChunkId(id as u64)).collect();

        tx.commit().await.map_err(map_sqlx)?;
        Ok(new_ids)
    }

    /// Batch-update embeddings for many chunks in a single statement.
    /// Use when re-embedding an existing corpus (model swap, dim change);
    /// for fresh ingest, prefer setting `NewChunk.embedding` so the vector
    /// is written inline with the chunk row.
    pub async fn put_embeddings_chunks(
        &self,
        pairs: Vec<(ChunkId, Vec<f32>)>,
    ) -> StorageResult<()> {
        if pairs.is_empty() {
            return Ok(());
        }
        let n = pairs.len();
        let mut ids: Vec<i64> = Vec::with_capacity(n);
        let mut vecs: Vec<Vector> = Vec::with_capacity(n);
        for (id, v) in pairs {
            ids.push(id.0 as i64);
            vecs.push(Vector::from(v));
        }
        sqlx::query(
            "UPDATE chunks AS c SET embedding = u.emb
             FROM UNNEST($1::bigint[], $2::vector(768)[]) AS u(id, emb)
             WHERE c.id = u.id",
        )
        .bind(&ids)
        .bind(&vecs)
        .execute(&self.pool)
        .await
        .map_err(map_sqlx)?;
        Ok(())
    }

    pub async fn get_chunk(&self, id: ChunkId) -> Option<Chunk> {
        let row = sqlx::query(
            "SELECT id, document_id, workspace_id, kind, position, text, embedding, metadata
             FROM chunks WHERE id = $1",
        )
        .bind(id.0 as i64)
        .fetch_optional(&self.pool)
        .await
        .ok()??;
        let kind: Json<ChunkKind> = row.get(3);
        let position: Json<ChunkPosition> = row.get(4);
        let metadata: Json<MetadataMap> = row.get(7);
        let embedding: Option<Vector> = row.get(6);
        let cid = ChunkId(row.get::<i64, _>(0) as u64);
        Some(Chunk {
            id: cid,
            document_id: DocumentId(row.get::<i64, _>(1) as u64),
            workspace_id: WorkspaceId(row.get::<i64, _>(2) as u64),
            kind: kind.0,
            position: position.0,
            text: row.get(5),
            embedding_id: embedding
                .as_ref()
                .map(|_| encode_embedding_id(EmbedOwner::Chunk, cid.0)),
            metadata: metadata.0,
        })
    }

    pub async fn chunks_in_document(&self, doc_id: DocumentId) -> Vec<ChunkId> {
        let ids: Vec<i64> = sqlx::query_scalar(
            "SELECT id FROM chunks WHERE document_id = $1 ORDER BY id",
        )
        .bind(doc_id.0 as i64)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();
        ids.into_iter().map(|i| ChunkId(i as u64)).collect()
    }

    /// Substring-match chunks by `position.qualified_name` within a workspace.
    /// Only `SymbolRange` chunks (code adapter output) participate — paragraph
    /// or page chunks have no symbol name to match against.
    ///
    /// Results are ordered by closeness:
    ///   0. Exact match (case-sensitive)
    ///   1. Exact match (case-insensitive)
    ///   2. Last-segment match (`%::<name>`) — `validate` matches `User::validate`
    ///   3. Other substring matches
    /// Ties break by shorter qualified_name first (more specific symbols), then
    /// by chunk id for stability.
    pub async fn search_symbols_by_name(
        &self,
        workspace_id: WorkspaceId,
        pattern: &str,
        limit: usize,
    ) -> Vec<ChunkId> {
        let pat_substr = format!("%{}%", pattern);
        let pat_suffix = format!("%::{}", pattern);
        let ids: Vec<i64> = sqlx::query_scalar(
            "SELECT id FROM chunks
             WHERE workspace_id = $1
               AND position->>'kind' = 'symbol_range'
               AND position->>'qualified_name' ILIKE $2
             ORDER BY
               CASE
                 WHEN position->>'qualified_name' = $3 THEN 0
                 WHEN lower(position->>'qualified_name') = lower($3) THEN 1
                 WHEN position->>'qualified_name' ILIKE $4 THEN 2
                 ELSE 3
               END,
               length(position->>'qualified_name'),
               id
             LIMIT $5",
        )
        .bind(workspace_id.0 as i64)
        .bind(pat_substr)
        .bind(pattern)
        .bind(pat_suffix)
        .bind(limit as i64)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();
        ids.into_iter().map(|i| ChunkId(i as u64)).collect()
    }

    pub async fn chunks_in_workspace(&self, ws: WorkspaceId, filter: &ChunkFilter) -> Vec<ChunkId> {
        // Filtering pushed entirely into SQL. JSONB containment uses the
        // GIN index `idx_chunks_metadata` for `language` and `tags` so we
        // don't sequential-scan the whole workspace.
        //
        // `kind` is a JSONB column with two shapes:
        //   - simple variants: `"paragraph"` (a JSON string)
        //   - tagged variant: `{"other": "..."}` (an object)
        // Containment (`@>`) handles both via `kinds_jsonb @> ARRAY[c.kind]`.
        let kinds_json: Option<Vec<serde_json::Value>> = filter
            .kinds
            .as_ref()
            .map(|ks| {
                ks.iter()
                    .filter_map(|k| serde_json::to_value(k).ok())
                    .collect()
            });
        let source_ids: Option<Vec<i64>> = filter
            .sources
            .as_ref()
            .map(|ss| ss.iter().map(|s| s.0 as i64).collect());
        let langs_json: Option<Vec<serde_json::Value>> = filter
            .languages
            .as_ref()
            .map(|ls| {
                ls.iter()
                    .filter_map(|l| serde_json::to_value(l).ok())
                    .collect()
            });
        let tags: Option<Vec<String>> = filter.tags.clone();
        let current_only = filter.current_only;

        let ids: Vec<i64> = sqlx::query_scalar(
            "SELECT c.id
             FROM chunks c JOIN documents d ON d.id = c.document_id
             WHERE c.workspace_id = $1
               AND ($2::boolean = FALSE OR d.current = TRUE)
               -- kind: any-of via array of JSONB candidates
               AND ($3::jsonb[] IS NULL OR c.kind = ANY($3::jsonb[]))
               -- source ids
               AND ($4::bigint[] IS NULL OR d.source_id = ANY($4::bigint[]))
               -- language: GIN-indexed JSONB containment, OR over candidates
               AND ($5::jsonb[] IS NULL OR EXISTS (
                     SELECT 1 FROM UNNEST($5::jsonb[]) AS l(lang)
                     WHERE c.metadata @> jsonb_build_object('language', l.lang)
               ))
               -- tags: any of the requested tags must appear in metadata.tags
               AND ($6::text[] IS NULL OR EXISTS (
                     SELECT 1 FROM UNNEST($6::text[]) AS t(tag)
                     WHERE c.metadata @> jsonb_build_object('tags', jsonb_build_array(t.tag))
               ))
             ORDER BY c.id",
        )
        .bind(ws.0 as i64)
        .bind(current_only)
        .bind(kinds_json.as_deref())
        .bind(source_ids.as_deref())
        .bind(langs_json.as_deref())
        .bind(tags.as_deref())
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();
        ids.into_iter().map(|i| ChunkId(i as u64)).collect()
    }

    /// Find commits (Documents with `external_id = "git+sha:<sha>"`) that
    /// touched a given file path or symbol qualified-name. Matches three
    /// patterns against `edges.to_uri`:
    ///
    ///   1. `git+path:<ws>:<target>` — exact file path (covers `ChangesFile`)
    ///   2. `git+symbol:<ws>:<target>:%` — any symbol declared in `<target>`
    ///      when the user passes a path (covers `ChangesSymbol` for any
    ///      symbol in that file)
    ///   3. `git+symbol:<ws>:%:<target>` — when the user passes a qualified
    ///      symbol name; matches that symbol regardless of file
    ///
    /// Returns commits ordered by committer time descending. Optional
    /// `since_ms` filters out commits older than that timestamp.
    ///
    /// Phase-1.5-aware: requires the git ingest to have run with the `git`
    /// feature (which now implies `code`) so that `ChangesSymbol` edges
    /// exist. Without symbol edges only pattern 1 produces hits.
    pub async fn git_history_for_target(
        &self,
        workspace_id: WorkspaceId,
        target: &str,
        since_ms: Option<u64>,
        limit: usize,
    ) -> Vec<CommitTouch> {
        let ws = workspace_id.0 as i64;
        let exact_path = format!("git+path:{}:{}", workspace_id.0, target);
        let symbol_in_path = format!("git+symbol:{}:{}:%", workspace_id.0, target);
        let symbol_by_qname = format!("git+symbol:{}:%:{}", workspace_id.0, target);
        let since = since_ms.map(|m| m as i64);

        // The CTE collapses many edges-per-commit (one ChangesFile + N
        // ChangesSymbol when the file/symbol both match) into one row per
        // commit. The match label tracks which pattern produced the
        // strongest hit so the response can show file vs. symbol provenance.
        let rows = sqlx::query(
            "WITH matched AS (
                SELECT
                    e.from_id AS doc_id,
                    bool_or(e.kind::text = '\"changes_symbol\"') AS hit_symbol,
                    bool_or(e.kind::text = '\"changes_file\"')   AS hit_file
                FROM edges e
                WHERE e.workspace_id = $1
                  AND e.from_kind    = 'doc'
                  AND e.from_id      IS NOT NULL
                  AND e.kind::text IN ('\"changes_file\"', '\"changes_symbol\"')
                  AND (
                       e.to_uri = $2
                    OR e.to_uri LIKE $3
                    OR e.to_uri LIKE $4
                  )
                GROUP BY e.from_id
             )
             SELECT d.id, d.external_id, d.title, d.metadata, d.source_modified_at,
                    m.hit_symbol, m.hit_file
             FROM matched m
             JOIN documents d ON d.id = m.doc_id
             WHERE d.workspace_id = $1
               AND d.current      = TRUE
               AND ($5::bigint IS NULL OR COALESCE(d.source_modified_at, 0) >= $5)
             ORDER BY COALESCE(d.source_modified_at, 0) DESC, d.id DESC
             LIMIT $6",
        )
        .bind(ws)
        .bind(exact_path)
        .bind(symbol_in_path)
        .bind(symbol_by_qname)
        .bind(since)
        .bind(limit as i64)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();

        rows.into_iter()
            .map(|row| {
                let doc_id = DocumentId(row.get::<i64, _>(0) as u64);
                let external_id: Option<String> = row.get(1);
                let summary: Option<String> = row.get(2);
                let metadata: Json<MetadataMap> = row.get(3);
                let modified: Option<i64> = row.get(4);
                let hit_symbol: bool = row.get(5);
                let hit_file: bool = row.get(6);
                let sha = external_id
                    .as_deref()
                    .and_then(|s| s.strip_prefix("git+sha:"))
                    .map(str::to_string)
                    .unwrap_or_default();
                let matched_kind = if hit_symbol && hit_file {
                    "symbol+file".to_string()
                } else if hit_symbol {
                    "symbol".to_string()
                } else {
                    "file".to_string()
                };
                CommitTouch {
                    document_id: doc_id,
                    sha,
                    summary: summary.unwrap_or_default(),
                    author: metadata.0.author.clone(),
                    time_ms: modified.unwrap_or(0).max(0) as u64,
                    matched_kind,
                }
            })
            .collect()
    }

    /// List `SymbolRange` chunks declared in `path`, ordered by line number.
    /// Skips paragraph / page chunks (markdown / pdf) — they have no symbol
    /// shape. When `include_head` is true, the first ~10 lines of each
    /// symbol's chunk text are returned in `head` (signature + adjacent doc
    /// comment for code adapters that span them).
    pub async fn list_symbols_in_file(
        &self,
        workspace_id: WorkspaceId,
        path: &str,
        include_head: bool,
        limit: usize,
    ) -> Vec<FileSymbol> {
        // Two queries are unwelcome but the alternative — pulling text in
        // every call — costs tokens proportional to the file size when most
        // callers just want the symbol map. Branch on the flag.
        let rows = sqlx::query(
            "SELECT c.id,
                    c.position->>'qualified_name' AS qname,
                    (c.position->>'line_start')::int AS line_start,
                    (c.position->>'line_end')::int   AS line_end,
                    CASE WHEN $3::boolean THEN c.text ELSE NULL END AS text
             FROM chunks c
             JOIN documents d ON d.id = c.document_id
             WHERE c.workspace_id = $1
               AND d.path_or_url  = $2
               AND d.current      = TRUE
               AND c.position->>'kind' = 'symbol_range'
             ORDER BY (c.position->>'line_start')::int, c.id
             LIMIT $4",
        )
        .bind(workspace_id.0 as i64)
        .bind(path)
        .bind(include_head)
        .bind(limit as i64)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();

        rows.into_iter()
            .map(|row| {
                let chunk_id = ChunkId(row.get::<i64, _>(0) as u64);
                let qualified_name: String = row.get::<Option<String>, _>(1).unwrap_or_default();
                let line_start = row.get::<Option<i32>, _>(2).unwrap_or(0).max(0) as u32;
                let line_end = row.get::<Option<i32>, _>(3).unwrap_or(0).max(0) as u32;
                let head = if include_head {
                    row.get::<Option<String>, _>(4).map(|t| {
                        // Trim to the first 10 lines — covers the signature
                        // and adjacent doc comments without dragging a long
                        // function body into the response.
                        t.lines().take(10).collect::<Vec<_>>().join("\n")
                    })
                } else {
                    None
                };
                FileSymbol {
                    chunk_id,
                    qualified_name,
                    line_start,
                    line_end,
                    head,
                }
            })
            .collect()
    }

    // ---------- Entities ----------

    pub async fn upsert_entity(&self, draft: NewEntity) -> StorageResult<EntityId> {
        let mut tx = self.pool.begin().await.map_err(map_sqlx)?;
        let ws_exists: Option<i64> =
            sqlx::query_scalar("SELECT id FROM workspaces WHERE id = $1")
                .bind(draft.workspace_id.0 as i64)
                .fetch_optional(&mut *tx)
                .await
                .map_err(map_sqlx)?;
        if ws_exists.is_none() {
            return Err(StorageError::WorkspaceNotFound(draft.workspace_id));
        }

        let kind_text = serde_json::to_string(&draft.kind)
            .map_err(|e| StorageError::Invalid(format!("kind json: {e}")))?;
        let existing: Option<(i64, Vec<String>)> = sqlx::query_as(
            "SELECT id, aliases FROM entities
             WHERE workspace_id = $1 AND kind::text = $2 AND canonical_name = $3",
        )
        .bind(draft.workspace_id.0 as i64)
        .bind(&kind_text)
        .bind(&draft.canonical_name)
        .fetch_optional(&mut *tx)
        .await
        .map_err(map_sqlx)?;

        let id = if let Some((id, mut aliases)) = existing {
            for a in &draft.aliases {
                if !aliases.iter().any(|x| x == a) {
                    aliases.push(a.clone());
                }
            }
            sqlx::query("UPDATE entities SET aliases = $1, metadata = $2 WHERE id = $3")
                .bind(&aliases)
                .bind(Json(&draft.metadata))
                .bind(id)
                .execute(&mut *tx)
                .await
                .map_err(map_sqlx)?;
            EntityId(id as u64)
        } else {
            let id: i64 = sqlx::query_scalar(
                "INSERT INTO entities (workspace_id, kind, canonical_name, aliases, metadata)
                 VALUES ($1, $2, $3, $4, $5) RETURNING id",
            )
            .bind(draft.workspace_id.0 as i64)
            .bind(Json(&draft.kind))
            .bind(&draft.canonical_name)
            .bind(&draft.aliases)
            .bind(Json(&draft.metadata))
            .fetch_one(&mut *tx)
            .await
            .map_err(map_sqlx)?;
            EntityId(id as u64)
        };
        tx.commit().await.map_err(map_sqlx)?;
        Ok(id)
    }

    pub async fn get_entity(&self, id: EntityId) -> Option<Entity> {
        let row = sqlx::query(
            "SELECT id, workspace_id, kind, canonical_name, aliases, embedding, metadata
             FROM entities WHERE id = $1",
        )
        .bind(id.0 as i64)
        .fetch_optional(&self.pool)
        .await
        .ok()??;
        let kind: Json<EntityKind> = row.get(2);
        let aliases: Vec<String> = row.get(4);
        let embedding: Option<Vector> = row.get(5);
        let metadata: Json<MetadataMap> = row.get(6);
        let eid = EntityId(row.get::<i64, _>(0) as u64);
        Some(Entity {
            id: eid,
            workspace_id: WorkspaceId(row.get::<i64, _>(1) as u64),
            kind: kind.0,
            canonical_name: row.get(3),
            aliases,
            embedding_id: embedding
                .as_ref()
                .map(|_| encode_embedding_id(EmbedOwner::Entity, eid.0)),
            metadata: metadata.0,
        })
    }

    pub async fn find_entity_by_canonical(
        &self,
        ws: WorkspaceId,
        kind: &EntityKind,
        canonical_name: &str,
    ) -> Option<EntityId> {
        let kind_text = serde_json::to_string(kind).ok()?;
        let id: Option<i64> = sqlx::query_scalar(
            "SELECT id FROM entities
             WHERE workspace_id = $1 AND kind::text = $2 AND canonical_name = $3",
        )
        .bind(ws.0 as i64)
        .bind(&kind_text)
        .bind(canonical_name)
        .fetch_optional(&self.pool)
        .await
        .ok()
        .flatten();
        id.map(|i| EntityId(i as u64))
    }

    // ---------- Edges ----------

    pub async fn add_edge(&self, draft: NewEdge) -> StorageResult<EdgeId> {
        let ids = self.add_edges(vec![draft]).await?;
        ids.into_iter().next().ok_or_else(|| {
            StorageError::Invalid("add_edges returned no ids for single draft".into())
        })
    }

    /// Atomic batch upsert. One statement, one round-trip, race-free
    /// (uses the `uniq_edges_endpoints` partial index as the conflict
    /// target). On conflict: weight becomes `GREATEST(existing, new)` and
    /// metadata is replaced with the new draft's metadata. Returns the ids
    /// of the affected rows (input-order is best-effort but not guaranteed).
    pub async fn add_edges(&self, drafts: Vec<NewEdge>) -> StorageResult<Vec<EdgeId>> {
        if drafts.is_empty() {
            return Ok(Vec::new());
        }
        // Dedupe within the batch. Postgres errors with "ON CONFLICT DO
        // UPDATE command cannot affect row a second time" when two input
        // rows collide on the same conflict key, so we collapse first.
        // Last write wins for metadata; weight is folded as max.
        type Key = (i64, &'static str, Option<i64>, Option<String>, &'static str, Option<i64>, Option<String>, String);
        let mut by_key: ahash::AHashMap<Key, NewEdge> = ahash::AHashMap::new();
        for d in drafts {
            let (fk, fid, furi) = pg_ref(&d.from);
            let (tk, tid, turi) = pg_ref(&d.to);
            let kind_text = serde_json::to_string(&d.kind)
                .map_err(|e| StorageError::Invalid(format!("edge kind json: {e}")))?;
            let key: Key = (
                d.workspace_id.0 as i64,
                fk,
                fid,
                furi.map(str::to_string),
                tk,
                tid,
                turi.map(str::to_string),
                kind_text,
            );
            by_key
                .entry(key)
                .and_modify(|existing| {
                    if d.weight > existing.weight {
                        existing.weight = d.weight;
                    }
                    existing.metadata = d.metadata.clone();
                })
                .or_insert(d);
        }

        let n = by_key.len();
        let mut wids: Vec<i64> = Vec::with_capacity(n);
        let mut fks: Vec<&str> = Vec::with_capacity(n);
        let mut fids: Vec<Option<i64>> = Vec::with_capacity(n);
        let mut furis: Vec<Option<String>> = Vec::with_capacity(n);
        let mut tks: Vec<&str> = Vec::with_capacity(n);
        let mut tids: Vec<Option<i64>> = Vec::with_capacity(n);
        let mut turis: Vec<Option<String>> = Vec::with_capacity(n);
        let mut kinds: Vec<serde_json::Value> = Vec::with_capacity(n);
        let mut weights: Vec<f32> = Vec::with_capacity(n);
        let mut metas: Vec<serde_json::Value> = Vec::with_capacity(n);
        let mut creators: Vec<String> = Vec::with_capacity(n);
        for (_k, d) in by_key {
            let (fk, fid, furi) = pg_ref(&d.from);
            let (tk, tid, turi) = pg_ref(&d.to);
            wids.push(d.workspace_id.0 as i64);
            fks.push(fk);
            fids.push(fid);
            furis.push(furi.map(str::to_string));
            tks.push(tk);
            tids.push(tid);
            turis.push(turi.map(str::to_string));
            kinds.push(serde_json::to_value(&d.kind).map_err(|e| {
                StorageError::Invalid(format!("edge kind json: {e}"))
            })?);
            weights.push(d.weight);
            metas.push(serde_json::to_value(&d.metadata).map_err(|e| {
                StorageError::Invalid(format!("edge metadata json: {e}"))
            })?);
            creators.push(
                serde_json::to_value(d.created_by)
                    .ok()
                    .and_then(|v| v.as_str().map(|s| s.to_string()))
                    .unwrap_or_else(|| "user".to_string()),
            );
        }

        let now = now_millis() as i64;
        let ids: Vec<i64> = sqlx::query_scalar(
            "INSERT INTO edges
                (workspace_id, from_kind, from_id, from_uri, to_kind, to_id, to_uri,
                 kind, weight, metadata, created_by, created_at)
             SELECT
                w, fk, fi, fu, tk, ti, tu, k, wt, md, cb, $12
             FROM UNNEST(
                 $1::bigint[],  $2::text[],   $3::bigint[], $4::text[],
                 $5::text[],    $6::bigint[], $7::text[],
                 $8::jsonb[],   $9::real[],   $10::jsonb[], $11::text[]
             ) AS t(w, fk, fi, fu, tk, ti, tu, k, wt, md, cb)
             ON CONFLICT (workspace_id, from_kind, COALESCE(from_id, -1), COALESCE(from_uri, ''),
                          to_kind, COALESCE(to_id, -1), COALESCE(to_uri, ''), (kind::text))
             DO UPDATE SET
                 weight = GREATEST(edges.weight, EXCLUDED.weight),
                 metadata = EXCLUDED.metadata
             RETURNING id",
        )
        .bind(&wids)
        .bind(&fks)
        .bind(&fids)
        .bind(&furis)
        .bind(&tks)
        .bind(&tids)
        .bind(&turis)
        .bind(&kinds)
        .bind(&weights)
        .bind(&metas)
        .bind(&creators)
        .bind(now)
        .fetch_all(&self.pool)
        .await
        .map_err(map_sqlx)?;
        Ok(ids.into_iter().map(|i| EdgeId(i as u64)).collect())
    }

    pub async fn get_edge(&self, id: EdgeId) -> Option<Edge> {
        let row = sqlx::query(
            "SELECT id, workspace_id, from_kind, from_id, from_uri, to_kind, to_id, to_uri,
                    kind, weight, metadata, created_by, created_at
             FROM edges WHERE id = $1",
        )
        .bind(id.0 as i64)
        .fetch_optional(&self.pool)
        .await
        .ok()??;
        let from = from_pg_ref(row.get(2), row.get::<Option<i64>, _>(3), row.get(4))?;
        let to = from_pg_ref(row.get(5), row.get::<Option<i64>, _>(6), row.get(7))?;
        let kind: Json<EdgeKind> = row.get(8);
        let metadata: Json<MetadataMap> = row.get(10);
        let created_by_str: String = row.get(11);
        let created_by: EdgeOrigin =
            serde_json::from_value(serde_json::Value::String(created_by_str))
                .unwrap_or(EdgeOrigin::User);
        Some(Edge {
            id: EdgeId(row.get::<i64, _>(0) as u64),
            workspace_id: WorkspaceId(row.get::<i64, _>(1) as u64),
            from,
            to,
            kind: kind.0,
            weight: row.get(9),
            metadata: metadata.0,
            created_by,
            created_at: row.get::<i64, _>(12) as u64,
        })
    }

    pub async fn edges_from(&self, node: &NodeRef, kind: Option<&EdgeKind>) -> Vec<Edge> {
        let (k, id, uri) = pg_ref(node);
        let kind_text = kind.and_then(|kk| serde_json::to_string(kk).ok());
        let rows = sqlx::query(
            "SELECT id, workspace_id, from_kind, from_id, from_uri, to_kind, to_id, to_uri,
                    kind, weight, metadata, created_by, created_at
             FROM edges
             WHERE from_kind = $1
               AND COALESCE(from_id, -1) = COALESCE($2, -1)
               AND COALESCE(from_uri, '') = COALESCE($3, '')
               AND ($4::text IS NULL OR kind::text = $4)",
        )
        .bind(k)
        .bind(id)
        .bind(uri)
        .bind(kind_text)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();
        rows.into_iter().filter_map(|row| edge_from_row(&row)).collect()
    }

    pub async fn edges_to(&self, node: &NodeRef, kind: Option<&EdgeKind>) -> Vec<Edge> {
        let (k, id, uri) = pg_ref(node);
        let kind_text = kind.and_then(|kk| serde_json::to_string(kk).ok());
        let rows = sqlx::query(
            "SELECT id, workspace_id, from_kind, from_id, from_uri, to_kind, to_id, to_uri,
                    kind, weight, metadata, created_by, created_at
             FROM edges
             WHERE to_kind = $1
               AND COALESCE(to_id, -1) = COALESCE($2, -1)
               AND COALESCE(to_uri, '') = COALESCE($3, '')
               AND ($4::text IS NULL OR kind::text = $4)",
        )
        .bind(k)
        .bind(id)
        .bind(uri)
        .bind(kind_text)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();
        rows.into_iter().filter_map(|row| edge_from_row(&row)).collect()
    }

    // ---------- Embeddings ----------

    pub async fn put_embedding(
        &self,
        key: EmbedKey,
        vector: Vec<f32>,
    ) -> StorageResult<EmbeddingId> {
        let table = embed_target_table(key.owner);
        let sql = format!("UPDATE {table} SET embedding = $1 WHERE id = $2");
        let res = sqlx::query(&sql)
            .bind(Vector::from(vector))
            .bind(key.id as i64)
            .execute(&self.pool)
            .await
            .map_err(map_sqlx)?;
        if res.rows_affected() == 0 {
            return Err(StorageError::Invalid(format!(
                "embedding owner not found: {:?}/{}",
                key.owner, key.id
            )));
        }
        Ok(encode_embedding_id(key.owner, key.id))
    }

    pub async fn get_embedding(&self, id: EmbeddingId) -> Option<Vec<f32>> {
        let (owner, row_id) = decode_embedding_id(id)?;
        let table = embed_target_table(owner);
        let sql = format!("SELECT embedding FROM {table} WHERE id = $1");
        let v: Option<Vector> = sqlx::query_scalar(&sql)
            .bind(row_id as i64)
            .fetch_optional(&self.pool)
            .await
            .ok()
            .flatten();
        v.map(|vec| vec.to_vec())
    }

    pub async fn get_embedding_by_owner(&self, key: EmbedKey) -> Option<Vec<f32>> {
        let table = embed_target_table(key.owner);
        let sql = format!("SELECT embedding FROM {table} WHERE id = $1");
        let v: Option<Vector> = sqlx::query_scalar(&sql)
            .bind(key.id as i64)
            .fetch_optional(&self.pool)
            .await
            .ok()
            .flatten();
        v.map(|vec| vec.to_vec())
    }

    pub async fn list_chunk_embeddings(
        &self,
        ws: WorkspaceId,
        current_only: bool,
    ) -> Vec<(ChunkId, Vec<f32>)> {
        let sql = if current_only {
            "SELECT c.id, c.embedding FROM chunks c
             JOIN documents d ON d.id = c.document_id
             WHERE c.workspace_id = $1 AND c.embedding IS NOT NULL AND d.current = TRUE"
        } else {
            "SELECT id, embedding FROM chunks
             WHERE workspace_id = $1 AND embedding IS NOT NULL"
        };
        let rows = sqlx::query(sql)
            .bind(ws.0 as i64)
            .fetch_all(&self.pool)
            .await
            .unwrap_or_default();
        rows.into_iter()
            .filter_map(|row| {
                let cid = ChunkId(row.get::<i64, _>(0) as u64);
                let v: Option<Vector> = row.get(1);
                v.map(|vec| (cid, vec.to_vec()))
            })
            .collect()
    }

    /// pgvector ANN search — returns the top-K chunks closest to `query` by
    /// cosine distance, paired with their cosine *similarity* (1 − distance).
    /// Uses the HNSW index on `chunks.embedding` when present.
    ///
    /// `hnsw.ef_search` is set per-query to `max(top_k * 2, 100)`. The default
    /// (40) caps recall at the wrong place when `top_k > 40` — pgvector docs
    /// recommend `ef_search >= top_k`. We use a fresh transaction so the
    /// `SET LOCAL` is scoped to this query and doesn't leak to other pool
    /// users.
    pub async fn semantic_search_chunks(
        &self,
        ws: WorkspaceId,
        query: &[f32],
        top_k: u32,
        current_only: bool,
    ) -> Vec<(ChunkId, f32)> {
        let q = Vector::from(query.to_vec());
        let ef_search = (top_k.saturating_mul(2)).max(100) as i64;
        let mut tx = match self.pool.begin().await {
            Ok(t) => t,
            Err(_) => return Vec::new(),
        };
        if sqlx::query(&format!("SET LOCAL hnsw.ef_search = {ef_search}"))
            .execute(&mut *tx)
            .await
            .is_err()
        {
            return Vec::new();
        }
        let sql = if current_only {
            "SELECT c.id, 1 - (c.embedding <=> $1) AS sim
             FROM chunks c JOIN documents d ON d.id = c.document_id
             WHERE c.workspace_id = $2 AND c.embedding IS NOT NULL AND d.current = TRUE
             ORDER BY c.embedding <=> $1
             LIMIT $3"
        } else {
            "SELECT id, 1 - (embedding <=> $1) AS sim
             FROM chunks
             WHERE workspace_id = $2 AND embedding IS NOT NULL
             ORDER BY embedding <=> $1
             LIMIT $3"
        };
        let rows = sqlx::query(sql)
            .bind(&q)
            .bind(ws.0 as i64)
            .bind(top_k as i64)
            .fetch_all(&mut *tx)
            .await
            .unwrap_or_default();
        let _ = tx.commit().await;
        rows.into_iter()
            .map(|row| {
                let cid = ChunkId(row.get::<i64, _>(0) as u64);
                let sim: f64 = row.get(1);
                (cid, sim as f32)
            })
            .collect()
    }

    /// All session-level score snapshots for a single session (most recent
    /// snapshot per target, since `snapshot_session_scores` replaces older
    /// snapshots).
    pub async fn session_scores_in_session(&self, session_id: SessionId) -> Vec<SessionScore> {
        self.session_scores_for_sessions(&[session_id]).await
    }

    /// Batched variant — fetches `session_scores` for many sessions in one
    /// query. Used by the predictive ranker to avoid N+1 round-trips when
    /// scoring against multiple past sessions.
    pub async fn session_scores_for_sessions(
        &self,
        session_ids: &[SessionId],
    ) -> Vec<SessionScore> {
        if session_ids.is_empty() {
            return Vec::new();
        }
        let ids: Vec<i64> = session_ids.iter().map(|s| s.0 as i64).collect();
        let rows = sqlx::query(
            "SELECT session_id, target_kind, target_id, target_uri, score, access_count,
                    productivity, pattern, was_edited, created_at
             FROM session_scores WHERE session_id = ANY($1)",
        )
        .bind(&ids)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();
        rows.into_iter()
            .filter_map(|row| {
                let target = from_pg_ref(row.get(1), row.get::<Option<i64>, _>(2), row.get(3))?;
                let pattern = pattern_from_str(row.get::<&str, _>(7))?;
                Some(SessionScore {
                    session_id: SessionId(row.get::<i64, _>(0) as u64),
                    target,
                    score: row.get(4),
                    access_count: row.get::<i32, _>(5) as u32,
                    productivity: row.get(6),
                    pattern,
                    was_edited: row.get(8),
                    created_at: row.get::<i64, _>(9) as u64,
                })
            })
            .collect()
    }

    /// Aggregated per-session retrieval for the predictive ranker. Pushes
    /// the cosine computation + per-session max into Postgres so we don't
    /// drag every recent context's 768-dim embedding back to the app
    /// process. Returns `(session_id, max_similarity, last_context_at)`
    /// for sessions whose best context similarity clears `min_similarity`,
    /// ordered by similarity descending and capped at `top_n_sessions`.
    ///
    /// The pre-filter (`workspace_id`, `created_at >= since`, `embedding IS
    /// NOT NULL`) is served by `idx_session_contexts_ws_time_embedded`
    /// (migration 0003); the cosine is computed on the filtered subset.
    pub async fn recent_session_max_sims(
        &self,
        ws: WorkspaceId,
        query_embedding: &[f32],
        since: Timestamp,
        exclude_session: Option<SessionId>,
        min_similarity: f32,
        top_n_sessions: u32,
    ) -> Vec<(SessionId, f32, Timestamp)> {
        let q = Vector::from(query_embedding.to_vec());
        let rows = sqlx::query(
            "SELECT session_id,
                    MAX(1 - (embedding <=> $1)) AS max_sim,
                    MAX(created_at) AS last_ts
             FROM session_contexts
             WHERE workspace_id = $2
               AND created_at >= $3
               AND embedding IS NOT NULL
               AND ($4::bigint IS NULL OR session_id <> $4)
             GROUP BY session_id
             HAVING MAX(1 - (embedding <=> $1)) >= $5
             ORDER BY max_sim DESC
             LIMIT $6",
        )
        .bind(&q)
        .bind(ws.0 as i64)
        .bind(since as i64)
        .bind(exclude_session.map(|s| s.0 as i64))
        .bind(min_similarity as f64)
        .bind(top_n_sessions as i64)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();
        rows.into_iter()
            .map(|row| {
                let sid = SessionId(row.get::<i64, _>(0) as u64);
                let sim: f64 = row.get(1);
                let ts: i64 = row.get(2);
                (sid, sim as f32, ts as u64)
            })
            .collect()
    }

    /// Legacy variant retained for callers that need the raw embeddings
    /// (e.g. offline analysis tools). The hot path uses
    /// `recent_session_max_sims`. Avoid in the ranker — pulls a 768-dim
    /// vector per row over the wire.
    pub async fn list_recent_context_embeddings(
        &self,
        ws: WorkspaceId,
        since: Timestamp,
        exclude_session: Option<SessionId>,
    ) -> Vec<(SessionContext, Vec<f32>)> {
        let rows = sqlx::query(
            "SELECT id, session_id, kind, content, iteration, embedding, created_at
             FROM session_contexts
             WHERE workspace_id = $1 AND created_at >= $2 AND embedding IS NOT NULL
               AND ($3::bigint IS NULL OR session_id <> $3)",
        )
        .bind(ws.0 as i64)
        .bind(since as i64)
        .bind(exclude_session.map(|s| s.0 as i64))
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();
        rows.into_iter()
            .filter_map(|row| {
                let kind = context_kind_from_str(row.get::<&str, _>(2))?;
                let v: Option<Vector> = row.get(5);
                let vec = v?.to_vec();
                let cid = ContextId(row.get::<i64, _>(0) as u64);
                let ctx = SessionContext {
                    id: cid,
                    session_id: SessionId(row.get::<i64, _>(1) as u64),
                    kind,
                    content: row.get(3),
                    iteration: row.get::<i32, _>(4) as u32,
                    embedding_id: Some(encode_embedding_id(EmbedOwner::SessionContext, cid.0)),
                    created_at: row.get::<i64, _>(6) as u64,
                };
                Some((ctx, vec))
            })
            .collect()
    }

    // ---------- Sessions ----------

    pub async fn create_session(
        &self,
        ws: WorkspaceId,
        agent_id: Option<&str>,
    ) -> StorageResult<SessionId> {
        let id: i64 = sqlx::query_scalar(
            "INSERT INTO sessions (workspace_id, agent_id, created_at)
             VALUES ($1, $2, $3) RETURNING id",
        )
        .bind(ws.0 as i64)
        .bind(agent_id)
        .bind(now_millis() as i64)
        .fetch_one(&self.pool)
        .await
        .map_err(map_sqlx)?;
        Ok(SessionId(id as u64))
    }

    pub async fn get_session(&self, id: SessionId) -> Option<Session> {
        let row = sqlx::query(
            "SELECT id, workspace_id, agent_id, kind, created_at, ended_at
             FROM sessions WHERE id = $1",
        )
        .bind(id.0 as i64)
        .fetch_optional(&self.pool)
        .await
        .ok()??;
        let kind = match row.get::<&str, _>(3) {
            "synthetic" => SessionKind::Synthetic,
            _ => SessionKind::Real,
        };
        Some(Session {
            id: SessionId(row.get::<i64, _>(0) as u64),
            workspace_id: WorkspaceId(row.get::<i64, _>(1) as u64),
            agent_id: row.get(2),
            kind,
            created_at: row.get::<i64, _>(4) as u64,
            ended_at: row.get::<Option<i64>, _>(5).map(|t| t as u64),
        })
    }

    pub async fn end_session(&self, id: SessionId) -> StorageResult<()> {
        let res = sqlx::query("UPDATE sessions SET ended_at = $1 WHERE id = $2 AND ended_at IS NULL")
            .bind(now_millis() as i64)
            .bind(id.0 as i64)
            .execute(&self.pool)
            .await
            .map_err(map_sqlx)?;
        if res.rows_affected() == 0 {
            // Confirm whether the session exists at all.
            let exists: Option<i64> =
                sqlx::query_scalar("SELECT id FROM sessions WHERE id = $1")
                    .bind(id.0 as i64)
                    .fetch_optional(&self.pool)
                    .await
                    .map_err(map_sqlx)?;
            if exists.is_none() {
                return Err(StorageError::SessionNotFound(id));
            }
        }
        // Best-effort: infer co-access edges from this session's interaction
        // history. Errors here don't fail the close — the row is already
        // marked `ended_at`, so the session is closed regardless.
        if let Err(err) = self.persist_coaccessed_edges(id).await {
            tracing::warn!(session_id = id.0, error = %err, "co-access inference failed");
        }
        Ok(())
    }

    /// Infer `EdgeKind::CoAccessed` edges from this session's interaction
    /// history and persist via `add_edges`. Idempotent through the existing
    /// ON CONFLICT path on `add_edges`. See `EdgeKind::CoAccessed` for the
    /// semantics; this is the producer.
    async fn persist_coaccessed_edges(&self, session_id: SessionId) -> StorageResult<()> {
        let edges = self.infer_coaccessed_edges(session_id).await?;
        if edges.is_empty() {
            return Ok(());
        }
        let _ = self.add_edges(edges).await?;
        Ok(())
    }

    /// Build `NewEdge` rows for every unordered pair of distinct
    /// productively co-accessed targets in this session. Productive =
    /// `Pattern` ∈ {`Cited`, `ReadEdit`, `EditOnly`} (productivity > 1.0).
    /// Caps the working set at 20 highest-productivity targets per session
    /// to keep `O(n²)` from blowing up on long-running sessions.
    pub(crate) async fn infer_coaccessed_edges(
        &self,
        session_id: SessionId,
    ) -> StorageResult<Vec<NewEdge>> {
        let workspace_id: Option<i64> =
            sqlx::query_scalar("SELECT workspace_id FROM sessions WHERE id = $1")
                .bind(session_id.0 as i64)
                .fetch_optional(&self.pool)
                .await
                .map_err(map_sqlx)?;
        let Some(ws) = workspace_id else {
            return Err(StorageError::SessionNotFound(session_id));
        };
        let workspace_id = WorkspaceId(ws as u64);

        // Aggregate per-target event counts. `event_type` already covers the
        // 5-verb vocabulary; we collapse counts and classify into `Pattern`
        // in code.
        let rows = sqlx::query(
            "SELECT target_kind, target_id, target_uri, event_type, COUNT(*) AS n
             FROM session_interactions
             WHERE session_id = $1
             GROUP BY target_kind, target_id, target_uri, event_type",
        )
        .bind(session_id.0 as i64)
        .fetch_all(&self.pool)
        .await
        .map_err(map_sqlx)?;

        // (target_key) → counts by event type
        type TargetKey = (String, Option<i64>, Option<String>);
        let mut counts: std::collections::HashMap<TargetKey, [u32; 5]> =
            std::collections::HashMap::new();
        for row in rows {
            let kind: String = row.get(0);
            let id: Option<i64> = row.get(1);
            let uri: Option<String> = row.get(2);
            let event: String = row.get(3);
            let n: i64 = row.get(4);
            let Some(ev) = event_type_from_str(&event) else {
                continue;
            };
            let idx = match ev {
                EventType::Retrieved => 0,
                EventType::Read => 1,
                EventType::Edited => 2,
                EventType::Cited => 3,
                EventType::Dismissed => 4,
            };
            counts.entry((kind, id, uri)).or_default()[idx] += n as u32;
        }

        // Classify each target into a Pattern. Order of checks matters:
        // a Cited target trumps Edited, which trumps Read.
        let mut productive: Vec<(NodeRef, Pattern, f32)> = Vec::new();
        for ((kind, id, uri), c) in counts {
            let Some(node) = from_pg_ref(&kind, id, uri) else {
                continue;
            };
            let cited = c[3] > 0;
            let edited = c[2] > 0;
            let read = c[1] > 0;
            let dismissed = c[4] > 0;
            let pattern = if dismissed {
                Pattern::Dismissed
            } else if cited {
                Pattern::Cited
            } else if edited && read {
                Pattern::ReadEdit
            } else if edited {
                Pattern::EditOnly
            } else if read && c[1] > 1 {
                Pattern::ReadRepeated
            } else {
                Pattern::Neutral
            };
            let productivity = pattern.multiplier();
            if productivity > 1.0 {
                productive.push((node, pattern, productivity));
            }
        }

        if productive.len() < 2 {
            return Ok(Vec::new());
        }

        // Cap to top-20 by productivity. Keeps `O(n^2)` bounded at 380
        // unordered pairs (× 2 for symmetric direction = 760 edges max).
        productive.sort_by(|a, b| b.2.partial_cmp(&a.2).unwrap_or(std::cmp::Ordering::Equal));
        productive.truncate(20);

        let session_id_v = serde_json::json!(session_id.0);
        let mut edges: Vec<NewEdge> = Vec::with_capacity(productive.len() * (productive.len() - 1));
        for i in 0..productive.len() {
            for j in 0..productive.len() {
                if i == j {
                    continue;
                }
                let (a, pa, prod_a) = &productive[i];
                let (b, pb, prod_b) = &productive[j];
                let weight = prod_a.min(*prod_b);
                let mut metadata = MetadataMap::default();
                metadata.extra = serde_json::json!({
                    "session_id": session_id_v,
                    "pattern_a": pattern_str(*pa),
                    "pattern_b": pattern_str(*pb),
                    "rationale": format!(
                        "co-accessed in session {}: {} + {}",
                        session_id.0,
                        pattern_str(*pa),
                        pattern_str(*pb)
                    ),
                });
                edges.push(NewEdge {
                    workspace_id,
                    from: a.clone(),
                    to: b.clone(),
                    kind: EdgeKind::CoAccessed,
                    weight,
                    metadata,
                    created_by: EdgeOrigin::Background,
                });
            }
        }
        Ok(edges)
    }

    // ---------- Session contexts ----------

    pub async fn append_context(&self, draft: NewContext) -> StorageResult<ContextId> {
        let workspace_id: Option<i64> =
            sqlx::query_scalar("SELECT workspace_id FROM sessions WHERE id = $1")
                .bind(draft.session_id.0 as i64)
                .fetch_optional(&self.pool)
                .await
                .map_err(map_sqlx)?;
        let workspace_id = workspace_id.ok_or(StorageError::SessionNotFound(draft.session_id))?;
        let id: i64 = sqlx::query_scalar(
            "INSERT INTO session_contexts (session_id, workspace_id, kind, content, iteration, created_at)
             VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
        )
        .bind(draft.session_id.0 as i64)
        .bind(workspace_id)
        .bind(context_kind_str(draft.kind))
        .bind(&draft.content)
        .bind(draft.iteration as i32)
        .bind(now_millis() as i64)
        .fetch_one(&self.pool)
        .await
        .map_err(map_sqlx)?;
        Ok(ContextId(id as u64))
    }

    pub async fn get_context(&self, id: ContextId) -> Option<SessionContext> {
        let row = sqlx::query(
            "SELECT id, session_id, kind, content, iteration, embedding, created_at
             FROM session_contexts WHERE id = $1",
        )
        .bind(id.0 as i64)
        .fetch_optional(&self.pool)
        .await
        .ok()??;
        let kind = context_kind_from_str(row.get::<&str, _>(2))?;
        let embedding: Option<Vector> = row.get(5);
        let cid = ContextId(row.get::<i64, _>(0) as u64);
        Some(SessionContext {
            id: cid,
            session_id: SessionId(row.get::<i64, _>(1) as u64),
            kind,
            content: row.get(3),
            iteration: row.get::<i32, _>(4) as u32,
            embedding_id: embedding
                .as_ref()
                .map(|_| encode_embedding_id(EmbedOwner::SessionContext, cid.0)),
            created_at: row.get::<i64, _>(6) as u64,
        })
    }

    pub async fn contexts_in_session(&self, session_id: SessionId) -> Vec<SessionContext> {
        let rows = sqlx::query(
            "SELECT id, session_id, kind, content, iteration, embedding, created_at
             FROM session_contexts WHERE session_id = $1 ORDER BY id",
        )
        .bind(session_id.0 as i64)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();
        rows.into_iter()
            .filter_map(|row| {
                let kind = context_kind_from_str(row.get::<&str, _>(2))?;
                let embedding: Option<Vector> = row.get(5);
                let cid = ContextId(row.get::<i64, _>(0) as u64);
                Some(SessionContext {
                    id: cid,
                    session_id: SessionId(row.get::<i64, _>(1) as u64),
                    kind,
                    content: row.get(3),
                    iteration: row.get::<i32, _>(4) as u32,
                    embedding_id: embedding
                        .as_ref()
                        .map(|_| encode_embedding_id(EmbedOwner::SessionContext, cid.0)),
                    created_at: row.get::<i64, _>(6) as u64,
                })
            })
            .collect()
    }

    // ---------- Session interactions ----------

    pub async fn append_interaction(
        &self,
        draft: NewInteraction,
    ) -> StorageResult<InteractionId> {
        let (tk, tid, turi) = pg_ref(&draft.target);
        let id: i64 = sqlx::query_scalar(
            "INSERT INTO session_interactions
               (session_id, context_id, iteration, event_type, target_kind, target_id, target_uri,
                weight, was_useful, tool_name, created_at)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NULL, $9, $10) RETURNING id",
        )
        .bind(draft.session_id.0 as i64)
        .bind(draft.context_id.map(|c| c.0 as i64))
        .bind(draft.iteration as i32)
        .bind(event_type_str(draft.event_type))
        .bind(tk)
        .bind(tid)
        .bind(turi)
        .bind(draft.weight)
        .bind(draft.tool_name.as_deref())
        .bind(now_millis() as i64)
        .fetch_one(&self.pool)
        .await
        .map_err(map_sqlx)?;
        Ok(InteractionId(id as u64))
    }

    /// Slim projection for the reactive ranker: only the four fields it
    /// actually uses, optionally windowed by iteration. The reactive channel
    /// applies an exponential decay with `λ=0.15`, so events more than ~30
    /// iterations old contribute < 1% of weight; ignoring them is free.
    /// Pass `min_iteration = 0` to disable the window.
    pub async fn interactions_for_reactive(
        &self,
        session_id: SessionId,
        min_iteration: u32,
    ) -> Vec<crate::rank::reactive::ReactiveEvent> {
        let rows = sqlx::query(
            "SELECT iteration, event_type, target_kind, target_id, target_uri, weight
             FROM session_interactions
             WHERE session_id = $1 AND iteration >= $2
             ORDER BY id",
        )
        .bind(session_id.0 as i64)
        .bind(min_iteration as i32)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();
        rows.into_iter()
            .filter_map(|row| {
                let target = from_pg_ref(row.get(2), row.get::<Option<i64>, _>(3), row.get(4))?;
                let event_type = event_type_from_str(row.get::<&str, _>(1))?;
                Some(crate::rank::reactive::ReactiveEvent {
                    target,
                    event_type,
                    weight: row.get(5),
                    iteration: row.get::<i32, _>(0) as u32,
                })
            })
            .collect()
    }

    pub async fn interactions_in_session(
        &self,
        session_id: SessionId,
    ) -> Vec<SessionInteraction> {
        let rows = sqlx::query(
            "SELECT id, session_id, context_id, iteration, event_type, target_kind, target_id,
                    target_uri, weight, was_useful, tool_name, created_at
             FROM session_interactions WHERE session_id = $1 ORDER BY id",
        )
        .bind(session_id.0 as i64)
        .fetch_all(&self.pool)
        .await
        .unwrap_or_default();
        rows.into_iter()
            .filter_map(|row| {
                let target = from_pg_ref(row.get(5), row.get::<Option<i64>, _>(6), row.get(7))?;
                let event_type = event_type_from_str(row.get::<&str, _>(4))?;
                Some(SessionInteraction {
                    id: InteractionId(row.get::<i64, _>(0) as u64),
                    session_id: SessionId(row.get::<i64, _>(1) as u64),
                    context_id: row
                        .get::<Option<i64>, _>(2)
                        .map(|i| ContextId(i as u64)),
                    iteration: row.get::<i32, _>(3) as u32,
                    event_type,
                    target,
                    weight: row.get(8),
                    was_useful: row.get(9),
                    tool_name: row.get(10),
                    created_at: row.get::<i64, _>(11) as u64,
                })
            })
            .collect()
    }

    pub async fn update_interaction_feedback(
        &self,
        id: InteractionId,
        was_useful: bool,
    ) -> StorageResult<()> {
        let res = sqlx::query("UPDATE session_interactions SET was_useful = $1 WHERE id = $2")
            .bind(was_useful)
            .bind(id.0 as i64)
            .execute(&self.pool)
            .await
            .map_err(map_sqlx)?;
        if res.rows_affected() == 0 {
            return Err(StorageError::InteractionNotFound(id));
        }
        Ok(())
    }

    // ---------- Session scores ----------

    pub async fn snapshot_session_scores(
        &self,
        session_id: SessionId,
        scores: Vec<NewSessionScore>,
    ) -> StorageResult<()> {
        let mut tx = self.pool.begin().await.map_err(map_sqlx)?;
        let exists: Option<i64> = sqlx::query_scalar("SELECT id FROM sessions WHERE id = $1")
            .bind(session_id.0 as i64)
            .fetch_optional(&mut *tx)
            .await
            .map_err(map_sqlx)?;
        if exists.is_none() {
            return Err(StorageError::SessionNotFound(session_id));
        }
        sqlx::query("DELETE FROM session_scores WHERE session_id = $1")
            .bind(session_id.0 as i64)
            .execute(&mut *tx)
            .await
            .map_err(map_sqlx)?;
        if scores.is_empty() {
            tx.commit().await.map_err(map_sqlx)?;
            return Ok(());
        }
        let now = now_millis() as i64;
        let n = scores.len();
        let mut tks: Vec<&str> = Vec::with_capacity(n);
        let mut tids: Vec<Option<i64>> = Vec::with_capacity(n);
        let mut turis: Vec<Option<String>> = Vec::with_capacity(n);
        let mut score_v: Vec<f32> = Vec::with_capacity(n);
        let mut acc_v: Vec<i32> = Vec::with_capacity(n);
        let mut prod_v: Vec<f32> = Vec::with_capacity(n);
        let mut pat_v: Vec<&str> = Vec::with_capacity(n);
        let mut edit_v: Vec<bool> = Vec::with_capacity(n);
        for s in scores {
            let (tk, tid, turi) = pg_ref(&s.target);
            tks.push(tk);
            tids.push(tid);
            turis.push(turi.map(str::to_string));
            score_v.push(s.score);
            acc_v.push(s.access_count as i32);
            prod_v.push(s.productivity);
            pat_v.push(pattern_str(s.pattern));
            edit_v.push(s.was_edited);
        }
        sqlx::query(
            "INSERT INTO session_scores
                (session_id, target_kind, target_id, target_uri, score, access_count,
                 productivity, pattern, was_edited, created_at)
             SELECT $1, tk, tid, turi, sc, ac, pr, pat, ed, $10
             FROM UNNEST($2::text[], $3::bigint[], $4::text[], $5::real[],
                         $6::int[], $7::real[], $8::text[], $9::boolean[])
                 AS t(tk, tid, turi, sc, ac, pr, pat, ed)",
        )
        .bind(session_id.0 as i64)
        .bind(&tks)
        .bind(&tids)
        .bind(&turis)
        .bind(&score_v)
        .bind(&acc_v)
        .bind(&prod_v)
        .bind(&pat_v)
        .bind(&edit_v)
        .bind(now)
        .execute(&mut *tx)
        .await
        .map_err(map_sqlx)?;
        tx.commit().await.map_err(map_sqlx)?;
        Ok(())
    }

    /// One-shot synthetic-session write used by the git-history ingest path
    /// (`crate::ingest_git`). Inserts the session, its single context, all
    /// interactions, and its score snapshot in a single transaction with all
    /// `created_at` columns backdated to `write.created_at`.
    ///
    /// The reason for the dedicated path is that the predictive ranker keys
    /// time decay off `sessions.created_at` and similarity off
    /// `session_contexts.embedding`. Replaying a 200k-commit history through
    /// the standard `create_session` + `append_context` + N×`append_interaction`
    /// + `snapshot_session_scores` chain is ≥4 round-trips per commit, ~2M
    /// in total — this collapses each commit to one round-trip and one transaction.
    pub async fn record_synthetic_session(
        &self,
        write: SyntheticSessionWrite,
    ) -> StorageResult<SessionId> {
        let mut tx = self.pool.begin().await.map_err(map_sqlx)?;
        let exists_ws: Option<i64> =
            sqlx::query_scalar("SELECT id FROM workspaces WHERE id = $1")
                .bind(write.workspace_id.0 as i64)
                .fetch_optional(&mut *tx)
                .await
                .map_err(map_sqlx)?;
        if exists_ws.is_none() {
            return Err(StorageError::WorkspaceNotFound(write.workspace_id));
        }
        let created_at = write.created_at as i64;

        // 1) sessions row — kind='synthetic' so dashboards / future ranker
        // tunings can discriminate replay from live sessions (D5).
        let session_id: i64 = sqlx::query_scalar(
            "INSERT INTO sessions (workspace_id, agent_id, kind, created_at, ended_at)
             VALUES ($1, $2, 'synthetic', $3, $3) RETURNING id",
        )
        .bind(write.workspace_id.0 as i64)
        .bind(&write.agent_id)
        .bind(created_at)
        .fetch_one(&mut *tx)
        .await
        .map_err(map_sqlx)?;

        // 2) the one context (with optional precomputed embedding)
        let context_emb: Option<Vector> = write.context_embedding.map(Vector::from);
        let context_id: i64 = sqlx::query_scalar(
            "INSERT INTO session_contexts
                 (session_id, workspace_id, kind, content, iteration, embedding, created_at)
             VALUES ($1, $2, $3, $4, 0, $5, $6) RETURNING id",
        )
        .bind(session_id)
        .bind(write.workspace_id.0 as i64)
        .bind(context_kind_str(write.context_kind))
        .bind(&write.context_content)
        .bind(context_emb.as_ref())
        .bind(created_at)
        .fetch_one(&mut *tx)
        .await
        .map_err(map_sqlx)?;

        // 3) interactions — UNNEST batch
        if !write.interactions.is_empty() {
            let n = write.interactions.len();
            let mut iters: Vec<i32> = Vec::with_capacity(n);
            let mut etypes: Vec<&str> = Vec::with_capacity(n);
            let mut tks: Vec<&str> = Vec::with_capacity(n);
            let mut tids: Vec<Option<i64>> = Vec::with_capacity(n);
            let mut turis: Vec<Option<String>> = Vec::with_capacity(n);
            let mut wts: Vec<f32> = Vec::with_capacity(n);
            for it in &write.interactions {
                let (tk, tid, turi) = pg_ref(&it.target);
                iters.push(it.iteration as i32);
                etypes.push(event_type_str(it.event_type));
                tks.push(tk);
                tids.push(tid);
                turis.push(turi.map(str::to_string));
                wts.push(it.weight);
            }
            sqlx::query(
                "INSERT INTO session_interactions
                     (session_id, context_id, iteration, event_type, target_kind, target_id,
                      target_uri, weight, was_useful, tool_name, created_at)
                 SELECT $1, $2, it, et, tk, tid, turi, wt, NULL, NULL, $3
                 FROM UNNEST($4::int[], $5::text[], $6::text[], $7::bigint[], $8::text[],
                             $9::real[]) AS t(it, et, tk, tid, turi, wt)",
            )
            .bind(session_id)
            .bind(context_id)
            .bind(created_at)
            .bind(&iters)
            .bind(&etypes)
            .bind(&tks)
            .bind(&tids)
            .bind(&turis)
            .bind(&wts)
            .execute(&mut *tx)
            .await
            .map_err(map_sqlx)?;
        }

        // 4) session_scores snapshot — UNNEST batch
        if !write.scores.is_empty() {
            let n = write.scores.len();
            let mut tks: Vec<&str> = Vec::with_capacity(n);
            let mut tids: Vec<Option<i64>> = Vec::with_capacity(n);
            let mut turis: Vec<Option<String>> = Vec::with_capacity(n);
            let mut score_v: Vec<f32> = Vec::with_capacity(n);
            let mut acc_v: Vec<i32> = Vec::with_capacity(n);
            let mut prod_v: Vec<f32> = Vec::with_capacity(n);
            let mut pat_v: Vec<&str> = Vec::with_capacity(n);
            let mut edit_v: Vec<bool> = Vec::with_capacity(n);
            for s in &write.scores {
                let (tk, tid, turi) = pg_ref(&s.target);
                tks.push(tk);
                tids.push(tid);
                turis.push(turi.map(str::to_string));
                score_v.push(s.score);
                acc_v.push(s.access_count as i32);
                prod_v.push(s.productivity);
                pat_v.push(pattern_str(s.pattern));
                edit_v.push(s.was_edited);
            }
            sqlx::query(
                "INSERT INTO session_scores
                     (session_id, target_kind, target_id, target_uri, score, access_count,
                      productivity, pattern, was_edited, created_at)
                 SELECT $1, tk, tid, turi, sc, ac, pr, pat, ed, $10
                 FROM UNNEST($2::text[], $3::bigint[], $4::text[], $5::real[],
                             $6::int[], $7::real[], $8::text[], $9::boolean[])
                     AS t(tk, tid, turi, sc, ac, pr, pat, ed)",
            )
            .bind(session_id)
            .bind(&tks)
            .bind(&tids)
            .bind(&turis)
            .bind(&score_v)
            .bind(&acc_v)
            .bind(&prod_v)
            .bind(&pat_v)
            .bind(&edit_v)
            .bind(created_at)
            .execute(&mut *tx)
            .await
            .map_err(map_sqlx)?;
        }

        tx.commit().await.map_err(map_sqlx)?;
        Ok(SessionId(session_id as u64))
    }

    pub async fn session_score(
        &self,
        session_id: SessionId,
        target: &NodeRef,
    ) -> Option<SessionScore> {
        let (tk, tid, turi) = pg_ref(target);
        let row = sqlx::query(
            "SELECT score, access_count, productivity, pattern, was_edited, created_at
             FROM session_scores
             WHERE session_id = $1 AND target_kind = $2
               AND COALESCE(target_id, -1) = COALESCE($3, -1)
               AND COALESCE(target_uri, '') = COALESCE($4, '')",
        )
        .bind(session_id.0 as i64)
        .bind(tk)
        .bind(tid)
        .bind(turi)
        .fetch_optional(&self.pool)
        .await
        .ok()??;
        let pattern = pattern_from_str(row.get::<&str, _>(3))?;
        Some(SessionScore {
            session_id,
            target: target.clone(),
            score: row.get(0),
            access_count: row.get::<i32, _>(1) as u32,
            productivity: row.get(2),
            pattern,
            was_edited: row.get(4),
            created_at: row.get::<i64, _>(5) as u64,
        })
    }
}

fn edge_from_row(row: &sqlx::postgres::PgRow) -> Option<Edge> {
    let from = from_pg_ref(row.get(2), row.get::<Option<i64>, _>(3), row.get(4))?;
    let to = from_pg_ref(row.get(5), row.get::<Option<i64>, _>(6), row.get(7))?;
    let kind: Json<EdgeKind> = row.get(8);
    let metadata: Json<MetadataMap> = row.get(10);
    let created_by_str: String = row.get(11);
    let created_by: EdgeOrigin =
        serde_json::from_value(serde_json::Value::String(created_by_str)).unwrap_or(EdgeOrigin::User);
    Some(Edge {
        id: EdgeId(row.get::<i64, _>(0) as u64),
        workspace_id: WorkspaceId(row.get::<i64, _>(1) as u64),
        from,
        to,
        kind: kind.0,
        weight: row.get(9),
        metadata: metadata.0,
        created_by,
        created_at: row.get::<i64, _>(12) as u64,
    })
}
