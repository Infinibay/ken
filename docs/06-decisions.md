# 06 — Decisions log

ADR-style liviano. Cada entrada: contexto, opciones, decisión, rationale,
fecha. Reverse chronological (más reciente arriba).

---

## D-022 — Sin graph DB dedicado: edges viven en Postgres

**Fecha**: 2026-05-05

**Contexto**: Diseñando D-021 (learned co-access edges, task #31) surge la
duda: ¿necesitamos un graph DB tipo neo4j para el grafo de relaciones
aprendidas y las consultas k-hop del canal graph-proximity?

**Decisión**: **No**. Edges se mantienen en la tabla `edges` de Postgres
con índice compuesto `(workspace_id, from_kind, from_id)`. 1-hop es una
query SQL trivial; 2-hop usa `WITH RECURSIVE`; si en escala medimos pain,
**Apache AGE** (extensión de Postgres con soporte Cypher) antes de
considerar un DB separado.

**Rationale**:

1. **Patrón de acceso es shallow.** Ranking quiere "vecinos a 1-hop con
   weight ≥ umbral" — eso es una query indexada en microsegundos, no es
   donde neo4j gana. neo4j brilla en deep traversals (5+ hops) o pattern
   matching estructural; ninguno es nuestro caso.

2. **License blocker.** neo4j Community es **GPLv3**, incompatible con el
   pitch comercial Apache 2.0. neo4j Enterprise es paga. Para un engine
   embebible en SaaS de clientes, no aplica.

3. **Distribuir transacciones.** Sesión termina → snapshot
   `SessionScores` + escribir 50 edges nuevos atómicamente. En Postgres
   es una `BEGIN/COMMIT`. Con neo4j separado, problema de consistencia
   distribuida.

4. **Costo operativo doble.** Backups, replication, monitoring, scaling
   de un sistema más para mantener.

5. **Algoritmos de grafo offline.** PageRank, community detection, etc.
   cuando se necesiten — batch jobs en Rust con `petgraph`/`rustworkx`,
   resultado materializado a tabla `node_scores`. No requieren graph DB
   en hot path.

**Cuándo se revisaría**: 5+ hops como caso común, 100M+ edges activos por
workspace, o pattern queries estructurales como hot path. Si pasa, el
salto natural es **AGE**, no neo4j — mantiene el cluster Postgres único.

**Referencias**: D-019 (elección de Postgres), D-020 (no abstracciones por
flexibilidad hipotética), task #31 (learned edges, primer consumidor del
graph-proximity channel).

---

## D-021 — Ranker generic-first; channels per-tipo son opt-in

**Fecha**: 2026-05-05

**Contexto**: Diseñando el ranker surgió la preocupación: para tipos de
contenido "raros" (emails, tickets, transcripts, CRM) no tenemos intuición
de cómo escribir un ranker bueno, y no hay feedback explícito del usuario
final → ¿el sistema queda como "RAG común y corriente" para esos tipos?

**Decisión**: el ranker se queda con **3 canales genéricos** (semantic +
reactive + predictive). NO se pre-diseñan canales per-tipo. Cualquier
señal type-specific (thread-graph para email, import-graph para código,
page-locality para PDF, …) se agrega como canal adicional **solo cuando
métricas en producción muestren que el default no alcanza** para ese tipo.

**Rationale** — el sistema ya tiene 3 capas de feedback que no requieren
al usuario final:

1. **El agente ES el feedback loop**. `EventType::{Cited, Edited, Read,
   Dismissed}` + `Pattern` multipliers (Cited 2.5×, ReadEdit 2.0×,
   Dismissed 0.3×) capturan utilidad implícita sin intervención humana.
2. **Semantic es content-type agnostic**. pgvector cosine no necesita
   saber el dominio — siempre da un piso de calidad RAG.
3. **Predictive aprende cross-session sin domain knowledge**. Correlaciona
   embedding de query con `productivity` de `SessionScore`s pasados; no
   sabe ni quiere saber si era código o email.

**Implicancia operativa**:
- Default ship: 3 canales, mismos pesos para todos los tipos.
- Loggear `(query, top-K, qué se citó al final, pattern por target)` por
  sesión. Esa es la métrica de calidad por tipo.
- Solo si una clase de queries baja del threshold de calidad, se agrega
  canal custom — y el adapter de ese tipo lo provee, no el core.
