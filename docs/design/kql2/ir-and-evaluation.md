# Contrato IR, conocimiento y evaluación

Propuesta 0.1; no implementada. [Índice](README.md).

Este capítulo fija la semántica. Su implementación propuesta se desarrolla en
el [plan del sistema](implementation-plan.md), con detalles de
[persistencia](storage-plan.md), [ejecución](query-engine-plan.md) y
[caché/índices/performance](cache-index-plan.md). Esos planes deben conservar
los contratos de conocimiento, contexto y evidencia definidos aquí.

## 1. Frontera entre lenguaje y análisis

El parser sólo entiende consultas. El frontend conserva sintaxis y semántica
nativa. Los análisis producen relaciones con garantías. Las bibliotecas definen
conceptos sobre esas relaciones. El catálogo selecciona conceptos y explica su
alcance. No introducir una arista especial por cada patrón para eludir un hueco
en el lenguaje o en los análisis generales.

Pipeline objetivo:

```text
fuentes → AST por lenguaje → instrucciones/valores/lugares/regiones
       → resolución + CFG + flujo + efectos + modelos → relaciones tipadas

KQL 2 → AST de consulta → resolución/tipos/capacidades
      → núcleo relacional + autómatas BODY/intervalos
      → plan/indexación/punto fijo → coincidencias + evidencia + cobertura
```

No es obligatorio reemplazar el almacenamiento por una base Datalog ni usar Rust
para adoptar este contrato. El lenguaje define resultados, no una tecnología.
Una implementación optimizada debe producir los mismos resultados/evidencias
observables que el evaluador de referencia del subconjunto correspondiente.

## 2. Entidades e identidades mínimas

| Entidad | Identidad y distinción esencial |
|---|---|
| Declaration/Binding | Archivo, revisión, ámbito y declaración; shadowing separa IDs |
| Value | Definición/ocurrencia y contexto; retornos de dos llamadas no se unifican por destino |
| Object | Identidad abstracta de asignación/objeto externo más contexto, con grado de precisión |
| Location | Slot, campo de una instancia o elemento con clave/índice, no sólo el nombre del campo |
| TypeRef | Tipo fuente estructurado, metadatos nativos y estado de resolución |
| Operation | Evento semántico con operandos, resultado y grupo fuente |
| Point | Antes/después de una operación con clase de salida y contexto |
| Region | Región de control con entradas/salidas, callable propietario y relaciones padre |
| Fragment | Testigo de operaciones/intervalos correlacionados con entrada y salida |
| Iteration | Fuente, item, cuerpo/callback, salida, consumo, cardinalidad y contexto |
| Argument/ArgumentPack | Ocurrencia en llamada; paso/posición/mapeo a Parameter independientes |
| Task/Lock | Contextos de ejecución y sincronización, no inferidos de un nombre |

Tipos fuente `unknown` y `any` no reemplazan `Knowledge<TypeRef>`. Un dato puede
ser conocido, conjunto de candidatos o desconocido. Un miembro de clase requiere
receptor para obtener Location. Aliases pueden compartir Object y conservar
Bindings diferentes. Copia superficial comparte hijos; copia profunda exige
modelo de footprint y ciclos. Move Rust no equivale a copia ni a alias mutable.

## 3. Familias de relaciones públicas objetivo

Estas firmas definen obligaciones de la biblioteca `ken.core`; no afirman que
el IR 1.77 las provea todas. Implementar una firma exige contrato y fixtures.

| Familia | Ejemplos de firmas |
|---|---|
| Estructura | `owns(Entity,Entity)`, `member_of(Field,TypeDecl)`, `declares(Module,Entity)` |
| Tipos | `type_of(Entity,TypeRef)`, `subtype(TypeRef,TypeRef)`, `instantiates(TypeRef,TypeDecl)` |
| Llamadas | `target(Operation,Callable)`, `possible_call(Callable,Callable)`, `argument(Operation,Argument)`, `argument_value(Argument,Value)` |
| Estado | `reads(Operation,Location,Value)`, `writes(Operation,Location,Value)`, `points_to(Value,Object)` |
| Procedencia | `reaches_definition(Value,Point)`, `value_flow(Value,Value)`, `taint_step(Value,Value)` |
| Control | `cfg_edge(Point,Point)`, `dominates(Point,Point)`, `postdominates(Point,Point)`, `must_reach(Point,Point)` |
| Efectos | `may_write(Operation,Location)`, `must_write(Operation,Location)`, `escapes(Object,Region)` |
| Colecciones | `lookup(Operation,Value,Value,Value)`, `insert(Operation,Value,Value,Value)`, `remove(Operation,Value,Value)` |
| Iteración | `iteration_source(Iteration,Value)`, `iteration_item(Iteration,Value)`, `produces(Iteration,Value,Value)`, `output_of(Iteration,Value)` |
| Concurrencia | `task_of(Operation,Task)`, `happens_before(Point,Point)`, `guards(Lock,Location)` |
| Módulos | `imports(Module,Entity)`, `exports(Module,Entity)`, `resolves_to(Entity,Entity)` |

