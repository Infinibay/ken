# Plan de implementación del sistema KQL 2

**Plan objetivo.** Revisión 0.1, 14 de septiembre de 2026.
La implementación posterior es parcial y está registrada en
[implementation-status.md](implementation-status.md); esa tabla es la autoridad
sobre progreso, no la mera existencia de un módulo o de sintaxis parseable.
Complementa la [definición del lenguaje](README.md) y concreta seis componentes:
parser, almacenamiento/migraciones, optimizador, evaluación, caché e índices.
Los módulos, tablas y comandos nombrados aquí describen el objetivo; no todos
están disponibles en el bootstrap experimental.

## 1. Decisiones de arquitectura

1. Mantener Tree-sitter para parsear **código fuente**. Crear un parser propio
   para **consultas KQL 2**, separado de los extractores de lenguajes fuente.
2. Almacén estructural SQLite independiente, con schema versionado, datos tipados
   y snapshots inmutables. No utilizar un JSON comprimido del proyecto completo
   como única representación consultable.
3. Evaluador híbrido: SQLite selecciona/reúne conjuntos indexados; operadores
   propios resuelven recursión, BODY, conocimiento, efectos y evidencia. No
   intentar traducir toda la semántica a un SELECT SQL gigantesco.
4. Empezar con Python para parser, compilador y evaluador de referencia. Representar
   filas con IDs enteros y lotes para habilitar un backend nativo posterior.
   Rust es una optimización sujeta a profiling, no requisito para empezar.
5. KQL 1 sigue disponible. La nueva base no reemplaza `.ken/ken.db` ni se usa
   desde el parser viejo. La compatibilidad de lenguaje y de almacenamiento son
   versiones distintas.
6. El grafo persistido sigue siendo **reconstruible** desde fuente/modelos. El
   presupuesto de caché KQL 2 incluye ese almacenamiento, sus índices y los demás
   artefactos retenidos. Si un proyecto no cabe, no se le asigna falsamente ausencia
   de resultados: se evalúa con almacenamiento de trabajo temporal o queda incomplete.

## 2. Punto de partida comprobado en el código

| Área | Implementación actual | Implicación |
|---|---|---|
| DB principal | [db.py](../../../src/ken/db.py), [schema.sql](../../../src/ken/schema.sql) | `.ken/ken.db` tiene `ci_*`, `cr_*`, FTS y meta; no es descartable en conjunto |
| Migraciones principales | `init_schema` ejecuta schema y `_migrate` agrega columnas/índices/triggers | No existe ahí un ledger up/down del nuevo almacén; no copiar el catch genérico de OperationalError |
| Caché estructural | [cache.py](../../../src/ken/structural/cache.py) | `.ken/structural-cache.sqlite`: `entries(key,value,size,touched)`, JSON+zlib, journal DELETE, LRU, 500 MB decimales |
| Construcción | [service.py](../../../src/ken/structural/service.py) | Reutiliza unidades por contenido y grafo por manifiesto; vuelve a enlazar si cambia el proyecto |
| Parser y engine | [kenql.py](../../../src/ken/structural/kenql.py) | Lexer regex, AST de cláusulas, planificación local, caminos y named queries del dialecto 1 |
| Índices | [model.py](../../../src/ken/structural/model.py), `FactIndex` | Buckets por relación y extremos/atributos bajo demanda; candidato no equivale a intersección exacta |
| Reglas/resultados | [rules.py](../../../src/ken/structural/rules.py) | Fingerprint incluye dependencias; memo de resultados por grafo completo |
| Packaging | [pyproject.toml](../../../pyproject.toml) | Python/Hatchling, sin extensión Rust obligatoria |

No hacer drop de `.ken/ken.db`: contiene memorias `cr_findings`, sesiones,
interacciones y referencias que no se regeneran a partir de las fuentes.
Los IDs de símbolos/vector slots tienen además vínculos y triggers propios.
El cambio de almacenamiento estructural no requiere migrar ese conjunto.

## 3. Documentos de ejecución para el implementador

| Componente | Contrato y tareas |
|---|---|
| Parser, compilador, optimizador, búsqueda | [query-engine-plan.md](query-engine-plan.md) |
| Tablas, snapshots, escritura, upgrade/down/rebuild | [storage-plan.md](storage-plan.md) |
| Cachés, índices, presupuesto, invalidación, benchmarks | [cache-index-plan.md](cache-index-plan.md) |
| Semántica que deben respetar | [language.md](language.md), [behavior.md](behavior.md), [ir-and-evaluation.md](ir-and-evaluation.md) |
| Datos/tipos del programa | [code-model.md](code-model.md) |
| Catálogo | [migration.md](migration.md) |
| Primeros oráculos del lenguaje | [conformance.md](conformance.md), C001–C096 |