- El framework ya lo soporta: `max_merge` toma cualquier `Vec<ChannelHit>`,
  los adapters declaran `ranking_signals()`.

**Lo que NO se hace**: pre-diseñar 8 canales per-tipo "por si acaso". Eso
es exactamente la trampa de la flexibilidad hipotética que llevó a D-020.

**Memory relacionada**: `project_tool_event_boundary.md` (de dónde sale
la señal) + `feedback_supersede_abstractions.md` (no inventar abstracciones
sin demanda real).

---

## D-020 — Drop `Storage` trait + `MemoryStorage`

**Fecha**: 2026-05-04

**Contexto**: Después de implementar `PostgresStorage` completo (D-019)
detrás del trait `Storage`, quedó claro que la abstracción ya no paga su
renta. Originalmente existía para permitir swap entre `MemoryStorage` y un
backend custom (D-018). Al quedar Postgres como backend único — Docker en
local, managed Postgres en prod — el swap dejó de ser real.

**Decisión**: eliminar el trait `Storage` y la impl `MemoryStorage`.
`PostgresStorage` queda como tipo concreto inherente. Tests que necesitan
storage corren contra Docker Postgres vía
`crates/engine/tests/postgres_integration.rs` (env `DATABASE_URL`, gated
`#[ignore]`).

**Rationale**:
- **Costo concreto que pagábamos**: el macro `async-trait` no hace elisión
  de lifetimes en parámetros con vidas implícitas (`dyn FnMut(...)`),
  obligando a contratos `list_chunk_embeddings -> Vec<(_, Vec<f32>)>` que
  fuerzan a clonar 768 floats × N para satisfacer la forma de Postgres.
- 38 métodos CRUD mantenidos en dos impls.
- `MemoryStorage` no cumplía los requisitos ACID/multi-conn que el trait
  documentaba — era una mentira a nivel de trait.
- Al no haber segundo backend planeado, la flexibilidad era hipotética.

**Lo que sobrevive** en `src/storage.rs`:
- `StorageError` / `StorageResult`
- `New*` drafts (`NewSource`, `NewDocument`, `NewChunk`, …)
- `ChunkFilter`, `UpsertOutcome`
- `is_visible(acl, principals)`, `now_millis()`

Estos viven en `src/storage.rs` (no `postgres.rs`) para que callers como
ranker/ingest puedan importarlos sin tocar la dependencia de sqlx.

**Si alguna vez aparece un segundo backend**: en lugar de reintroducir
`Storage` global, diseñar traits chicos *desde el consumidor* — un
`RankerRepo` con los 5 métodos que el ranker llama, un `IngestRepo` con
los del ingest. Interface segregation > defensive abstraction.

**Memory relacionada**: `feedback_supersede_abstractions.md` y
`project_storage_architecture.md`.

---

## D-019 — Backend persistente: PostgreSQL + pgvector

**Fecha**: 2026-05-04

**Contexto**: Después de D-018 (definir el bar ACID + multi-conn), había
que elegir CÓMO cumplirlo. Tres caminos en juego: A) custom puro, B)
embedded (redb/sled) puro, C) híbrido (redb + slabs custom). Después de
revisarlo de nuevo, el usuario propone una cuarta opción: **PostgreSQL**.

**Por qué PostgreSQL gana sobre las tres anteriores**:
1. **Construir DB ACID propia es inviable** a tiempos de MVP startup.
   D-018 ya documentaba esto; opción A descartada definitivamente.
2. **`pgvector`** da búsqueda vectorial con HNSW e IVFFlat. Mejor que
   nuestro cosine sweep brute-force a partir de ~50k chunks. Soluciona
   el caso "embedding slab" sin código custom.
3. **`tsvector` + GIN index** da full-text search built-in. **Regalo**:
   un canal extra del ranker (BM25/keyword) sin código nuestro.
4. **JSONB** + índices GIN: cubre `metadata.extra`, configs opacas,
   enums con `Other(String)`. Postgres lo indexa y consulta eficiente.
5. **Recursive CTEs**: 1-hop / 2-hop traversal para el KG sin código
   custom. Si en escala pinta lento, **Apache AGE** (extensión postgres)
   da Cypher-on-postgres. Mejor que mantener un store CSR custom.
6. **Row-Level Security**: ACL multi-tenant a nivel DB (cuando los
   clientes lo pidan).
7. **Madurez operacional**: backups, replication, point-in-time recovery,
   monitoring, métricas — todo resuelto. **Las empresas ya operan
   postgres**, no hay fricción de adopción.
