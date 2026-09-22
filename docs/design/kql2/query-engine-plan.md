# Parser, compilación, optimización y búsqueda

**Plan con implementación parcial.** [Plan principal](implementation-plan.md).
El subconjunto ejecutable figura en [estado actual](implementation-status.md).
La organización actual del código, los puntos de extensión y el profiling
están en [arquitectura del engine](engine-architecture.md).

## Arquitectura que ejecuta hoy

`KQL → parser → validación/compilación → plan → ordenamiento heurístico → ejecución`.
No genera código Python ni traduce la query completa a SQL. El plan es un objeto
tipado/serializable: SQLite recupera candidatos usando índices, mientras el
ejecutor Python interpreta joins, filtros, relaciones, recursión y BODY.
Puede realizar varias consultas SQL por unidad o por binding de un join.

La heurística prioriza roles ligados, nombres exactos y padres disponibles, y
adelanta condiciones cuando sus dependencias lo permiten. No hay todavía un
optimizador global de costes/cardinalidades que compare todos los planes.
Los índices de SQLite sí tienen su propio planificador físico. La cache conserva
unidades, planes y resultados; no archivos Python generados.

El diseño restante de este capítulo no debe confundirse con capacidades ya
ejecutables.

## 1. Los dos parsers

**Fuente:** conservar `frontend.lower_source`/Tree-sitter como punto de entrada
inicial. Separar parsing sintáctico, lowering de instrucciones, resolución y
análisis. El resultado de cada fase declara versión/capacidades; ampliar un tipo
de nodo no habilita automáticamente una garantía de efectos o control.

**KQL:** parser independiente en `ken.kql2.syntax`. Recomendación inicial:
lexer determinista, descenso recursivo para declaraciones/bloques y Pratt para
expresiones. La [EBNF](grammar.ebnf) es una especificación con restricciones
contextuales, no una gramática LL(1) lista para copiar a un generador.

Tareas P10:

1. Token con kind, texto/valor, byte_start/end y SourceId; tabla de líneas para
   mensajes. Mantener offsets UTF-8 y no confundirlos con índices de caracteres.
2. Lexer con modo regex/matcher frente a división, strings JSON, comentarios,
   longest operator, palabras reservadas y límites de profundidad/tamaño.
3. AST inmutable y tipado: File, Pattern, Predicate, Query, Model, Selector,
   Property, CallPattern, SourceExpression, QueryExpression, Body, Gap, Restriction,
   Iteration, Quantifier y Aggregate. No reutilizar `Node(kind,value:Any)` para todo.
4. Distinguir expresión de cálculo de query y expresión de código que se busca.
   `bind` no es store fuente, `let` no es const fuente, `=` no es igualdad lógica.
5. Nodos de error sólo para editor/diagnóstico. La ejecución exige árbol válido;
   jamás saltar un fragmento mal parseado y ejecutar el resto como si fuese la query.
6. Tests de todos los ejemplos completos, AST snapshots y errores con spans;
   fragmentos documentales se prueban con wrappers explícitos.

No empezar por un lexer regex único que trate arbitrariamente `/`, `<T>` y
comparaciones según el orden de alternativas. Fijar casos ambiguos antes de Pratt.
Un grammar Tree-sitter de KQL para editor puede hacerse después; no es requisito
del compilador ni autoriza ejecutar ASTs con recuperación.

## 2. Compilación por fases

P11/P12 producen un programa lógico versionado:

| Fase | Salida | Errores que debe detectar |
|---|---|---|
| Resolve imports | Snapshot de bibliotecas/firmas con hashes | IDs/versiones/exports ausentes o conflictivos |
| Resolve scopes | Symbol IDs de query y captura | Roles no ligados, escapes de rama/negación, inputs faltantes |
| Typecheck | Tipos de cada rol/expresión y firmas instanciadas | Binding vs Value vs Object/Location, propiedades inválidas |
| Capability planning | Obligaciones de análisis por rama/operador | Construcción sintáctica no soportada vs datos semánticos desconocidos |
| Desugar | Núcleo relacional + autómatas y puntos | `next` sin anclas, scopes de fragments, exact con universo incorrecto |
| Dependency/strata | SCCs, orden de estratos, dominios | Recursión negativa/agregada o generadores no finitos |
| Normalize | IR lógico canónico, SourceMap y hash | Pérdida de contexto/claim al normalizar |

