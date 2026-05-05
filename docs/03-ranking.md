# 03 — Ranking

El ranker es el corazón del producto. Decide qué chunks devolver para un
`(session_id, query)` dado. Idea base levantada de infinidev's
`engine/context_rank/ranker.py`, generalizada al modelo Document/Chunk.

## Contrato de interacción (tool → EventType)

El engine **no conoce las tools del cliente** — ni sus nombres ni su semántica.
Expone un vocabulario fijo de 5 verbos en `EventType`:

| Verbo | Mapeo CRUD | Semántica |
|---|---|---|
| `Retrieved` | R (búsqueda) | Search devolvió este target; el agente todavía no lo consumió. |
| `Read` | R (consumo) | El agente leyó/consumió el contenido. |
| `Edited` | U | El agente modificó el recurso. Implica `Read` previo. |
| `Cited` | señal positiva | El agente citó este target en su output al usuario. |
| `Dismissed` | señal negativa | El agente recibió este target y lo descartó como irrelevante. |

**El cliente mapea sus propias tools a estos verbos.** Por ejemplo:

```rust
// Cliente con toolbelt de email
match tool_call {
    "gmail.search"  => record(EventType::Retrieved, weight=1.0, tool_name="gmail.search"),
    "gmail.read"    => record(EventType::Read,      weight=1.0, tool_name="gmail.read"),
    "gmail.archive" => record(EventType::Dismissed, weight=1.0, tool_name="gmail.archive"),
    "gmail.draft"   => record(EventType::Cited,     weight=2.0, tool_name="gmail.draft"),
}
```

C (Create) y D (Delete) **no aplican al ranker**: los recursos creados son
*outputs* (entran por el pipeline de ingest, no por interactions); los borrados
ya no se rankean.

`tool_name: Option<String>` es **forensics / telemetría** — el ranker nunca lo
lee. Sirve para debug y para futura aprendizaje per-tool en MVP+ (ver D-020).

**Por qué este boundary es crítico**: solo el agente conoce la semántica de
sus propias tools. La misma llamada (`email.archive`) puede ser `Edited`
(cambió de carpeta) o `Dismissed` (sacó de vista) según el workflow. El
engine no puede ni debe decidirlo. Decisión guardada en
`project_tool_event_boundary.md`.

## Estado actual (lo que está implementado)

| Pieza | Archivo | Tests |
|---|---|---|
| `stats` (median, MAD, normal inv-CDF, cosine, exp_decay) | `crates/engine/src/rank/stats.rs` | 14 unit |
| `merge` (alpha blend + max-merge + confidence + MAD filter) | `crates/engine/src/rank/merge.rs` | 11 unit |
| Canal **Reactive** | `crates/engine/src/rank/reactive.rs` | 6 unit + 2 integration |
| Canal **Predictive** | `crates/engine/src/rank/predictive.rs` | cubierto por end-to-end |
| Canal **Semantic** (pgvector ANN) | `crates/engine/src/rank/semantic.rs` | cubierto por end-to-end |
| Public `Ranker` | `crates/engine/src/rank/ranker.rs` | 1 integration end-to-end |

