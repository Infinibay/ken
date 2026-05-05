# 02 — Data model

Schema acordado. Pseudo-Rust; los structs reales pueden tener tweaks menores
de naming/derives. Las invariantes son lo que importa.

## Capa 1 — Identidad y origen

```
Tenant            // boundary multi-tenant. ULID global.
  id: TenantId (ULID),
  name, plan, created_at

Workspace         // ámbito de retrieval. Contiene N sources, N docs.
  id: WorkspaceId (u64, monótono per-tenant),
  tenant_id, name, settings, created_at

Source            // de dónde vienen los documentos. Define ingest policy.
  id: SourceId (u64, monótono per-workspace),
  workspace_id,
  kind: SourceKind,
  name, config_json,
  keep_history: bool,
  default_acl: Acl,
  last_sync_at, created_at
```

`SourceKind`: `LocalFs | Http | GitHub | Slack | Confluence | Gmail | S3 |
Manual | Custom(String)`.

**Versionado** (decisión recordada): `keep_history` es **per-Source**. Code
source → `false`. Contracts source → `true`. Ver [06 — Decisions](./06-decisions.md#decisión-versionado).

## Capa 2 — Contenido

### Document

Unidad ingerida. Lo que el humano percibe como "un archivo / un email / un PDF".

```
Document
  id: DocumentId (u64, per-workspace),
  workspace_id, source_id,
  external_id: Option<String>,        // ID en sistema origen (msg_id, sha, page_url, ...)
  kind: ContentKind,                  // CodeFile | Markdown | Pdf | Email | TextBlob | Notebook | ... | Other(String)
  mime: String,
  title: Option<String>,
  path_or_url: Option<String>,
  content_hash: [u8; 32],             // blake3 del contenido normalizado
  version: u64,                       // monótono por (source_id, external_id)
  current: bool,
  replaced_by: Option<DocumentId>,
  acl: Acl,
  metadata: MetadataMap,
  ingested_at: Timestamp,
  source_modified_at: Option<Timestamp>
```

### Chunk

Unidad de retrieval. **Solo el chunk lleva embedding** — el documento agrega
los suyos si hace falta resumen o boost por documento.

```
Chunk
  id: ChunkId (u64, per-workspace),
  document_id, workspace_id,          // workspace duplicado para query path
  kind: ChunkKind,                    // Paragraph | CodeSymbol | EmailMessage | PdfSection | TableRow | ... | Other(String)
  position: ChunkPosition,            // ByteRange | PageLineRange | SymbolRange | MessageIndex | ...
  text: String,
  embedding_id: EmbeddingId,
  metadata: MetadataMap
```

### Entity (fase 1.5+)

Átomo nombrado canónico (persona, función, producto, fecha, ticket, …). Aparece
dentro de chunks vía edges `Mentions`. Permite "todo lo que menciona a Juan".

```
Entity
  id: EntityId (u64, per-workspace),
  workspace_id,
  kind: EntityKind,                   // Person | Organization | Product | CodeFunction | Ticket | Date | ...
  canonical_name: String,
  aliases: Vec<String>,
  metadata: MetadataMap
```

### Edge — el grafo

```
Edge
  id: EdgeId (u64, per-workspace),
  workspace_id,
  from: NodeRef, to: NodeRef,
  kind: EdgeKind,                     // Imports | Cites | Replies | Authored | Mentions | DerivedFrom | SimilarTo | References | Defines | ...
  weight: f32,                        // confianza/fuerza
  metadata: MetadataMap,
  created_by: EdgeOrigin              // Adapter | UrlResolver | Annotator | Background | User
```

### NodeRef

Polimórfico. Puede apuntar a cualquier nodo del grafo o a uno externo aún no
ingerido (late-binding cuando se resuelva).

```
enum NodeRef {
    Document(DocumentId),
    Chunk(ChunkId),
    Entity(EntityId),
    External(String),                 // URI no resuelto todavía
}

// Display / FromStr:  "doc:123" | "chunk:456" | "ent:789" | "ext:https://..."
```

## MetadataMap (híbrido typed + json)

```
MetadataMap {
  // typed-common — indexable, filtrable
  language: Option<Language>,         // Rust | Python | English | Spanish | ...
  author: Option<String>,
  size_bytes: Option<u64>,
  word_count: Option<u32>,
  source_modified_at: Option<Timestamp>,
  tags: Vec<String>,
  // ... un set chico, decidido por uso real

  extra: serde_json::Value            // todo lo type-specific
}
```

Solo los typed-common van a tener índices invertidos. El resto se devuelve al
cliente junto con el chunk (útil para que las plantillas de output formateen
respuestas).

## Capa 3 — Sesión + interacciones (agent-first)

```
Session                               // una "conversación" del agente
  id: SessionId (u64, per-workspace),
  workspace_id, agent_id: Option<String>,
  created_at, ended_at: Option<Timestamp>

SessionContext                        // qué le dijo el agente al engine
  id: ContextId (u64, per-workspace),
  session_id,
  kind: ContextKind,                  // UserInput | ToolResult | StepDescription | Reflection
  content: String,
  iteration: u32,
  embedding_id: EmbeddingId,
  created_at

SessionInteraction                    // qué agarró el agente o qué editó
  id: InteractionId (u64, per-workspace),
  session_id, context_id: Option<ContextId>,
  iteration: u32,
  event_type: EventType,              // Retrieved | Read | Edited | Cited | Dismissed
  target: NodeRef,
  weight: f32,
  was_useful: Option<bool>,           // feedback opcional del agente
  created_at

SessionScore                          // snapshot al cierre de sesión
  session_id, target: NodeRef,
  score, access_count, productivity, pattern: Pattern,
  created_at
```

## ACL — modelo simple

```
Acl {
  visibility: Visibility,             // Public (todo el workspace) | Restricted | Private
  principals: Vec<Principal>          // si Restricted: lista de quienes pueden ver
}
Principal { kind: User | Group, id: String }
```

Filtrado **antes** del ranking, vía bitmap o set por chunk al cargar. RBAC
complejo (roles, herencia) queda como follow-up.

## Pattern — productivity multipliers (extendido)

| Pattern | Multiplier | Significado |
|---|---|---|
| `Cited` | 2.5× | El agente lo devolvió al usuario / lo citó. Señal *fortísima* de utilidad. |
| `ReadEdit` | 2.0× | Read seguido de edit del mismo target. Productivo. |
| `EditOnly` | 1.5× | Edit directo (el agente sabía qué hacer). |
| `Neutral` | 1.0× | Default. |
| `ReadRepeated` | 0.7× | Re-reads sin edit subsecuente. Indicador de confusión. |
| `Dismissed` | 0.3× | El agente lo recibió y descartó. Señal negativa. |

`Pattern` se computa al cierre de sesión via análisis de la secuencia de
`SessionInteraction` por target. Se snapshot a `SessionScore`.

## EventType (eventos en sesión)

`Retrieved | Read | Edited | Cited | Dismissed`. Más se agregarán cuando los
adapters/conectores específicos lo necesiten (e.g., `Replied` para email).

## ContentKind — enum cerrado + escape hatch

```
enum ContentKind {
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
    Other(String),                    // escape hatch para custom adapters
}
```

Misma estructura para `ChunkKind` (`Paragraph | CodeSymbol | EmailMessage | ...
| Other(String)`) y `EntityKind`.

## IDs — convención

| Entidad | Tipo | Justificación |
|---|---|---|
| `TenantId` | ULID (string) | Globalmente único entre customers |
| Todo lo demás | `u64` monótono per-tenant/workspace | Compacto, rápido, indexable |

Un `EmbedKey { owner: EmbedOwner, id: u64 }` resuelve qué tipo de entidad es
dueña del embedding (`Chunk | Document | Entity | SessionContext`).

## Resumen visual de relaciones

```
Tenant ─┬─< Workspace ─┬─< Source ─┬─< Document ─┬─< Chunk ──[Embedding]
        │              │           │             │
        │              │           │             ├─< Edge (intra/cross-doc)
        │              │           │             │
        │              ├─< Session ┴─< SessionContext, SessionInteraction
        │              │
        │              └─< Entity ──< Edge
```