La ausencia de una capacidad puede ser rechazo si el engine no implementa el
operador; si el operador existe pero el frontend/modelo no aporta evidencia para
ese ámbito, será unknown/capability_missing. No confundirlo con query inválida.

### Núcleo relacional objetivo

Operadores: `DomainScan`, `RelationScan`, `Filter`, `Project`, `Join`, `Union`,
`SemiJoin`, `ScopedAntiJoin`, `Aggregate`, `OptionalEvidence`, `PatternApply`,
`Fixpoint`, `BodyMatch`, `IntervalCheck`, `IterationMatch`, `Sort`, `Limit`.
Todos declaran:

* Entradas requeridas, salidas producidas y tipos.
* Ámbito, perfil/capacidades y dependencias de cobertura.
* Semántica de multiplicidad/identidad y tratamiento de unknown.
* Dependencias de prueba/contexto/guardas; pureza o errores posibles de cálculo.
* Cardinalidad estimada y acceso físico propuesto, sin convertir estimación en verdad.

Nested `class → method → param` se convierte en scans + owns + filtros. `fields
exact` añade inventario cerrado y comparación de conjuntos distintos. BODY no se
convierte en un AND de «hay estas operaciones en el archivo»: lleva orden,
contexto y autómata. `gap until next` se expande antes de optimizar y congela anclas.

## 3. Evaluador de referencia antes del optimizador

E10 interpreta el núcleo con colecciones pequeñas y estrategias simples,
deterministas. No comparte reescrituras complejas con el optimizador, para que
sirva de oráculo diferencial. Usa el mismo contrato de SnapshotReader, tipos y
pruebas que el backend productivo. Puede ser lento, pero no incompleto por diseño.

Cada fila es `(typed_bindings, truth, guard_context, proof_ref)`. Dos filas con
bindings iguales pueden tener derivaciones diferentes: deduplicar la clave
pública sin mezclar guardas o fragmentos incompatibles. Conservar DAG de pruebas,
conjunciones y alternativas; evitar copiar toda la evidencia en cada join.

Pruebas iniciales con grafos pequeños generados, órdenes permutados y fixtures
fuente con identidades conocidas. Comparar conjunto de bindings, modalidades,
coverage y completitud; no sólo número de matches o strings de explain.

## 4. Optimizador lógico

Implementar O10 con reglas pequeñas y condiciones de aplicación visibles:

1. Propagar igualdades/tipos/constantes y eliminar cláusulas idénticas cuando no
   cambie conteos ni origen de evidencia.
2. Adelantar filtros exactos por nombre/kind/lenguaje/owner y rango numérico
   tipado. Regex se evalúa después del prefiltro seguro; no convertir una regex
   general en búsqueda literal que descarte matches válidos.
3. Proyectar columnas no usadas, conservando claves de correlación, contexto y
   proof IDs requeridos. No eliminar un rol oculto que distingue dos invocaciones.
4. Reducir joins existenciales a semi-joins si su multiplicidad no afecta select,
   aggregate ni evidencia pública requerida.
5. Compartir subexpresiones puras entre reglas; instanciar modelos y entradas
   para especializar búsquedas antes de explorar relaciones completas.
6. Reordenar únicamente conjunciones con dominios y obligaciones equivalentes.
   Mantener barreras para negación, optional, aggregates, BODY, intervals y errores
   parciales. No adelantar división por cero a filas que un filtro válido excluye.

No aplicar leyes de dos valores a unknown. No distribuir una prueba entre ramas
para inventar un testigo. No mover restricciones fuera del callable, loop o
intervalo donde se acreditó coverage. Que una optimización reduzca tiempo no la
habilita si cambia el ámbito de certeza.

## 5. Orden de joins y estadísticas

Estadísticas por segmento inmutable: número de filas, NDV por columna relevante,
frecuencias de heavy hitters, null/knowledge states y correlaciones owner/kind.
Actualizar al publicar; snapshot combina estadísticas con marca exacta/muestreada.
La existencia real de una fila sigue resolviéndose por ejecución.

Primera estrategia: programación dinámica para hasta 8 átomos de join compatibles;
greedy con lookahead para grupos mayores. Umbral configurable y medido; no forma
parte de la semántica. Coste aproximado = filas leídas + filas intermedias + bytes
materializados + construcción de índice + costo de análisis/proof/transferencia.

