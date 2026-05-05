# 00 — Vision

## Problema

Cada vez que un sistema agéntico (Claude Code, Cursor, Devin, agentes custom de
empresa, …) arranca un task, redescubre los mismos archivos, mensajes,
documentos y findings desde cero. Eso quema:

1. **Tokens** — cada exploración (read file, grep, search) infla el contexto.
2. **Latencia** — el usuario espera mientras el agente "ve" la base.
3. **Calidad** — modelos chicos se confunden cuando la ventana se llena de
   ruido exploratorio.

A nivel empresa, además, el conocimiento está disperso: parte en código, parte
en Confluence, parte en hilos de Slack, parte en PDFs de un drive, parte en
tickets viejos. Nadie tiene un substrato unificado de contexto.

## Solución

**context-ai-engine** es un substrato de retrieval optimizado para agentes:

- Las empresas ingieren su corpus heterogéneo (código + docs + emails + PDFs
  + tickets + …) por una API.
- Los agentes le piden contexto relevante a la sesión actual con una sola
  llamada.
- El engine devuelve top-K **mixto** (un email + dos chunks de código + una
  sección de PDF, todos rankeados con un score comparable) y aprende de qué
  fue útil para mejorar futuras respuestas.

## Target

- **Empresas con sistemas agénticos internos** (cualquier vertical).
- **Vendedores de plataformas de agentes** (B2B2B) que necesitan un retrieval
  layer agnóstico.
- **Equipos de ML / Platform** que arman copilots internos con conocimiento
  propio.

No es un producto consumer ni una herramienta de developer individual.

## Diferenciadores

1. **Performance Rust + DB propia** — latencia p99 baja, costo por query
   bajo. Vector DBs genéricas (Pinecone, Weaviate, …) son optimizadas para
   pure-vector retrieval; nosotros optimizamos para retrieval híbrido
   (vector + grafo + filtros + señales de sesión).
2. **Knowledge graph real** — relaciones tipadas entre cualquier par de
   nodos (no solo embeddings + filtros). Permite "todo lo relacionado con
   este PR" cubriendo email, tickets, docs y código en una traversal.
3. **Pre-population vs retrieval** — además del retrieval clásico
   (query → top-K), el engine prepara contexto *anticipado*
   (sesión + iteración → contexto a inyectar). Esto viene del
   `context_rank` de infinidev y es lo que más tokens ahorra.
4. **Adapter pattern** — cada tipo de dato tiene su propio mini-engine que
   sabe cómo extraer estructura, qué señales aporta al ranking y qué edges
   produce. Agregar un tipo nuevo es una crate, no un fork.
5. **Productivity-aware ranking** — en vez de premiar frecuencia (que es
   ruido), premia *patrón* (qué hizo el agente con eso: lo citó, lo editó,
   lo descartó). Vinieron ideas de infinidev, generalizadas.
6. **Agent-first API** — feedback loop nativo (`was_useful`), single-call
   retrieval cross-type, sesión es first-class no afterthought.

## Inspiración

- **infinidev** (`/home/andres/Proyects/infinidev/`): nuestro propio prior art.
  El módulo `engine/context_rank/` es la base conceptual del ranker. Ver
  [07 — Prior art](./07-prior-art-infinidev.md).
- **Glean / Sana / Mendable**: RAG-as-a-service con conectores empresa.
  Nuestro diferenciador es agent-first + KG real + Rust.
- **Cody (Sourcegraph)**: ranking de código con repo-graph. Nosotros lo
  generalizamos más allá de código.
