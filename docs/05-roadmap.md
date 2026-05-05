# 05 — Roadmap

## Fases

### MVP (lo que persigue esta sesión)

Objetivo: demo end-to-end con tipos básicos (PlainText + Markdown), un
adapter funcional cada uno, ranking básico, API HTTP, sobre PostgreSQL.

Includes:
- Workspace Cargo + scaffolding ✅
- Modelo de datos genérico (Document/Chunk/Entity/Edge + Session) ✅
- `Embedder` trait + `MockEmbedder` ✅ (fastembed real en MVP+)
- `ContentAdapter` trait + PlainText adapter ✅
- Postgres infra: docker-compose + pgvector + schema + migraciones ✅
- `PostgresStorage` concreto (sin trait abstraction) — todos los métodos
  inherentes async, con integration tests contra Docker Postgres ✅
- Markdown adapter (próximo)
- Ranker: reactive + predictive + semantic + FTS (4to canal gratis), con
  merge + confidence + MAD
- HTTP API: ingest, retrieve, event, feedback
- Tests integrales: ingiero N docs, hago una sesión, retrieve devuelve
  los esperados, feedback se loggea.

### MVP+ (estabilización)

- Code adapter con tree-sitter (Rust + Python + TS)
- PDF adapter
- Wire `fastembed` (`nomic-embed-text-v1.5`)
- testcontainers-rs integration tests para PostgresStorage
- Backups automáticos en docker-compose (pg_basebackup script)

### Fase 1.5 (producto vendible v1)

- Email adapter
- DOCX, HTML adapters
- KG channel del ranker (1-hop / 2-hop via recursive CTE)
- URL/identifier annotator end-to-end
- Multi-tenant: aislamiento físico opcional (schema-per-tenant)
- ACL enforcement vía Row-Level Security
- Versionado per-source funcional con audit queries

### Fase 2 (enterprise feature surface)

- Conectores: Slack, Confluence, Jira, GitHub, Google Drive, S3
- Apache AGE (Cypher sobre postgres) para queries de KG complejas si
  recursive CTE se queda corto a escala
- gRPC API además de HTTP
- Output templates (custom response shapes por workspace)
- Background semantic-neighborhood edges
- Métricas/observabilidad (OpenTelemetry, exporter a Prometheus/Datadog)
- Auth: API keys, JWT, SSO (OIDC)
- Audit logs (qué tenant tocó qué document, cuándo)
- RBAC con grupos/herencia
- Replicación read-only para queries pesadas
- Point-in-time recovery automatizado

### Fase 3 (polish + scale)

- Embedding refresh policy (re-embed cuando cambia content_hash)
- Document compaction job
- Backup/restore CLI
- Multi-region replication (logical replication)
- Hosted SaaS deployment (k8s manifests)

## Estado actual de tareas

Ver `TaskList` en sesión activa de Claude. Snapshot al cierre del pivot
a Postgres (mayo 2026):