Estimar filtros sin recorrer exhaustivamente sus resultados durante cada plan:
el conteo exacto actual de `clause_size` es una referencia de semántica, no una
estrategia que deba repetirse para millones de bindings. Usar histogramas o
muestreo etiquetado y caché de estimación por forma/parámetros selectivos.

Si faltan stats: heurística por extremos ligados/índice/selectividad conocida y
coste conservador. Reoptimización al límite de una materialización/lote, nunca a
mitad de una derivación de BODY o un estrato de negación. Stats obsoletas pueden
dar un plan lento, no resultados distintos.

## 6. Ejecución física

Access paths: scan de dominio, B-tree lookup, range scan, adjacency lookup,
hash/index nested-loop join, merge join si hay orden conocido, semijoin,
anti-join con coverage, aggregate hash/ordered, fixpoint worklist y autómata CFG.

SQLite ejecuta filtros/scans o pequeños subplanes relacionales sobre tablas
tipadas; el engine controla truth/coverage, parámetros, contextos y evidencia.
No delegar igualdad tipada al coercion implícito de SQLite. SQL parametrizado;
nombres de tablas/columnas sólo provienen del schema compilado, no texto de usuario.

Procesar lotes iniciales de 4096 filas (tunable) y controlar budgets cada lote y
cada bloque acotado de trabajo en loops intensivos. Cancelación también durante
lecturas SQLite/parse/análisis; no esperar a materializar el grafo completo.
Derramar hash joins/sorts a archivos temporales bajo presupuesto de trabajo.
No recurrir a carga completa de todos los blobs cuando basta una relación.

`Limit` de salida no permite certificar el resto de la query como completo si
el engine se detuvo temprano. Ordenamiento requiere conjunto suficiente para
top-k correcto; optimización top-k sólo con prueba de equivalencia.

## 7. Recursión, BODY y análisis costosos

E11: SCCs positivas, evaluación seminaive de deltas y deduplicación por tupla y
modalidad/contexto. Reutilizar relaciones base y deltas; no relanzar recursivamente
una query Python por cada arista. Dominios finitos, negaciones/aggregates contra
estratos cerrados. Un budget compartido cuenta todo el trabajo de dependencias.

E12: BODY como producto de autómata × CFG × bindings/contexto relevante. Usar
filtros de estructura/operación antes del recorrido; visitar estados ya vistos
sin enumerar todos los caminos. `adjacent` cuenta grupos fuente; saltos sintéticos
se ignoran, instrucciones vacías explícitas no. SourceMap permite explicar eso.

`IntervalCheck(all)` busca violaciones y huecos de coverage entre anclas; necesita
conectividad no vacía. Resúmenes de efectos por callable/región reducen exploración
si acreditan el footprint. `may_write` no se promueve a write inevitable. No
confundir all de conectores con terminación/must_reach.

E13: iteración fuente/item/callback/output/consumo se conecta por el mismo testigo.
Estados configurables usan dominios finitos y contextos de recurso. Flujo entre
funciones exige emparejamiento de llamadas/retornos; contextos finitos se declaran
en el perfil. No basta cierre transitivo sobre aristas VALUE_FLOW sin contexto.

## 8. Explain y profiling

`explain` futuro, sin ejecutar: AST tipado, expansión de azúcar, dependencias,
capabilities requeridas, plan lógico/físico, índices, estimaciones y barreras.
`explain analyze` ejecuta y añade filas reales/descartadas, estados, tiempos,
materializaciones, caché, memoria, desconocidos y causa de stop.

Ambos conservan SourceMap al texto KQL y versionan su formato JSON. Mostrar
`estimated` vs `actual`; stats de una ejecución cacheada no son tiempo de la
ejecución actual. No publicar «0 ms» como velocidad de búsqueda completa por hit.

## 9. Criterios para considerar Rust

Después de baseline y profiling, aislar kernels con costo dominante: intersección
de IDs, joins por lotes, SCC/alcanzabilidad, autómatas e internado. Evitar una
llamada FFI por hecho; definir buffers tipados y ownership de snapshot/proofs.
Parser Python no necesita reescribirse porque un join sea lento.

Un backend nativo debe pasar la misma suite diferencial, cancelación y budgets;
beneficio medido contra overhead de cruce/serialización. Packaging/wheels y
compilación desde sdist constituyen una tarea explícita posterior, no una
dependencia oculta de este plan.
