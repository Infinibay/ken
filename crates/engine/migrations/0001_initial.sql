-- Initial schema for context-ai-engine. See docs/08-schema.md for explanations.
-- Requires the `vector` extension (pgvector) to be enabled, which the docker
-- init.sql handles in dev. In production environments the operator must
-- ensure CREATE EXTENSION vector has run before this migration.

CREATE EXTENSION IF NOT EXISTS vector;

-- ----------------------------------------------------------------------------
-- Identity & origin
-- ----------------------------------------------------------------------------

CREATE TABLE tenants (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    plan        TEXT NOT NULL,
    created_at  BIGINT NOT NULL
);

CREATE TABLE workspaces (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    settings    JSONB NOT NULL DEFAULT '{}',
    created_at  BIGINT NOT NULL
);
CREATE INDEX idx_workspaces_tenant ON workspaces(tenant_id);

CREATE TABLE sources (
    id              BIGSERIAL PRIMARY KEY,
    workspace_id    BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    kind            JSONB NOT NULL,
    name            TEXT NOT NULL,
    config_json     JSONB,
    keep_history    BOOLEAN NOT NULL DEFAULT FALSE,
    default_acl     JSONB NOT NULL,
    last_sync_at    BIGINT,
    created_at      BIGINT NOT NULL
);
CREATE INDEX idx_sources_workspace ON sources(workspace_id);

-- ----------------------------------------------------------------------------
-- Content
-- ----------------------------------------------------------------------------

CREATE TABLE documents (
    id                   BIGSERIAL PRIMARY KEY,
    workspace_id         BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    source_id            BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_id          TEXT,
    kind                 JSONB NOT NULL,
    mime                 TEXT NOT NULL,
    title                TEXT,
    path_or_url          TEXT,
    content_hash         BYTEA NOT NULL,
    version              BIGINT NOT NULL DEFAULT 1,
    current              BOOLEAN NOT NULL DEFAULT TRUE,
    replaced_by          BIGINT REFERENCES documents(id),
    acl                  JSONB NOT NULL,
    metadata             JSONB NOT NULL DEFAULT '{}',
    ingested_at          BIGINT NOT NULL,
    source_modified_at   BIGINT
);
-- Only one *current* version of a (source, external_id) pair at a time.
-- Historical versions keep their external_id but have current = FALSE.
CREATE UNIQUE INDEX uniq_documents_source_external_current
    ON documents(source_id, external_id)
    WHERE current = TRUE AND external_id IS NOT NULL;
CREATE INDEX idx_documents_workspace_current ON documents(workspace_id, current);
CREATE INDEX idx_documents_source_external ON documents(source_id, external_id);
CREATE INDEX idx_documents_metadata ON documents USING GIN (metadata jsonb_path_ops);

CREATE TABLE chunks (
    id              BIGSERIAL PRIMARY KEY,
    document_id     BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    workspace_id    BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    kind            JSONB NOT NULL,
    position        JSONB NOT NULL,
    text            TEXT NOT NULL,
    embedding       vector(768),
    metadata        JSONB NOT NULL DEFAULT '{}',
    fts             tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED
);
CREATE INDEX idx_chunks_document ON chunks(document_id);
CREATE INDEX idx_chunks_workspace ON chunks(workspace_id);
CREATE INDEX idx_chunks_fts ON chunks USING GIN (fts);
CREATE INDEX idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;
CREATE INDEX idx_chunks_metadata ON chunks USING GIN (metadata jsonb_path_ops);

-- ----------------------------------------------------------------------------
-- Knowledge graph
-- ----------------------------------------------------------------------------

CREATE TABLE entities (
    id              BIGSERIAL PRIMARY KEY,
    workspace_id    BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    kind            JSONB NOT NULL,
    canonical_name  TEXT NOT NULL,
    aliases         TEXT[] NOT NULL DEFAULT '{}',
    embedding       vector(768),
    metadata        JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_entities_workspace ON entities(workspace_id);
CREATE UNIQUE INDEX uniq_entities_canonical ON entities(workspace_id, (kind::text), canonical_name);
CREATE INDEX idx_entities_embedding ON entities USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

CREATE TABLE edges (
    id              BIGSERIAL PRIMARY KEY,
    workspace_id    BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    from_kind       TEXT NOT NULL,
    from_id         BIGINT,
    from_uri        TEXT,
    to_kind         TEXT NOT NULL,
    to_id           BIGINT,
    to_uri          TEXT,
    kind            JSONB NOT NULL,
    weight          REAL NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_by      TEXT NOT NULL,
    created_at      BIGINT NOT NULL
);
CREATE UNIQUE INDEX uniq_edges_endpoints
    ON edges(workspace_id, from_kind, COALESCE(from_id, -1), COALESCE(from_uri, ''),
             to_kind,   COALESCE(to_id,   -1), COALESCE(to_uri,   ''),
             (kind::text));
CREATE INDEX idx_edges_from ON edges(workspace_id, from_kind, from_id);
CREATE INDEX idx_edges_to   ON edges(workspace_id, to_kind,   to_id);
CREATE INDEX idx_edges_from_uri ON edges(workspace_id, from_kind, from_uri)
    WHERE from_uri IS NOT NULL;
CREATE INDEX idx_edges_to_uri   ON edges(workspace_id, to_kind, to_uri)
    WHERE to_uri IS NOT NULL;

-- ----------------------------------------------------------------------------
-- Sessions & interactions (agent-first)
-- ----------------------------------------------------------------------------

CREATE TABLE sessions (
    id              BIGSERIAL PRIMARY KEY,
    workspace_id    BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id        TEXT,
    created_at      BIGINT NOT NULL,
    ended_at        BIGINT
);
CREATE INDEX idx_sessions_workspace ON sessions(workspace_id);

CREATE TABLE session_contexts (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    workspace_id    BIGINT NOT NULL,
    kind            TEXT NOT NULL,
    content         TEXT NOT NULL,
    iteration       INT NOT NULL,
    embedding       vector(768),
    created_at      BIGINT NOT NULL
);
CREATE INDEX idx_session_contexts_session ON session_contexts(session_id);
CREATE INDEX idx_session_contexts_ws_time ON session_contexts(workspace_id, created_at DESC);
CREATE INDEX idx_session_contexts_embedding ON session_contexts USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

CREATE TABLE session_interactions (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    context_id      BIGINT REFERENCES session_contexts(id) ON DELETE SET NULL,
    iteration       INT NOT NULL,
    event_type      TEXT NOT NULL,
    target_kind     TEXT NOT NULL,
    target_id       BIGINT,
    target_uri      TEXT,
    weight          REAL NOT NULL,
    was_useful      BOOLEAN,
    created_at      BIGINT NOT NULL
);
CREATE INDEX idx_session_interactions_session ON session_interactions(session_id);

CREATE TABLE session_scores (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    target_kind     TEXT NOT NULL,
    target_id       BIGINT,
    target_uri      TEXT,
    score           REAL NOT NULL,
    access_count    INT NOT NULL,
    productivity    REAL NOT NULL,
    pattern         TEXT NOT NULL,
    was_edited      BOOLEAN NOT NULL,
    created_at      BIGINT NOT NULL
);
CREATE UNIQUE INDEX uniq_session_scores_target ON session_scores(
    session_id, target_kind, COALESCE(target_id, -1), COALESCE(target_uri, '')
);
CREATE INDEX idx_session_scores_session ON session_scores(session_id);
