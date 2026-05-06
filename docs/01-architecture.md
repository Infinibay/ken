# 01 — Architecture

## Capas del sistema

```
┌──────────────────────────────────────────────────────────────────┐
│                            API HTTP/gRPC                          │
│  /v1/sources  /v1/documents  /v1/sessions/:id/retrieve  /events   │
└──────────────────────────────────────────────────────────────────┘
                                │
┌──────────────────────────────────────────────────────────────────┐
│                          ENGINE CORE                              │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │  Ingest    │  │  Ranker    │  │  Session   │  │  Annotator │  │
│  │  (orchest) │  │ (channels) │  │   state    │  │ (URLs/IDs) │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
└──────────────────────────────────────────────────────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌────────────────┐   ┌────────────────┐   ┌────────────────────┐
│   Adapters     │   │   Embedder     │   │   Storage layers   │
│ (per content   │   │ (nomic-embed-  │   │  - main custom DB  │
│   type)        │   │   text-v1.5)   │   │  - KG store (sep)  │
└────────────────┘   └────────────────┘   └────────────────────┘
```

- **API**: HTTP+JSON para MVP, gRPC follow-up. Multi-tenant via header
  `X-Tenant-Id` o token JWT.
- **Engine core**: orquesta. No conoce formatos de input ni físico de storage.
- **Adapters**: traducen `RawDocument` (bytes + metadata) → modelo genérico
  (`Document/Chunk/Edge/Entity`).
- **Embedder**: vectoriza. Único modelo en MVP, con trait que permite swap.
- **Storage**: dos backends — main DB para Document/Chunk/Session, KG store
  aparte para edges (separación por patrón de acceso, ver [04](./04-storage.md)).

## Patrón Adapter (mini-engine por tipo de dato)

**Premisa**: cada tipo de dato (código, PDF, email, …) se estructura distinto y
se relaciona con otros tipos distinto. Forzar un único parser/chunker pierde
señal. Pero el modelo de salida (Document/Chunk/Edge) sí es uniforme — eso es
lo que el ranker consume.

### Pipeline interno de un Adapter

```
RawDocument (bytes + source_uri + mime hint + hint_metadata)
        │
        ▼
   [Extractor]    bytes → texto + estructura cruda
        │           (PDF→páginas, DOCX→XML, code→AST, email→headers+body)
        ▼
   [Parser]       texto crudo → unidades semánticas tipadas
        │           (Symbol, EmailMessage, PdfSection, MdHeading, Paragraph)
        ▼
   [Chunker]      unidades → Chunks con position + metadata
        │           (granularidad depende del tipo — ver 02-data-model.md §5)
        ▼
   [Annotator]    agrega Entities + Edges
        │           (intra-doc: imports, headings; cross-doc: URLs, IDs, mentions)
        ▼
   [Embedder]     Chunks → vectores (request batched al embedder global)
        │
        ▼
   IngestOutput { document, chunks, entities, edges, embed_requests }
```

### Trait

```rust
trait ContentAdapter: Send + Sync {
    fn kind(&self) -> ContentKind;
    fn accepts(&self, hint: &MimeHint) -> bool;
    fn ingest(&self, raw: RawDocument, ctx: &IngestContext) -> Result<IngestOutput>;

    /// Qué tipos de señales aporta este adapter al ranker.
    fn ranking_signals(&self) -> &'static [SignalKind];
    /// Qué tipos de edges puede emitir.
    fn relation_kinds(&self) -> &'static [EdgeKind];
}
```

### Set de Adapters por fase

| Fase | Adapter | Extractor | Chunker | Edges propias |
|---|---|---|---|---|
| MVP | PlainText | identity | paragraph + token-window | URLs, mentions |
| MVP | Markdown | `pulldown-cmark` | por heading + section-aware | URLs, links, headings-as-anchor |
| MVP | Code (Rust/Python/TS) | identity | per-symbol via tree-sitter | Imports, Defines |
| MVP | PDF | `pdf-extract`/`lopdf` | por página / sección detectada | Citations (regex), URLs |
| 1.1 | Email | `mail-parser` | un mail = un Document (decisión 5) | Reply-to, Authored, Mentions |
| 1.5 | DOCX | `docx-rs` | por heading | URLs, mentions |
| 1.5 | HTML/Web | readability-style | semantic blocks | Links, mentions |
| 2 | Slack/Confluence/Jira | JSON pre-estructurado | por mensaje/página/ticket | References, Replies, Authored |
| 2 | CSV/Sheet | identity | por fila | (referencias semánticas) |

Agregar un Adapter nuevo = nuevo crate `adapter-{tipo}` que implementa
`ContentAdapter`. El engine los descubre via registry.

## Edges entre tipos (donde está el valor del KG)

Tres mecanismos de edge-creation:

1. **Intra-Adapter** — el adapter emite edges nativos a su tipo (Imports en
   code, Reply-to en email, Cites en PDF).
2. **URL/identifier resolver** (engine-side, corre sobre todo chunk) —
   extrae URLs (`*.atlassian.net`, `github.com/.../pull/N`,
   `slack.com/archives/...`), tickets (`ABC-1234`), PR refs (`#42`),
   `@menciones`. Resuelve contra Documents/Entities existentes en el mismo
   workspace; los unresolved quedan como `External(uri)` y se promueven a
   edge interno cuando el target se ingiere después.
3. **Semantic neighborhood** (background job, fase 2) — pares de chunks con
   cosine alta cross-type se conectan con `SimilarTo`. Caro; corre offline.

## Embedder

Modelo por defecto: **`all-MiniLM-L6-v2`** (Apache 2.0), variante cuantizada
(`AllMiniLML6V2Q`).

| Propiedad | Valor |
|---|---|
| Dimensiones | 384 |
| Contexto máximo | 256 tokens |
| Multilingual | Pobre (mayormente EN) |
| Performance código | Aceptable; menor que nomic en prosa larga |
| Distribución | Disponible vía `fastembed-rs` |

El modelo anterior (`nomic-embed-text-v1.5`, 768 dims) era demasiado pesado
para máquinas dev modestas (~280 MB residentes). MiniLM-L6 ronda los ~80 MB
y corre 5–10× más rápido en CPU. La migración `0005` redujo las columnas
`vector(768)` → `vector(384)` cuando se hizo el cambio.

Trait `Embedder` permite swap. MVP usa `MockEmbedder` determinista para tests
(no requiere modelo descargado). Server enable feature `fastembed` para
producción.

## API agent-first (esbozo)

Endpoint estrella:

```
POST /v1/sessions/:id/retrieve
{
  "query": "estoy debuggeando por qué falla auth de Stripe",
  "top_k": 10,
  "filters": { "kinds": ["CodeFile", "Email", "Pdf"], "since": "..." }
}

→ 200 OK
{
  "results": [
    { "node_ref": "chunk:1832", "score": 0.91,
      "document": { "title": "stripe_auth.rs", "kind": "CodeFile", "path": "..." },
      "excerpt": "...", "why": ["semantic", "reactive(0.4)"] },
    { "node_ref": "chunk:9210", "score": 0.78,
      "document": { "title": "Re: Stripe webhook 401s", "kind": "Email", ... },
      ... },
    ...
  ],
  "feedback_token": "fb_..."   // se usa para POST /retrieve/:fb_token/feedback
}
```

Feedback loop: agente reporta `was_useful: bool` → alimenta la columna
`was_useful` de `SessionInteraction`. Señal directa de calidad para el ranker.
