# 08 — Schema (PostgreSQL)

Schema completo del backend persistente. Fuente de verdad ejecutable:
`crates/engine/migrations/0001_initial.sql`. Este doc lo explica.

## Tablas

### Catálogo

```sql
-- tenants: boundary multi-tenant. ULID como string.
CREATE TABLE tenants (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    plan        TEXT NOT NULL,           -- 'free' | 'team' | 'enterprise'
    created_at  BIGINT NOT NULL          -- epoch millis
);

-- workspaces: ámbito de retrieval. N workspaces por tenant.
CREATE TABLE workspaces (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    settings    JSONB NOT NULL DEFAULT '{}',
    created_at  BIGINT NOT NULL
);
CREATE INDEX ON workspaces (tenant_id);

-- sources: de dónde vienen los documents (LocalFs, GitHub, Slack, ...)
CREATE TABLE sources (
    id              BIGSERIAL PRIMARY KEY,
    workspace_id    BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    kind            JSONB NOT NULL,      -- enum cerrado + Custom(String)
    name            TEXT NOT NULL,
    config_json     JSONB,
    keep_history    BOOLEAN NOT NULL DEFAULT FALSE,
    default_acl     JSONB NOT NULL,
    last_sync_at    BIGINT,
    created_at      BIGINT NOT NULL
);
CREATE INDEX ON sources (workspace_id);
```

### Contenido

```sql
-- documents: unidad ingerida. (source_id, external_id) identifica la versión
-- *vigente*; las versiones históricas conservan su external_id pero quedan
-- con current = FALSE. El índice único parcial garantiza una sola versión
-- vigente por (source, external_id) sin colisionar con el historial.
CREATE TABLE documents (
    id                   BIGSERIAL PRIMARY KEY,
    workspace_id         BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    source_id            BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_id          TEXT,
    kind                 JSONB NOT NULL,
    mime                 TEXT NOT NULL,
    title                TEXT,
    path_or_url          TEXT,
    content_hash         BYTEA NOT NULL,        -- blake3, 32 bytes
    version              BIGINT NOT NULL DEFAULT 1,
    current              BOOLEAN NOT NULL DEFAULT TRUE,
    replaced_by          BIGINT REFERENCES documents(id),
    acl                  JSONB NOT NULL,
    metadata             JSONB NOT NULL DEFAULT '{}',
    ingested_at          BIGINT NOT NULL,
    source_modified_at   BIGINT
);
CREATE UNIQUE INDEX uniq_documents_source_external_current
    ON documents (source_id, external_id)
    WHERE current = TRUE AND external_id IS NOT NULL;
CREATE INDEX ON documents (workspace_id, current);
CREATE INDEX ON documents (source_id, external_id);
CREATE INDEX ON documents USING GIN (metadata jsonb_path_ops);

-- chunks: unidad de retrieval. Embedding inline + FTS generado.
CREATE TABLE chunks (
    id              BIGSERIAL PRIMARY KEY,
    document_id     BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    workspace_id    BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    kind            JSONB NOT NULL,
    position        JSONB NOT NULL,
    text            TEXT NOT NULL,
    embedding       vector(768),                                            -- pgvector
    metadata        JSONB NOT NULL DEFAULT '{}',
    fts             tsvector GENERATED ALWAYS AS
                    (to_tsvector('simple', text)) STORED                    -- FTS
);
CREATE INDEX ON chunks (document_id);
CREATE INDEX ON chunks (workspace_id);
CREATE INDEX ON chunks USING GIN (fts);                                     -- keyword
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;                                            -- ANN
CREATE INDEX ON chunks USING GIN (metadata jsonb_path_ops);                 -- filtros
```

### Knowledge graph

```sql
-- entities: átomos canónicos opcionales.
CREATE TABLE entities (
    id              BIGSERIAL PRIMARY KEY,
    workspace_id    BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    kind            JSONB NOT NULL,
    canonical_name  TEXT NOT NULL,
    aliases         TEXT[] NOT NULL DEFAULT '{}',
    embedding       vector(768),
    metadata        JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX ON entities (workspace_id);
CREATE UNIQUE INDEX ON entities (workspace_id, kind, canonical_name);

-- edges: NodeRef polimórfico via (kind, id, uri).
-- from_kind / to_kind ∈ {'doc', 'chunk', 'ent', 'ext'}
-- *_id NULL cuando kind='ext'; *_uri NULL en otros casos.
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
    created_by      TEXT NOT NULL,            -- 'adapter' | 'url_resolver' | ...
    created_at      BIGINT NOT NULL,
    UNIQUE (workspace_id, from_kind, from_id, from_uri, to_kind, to_id, to_uri, kind)
);
CREATE INDEX ON edges (workspace_id, from_kind, from_id);
CREATE INDEX ON edges (workspace_id, to_kind, to_id);
```

### Sesión + interacciones

