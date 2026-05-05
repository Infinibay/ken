# 04 — Storage

## Backend persistente: PostgreSQL + pgvector

Decidido el 2026-05-04 (ver D-019 en `06-decisions.md`). El backend de
producción es **PostgreSQL ≥ 14 con la extensión `pgvector`**. La idea
original de construir una DB propia ACID se descartó por inviable a
tiempos de startup MVP — D-018 documenta el requisito ACID que motivó la
búsqueda; D-019 documenta cómo lo cumplimos.

## Por qué Postgres y no algo más

| Alternativa | Por qué no la elegimos |
|---|---|
| Custom DB ACID propia | 3–6 meses base + años de cola de bugs. Proyecto de PhD, no MVP. |
| SQLite + sqlite-vec | Single-writer, multi-conn limitado, sin RLS robusto. Ok para single-user pero no para B2B SaaS. |
| Pinecone / Weaviate / Qdrant | Specialized vector DBs, pero sin transacciones, FTS, JSONB ni KG en el mismo store. Tendríamos que sumar otra DB y orquestar. |
| Postgres puro sin pgvector | Vectores como BLOB/array, sin índices ANN. Inviable a escala. |
| **Postgres + pgvector** | **ACID, MVCC, multi-conn, vectors con HNSW, FTS via tsvector, JSONB, RLS para ACL, recursive CTEs para KG, ya operan en empresa.** |

## Mapping a alto nivel

Cada entidad del modelo de datos (`docs/02-data-model.md`) → una tabla:

| Entidad | Tabla |
|---|---|
| `Tenant` | `tenants` |
| `Workspace` | `workspaces` |
| `Source` | `sources` |
| `Document` | `documents` |
| `Chunk` | `chunks` (incluye columna `embedding vector(768)` y FTS generated) |
| `Entity` | `entities` |
| `Edge` | `edges` (NodeRef como `(kind, id, uri)` triplet) |
| `Session` | `sessions` |
| `SessionContext` | `session_contexts` |
| `SessionInteraction` | `session_interactions` |
| `SessionScore` | `session_scores` |

El schema completo y comentado vive en `docs/08-schema.md`. La fuente de
verdad ejecutable son las migraciones en `crates/engine/migrations/`.

## Decisiones de schema relevantes

- **IDs**: `TenantId` es `TEXT` (ULID como string). El resto son
  `BIGSERIAL` (`u64` autoincrementales).
- **Enums con `Other(String)`** (`ContentKind`, `ChunkKind`, `EntityKind`,
  `EdgeKind`, `SourceKind`) → almacenados como `JSONB` para acomodar
  variantes canónicas (`"pdf"`) y extendidas (`{"other": "Custom"}`).
- **Enums sin extensión** (`Pattern`, `EventType`, `ContextKind`, etc.)
  → `TEXT` plano.
- **`embedding`**: columna `vector(768)` (dim de `nomic-embed-text-v1.5`).
  Índice **HNSW** sobre `vector_cosine_ops` con filtro `WHERE embedding
  IS NOT NULL`.
- **FTS**: columna `fts tsvector GENERATED ALWAYS AS to_tsvector('simple',
  text) STORED` en `chunks` y `session_contexts`. Índice GIN. Da el canal
  keyword del ranker gratis.
- **`metadata.extra`** y campos opacos → `JSONB`. Índice `GIN
  jsonb_path_ops` para filtros eficientes.
- **`Acl`** → JSONB en cada `Document`. Pre-filter en query path.
  Migración futura a Row-Level Security cuando un cliente pida
  enforcement a nivel de DB.
- **`NodeRef`** (campo `from`, `to` de edges; `target` de interactions y
  scores) → tres columnas: `*_kind` (TEXT), `*_id` (BIGINT, NULL si
  external), `*_uri` (TEXT, NULL si interno). Permite índices
  separados para queries por id vs por uri.
- **Versionado**: `documents.current` BOOLEAN + `documents.replaced_by`
  FK self-reference. Constraint UNIQUE `(source_id, external_id)` con
  cuidado: postgres permite múltiples NULLs.