Accesores escalares parciales (`name`, `owner`, `type_of` en forma funcional,
`value_at`) sólo devuelven valor si éste es único en el perfil solicitado.
Ausencia o ambigüedad produce `Option<T>` o unknown según la firma, nunca un valor
elegido arbitrariamente. `stable_id` siempre existe para entidades identificadas.

Constructores de footprint como `binding($b)`, `object($o)`, `elements($c)` y
`member($o,$f)` en restricciones son descriptores tipados de ubicaciones/estado;
no ejecutan métodos del objeto fuente. `object` admite Object o Value cuya
identidad de objeto sea resoluble; Value escalar es error de tipos.

## 4. Resultado lógico y evidencia

Cada obligación tiene resultado `true`, `false` o `unknown` sobre un perfil
de análisis declarado. Lógica fuerte de Kleene: `not unknown = unknown`,
`false and unknown = false`, `true or unknown = true`; el resto propaga unknown.
Un patrón con una derivación verdadera se satisface aunque otras sean desconocidas.
La disyunción conserva pruebas separadas; no agrega mitades de una derivación.

Una ausencia sólo es falsa si el universo y relación relevantes están cerrados.
Ejemplo: el archivo parseado puede tener inventario completo de campos directos;
eso no cierra posibles escrituras a esos campos desde código externo.
Para refutar una garantía universal basta un contraejemplo acreditado; un efecto
posible no resuelto sólo impide confirmarla. Los predicados explícitos de
posibilidad (`may_write`, `possible_call`) afirman pertenencia al modelo, no hechos
inevitables. Esa diferencia aparece en la evidencia y no se convierte en must.

Estados públicos independientes:

* `match`: contrato satisfecho sobre el perfil indicado.
* `candidate`: obligaciones desconocidas, incluidas en modo de candidatos.
* `no_match`: dominio solicitado enumerado, sin prueba ni candidato aplicable.
* `complete`: si terminó la enumeración solicitada; distinto de verdad semántica.
* `results_truncated` / `evidence_truncated`: límites de salida/pruebas, separados.

Si hay candidatos y ningún match, no etiquetar toda la búsqueda como `no_match`.
El modo estricto muestra sólo matches pero conserva conteo/razones de candidatos;
lista vacía no oculta cobertura desconocida. Una query inválida produce error
antes de escanear; frontend/capacidad faltante producen diagnóstico de ámbito.

Todo resultado lleva: versión del lenguaje, schema del IR, perfil, versiones de
modelos, fuentes/revisiones, bindings tipados, variantes, operaciones/anclas,
testigos y obligaciones desconocidas. Una negativa explicable identifica dominio
y certificado de completitud, no sólo «se encontraron cero aristas».

Razones mínimas: `unsupported_language_feature`, `partial_parse`,
`unresolved_call`, `alias_unknown`, `effects_unknown`, `open_world`,
`iteration_context_unknown`, `path_feasibility_unknown`, `termination_unknown`,
`capability_missing`, `budget_exhausted`, `cancelled`.

El CFG abstracto puede contener caminos inviables. Una consulta de alcanzabilidad
abstracta verdadera se etiqueta como tal. No se presenta como prueba de ejecución
concreta; el análisis de factibilidad requerido debe solicitarse por perfil y,
si no existe, producir `capability_missing`. KQL no promete resolver indecidibilidad.

## 5. Recursión y agregaciones

Se permiten componentes fuertemente conexas de predicados/patrones **positivos**
sobre un universo finito de entidades y valores del programa/modelo. Evaluación
por menor punto fijo, preferentemente seminaive. La query puede definir cierre
transitivo sin un límite fijo de 32 saltos.

No permitir construir nuevos strings, números, listas o contextos ilimitados en
una SCC recursiva. Estados de modelos son enums finitos; contextos de análisis
tienen abstracción finita publicada. Detectar riesgo de universo no acotado al
compilar. Recursión sin caso base es válida pero vacía, con warning explicativo;
no se inventa una semilla.

Negación, `forall` traducido con negación y agregaciones dependen únicamente de
estratos ya cerrados. Rechazar recursión a través de negación o agregación en 0.1,
incluso si un caso particular pudiera ser monotónico. El motor no debe adivinar
una estratificación para una query no estratificable.

Para relaciones incompletas se calculan cotas de conocimiento: derivaciones
acreditadas y posibles. Se confirma una negación sólo al cerrar la cota superior
correspondiente. Unknown no se usa como ausencia dentro del punto fijo.
No se requiere enumerar infinitos valores candidatos: los candidates explícitos
se limitan al universo conocido; lo no enumerable se registra como hueco de ámbito.