```sql
CREATE TABLE sessions (
    id              BIGSERIAL PRIMARY KEY,
    workspace_id    BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id        TEXT,
    created_at      BIGINT NOT NULL,
    ended_at        BIGINT
);
CREATE INDEX ON sessions (workspace_id);

CREATE TABLE session_contexts (
    id              BIGSERIAL PRIMARY KEY,
    session_id      BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    workspace_id    BIGINT NOT NULL,            -- denormalizado para queries de workspace
    kind            TEXT NOT NULL,
    content         TEXT NOT NULL,
    iteration       INT NOT NULL,
    embedding       vector(768),
    created_at      BIGINT NOT NULL
);
CREATE INDEX ON session_contexts (session_id);
CREATE INDEX ON session_contexts (workspace_id, created_at DESC);
CREATE INDEX ON session_contexts USING hnsw (embedding vector_cosine_ops)
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
CREATE INDEX ON session_interactions (session_id);

CREATE TABLE session_scores (
    session_id      BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    target_kind     TEXT NOT NULL,
    target_id       BIGINT,
    target_uri      TEXT,
    score           REAL NOT NULL,
    access_count    INT NOT NULL,
    productivity    REAL NOT NULL,
    pattern         TEXT NOT NULL,
    was_edited      BOOLEAN NOT NULL,
    created_at      BIGINT NOT NULL,
    PRIMARY KEY (session_id, target_kind, target_id, target_uri)
);
```

## Decisiones por columna

### Por qué `JSONB` para enums con `Other(String)`

`ContentKind`, `ChunkKind`, `EntityKind`, `EdgeKind`, `SourceKind` tienen
variantes canónicas (e.g. `Pdf`, `CodeFile`) **y** un escape hatch
`Other(String)`. Serde serializa la canonical como string `"pdf"` y la
extension como objeto `{"other": "X"}`. JSONB acepta ambas y permite
queries:

```sql
WHERE kind = '"pdf"'::jsonb                  -- canonical
WHERE kind ? 'other'                          -- has Other variant
WHERE kind ->> 'other' = 'CustomFormat'       -- specific Other
```

TEXT plain serviría para los canonicals pero no para el escape hatch sin
parsing manual. JSONB es más limpio.

Para enums sin `Other` (`Pattern`, `EventType`, `ContextKind`,
`Visibility`, `EdgeOrigin`, `PlanTier`) → TEXT directo.

### Por qué `BIGINT` para timestamps

Epoch millis como `u64` en Rust → `BIGINT` (`i64`) en postgres. Llega
hasta el año 292M. No usamos `TIMESTAMPTZ` para evitar conversión de
zonas horarias en cada query — los timestamps son opacos al engine.

### Por qué `BYTEA` para `content_hash`

Blake3 outputs 32 bytes; `BYTEA` los almacena directos. `TEXT` con
encoding hex sería 64 chars + overhead.

### Por qué generated `tsvector` en lugar de calcular en query

Indexable. Postgres recalcula automáticamente cuando `text` cambia. Cero
mantenimiento.

### Por qué HNSW y no IVFFlat

HNSW: mejor recall a la misma latencia, no requiere "training" sobre el
dataset. IVFFlat necesita un sample para calibrar centroides. HNSW es
strictly better para nuestro tamaño esperado (hasta ~100M chunks por
workspace).

### Por qué `WHERE embedding IS NOT NULL` en el HNSW

Chunks recién creados pueden no tener embedding todavía (ingesta
síncrona del Document, embedding async después). El partial index
ahorra entries vacías y acelera builds.

### Por qué edges con tres columnas en lugar de un solo `node_ref TEXT`

Queries comunes son del estilo "edges salientes del Document con id 42".
Con `from_kind`, `from_id` separados, índice btree compuesto las hace
O(log n). Con un solo string `"doc:42"` requeriría parsing en query.

### `UNIQUE (workspace_id, from_kind, from_id, from_uri, to_kind, to_id, to_uri, kind)` en edges

Previene edges duplicados entre los mismos endpoints con el mismo kind.
Cuando el `add_edge` re-aparece (e.g., re-ingesta), usamos `INSERT ...
ON CONFLICT (...) DO UPDATE SET weight = GREATEST(weight, EXCLUDED.weight)`
para "weight = max" sin duplicar fila.

## Volumen estimado por tenant grande

| Entidad | Filas (orden de magnitud) | Tamaño aprox |
|---|---|---|
| `tenants` | 1 | < 1 KB |
| `workspaces` | 1–10 | < 10 KB |
| `sources` | 10–100 | < 100 KB |
| `documents` | 100k | ~50 MB |
| `chunks` | 1M–10M | ~3 GB texto + ~3 GB embeddings (HNSW ~5 GB índice) |
| `edges` | 1M–10M | ~500 MB |
| `entities` | 10k–100k | ~10 MB |
| `sessions` + `session_*` | 100k sesiones × ~20 events = 2M | ~500 MB |

Total: 10–15 GB para un workspace empresarial mediano. Postgres lo
maneja sin sudar.

## Migrations

Live en `crates/engine/migrations/0001_initial.sql`. Aplicadas via
`sqlx::migrate!()`. Cambios futuros en `0002_*.sql`, etc. Naming
convention: `NNNN_<descriptive_slug>.sql`.

## Lo que falta documentar

- Estrategia de backups (tira de pg-base-backup + WAL archiving — ver
  `docs/05-roadmap.md` Phase 2).
- RLS policies (cuando un cliente lo pida).
- Sharding cross-tenant (Phase 2+).