## 4. Límites entre módulos propuestos

```text
src/ken/kql2/
  syntax/          lexer, tokens, AST, parser, spans, diagnostics
  compiler/        scopes, types, imports, desugaring, logical IR, capabilities
  optimizer/       statistics, rewrites, join order, physical planner, explain
  execution/       operators, batches, recursion, BODY, effects, evidence, budgets
  library/         schema and public semantic/model signatures

src/ken/structural_store/
  connection       connection/transaction policy; independent of main DB
  migrations/      numbered migrations + checksums + validation/rollback
  schema           typed schema manifest, not CREATE IF NOT EXISTS only
  writer           immutable units/segments, manifests and publication
  snapshot         read handles, pinning, version/capability checks
  relations        typed scans and hot projections
  statistics       statistics per immutable segment/snapshot
  cache            shared accounting, retention, eviction and artifact keys
  maintenance      rebuild, recovery, GC and verification
```

Son responsabilidades y rutas sugeridas, no obligación de un archivo por clase.
No poner el parser dentro del store ni llamar Tree-sitter desde el optimizador.
No importar metadata de GoF desde un operador genérico del engine.

Interfaces objetivo, firmas documentales:

```text
parse(text, source_id) -> SyntaxTree | Diagnostics
compile(tree, library_snapshot, capability_schema) -> LogicalProgram | Diagnostics
prepare(logical_program, statistics, execution_profile) -> PhysicalPlan
acquire_snapshot(manifest, analysis_profile) -> SnapshotHandle
scan(snapshot, relation, bindings, predicates) -> BatchStream
execute(plan, snapshot, inputs, budget, cancellation) -> ResultStream + Outcome
publish(staging_snapshot, expected_parent) -> PublishedSnapshot
```

Parse/compile no crean DB ni escanean el proyecto. SnapshotHandle fija schema,
manifiesto, modelos y perfil. Los lotes son inmutables, IDs tipados y máscaras de
conocimiento; no listas de dicts de strings en el hot path como API obligatoria.

## 5. Etapas y dependencias

Los IDs sirven para dividir el trabajo. Consultar el estado enlazado para saber
qué parte de cada tarea está implementada y qué falta para cerrarla.

| ID | Entrega concreta | Depende de | Criterio de salida |
|---|---|---|---|
| I00 | Inventario congelado y corpus de referencia con hashes | — | Versiones y resultados KQL 1 guardados; sin inventar baseline de KQL 2 |
| P10 | Lexer/parser con AST y spans | I00 | Gramática y diagnósticos; no acepta/ignora construcciones desconocidas |
| P11 | Imports, scopes, tipos, firmas y capabilities | P10 | C001–C020 y errores de modelo; ningún query inválido crea caché |
| P12 | Desugaring a núcleo relacional y autómatas | P11 | Explain muestra roles/intervalos equivalentes; adjacent/next inequívocos |
| S10 | Runner de migraciones estructurales y storage vacío | I00 | Up/down/fresh/crash con fixtures aislados; DB principal intacta |
| S11 | Unidades, términos, relaciones, snapshots y reader | S10 | Roundtrip de identidades/tipos/evidencia y transacciones |
| S12 | Adaptador frontend → segmentos y capacidades | S11 | Reparse selectivo; normalización no convierte datos parciales en must |
| E10 | Evaluador relacional de referencia, sin optimizaciones | P12, S11 | Joins, alternativas, negación/cuentas con oráculos pequeños |
| O10 | Estadísticas, índices iniciales y planes físicos | E10, S11 | Equivalencia reference/optimized; planes sin productos evitables |
| E11 | Recursión positiva, estratos y modelos | E10 | SCCs, >32 saltos, finite domains; rechazo de ciclos no admitidos |
| E12 | BODY, scopes/llamadas, adjacent e intervalos | P12, E10, S12 | C021–C052; excepciones/loops y efectos desconocidos correctos |
| E13 | Iteración, flujo/estado y contextos | E11, E12 | Contratos por lenguaje/modelo, no «todos soportados» por parser |
| C10 | Presupuesto, caché de planes/resultados y mantenimiento | S11, E10 | Caché fría/caliente/0 equivalente, recuento de bytes correcto |
| S13 | Actualización incremental conservadora | S12, C10 | Edits/add/delete/model changes equivalentes a reconstrucción |
| O11 | Optimización de BODY/SCC y particiones calientes | O10, E11, E12 | Mismo conocimiento/evidencia; reducción medida de trabajo |
| V10 | Migrar bibliotecas y catálogo por claims | E12, E13 | Positivos/negativos/unknown y comparación por roles |
| V11 | Benchmarks reales, recovery y distribución | O11, S13, V10 | Matriz de aceptación debajo, Linux/macOS |

