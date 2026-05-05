# 07 — Prior art: infinidev

## Qué es infinidev

Repo en `/home/andres/Proyects/infinidev/`. CLI agéntico Python para hacer
útiles a LLMs open-weight chicos (7–14B) en hardware consumer. Diseño base:
"asumí que el modelo se confunde fácil; coachealo".

**Pieza relevante para nosotros**: `engine/context_rank/`. Sistema multi-canal
que recuerda qué archivos/símbolos/findings le sirvieron a sesiones pasadas
para tareas similares y los pre-popula en futuras.

## Qué levantamos verbatim

Estas ideas son matemática portable a Rust sin cambios:

1. **Productivity multipliers** (`logger.py:329–335`)
   `read+edit=2.0×, edit-only=1.5×, repeated-read-no-edit=0.7×`. Cambio del
   modelo de "frecuencia" a "patrón" mejoró calidad masivamente.
   Nosotros lo extendemos con `Cited=2.5×` y `Dismissed=0.3×` (señales
   adicionales agent-first).

2. **Adaptive alpha blending** (`ranker.py:358–359`, `_compute_alpha:1390–1408`)
   El alpha que pondera reactive vs predictive empieza biased a predictive
   (cold-start cubierto) y satura a reactive (recency emerge). Una fórmula
   resuelve dos problemas.

3. **MAD outlier filter sobre la mitad inferior**
   (`ranker.py:1429–1492`). Cómputo de MAD en bottom-half evita que los
   outliers altos contaminen el baseline. Threshold via percentile-tunable.

4. **Confidence gate** (`ranker.py:383–399`)
   Si el max score < umbral, mejor no contestar que devolver ruido.
   Crítico para queries off-topic.

5. **Stop-word-filtered query embeddings** (`ranker.py:792–846`)
   Para búsqueda semántica de símbolos: filtrar stop-words conversacionales
   con Zipf-frequency concentra la query en tokens distintivos.

6. **Per-iteration context snapshots** (`logger.py:220–252`)
   Almacenar *qué* le pidieron al agente en cada step, no solo *qué hizo*.
   Permite matching de futuras tareas por intención.

7. **Pivot-based ranking invocation** (`hooks.py:34–154`)
   No re-rankear cada iteración; solo en pivots (iter 0 + cambios de step).
   El resto sirve cache. Reduce overhead drástico.

## Qué cambiamos / extendemos

| Aspecto | infinidev | context-ai-engine |
|---|---|---|
| **Lenguaje** | Python | Rust |
| **Storage** | SQLite + WAL + thread-local pool | DB propia: WAL append-only + slabs mmap'd + KG aparte |
| **Modelo de datos** | `File/Symbol/Import/Finding` (code-céntrico) | `Document/Chunk/Entity/Edge` (genérico, code es un Adapter) |
| **Tipos de dato** | Solo código + findings | Code + PDF + Markdown + Email + DOCX + tickets + ... (cada uno con su Adapter) |
| **Embedding storage** | BLOB en SQLite (deserializar c/query) | Slab mmap'd, slice directo a `&[f32]` |
| **Embedder** | ChromaDB ONNX runtime (CPU) o MNN (10× más rápido) | `fastembed-rs` con `nomic-embed-text-v1.5` (768d, contexto 8192) |
| **Knowledge graph** | Solo import-graph (file→file) | KG real con storage propio: Imports, Cites, Replies, Authored, Mentions, References, SimilarTo, ... |
| **Tenancy** | Single-user CLI local | Multi-tenant desde day 1 (aislamiento físico por tenant) |
| **API** | No tiene (es CLI) | HTTP+JSON (gRPC follow-up) |
| **Feedback loop** | Inferido de patterns | Explícito (`was_useful: bool` en `SessionInteraction`) |
| **ACL** | N/A | Simple ACL desde day 1 (pre-filter en query path) |
| **Versionado** | No | Per-Source (`keep_history: bool`) |

## Pain points de infinidev que resolvemos

De `FEATURE.md` y notas de instrumentación:

1. **Embeddings CPU bottleneck**: ~115 ms/query en CPU baseline; reducible a
   11 ms con MNN runtime. → En Rust con `nomic-embed-text-v1.5` esperamos
   < 30 ms cold, < 5 ms warm con batching. Cosine sweeps con SIMD.

2. **DB connection setup**: 1812 ms → 12 ms con thread-local pool. → No
   tenemos connections; es in-memory + mmap.

3. **Synchronous file indexing**: 478 ms → 0.18 ms con background queue.
   → Mismo patrón en Rust con `tokio::sync::mpsc` para IngestQueue.

4. **`between_llm_calls` gap**: ~4754 ms → ~1704 ms tras optimizaciones.
   → Engine externo: el agente paga solo el costo del retrieve (< 60 ms p99).

## Lo que NO levantamos

- **Coaching/guidance system** de infinidev (`engine/guidance/`). Ese es el
  CLI; nuestro engine no se mete con la lógica del agente. Devuelve
  contexto, el agente hace lo que quiere.
- **AnalystPlanner / LoopEngine**: orquestación específica de infinidev.
- **Tools de infinidev** (`tools/`): específicos al CLI.
- **TUI / classic CLI**: nosotros no tenemos UI, solo API.

## Reférencia rápida de archivos relevantes en infinidev

| Path | Qué tiene |
|---|---|
| `engine/context_rank/ranker.py` | 10 channels, merge `max()`, MAD filter, confidence gate |
| `engine/context_rank/hooks.py` | Pivot-based invocation, background task-embedding |
| `engine/context_rank/logger.py` | Productivity multipliers, `cr_session_scores` snapshots |
| `db/service.py` | Schema actual: `cr_*`, `ci_*`, `findings`, `findings_fts` |
| `code_intel/indexer.py` | tree-sitter ingestion (lo levantamos para el Code Adapter) |
| `code_intel/symbol_embeddings.py` | Embedding strings: `"{kind} {name} — {docstring|signature}"` |
| `FEATURE.md` | Performance notes, optimizaciones logradas |
