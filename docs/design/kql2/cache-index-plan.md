# Caché, índices y performance desde el primer corte

**Plan, no implementación.** [Plan principal](implementation-plan.md).
Los objetivos de rendimiento de este documento no son resultados ya medidos.

## 1. Presupuesto único y clases de memoria

`cache_budget_mb=500` por proyecto, MB decimales. Incluye datos retenidos en el
store KQL2, índices/estadísticas, artefactos y copias retenidas en memoria, contadas
por separado. No asignar 500 MB independientes a cada capa. El coordinador reparte
el presupuesto; punto de partida: hasta 80% almacenamiento persistente y 20%
memoria retenida, con préstamo de capacidad libre entre ambos y límites explícitos.

Tres cuentas distintas y visibles:

| Cuenta | Qué incluye | Qué ocurre al agotarse |
|---|---|---|
| Retención/caché | DB/índices/páginas libres asignadas + objetos retenidos entre consultas | Evict/no admitir, sin modificar resultados |
| Trabajo de request | Batches, hash tables, autómatas, extracción, snapshots activos no retenibles | Spill o incomplete con motivo |
| Overhead temporal de disco | WAL/journal, rebuild, backups y spills | Checkpoint/cleanup/backpressure; error claro si no cabe |

El límite de caché no es límite de RSS total ni del tamaño transitorio del
directorio. Medir además `working_memory_mb`, `temporary_disk_mb`, RSS real,
SQLite page cache y WAL. Un buffer no deja de ser retenido por renombrarlo
«working»: al terminar el último usuario debe liberarse o imputarse al presupuesto.

`cache_budget_mb=0`: no abrir/escribir el store persistente para memoización;
usar reader/store de trabajo temporal, destruido al terminar. Sin cache no significa
«sin índices»: los índices necesarios para esa ejecución son trabajo efímero.

Un snapshot más grande que el presupuesto no se persiste completo a la fuerza.
Se construye/consulta en almacenamiento temporal con el mismo contrato, pudiendo
reutilizar units retenidas. Si tampoco cabe el trabajo permitido, devolver
incomplete/resource_exhausted; nunca eliminar filas para que parezca caber.

La caché legacy se administra separadamente durante transición. La versión nueva
debe informar sus bytes y evitar retener dos caches completas por default: retirar
legacy al abandonar KQL1, o asignarle una cuota explícita de compatibilidad dentro
del presupuesto gestionado. Un binario viejo ejecutado independientemente no
obedece el coordinador nuevo; la coexistencia debe señalar esa limitación.
Backups de migración son temporales, con bytes/política de retiro visibles.

## 2. Qué cachear y con qué clave

| Artefacto | Clave mínima | Invalidación |
|---|---|---|
| Tokens/AST KQL | Dialecto, bytes, versión de parser | Texto/parser |
| Programa tipado | AST canónico, imports/exports, firmas/modelos, semántica compilador | Cambio transitivo de biblioteca/schema |
| Plan físico | Programa lógico, shape/selectividad de inputs, stats revision, perfil/optimizador | Cambio de stats relevante o backend |
| Unit fuente | Path/namespace, bytes hash, lenguaje/grammar/lowering/config | Edición/rename/frontend |
| Segmento de análisis | Producer/version, inputs, dependencias, modelos, perfil | Callee/alias/namespace/capability cambiado |
| Índice/materialización | Segmento inmutable, layout/schema, relación/columna | Segmento o layout |
| Resultado | Semántica query+dependencias, snapshot, inputs, perfil/modelos | Cualquier dependencia semántica incluida |

Contextos de scopes y de llamadas forman parte de las claves: un resultado para
un método no se reutiliza en otro con el mismo nombre. El AST canónico elimina
formato/comentarios sólo donde no cambian significado; SourceMap del usuario se
conserva aparte. Un plan no reutiliza referencias a tokens/roles de otra query.

Primera versión: resultados por snapshot completo, como frontera conservadora.
Después, resultados por partición sólo si existe certificado de dependencias.
Una query negativa depende también de archivos/símbolos **que podrían aparecer**,
no sólo de los hechos que sí encontró. Registrar fingerprint de universo de
resolución/cobertura; ante incertidumbre invalidar por snapshot.

No servir un outcome incompleto como negativo. Se pueden guardar diagnósticos o
progreso incompleto con su estado para reanudación, sin convertirlo en completo.
Planes fallidos por error determinista de sintaxis pueden cachear diagnóstico por
hash de texto/parser; errores de disco o budgets no son errores permanentes de query.

## 3. Admisión, evicción e invalidación

* Empezar con LRU por artefacto/segmento y cuotas; añadir peso por costo de
  reconstrucción sólo después de medir. No implementar una política sofisticada
  antes de garantizar invalidación y contabilidad.
* Batches de actualización de `last_used`; no una transacción SQLite por hit.
* Admitir una entrada sólo si cabe tras reserva. Evict artefactos fríos primero,
  luego snapshots sin lectores y segmentos sin referencias; mantener integridad
  del cierre de snapshot y nunca borrar una arista aislada de un snapshot publicado.
