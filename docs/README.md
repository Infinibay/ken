# context-ai-engine

Engine en Rust para **pre-poblar contexto de manera inteligente** en sistemas
agénticos / semi-automatizados. Pensado para venderse a empresas que quieren
ahorrar tokens (y latencia) en sus pipelines con LLMs: en vez de que el agente
explore desde cero en cada sesión, el engine recuerda qué fue útil antes y
devuelve los chunks más relevantes (código, emails, PDFs, docs, tickets, etc.)
en una sola llamada.

Estado: **diseño + scaffolding del MVP** (mayo 2026).

## Tabla de contenido

| Doc | Contenido |
|---|---|
| [00 — Vision](./00-vision.md) | Problema, solución, target, diferenciadores |
| [01 — Architecture](./01-architecture.md) | Capas del sistema y patrón Adapter (mini-engine por tipo de dato) |
| [02 — Data model](./02-data-model.md) | Schema concreto: Tenant/Workspace/Source + Document/Chunk/Entity/Edge + Session |
| [03 — Ranking](./03-ranking.md) | Channels (reactivo, predictivo, semántico, KG-proximity), alpha blending, MAD |
| [04 — Storage](./04-storage.md) | Backend persistente sobre PostgreSQL + pgvector (decisión D-019) |
| [08 — Schema](./08-schema.md) | Schema SQL completo + decisiones por columna |
| [05 — Roadmap](./05-roadmap.md) | Fases del MVP y estado actual de tareas |
| [06 — Decisions](./06-decisions.md) | Log de decisiones (ADR-style, liviano) |
| [07 — Prior art: infinidev](./07-prior-art-infinidev.md) | Qué levantamos del proyecto previo y qué cambiamos |

## TL;DR

- **Lenguaje**: Rust (performance es diferenciador del producto).
- **Storage**: PostgreSQL + pgvector (decisión D-019). Schema y queries propias optimizadas para los hot paths.
- **Modelo de datos**: genérico (`Document/Chunk/Entity/Edge`), code es una
  *especialización* — no la base. Cada tipo (PDF, email, código, markdown, …)
  tiene su propio "mini-engine" (Adapter) que extrae, parsea, chunkea y
  anota.
- **Embedder**: uno solo (`nomic-embed-text-v1.5` — open source, 768 dim,
  contexto 8192).
- **Knowledge graph**: capa separada con storage propio (CSR/CSC mmap'd) para
  no entorpecer el path de retrieval por documento.
- **Multi-tenant + ACL** desde el día 1.
- **API agent-first**: endpoint principal es `retrieve(session_id, query) →
  top-K mixto` con feedback loop opcional (`was_useful`).