| # | Tarea | Status |
|---|---|---|
| 1 | Scaffold Cargo workspace + git init | done |
| 2 | Define core domain types (modelo viejo) | done — superseded by #13 |
| 3 | Storage trait + memory backend (modelo viejo) | done — superseded by #14 |
| 4 | Embedder + mock + stop-word filter | done |
| 12 | Write design docs | done |
| 13 | Rewrite types.rs to generic model | done |
| 14 | Rewrite Storage trait + MemoryStorage | done — superseded by #26 |
| 15 | ContentAdapter trait + PlainText | done (Markdown pending) |
| 20 | docker-compose + Postgres+pgvector + init.sql | done |
| 21 | `0001_initial.sql` migrations file | done |
| 22 | sqlx + pgvector deps + `postgres` feature flag | done |
| 23 | `PostgresStorage` skeleton (connect + migrate + health) | done |
| 24 | Convert `Storage` trait to async fn | done — superseded by #26 |
| 10 | Implement full `Storage` impl on `PostgresStorage` | done — superseded by #26 |
| **26** | **Drop `Storage` trait + `MemoryStorage`; `PostgresStorage` inherente concreto** | done |
| **25** | **Markdown adapter** (pulldown-cmark): H1/H2 sectioning + Cites edges from inline links + adapter registry dispatch | done |
| **16** | **Code adapter — Rust** (tree-sitter): per-symbol chunks (fn/struct/enum/trait/methods), doc-comments + attributes preserved, `Imports` edges from `use` statements; Python+TS split to #32/#33 | done |
| **32** | **Code adapter — Python**: function/class chunks (decorators included), `import x`/`from x import …` edges with `python:` prefix, refactored `ingest_code/` into per-language modules | done |
| **33** | **Code adapter — TypeScript / TSX**: per-symbol chunks (function/class/interface/type/enum) with `export` modifier captured, JSDoc on outer `export_statement` resolved, methods inside class bodies, both `LANGUAGE_TYPESCRIPT` and `LANGUAGE_TSX` grammars, mixed `ts:` (relative) / `npm:` (bare specifier) import namespaces | done |
| **34** | **Code adapter — Go**: function/method/type chunks (struct/interface/alias), pointer receiver collapses to base type for method qualified names (`*User → User.Method`), single + grouped imports under `go:` namespace, `//`-prefixed doc comments folded into chunk | done |
| **35** | **Code adapter — JavaScript**: function/class/method chunks, `export_statement` wrapper captured, JSDoc resolved, `js:` (relative) / `npm:` (bare) import namespaces — same convention as TS but distinct namespace so module systems don't conflate | done |
| **36** | **Code adapter — Java**: class/interface/enum/record/annotation declarations + methods + constructors, scope-aware qualified names (`Outer.Inner.method`), `import_declaration` under `java:` namespace, `package` declaration emitted as synthetic edge, wildcard imports dropped | done |
| **37** | **Code adapter — C and C++**: `function_definition` / `struct_specifier` / `union_specifier` / `enum_specifier` shared, C++ adds `class_specifier` + `namespace_definition` (pushed into scope) + `template_declaration` (recurses), `#include <...>` → `c-system:` and `#include "..."` → `c:` namespaces | done |
| **38** | **Code adapter — Ruby**: `class` / `module` / `method` / `singleton_method` chunks, members joined with `.` to parent and parents with `::` (`Foo::Bar.method`), `require`/`require_relative`/`load` calls collected as `ruby:` / `ruby-rel:` imports | done |
| **17** | **PDF adapter** (pdf-extract): one chunk per page (PageRange position), char-aligned sub-chunking for oversize pages, form-feed split workaround for missing `_by_pages_from_mem`, plus new `/ingest_blob` endpoint for binary uploads via base64 | done |
| **18** | **URL annotator**: hand-rolled URL extractor + Chunk→External edges + wired into both ingest paths | done |
| 5 | Ranking channels: reactive + predictive + semantic + FTS | done (FTS deferred a #16/#25) |
| 6 | Confidence gate + MAD outlier filter | done |
| 7 | Adaptive alpha blending | done |
| 27 | Add `tool_name` forensics column to session_interactions | done |
| 28 | Ranker step 1: stats + merge | done |
| 29 | Ranker step 2: reactive channel | done |
| 30 | Ranker step 3: predictive + semantic + Ranker::rank | done |
| **9** | **HTTP API (axum)**: tenants/workspaces/sources/sessions/ingest/rank/events + smoke test | done |
| **11** | **Wire fastembed (`nomic-embed-text-v1.5`)** + asymmetric embedder trait + spawn_blocking dispatch | done |
| 31 | Learned co-access edges (session-close edge inference) | pending — fase 1.5+ |
| 19 | KG storage físicamente separado | **deleted** (Postgres lo cubre) |
| **54–58** | **Git history ingest — Phase 0**: libgit2 walker (filters merges/bots/whitespace), mode A Documents (`ContentKind::Other("commit")` + ChangesFile/Authored edges), mode B synthetic Sessions (commit message → SessionContext, file status → EventType, backdated `created_at`, single-transaction write via `record_synthetic_session`), CLI subcommand `context-engine ingest-git`, integration tests with hermetic fixture repo. Phases 1–4 designed in `docs/11-git-history-plan.md`. | done |

## Orden recomendado

1. ~~Infra Postgres~~ ✅
2. ~~`PostgresStorage` completo~~ ✅
3. ~~Drop trait/MemoryStorage~~ ✅
4. ~~Ranker (reactive + predictive + semantic + alpha + MAD)~~ ✅
5. ~~HTTP API mínima~~ ✅
6. **Wire fastembed real (#11)** — sustituye MockEmbedder.
7. Markdown adapter (#25).
8. **Demo end-to-end del MVP funcionando** con embedder real + curl.
9. Code adapter (#16), PDF adapter (#17).
10. Learned co-access edges (#31, fase 1.5+).

## Métricas de éxito por fase

| Fase | Métrica |
|---|---|
| MVP | Ingest 100 docs (PlainText + Markdown), retrieve devuelve top-5 sano (eval manual) |
| MVP | Latencia retrieval < 100 ms p99 sobre 10k chunks (Postgres + HNSW) |
| MVP+ | Sobrevive crash de postgres + restart sin pérdida de writes confirmados |
| MVP+ | Latencia retrieval < 50 ms p99 sobre 1M chunks (HNSW kicks in) |
| 1.5 | Soporta 10 tenants concurrentes, 100k chunks cada uno, en una sola box |
| 1.5 | API key + ACL filter funcionando + audit log |