8. **MVCC**: readers no bloquean writers. Multi-conn nativo.

**Trade-offs aceptados**:
- Pierde el pitch "DB 100% propia". Replanteado: el diferenciador es
  el **engine encima** (ranker + adapters + KG + agent-first API), no
  la persistencia. Pitch revisado: "Engine sobre Postgres tuneado para
  retrieval agéntico".
- Latencia: ~50–200µs de overhead de red por query (vs in-process). Despreciable
  comparado a embedder o cosine sweep.
- Dependencia operativa: cliente necesita Postgres ≥14 con pgvector.
  Aceptable — todos lo tienen ya.

**Lo que sobrevive**:
- Trait `Storage` (contrato estable). `MemoryStorage` para tests.
- Adapters, Ranker, Annotator, API HTTP, todos los tipos del modelo.

**Lo que se descarta**:
- Custom WAL + snapshots + replay (Postgres ya lo hace).
- Embedding slab mmap'd custom (pgvector + HNSW gana).
- KG storage físicamente separado con CSR mmap'd (tabla `edges` +
  índices alcanza para MVP; AGE en fase 2 si hace falta).
- Opciones B y C de D-018.

**Schema base**: definido en `docs/08-schema.md`. Migraciones en
`crates/engine/migrations/`.

**Stack Rust**: `sqlx` 0.8 + `pgvector` 0.4, ambos detrás de cargo
feature `postgres` en `cae-engine`. `testcontainers-rs` para integration
tests.

**Implicancia en el trait**: `Storage` debe convertirse a `async fn` en
trait (Rust 1.75+). Se hace cuando se implemente `PostgresStorage`.
`MemoryStorage` se vuelve trivialmente async (futures inmediatos).

**Tasks**: #10 reescala a "PostgresStorage impl + migrations". #19
(KG separado) descartada. Nuevas tasks para conversión async del trait
y para el impl real.

---

## D-018 — Persistent Storage debe ser ACID + multi-thread + multi-conn

**Fecha**: 2026-05-04

**Contexto**: Después de revisar el primer `MemoryStorage` (in-memory, volátil,
single-method-atomic), el usuario marcó como crítico que la DB del producto
debe ser **ACID, multi-thread y multi-conexión**. Esto es requisito de venta
a empresas, no negociable.

**Definición operativa de "ACID + multi-conn" en este proyecto**:
- **A**tomicity: transacciones multi-op con rollback (e.g. ingestar un
  Document + sus Chunks + sus Embeddings + sus Edges en una sola unidad).
- **C**onsistency: invariantes referenciales (chunks↔documents,
  embeddings↔owners, version chains) preservados ante crash.
- **I**solation: snapshot isolation como mínimo; MVCC preferido (readers no
  bloquean writers).
- **D**urability: fsync-on-commit. Tiers configurables (Strong / GroupCommit
  / Eventual) OK siempre que "committed = sobrevive crash" sea verdad para
  Strong y GroupCommit.
- Multi-thread: `Send + Sync` real, sin global locks que serialicen todo.
- Multi-conn: muchos clientes concurrentes (HTTP server con N requests),
  cada uno con su tx aislada.

**Estado actual**: `MemoryStorage` **NO** cumple A/D y solo cumple I de
manera trivial ("read-latest"). Se mantiene como backend de tests y para
desbloquear el desarrollo upstream (adapters, ranker, API), pero no va a
producción.

**Opciones evaluadas para el backend persistente** (a decidir cuando se
empiece la implementación, ver D-019 cuando se tome la call):
- **A — Custom puro**: WAL + MVCC + recovery propios. 3–6 meses de un
  senior + cola larga de bugs por años. Pitch "DB 100% propia" puro.
- **B — `redb` o `sled` puro como backend único**: ACID gratis y
  battle-tested, pero los hot paths (cosine sweep + KG traversal) sufren
  porque esos engines no están optimizados para slabs columnares de f32 ni
  CSR.