Agregaciones exactas requieren dominio completo. Si falta parte del dominio,
`count` exacto es unknown; un predicado de umbral `at_least(N,...)` puede confirmar
con N testigos distintos sin cerrar todo el universo. No devolver un límite
inferior etiquetado como cuenta exacta. Ordenar/puntuar sobre unknown exige política
explícita de la query, no asignarle cero.

## 6. BODY y restricciones como planes

Compilar BODY a un autómata de eventos correlacionado con bindings y CFG. Probar
orden por alcance, no joins de todos los pares de operaciones por posición.
Compilar gaps a obligaciones de efectos sobre las regiones entre anclas.
Para `all`, buscar contraejemplos y huecos de cobertura en el producto relevante
CFG × estado; no enumerar todos los caminos. Para `witness`, conservar un camino
válido con sus modalidades. Las pruebas pueden compactarse, no cambiar su lógica.

Las restricciones universales no se desplazan fuera de su región al reordenar
joins. Restricciones independientes pueden adelantarse cuando sus roles existen.
Casts, excepciones, finally, defer, break/continue, entradas/salidas de callbacks
y control de iteración no pueden omitirse por una optimización.

Flujo entre funciones exige correspondencia caller/argument/parameter/return y
contexto: un camino no debe entrar por una llamada y retornar por otra incompatible.
Resúmenes de efectos publican footprint, escapes, modalidades y completitud. No
asumir pureza de una llamada externa para hacer pasar `preserve`.

## 7. Rendimiento y caché

Indexar por tipo de entidad, relación, extremos y propiedades selectivas; elegir
joins por cardinalidad; empezar por estructura/firma antes de efectos profundos.
Memoizar patrones por entradas tipadas, modelo, perfil y revisión. Compartir
subconsultas entre variantes y usar máscaras/lotes para múltiples reglas.
SCCs de flujo/recursión y resúmenes de efectos se calculan bajo demanda.

Presupuesto propuesto: `cache_budget_mb = 500`, donde MB significa 1.000.000 bytes.
Cuenta las entradas retenidas de caché de grafo, resúmenes, planes y resultados,
incluidas copias en memoria/disco por separado. `0` desactiva caché persistente y
retención entre consultas; el estado de trabajo de una evaluación no es caché.
La contabilidad de memoria usa tamaño real estimado conservador con overhead,
no sólo longitud del JSON. La política de división memoria/disco puede variar,
pero debe informar bytes por nivel y respetar el presupuesto retenido.

Este límite no promete que el RSS completo del proceso sea menor de 500 MB.
`working_memory_mb` y tiempo/estados/filas son presupuestos separados; agotarlos
produce incomplete. Entradas activamente fijadas no se evictan mientras se usan:
si no entran en presupuesto de retención, se mantienen como trabajo efímero y no
se publican en caché. Evicción LRU ponderada por costo es política, no semántica.

Claves incluyen hashes de fuente, dependencias resueltas, configuración del
frontend, schema IR, versiones de modelos, perfil, AST normalizado de consulta y
dependencias transitivas. Invalidar callers/efectos/negaciones afectados por
cambios de resolución, incluyendo archivos añadidos y símbolos antes ausentes.
Renombrar sin cambiar bytes relativos no autoriza reutilizar IDs de ámbito antiguos.

Los resultados parciales nunca se cachean como negativos. Si se conserva progreso,
debe estar marcado incompleto y reanudable bajo la misma clave. Cambios concurrentes
del árbol fuente invalidan la instantánea o producen revisión mixta explícita,
que no puede alimentar una garantía estricta.

Perfiles de ejecución propuestos: `batch` sin límite temporal implícito;
`interactive` opt-in con 3000 ms por solicitud, configurable, siempre publica incomplete
si corta. `limit` de presentación no sustituye estos presupuestos. Cancelación
cooperativa durante joins, recursión, extracción y serialización.

Medir por separado extracción, enlace/análisis, compilación de query, evaluación
fría/caliente, actualización incremental, memoria pico y tamaños retenidos.
No se atribuye una mejora de velocidad a esta propuesta: requiere benchmarks.

## 8. Lo reutilizable y lo faltante en Ken

IR 1.77 aporta identidades léxicas, operadores, instrucciones/CFG parciales,
relaciones de argumentos/retornos y resúmenes concretos. Eso sirve como entrada,
pero no acredita por sí solo los contratos de KQL 2.

Faltan o son parciales: reaching definitions general, heap/aliases/efectos,
fragmentos/contextos, flujo interprocedural configurable, estados finitos de
consulta, iteración con salida/consumo, concurrencia, recursión de queries,
agregaciones calculadas y negación universal con cobertura suficiente.
La implementación futura debe mantener una matriz capacidad × lenguaje × perfil.
El nuevo parser no puede convertir relaciones heurísticas en garantías fuertes.