* Queries activas fijan componentes por handles. Datos fijados que excedan cuota
  se liberan al terminar; no se fuerzan dentro de retención ni se pierden a mitad.
* Cache misses concurrentes iguales usan single-flight por clave/version para
  evitar reconstrucciones duplicadas. Un request cancelado no cancela trabajo aún
  requerido por otros; la cuenta de usuarios controla su vida.
* Invalidation dirigida sólo con dependencias acreditadas. MVP: reuse units y
  rebuild del enlace/análisis global. Eliminación de hechos o cambios en negación
  requieren recomputación de SCC/estratos afectados, no sólo añadir un delta.
* SQLite page_count × page_size forma parte de la cuenta, incluidos free pages.
  Compactar incrementalmente en mantenimiento, con costo y WAL visibles; no hacer
  VACUUM de toda la DB por cada inserción/evicción.

## 4. Índices persistentes iniciales

Cada índice tiene una consulta objetivo y un test de equivalencia. No indexar
todas las permutaciones de todas las columnas. Las PK/UQ del schema ya aportan
algunos access paths y no deben duplicarse por costumbre.

| ID | Tabla/columnas propuestas | Consulta que acelera |
|---|---|---|
| X01 | `k2_units(path,source_hash,frontend_hash)` cubierto por clave de identidad completa | Reuse de archivo; conservar lenguaje/config en comprobación final |
| X02 | `k2_nodes(kind,name_tid,unit_id,term_id)` | Clase/método/campo con nombre exacto |
| X03 | `k2_nodes(owner_tid,kind,term_id)` | Miembros y operaciones de un owner |
| X04 | `k2_nodes(scope_tid,kind,term_id)` | Bindings por scope/shadowing |
| X05 | `k2_nodes(unit_id,start_byte,end_byte)` | Ámbito fuente y evidencias localizadas |
| X06 | `k2_edges(segment_id,relation_id,subject_tid,object_tid,modality)` vía UQ | Aristas salientes y comprobación exacta de ambos extremos |
| X07 | `k2_edges(segment_id,relation_id,object_tid,subject_tid,modality)` | Entrantes, callers y productores |
| X08 | `k2_properties(segment_id,key_id,value_tid,subject_tid)` | Filtros por atributo escalar conocido |
| X09 | `k2_properties(segment_id,subject_tid,key_id,value_tid)` vía UQ | Propiedades de un candidato |
| X10 | `k2_tuple_args(term_id,position,tuple_id)` | Join a relación n-aria con un argumento ligado |
| X11 | `k2_tuples(segment_id,relation_id,tuple_id)` | Tuplas de un contrato en un snapshot |
| X12 | `k2_coverage(segment_id,subject_tid,relation_id,scope_key)` | Certificado de cierre/unknown para negación |
| X13 | `k2_dependencies(dependency_kind,dependency_key,consumer_segment)` | Invalidación inversa, incluidas dependencias de universo |
| X14 | `k2_artifacts(kind,last_used,artifact_key)` | Evicción por clase/recencia |

X01 es candidato: no crear si el UNIQUE completo ya cubre los prefijos usados.
X10 puede requerir proyección caliente con relation_id para evitar una búsqueda
global por un literal muy común. Justificar con perfil; no duplicar relation_id
sin constraint/validación que mantenga concordancia con k2_tuples.

Todas las lecturas restringen membership del snapshot. Un nodo/edge viejo existente
en la DB no es evidencia del snapshot actual. Operaciones filtradas por owner
deben comprobar también unidad/contexto cuando la relación lo requiere.

Nombres regex: primer filtro por kind/owner/language; igualdad y prefijo seguro
pueden usar índice adicional sobre texto normalizado **compatible con flags**.
Regex sin prefijo usable se evalúa sobre candidatos. No prometer que B-tree
acelera `/.*name.*/i` ni sustituirlo por FTS con tokenización diferente.

## 5. Índices en memoria y especiales

Construir bajo demanda para segmentos calientes: adjacency forward/reverse,
maps de tipo/owner, bitsets de membership y tablas de intersección de IDs.
Representación compacta con arrays/IDs; no otra copia completa de todos los Fact
como objetos Python. Comprobar costo de construir el índice frente a una sola
lectura SQL antes de admitirlo a caché.

Para BODY/CFG: índice por `(callable,context,point)` y adjacency inversa; SCC del
CFG y reachability local memoizados. Dominadores/resúmenes sólo cuando se piden,
con invalidación por región/analysis fingerprint.
No materializar cierre transitivo de todo el grafo por default: puede ocupar O(V²).
Consultas recurrentes pueden usar summaries/condensation DAG y cierre parcial
por origen/objetivo bajo presupuesto, conservando modalidad y contextos.

Para escrituras/efectos: índice por Location/Object y punto/callable, con posibles
aliases y cobertura. Filtrar por footprint antes de recorrer un intervalo;
ausencia de bucket no certifica que no haya efecto desconocido.