Primer corte utilizable: P10–P12 + S10–S12 + E10 + O10 + C10. Sólo búsquedas
estructurales del subconjunto acreditado; no declarar BODY completo aún.
Segundo corte: E11/E12 con efectos conservadores. Tercero: E13 y catálogo fuerte.

## 6. Lo que se prueba por componente

| Componente | Pruebas futuras necesarias |
|---|---|
| Parser | AST snapshots, precedencia, source/query expressions, bytes Unicode, errores recuperables, EOF, profundidad, regex/comentarios |
| Store | IDs, scalars bool/int/null separados, aridad, FKs, materializaciones, scopes, snapshots, publicación CAS y fallo de disco |
| Migraciones | Fresh/up/down/up, migración repetida, checksum cambiado, schema futuro, rollback, dos writers, lectores activos, legacy corrupto |
| Optimizer | Permutar joins, datos sesgados, estadísticas ausentes/viejas, exact vs candidate indexes, unknown, errores aritméticos, evidencia disyuntiva |
| Engine | Reference differential, SCC/ciclos, contextos de llamada, BODY/adjacent, alias, gaps, excepción/finally, cancellation y límites |
| Cache | Key dependency closure, memoria/disco, eviction/pins, 0, oversized snapshot, cache poisoning, negativos tras archivo nuevo |
| Indexes | Cada access path devuelve superset correcto; residual filters; huella/costo; materializaciones consistentes al publicar |
| Integración | CLI/MCP mismo resultado, daemon/watchers, dos versiones, downgrade, reglas propias y memorias conservadas |

No ejecutar código descargado del corpus para escanearlo. Compilar fixtures de
lenguajes fuente, cuando proceda, es una validación distinta y explícita del parser.

## 7. Métricas y definición de terminado

* Correctitud: mismo conjunto de bindings y modalidad que el evaluador de
  referencia; resultados incompletos nunca cuentan como negativos.
* Migración: repetir una migración no modifica datos de usuario; fallar antes de
  publicación conserva el snapshot anterior; up después de down reconstruye.
* Incremental: después de cada edición, iguales resultados/coverage que rebuild
  bajo mismo perfil. Medir archivos reparseados y segmentos recalculados.
* Rendimiento: p50/p95 de fases separadas, CPU, RSS pico, bytes DB/WAL/temp/caché,
  filas/estados, aciertos y evicciones. Cinco o más repeticiones, muestras crudas
  publicadas; p95 con pocas muestras se etiqueta como descriptivo.
* Presupuesto: el perfil interactive opt-in de 3000 ms puede devolver incomplete;
  no es una promesa de completar cualquier query en 3 s. Batch no tiene timeout
  implícito, pero sigue atendiendo cancelación y errores de recursos.
* Regresiones: comparar consultas equivalentes con KQL 1 y versiones sucesivas.
  Propuesta de gate inicial: investigar regresión mediana >20% que exceda 20 ms,
  no hacer fallar CI por un único sample; nunca compensar menor precisión con velocidad.
* Distribución: Python puro primero; si profiling justifica Rust, ABI de batches,
  wheels Linux/macOS y sdist con toolchain se planifican como entrega separada.
  No cambiar Hatchling o exigir compilación nativa antes de esa decisión.

## 8. Orden para ejecutar un futuro encargo

Empezar por I00, P10 y S10 como tareas delimitadas. Después validar interfaces
con un único patrón estructural y una base pequeña. Mantener snapshots de salida
del evaluador de referencia antes de optimizar. Ninguna etapa autoriza borrar
almacenamientos de usuario ni declarar toda la especificación implementada.

Este documento no ejecuta migraciones, no crea tablas de producción, no cambia
el parser ni corre benchmarks nuevos. Los detalles de cada entrega están en los
planes enlazados arriba.