- **Cascades**: `ON DELETE CASCADE` desde `documents` → `chunks` y desde
  `sessions` → `session_contexts`/`session_interactions`. El resto de las
  invariantes referenciales son manuales (las hace el código del
  `PostgresStorage`).

## Multi-tenancy

**MVP**: single schema. Toda fila lleva `workspace_id` (y workspace
lleva `tenant_id`). Filtros lógicos por workspace en cada query del
storage. Sin RLS todavía.

**Fase 2**: cuando un cliente lo pida (compliance / aislamiento físico),
agregamos schema-per-tenant: `CREATE SCHEMA tenant_<id>` con las mismas
tablas. La migración es transparente al engine (resolve `tenant_id` a
schema antes de cada query).

## Pool de conexiones, transacciones, durabilidad

- **Connection pool**: `sqlx::PgPool` con `max_connections=20` por
  default. Tunable via env.
- **Transacciones**: el trait `Storage` actualmente expone métodos
  auto-commit. Cuando el ingest path lo requiera (multi-step:
  `upsert_document` + `replace_chunks` + `put_embedding × N` + `add_edge
  × N` deben ser atómicos), agregamos un `transaction(|tx| { ... })`
  closure-based al trait. Se mappea a `pool.begin().await?`.
- **Durabilidad**: `synchronous_commit = on` (default). Para tiers más
  laxos (e.g. session events), expone `synchronous_commit = off` por
  workspace. Por ahora todo strong.

## Migrations

Vivien en `crates/engine/migrations/`. Naming `NNNN_<slug>.sql`. Aplicadas
via `sqlx::migrate!("./migrations").run(&pool)`. Idempotente, embebidas
en el binario en compile-time.

Versión inicial: `0001_initial.sql` con todas las tablas + índices +
extensiones. Cambios futuros en `0002_*.sql`, etc.

## Stack Rust

- **`sqlx` 0.8** — async, compile-time SQL check, pure Rust.
- **`pgvector` 0.4** — tipo `Vector` integrado a sqlx para columnas
  `vector(N)`.
- **`testcontainers-rs`** (dev-dep) — postgres efímero por test de
  integración.
- Detrás de cargo feature `postgres` en `cae-engine` para que builds
  sin postgres no paguen el costo de compilar sqlx.

## Layout en disco (orientativo, lo maneja postgres)

```
postgres data dir/
├── base/<oid>/                    # tablespaces, pages
│   ├── <relid>                    # cada tabla y cada índice un archivo
│   └── ...
├── pg_wal/                        # WAL — postgres se encarga
├── pg_xact/                       # commit log
└── ...
```

No es nuestro problema. Postgres gestiona pages, MVCC, WAL, vacuum,
checkpoints, backups, replicación.

## Lo que tenemos en código hoy

- **`PostgresStorage`** (en `src/postgres.rs`, gated en feature `postgres`)
  es el backend persistente y **único** del engine. No hay trait `Storage`
  ni `MemoryStorage` (decisión D-020). Métodos inherentes pub `async fn`
  cubren todo el dominio (tenants, workspaces, sources, documents, chunks,
  entities, edges, embeddings, sessions, contexts, interactions, scores).
- **`src/storage.rs`** queda solo con los tipos de soporte: `StorageError`,
  los `New*` drafts, `ChunkFilter`, `UpsertOutcome`, `is_visible`,
  `now_millis`. Vivien acá para que callers (ranker, ingest) no tengan
  que pull la dependencia de postgres si no la necesitan.

### Por qué se eliminó el trait `Storage`

El trait + `MemoryStorage` se diseñaron cuando íbamos a escribir DB custom
(D-018), para permitir swap de backend. Al pivotar a Postgres (D-019) ese
swap dejó de existir: dev local usa Docker, prod usa Postgres managed.
Mantener la abstracción costaba lifetime gymnastics con `async-trait`,
38 métodos en dos impls, y forzaba `MemoryStorage` a clonar vectores para
cumplir un contrato pensado para Postgres. Ver D-020 y la project memory
`project_storage_architecture.md`.

## Local dev

`docker-compose.yml` levanta postgres 16 + pgvector preinstalado. Datos
persisten en volumen Docker. Ver el README del repo para el comando.