El contrato de `FactIndex.rows` actual devuelve un bucket candidato. El nuevo
reader debe distinguir `candidate_scan` de `exact_scan` o documentar siempre
residual filters. Sus tests comparan conjuntos finales contra full scan tipado.

## 6. Performance como dependencia, no fase final

Añadir a I00 un harness que se reutilice desde E10/S11. En cada PR futuro de un
operador/índice: fixture de correctitud, contador de trabajo y benchmark asociado.
No esperar a migrar los 33 TOML para descubrir productos cartesianos o carga total.

Familias mínimas de carga:

| ID | Carga | Riesgo/medida |
|---|---|---|
| B01 | Nombre exacto dentro de un owner pequeño en proyecto grande | No leer/materializar todo el grafo |
| B02 | Dos/tres joins con alta selectividad y heavy hitters | Orden de join, fan-out y costo de stats |
| B03 | Conteo/negación con dominio completo e incompleto | Coverage y cero no confundidos |
| B04 | Cadena >32, ciclo y SCC densa | Deltas, dedup y explosión de cierre |
| B05 | BODY con 0/20/100 instrucciones neutras y adjacent | Costo por región y semántica de intercalación |
| B06 | Intervalo protegido con aliases y llamadas externas | Summaries, unknown y contraejemplos |
| B07 | Lote de catálogo con dependencias compartidas | Compilar/reutilizar una vez, pruebas compactas |
| B08 | Editar un archivo, agregar símbolo, borrar callee, cambiar modelo | Invalidation exacta/conservadora y trabajo evitado |
| B09 | Caché 0, pequeña, 500 MB y snapshot mayor que el presupuesto | Correctitud/evicción/spill/RSS |
| B10 | Dos lectores, writer, query cancelada y mantenimiento | Latencia, WAL y single-flight sin bloqueos largos |

Tamaños sintéticos de referencia: 10k/100k/1M nodos, con relaciones y skew
declarados; no confundir número de archivos con tamaño del IR. Completar con
repositorios reales congelados y queries/claims verificables. Los fixtures
pueden generar datos de grafo; el corpus real valida costos no representados allí.

Contadores deterministas para CI: unidades reparseadas, relaciones consultadas,
filas inspeccionadas, tamaño máximo de join, estados de autómata/SCC, bytes
materializados/serializados, índices creados, misses y dependencias invalidadas.
Ejemplo de gate: B01 selectivo no puede hacer un scan de todas las relaciones
ni reconstruir el grafo para cada query. No fijar un tiempo frágil en tests unitarios.

Objetivos iniciales de laboratorio (a calibrar tras I00, no promesas): consulta
estructural selectiva caliente sobre 100k nodos, <1000 candidatos útiles, p95
≤250 ms; costo de planificación caliente ≤10% del total salvo queries triviales.
Medir por separado el primer query que construye índices. Ajustar objetivos con
hardware/fixtures publicados; no degradar perfiles para cumplirlos.

## 7. Frío, caliente y frescura

Reportar al menos cuatro caminos:

1. Fuente → parse/lower → store → análisis → query: frío completo.
2. Snapshot persistido, proceso nuevo: frío de proceso sin reparse.
3. Snapshot/plan/índices retenidos: caliente; indicar si fue memo de resultado.
4. Actualización incremental: descubrir cambios → hash → unit(s) → enlace/análisis
   afectados → query. Incluir archivos añadidos/eliminados.

`freshness=snapshot` consulta una revisión fijada y publica su manifiesto/edad;
`freshness=live_verified` verifica fuente y posibles cambios de universo antes de
declarar actual. Son modos de adquisición, no de semántica de query. Un watcher
puede acelerar descubrimiento, pero pérdida de eventos/overflow obliga a reconciliar.
mtime/tamaño por sí solos no prueban igualdad de bytes. Coste de verificación y
lectura de archivos se informa, no se esconde fuera de los benchmarks.

Warm no debe incluir a escondidas reconstrucción fuera del cronómetro. Cache hit
de resultado no mide velocidad del evaluador. Medir p50/p95, muestras crudas, RSS,
DB/WAL/temp, page faults si disponibles, tamaños de lotes y distribuciones de datos.

## 8. Antipatrones de implementación a evitar

* Descomprimir/deserializar un JSON de proyecto entero por consulta selectiva.
* Crear todos los índices al abrir, aunque no se usen, o volver a crearlos por regla.
* Escanear exactamente cada cláusula para estimar su costo para cada binding.
* Repetir parse/compile de todas las dependencias por cada variante de catálogo.
* Copiar dicts grandes de evidencia por fila intermedia en un join.
* Traversal sin visited/contexto finito o cierre global materializado sin necesidad.
* Escribir timestamps en DB por cada hit, serializando lectores detrás de LRU.
* Invalidar sólo archivos cambiados cuando cambió resolución/negación global.
* Contar sólo payload comprimido y olvidar índices, páginas, objetos y WAL.
* Usar un timeout/limit como si mejorara una ejecución completa.

Cada optimización necesita prueba diferencial. Cuando la semántica es desconocida,
la salida correcta y rápida puede ser unknown; nunca un falso certificado de seguridad.