- **C — Híbrido (recomendado)**: `redb` como ACID kernel para metadata
  (Tenants/Workspaces/Sources/Documents/Chunks/Sessions/Contexts/
  Interactions/Scores/Edges/Entities) + storage propio para el embedding
  slab (mmap'd columnar, SIMD cosine) + storage propio para el KG (CSR/CSC
  adjacency mmap'd). Ship en semanas, no meses. Diferenciación técnica vive
  donde realmente importa (hot paths). Pitch comercial honesto: "DB tuneada
  al uso del engine, con storage propio para los hot paths y un kernel ACID
  embebido pure-Rust para garantías transaccionales".

**Decisión**: el requisito ACID + multi-conn es **no negociable** para todo
backend persistente. Implementación se difiere — primero MVP (adapters +
ranker + API) sobre `MemoryStorage`. La implementación del backend
persistente queda en task #10 con el bar elevado a estos requisitos.

**Implicancia en el contrato actual**: la trait `Storage` se mantiene como
está (ningún cambio de API hoy). Cuando se necesite agrupar operaciones
atómicamente desde el caller (probablemente al implementar el path de
ingest), se agrega un método `transaction()` o un wrapper closure-based
sin romper la API actual.

---

## Decisión: Pattern extendido con `Cited` y `Dismissed`

**Fecha**: 2026-05-04

**Contexto**: El `Pattern` enum de infinidev era code-céntrico
(`ReadEdit/EditOnly/ReadRepeated/Neutral`). En un engine generic-over-types
agent-first, hay dos señales nuevas que valen oro: cuando el agente *cita*
un chunk al usuario (lo devolvió como respuesta) y cuando lo *descarta*
(`was_useful=false`).

**Opciones**:
1. Mantener Pattern original, derivar señales nuevas a otro lado.
2. Extender Pattern con `Cited` y `Dismissed`.

**Decisión**: Opción 2. `Cited` con multiplier 2.5×, `Dismissed` con 0.3×.

**Rationale**: Pattern es justamente "qué hizo el agente con esto". `Cited`
y `Dismissed` son acciones del agente — caben perfectamente en la abstracción
y dan al ranker señal directa de utilidad. Mantener todo en una sola
dimensión (el multiplier) hace la matemática del ranker más simple.

---

## Decisión: `ContentKind` cerrado + `Other(String)` escape hatch

**Fecha**: 2026-05-04

**Opciones**:
1. Enum cerrado (cada adapter nuevo requiere variant nueva en core).
2. String libre (cada adapter elige su discriminator).
3. Enum cerrado con `Other(String)` (ambos mundos).

**Decisión**: Opción 3.

**Rationale**: Los tipos canónicos (`CodeFile | Email | Pdf | Markdown |
PlainText | ...`) merecen exhaustividad type-checked porque el ranker y
queries hacen pattern-match sobre ellos. Pero el escape hatch permite
adapters custom (de usuarios o de fases futuras) sin requerir bump del
core.

---

## Decisión: `NodeRef` como enum + `Display`/`FromStr`

**Fecha**: 2026-05-04

**Contexto**: Edges referencian Documents, Chunks, Entities, o externos
no-ingestados-todavía. Necesitamos un tipo poly que sea type-safe en Rust pero
serializable de forma uniforme en API.

**Opciones**:
1. Tagged tuple `(NodeKind, u64_or_string)`.
2. Enum + `Display`/`FromStr` que serializa a `"doc:123"` / `"chunk:456"` /
   `"ent:789"` / `"ext:https://..."`.

**Decisión**: Opción 2.

**Rationale**: Type-safe en Rust (impossible-state-impossible), uniforme en
API. Display compacto y human-readable. FromStr permite parsing en queries
HTTP sin schemas complejos.

---

## Decisión: IDs — ULID para Tenant, `u64` para todo lo demás

**Fecha**: 2026-05-04

**Opciones**:
1. UUID/ULID en todos los niveles (uniforme, peor compresión).
2. ULID solo en `Tenant`, `u64` per-tenant para todo lo demás.

**Decisión**: Opción 2.

**Rationale**: Tenant es el único nivel donde necesitamos uniqueness global
(no queremos colisiones entre customers). Dentro de un tenant, secuencias
monótonas u64 son suficientes y mucho más compactas (8 bytes vs 16+) — clave
porque vamos a tener miles de millones de chunks/edges por tenant grande.

---

## Decisión: KG storage separado del main DB

**Fecha**: 2026-05-04

**Contexto**: El grafo de conocimiento podría vivir como una "tabla más" en
el main DB.

**Opciones**:
1. Misma DB, mismo storage engine.
2. Storage propio (CSR/CSC adjacency files mmap'd) en directorio aparte.

**Decisión**: Opción 2.

**Rationale**: Patrón de acceso de queries grafo (k-hop traversal, neighbor
lookup) es muy distinto al de queries de chunk (filter + cosine sweep).
Compartir storage significa compartir locks → contention. CSR/CSC es el
layout óptimo para grafo y meterlo en el log-structured store es perderlo.
Performance + locking + claridad de modelo. Trade-off: dos backends para
mantener. Aceptable.

---

## Decisión: Embedder único — `nomic-embed-text-v1.5`

**Fecha**: 2026-05-04

**Contexto**: ¿Mismo embedder para código y texto, o uno por dominio?

**Opciones**:
1. Embedder único (MiniLM, BGE-small, nomic, ...) para todo.
2. Embedder por tipo (CodeBERT/Codestral para código, MiniLM para prosa).

**Decisión**: Opción 1, con `nomic-embed-text-v1.5`.

**Rationale**: Mezclar espacios vectoriales agrega complejidad masiva
(distintos dim, distintas distribuciones, normalización cross-space) sin
beneficio comprobado para nuestra escala. nomic-embed-text-v1.5 es Apache
2.0, soporta contexto largo (8192) — cubre PDFs sin chunkear demasiado
fino, anda bien en código (mejor que MiniLM/BGE-small en MTEB code subsets),
multilingual razonable.

---

## Decisión: Versionado per-Source (`keep_history: bool`)

**Fecha**: 2026-05-04

**Contexto**: Algunos contenidos necesitan historial (contratos legales),
otros no (código actual).

**Opciones**:
1. Historial siempre (caro).
2. Historial nunca (perdemos auditoría).
3. Per-Source: flag en `Source.keep_history`.

**Decisión**: Opción 3.

**Rationale**: Source es la unidad natural — un cliente puede tener su Git
source con historial off y su Contracts source con historial on. Embeddings
viejos se dropean por default; opcional retenerlos para citas a versiones
específicas. Default seguro: `false` (no historial).

---

## Decisión: Engine es dueño de la extracción (no upstream)

**Fecha**: 2026-05-04

**Contexto**: ¿El engine acepta solo texto-listo-para-embedder, o también
parsea PDFs/DOCX/etc?

**Decisión**: El engine extrae. PDFs, DOCX, código, etc. son parseados por
los Adapters internos.

**Rationale**: El cliente no debería preocuparse por cómo limpiar texto de un
PDF. Adapter por tipo simplifica la API (mandás bytes + mime, te devuelve
chunks listos), permite optimización per-tipo (PDFs con layout, código con
AST, email con header parsing), y preserva metadata estructural que se
perdería si el cliente normalizara a texto plano.

---

## Decisión: Modelo de datos genérico (no code-céntrico)

**Fecha**: 2026-05-04

**Contexto**: La primera versión de `types.rs` copiaba el schema de
infinidev (`File/Symbol/Import`). Eso ataba el engine al caso "código" y
no escalaba a PDFs/emails/etc.

**Decisión**: Modelo genérico Tenant/Workspace/Source + Document/Chunk/
Entity/Edge. Code se vuelve una *especialización* (Document.kind=CodeFile,
Chunk.kind=CodeSymbol).

**Rationale**: El producto se vende a empresas que tienen mucho más que
código. Atar el schema al caso código ahora cuesta mucho refactor después.
Generalizar antes de implementar lógica encima vale el doble-trabajo en
`types.rs` (que era apenas 263 líneas).

---

## Decisión: Adapter pattern (mini-engine por tipo de dato)

**Fecha**: 2026-05-04

**Contexto**: Cada tipo de dato (PDF, email, código) se estructura distinto.
¿Un parser genérico que intenta cubrir todo, o uno por tipo?

**Decisión**: Trait `ContentAdapter`, una impl por tipo. Cada adapter declara
qué señales aporta al ranker y qué edges puede emitir.

**Rationale**: Imposible que un parser genérico extraiga símbolos de código
*y* respete layout de PDF *y* parsee headers de email. La especialización
está donde está el valor — el resto del engine (ranker, storage) consume el
modelo unificado de salida.

---

## Decisión: Rust + custom DB

**Fecha**: 2026-05-04 (constraint inicial del usuario)

**Rationale**: Performance es diferenciador comercial. SQLite es genérico;
nuestro patrón de acceso (cosine sweeps, append-heavy interactions, joins
fijos) merece storage tuneado. Ver [04 — Storage](./04-storage.md).