Diferido hasta que exista el code adapter (#16):
- Canal fuzzy-symbol-search.
- Boost de import-graph (1-hop edges).

Diferido para MVP+:
- Boost de co-occurrence (sessions con accesos co-temporales).
- Boost de freshness.
- Per-tool weight learning (sustento ya existe via `tool_name`).

## Channels (señales independientes que se mergean)

Cada channel produce un score por candidato. Mergeo final por `max()` por
chunk, después se aplican boosts y filtros. Esto evita que un chunk gane por
acumular señales débiles — gana por tener al menos una señal fuerte.

### MVP

| # | Channel | Señal | Notas |
|---|---|---|---|
| 1 | **Reactive** | Lo que el agente *tocó en esta sesión* | Decay exponencial por iteración (λ=0.15) + `Pattern.multiplier()` |
| 2 | **Predictive** | Cosine entre query/sesión y `SessionContext`s pasados | Age-filter 180d, weekly decay, sim², productivity multiplier de `SessionScore` pasado |
| 3 | **Semantic** | Cosine entre query simplificada y todos los chunks del workspace | Query pre-filtrada con stop-words; min cosine 0.45 (Chunk), 0.40 (Document-summary) |

### Fase 1.5+

| # | Channel | Señal | Notas |
|---|---|---|---|
| 4 | **Co-occurrence** | Chunks frecuentemente accedidos junto a los top-scored en últimos 90d | Self-join en `SessionScore` |
| 5 | **Graph-proximity** | 1-hop / 2-hop neighbors via Edges | `Imports/Cites/References/Replies/Authored/Mentions` propagan score; pesos por edge_kind |
| 6 | **Freshness** | Boost multiplicativo por recency | `source_modified_at` reciente → 1.0–1.3× |
| 7 | **User-feedback** | Chunks marcados `was_useful=true` en sesiones similares | Boost directo; señal limpia de calidad |

## Pattern multipliers (productivity-aware)

En vez de premiar frecuencia (que mete ruido), pesamos por *patrón de uso*:

| Pattern | Mul | Cuándo |
|---|---|---|
| `Cited` | 2.5× | Agente devolvió/citó el chunk al usuario. Señal *fortísima*. |
| `ReadEdit` | 2.0× | Read seguido de edit. Productivo. |
| `EditOnly` | 1.5× | Edit directo. Sabía qué hacer. |
| `Neutral` | 1.0× | Default |
| `ReadRepeated` | 0.7× | Re-reads sin edit. Confusión. |
| `Dismissed` | 0.3× | Agente lo recibió y descartó. |

Pattern se computa al cierre de sesión via análisis de la secuencia de
`SessionInteraction` por target. Se snapshot a `SessionScore`.

Esta es **la** idea más portable de infinidev — un solo cambio (frecuencia →
patrón) mejoró calidad masivamente.

## Adaptive alpha blending (reactive ↔ predictive)

Channel 1 y 2 representan visiones distintas: "qué está usando el agente
*ahora*" vs "qué le sirvió en sesiones *pasadas*". Si pesamos solo reactive,
cold-start (primera iteración, sin nada en sesión) devuelve nada. Si pesamos
solo predictive, recency bias se pierde.

Solución (de infinidev): **alpha** dinámico:

```
alpha(iteration) = clamp( base_alpha + slope * iteration, 0.0, 1.0 )
score = alpha * reactive_score + (1 - alpha) * predictive_score
```

`base_alpha` arranca chico (~0.2 — pesa más predictive en iter 0); `slope`
positivo → alpha crece y satura cerca de iter 8–12. Resultado: cold-start
funciona, recency emerge naturalmente.

## Confidence gate + MAD outlier filter

Después del merge:

1. **Confidence gate** — si el max score across all candidates < umbral
   configurable (default 0.5), devolvemos lista vacía. Mejor no contestar
   que devolver ruido. (Crítico para el caso "agente pregunta algo
   off-topic".)
2. **MAD outlier filter** — sobre la mitad inferior de scores se calcula
   `Median Absolute Deviation`; cualquier candidato no claramente arriba del
   baseline se podan. Threshold via percentile-tunable (default 95% → ≈2.44×
   MAD).

Ambos vienen de infinidev sin cambios — la matemática es portable verbatim.

## Score normalization across content types

Comparar cosine 0.7 entre dos chunks de código vs dos de prosa no es justo:
distribuciones distintas. Cada `ContentAdapter` declara `ranking_signals()`;
el ranker normaliza usando la distribución observada por kind antes de
mergear cross-type.

Implementación simple para MVP: z-score per-kind sobre los top-N candidatos
del workspace. Más sofisticado (calibración por workspace) queda como
follow-up.

## Pivot-based ranking (cuándo correr)

Re-rankear en cada iteración del agente es caro (cosine sweep). Infinidev
descubrió que basta con re-rankear en *pivots*: iter 0 + cada cambio de step
del agente. En el medio se sirve cache.

Pivot ≈ 48 ms en infinidev. Con Rust + custom DB esperamos llevarlo a < 10
ms. Total por sesión: ~3 pivots × 10 ms = sub-50ms overhead.

## Latencia objetivo (presupuesto)

| Componente | Budget p99 |
|---|---|
| HTTP parse + auth | < 1 ms |
| ACL pre-filter | < 1 ms |
| Embedder (query, una vez por sesión cacheado) | < 30 ms cold, 0 ms cached |
| Channel: reactive | < 2 ms |
| Channel: predictive | < 5 ms |
| Channel: semantic (full workspace cosine sweep) | < 15 ms |
| Channel: graph-proximity (k-hop) | < 5 ms |
| Merge + MAD + confidence | < 1 ms |
| Serialization | < 1 ms |
| **TOTAL p99 retrieve** | **< 60 ms** |

(Asume embedding query cacheado por sesión. Cold path con embedder real
agrega ~30 ms en CPU, < 10 ms con GPU.)
