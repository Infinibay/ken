# Arquitectura del parser y ejecución de KQL2

La refactorización de septiembre de 2026 separa las producciones sintácticas,
la planificación, los operadores físicos y los servicios de cada ejecución.
Conserva `parse`, `compile`, `execute`, `prepare` y el formato de los artefactos
compilados. Las extensiones son cambios explícitos y revisables en el lenguaje;
no hay un registro global mutable de plugins que habilite sintaxis sin validarla.

## Mapa de responsabilidades

| Componente | Responsabilidad | Punto de extensión |
|---|---|---|
| `syntax/parser.py` | Cursor, checkpoints, profundidad, declaraciones y coordinación | API compartida de las producciones |
| `syntax/vocabulary.py` | Selectores, nombres reservados y precedencia | Vocabulario del lenguaje |
| `syntax/expression_parser.py` | Pratt, argumentos, matchers y tipos fuente | Expresiones; mantiene distintos `Expr` y `SourceExpr` |
| `syntax/clause_parser.py` | Query y restricciones | `COMMON_PRODUCTIONS`, `CONSTRAINT_PRODUCTIONS` |
| `syntax/body_parser.py` | Sentencias fuente | `BODY_PRODUCTIONS` |
| `syntax/call_parser.py` | Llamadas, construcciones y argumentos fuente | Producciones compartidas por BODY e inicializadores |
| `compiler.py`, `graph.py`, `body.py` | Resolución, validación y lowering existentes | Semántica y capacidades; parsear no habilita ejecutar |
| `planning.py` | Ordenar grupos de scans y preservar barreras | `prepare`, `schedule`, `explain` |
| `operators.py` | Expandir un frame de bindings | Protocolo `Operator.apply` y `build_operator` |
| `pipeline.py` | Componer operadores con una pila de iteradores | Joins, cierre de recursos y profiling exclusivo |
| `runtime.py` | Expresiones, dominios, propiedades y relaciones de un snapshot | Servicios de evaluación compartidos |
| `execution_control.py` | Presupuesto, cancelación y leases | `ExecutionBudget`, `ExecutionControl` |
| `execution.py`, `outcome.py` | Selección de backend, unión, proyección y resultados | Fachada pública |
| `structural/relational_planning.py` | Planificación del backend de grafos | Selectividad, filtros y barreras de evidencia |
| `structural/relational_operators.py` | Operadores de grafos compartidos por KQL1/KQL2 | `OperatorSpec` y `OPERATORS` |
| `structural/relational.py` | Estado de ejecución, índices, pruebas y coordinación | Ejecución del plan relacional |
| `structural/relational_validation.py` | Validación del plan sin capturar un executor | Contratos de operadores y dependencias |
| `structural/index_service.py` | Reutilización y publicación del índice del proyecto | Manifiesto de archivos y revisión de datos |
| `structural_store/graph_index.py` | Selección y estimación mediante índices SQL | Accesos por relación, extremos y atributos |
| `structural_store/graph_rows.py`, `graph_records.py` | Colecciones y atributos leídos bajo demanda | Contrato de lectura del grafo |
| `structural_store/graph_projection.py`, `graph_values.py` | Publicación y valores nativos deduplicados | Metadatos extensibles sin documentos JSON |
| `structural_store/graph_source.py` | Vista BODY limitada al owner consultado | Adaptador del matcher CFG |
| `common_ast/boundaries.py`, `structural_store/graph_syntax.py` | Límites de subárboles y cuerpos | Rangos sintácticos independientes de CFG |
| `structural_store/ast_columns.py`, `common_ast.py` | AST canónico en columnas nativas | Nodos, scopes, símbolos, referencias y cuerpos |
| `structural_store/graph_control.py` | Cancelación dentro de la máquina virtual SQLite | Presupuestos y cierre del handler |

## Agregar una cláusula

1. Escribir una función de producción en el módulo de su familia. Recibe el
   `Parser`, consume los tokens de esa producción y devuelve un `Clause`.
2. Registrarla en la tabla correspondiente. Los handlers BODY reciben la palabra
   inicial **ya consumida**; los handlers de cláusulas reciben además `mode` y
   `start`. No necesitan modificar el bucle principal del parser.
3. Usar `expect`, `role`, `expr`, `block` y `span` del parser. El dispatcher
   conserva la precedencia de propiedades con nombres reservados: `body: ...`
   es una propiedad donde el contexto permite propiedades.
4. Validar y bajar el nuevo `Clause` en el compilador correspondiente. Una
   extensión que introduce comportamiento nuevo también necesita su contrato
   de tipos, bindings, cobertura y ejecución; registrar el parser no lo sustituye.
5. Probar un caso válido, un error con ubicación, y la equivalencia entre
   referencia y ejecución optimizada cuando corresponda.

Ejemplo concreto: una nueva instrucción fuente se incorpora en `body_parser.py`
y `BODY_PRODUCTIONS`; si introduce un efecto nuevo, también se agrega su
validación/matching en `body.py`. Una abreviatura de sintaxis puede devolver un
`Clause` ya existente y reutilizar su semántica.

El parser usa checkpoints que guardan el token de lookahead y el último span.
Deshacer una alternativa no vuelve a tokenizar ese token. Los spans son offsets
UTF-8; los cursores del lexer son posiciones de caracteres. La relectura de un
token BODY ya consumido mantiene esa conversión explícita.

## Agregar un operador

En el backend indexado, un operador implementa:

```python
def apply(self, frame: Frame) -> Iterator[Frame]:
    ...
```

Debe producir nuevos frames sin modificar los bindings de entrada, conservar
`uncertain` y consultar `runtime.check()` durante trabajo interno prolongado.
La selección de estrategia ocurre una vez, en `build_operator`, antes del join.
La pila de `pipeline.run` cierra los iteradores suspendidos incluso cuando una
excepción o un presupuesto interrumpe el consumo. Su profundidad no consume una
llamada Python por cada paso del plan.

En el backend de grafos se registra un `OperatorSpec` que une el handler con su
barrera de optimización. `barrier=True` es el valor conservador por defecto.
El handler recibe el executor, nodo, fila, batch de salida y restricciones de candidatos;
agrega resultados al batch para evitar una lista temporal por cada fila.
`run_nodes` no necesita otro `if` para reconocer el operador.

Una barrera sólo se elimina si se demuestra que el operador permite ese
reordenamiento. Ausencia, conteos, patrones, BODY y recorridos tienen contratos
de evidencia y bindings que no se reducen a un filtro booleano.

## Depurar y medir

Desde Python, sin abrir un store:

```python
from ken.kql2.syntax import parse
from ken.kql2.compiler import compile
from ken.kql2.planning import explain

program = compile(parse('''language "kql/2"; module demo;
query q { class $c { name: "Worker"; } select $c; }
'''))
print(explain(program))
```

`explain` muestra el schedule del backend indexado, incluyendo acciones,
ubicaciones disponibles y barreras. Para grafos identifica el backend; el
orden efectivo depende de los candidatos y se observa ejecutando con profiling.
El perfil de grafos incluye la cardinalidad estimada, las alternativas consideradas
y la razón de selección (`bound_filter`, `estimated_cardinality` o barrera).
`stats.planning_ms` separa el tiempo de planificación. La estimación registrada corresponde a la primera invocación y su primera fila
de entrada; los contadores de trabajo real acumulan todas las invocaciones.

```console
ken kql2 consulta.kql --root . --profile
```

También se puede usar `execute(..., profile=True)` o
`search(..., profile=True)`. La API directa devuelve `Outcome.profile`; el
servicio y la CLI lo exponen en `analysis.operator_profile`.

- Indexado: `input_rows`, `output_rows` y `elapsed_ms` por paso. El tiempo es
  exclusivo: mide avanzar el operador, sin sumar el consumo de sus descendientes.
- Grafos: `calls`, entradas/salidas, estados, hechos examinados e `inclusive_ms`.
  `parent` identifica el operador contenedor; no se deben sumar padre e hijos
  como si fueran tiempos exclusivos. Las invocaciones repetidas se agregan por
  ubicación del plan, en vez de retener un evento por binding.
- El profiling del servicio omite la caché de **resultados**, pero puede reutilizar
  compilación y snapshots. Sin profiling no se toman tiempos por operador.
- Los límites de tiempo incluyen el overhead del profiling; límites por estados
  y filas conservan su comportamiento. `limit` de lenguaje y `max_rows` de
  ejecución siguen siendo cosas distintas.

## Optimizaciones concretas y límites

Los tests de propiedades se preparan una vez por scan. `name`, `path` y
`language` se leen del nodo, sin consultar el inventario SQL de propiedades.
El resto usa una LRU de hasta 1.024 nodos por ejecución/snapshot, compartida por
scans y expresiones; no se copian diccionarios de propiedades por cada join.
El contexto de expresiones se construye una vez por consulta.

La planificación indexada sigue siendo heurística: roles ligados, nombres
exactos y owners disponibles. El backend relacional estima filas después de las
restricciones de candidatos y prefiere uniones correlacionadas cuando empatan.
Es una elección incremental por cardinalidad, no una búsqueda exhaustiva de
planes: no garantiza el óptimo global ni modela todos los costos de CPU, I/O y
memoria. Preserva las barreras semánticas y adelanta filtros cuando sus entradas
ya están ligadas. El matcher CFG de `body.py` sigue verificando la semántica
completa de cada candidato.

### Restricciones necesarias antes de BODY

`kql2/source_candidates.py` separa el análisis de prerrequisitos de la ejecución.
`SourceCandidatePlanner` produce `ScanConstraints`; el planificador usa sus
dominios al estimar y el scan los aplica antes de multiplicar filas. Las uniones
de posting lists se cuentan antes de materializarlas: un índice de miles de
filas no se copia cuando ya hay una búsqueda por sujeto de una sola fila.

Para agregar una optimización fuente se registra una estrategia en
`OWNER_REQUIREMENTS`. La estrategia recibe el rol del callable y la cláusula,
y devuelve `OwnerRequirement`: relaciones alternativas necesarias y, sólo si la
semántica lo permite, el rol de la colección. `insertion_requirement` sirve de
ejemplo; no depende del nombre de un patrón del catálogo. Una extensión que no
tenga prerrequisitos demostrables no necesita registrar nada.

El análisis usa el prefijo positivo anterior al próximo BODY y se vuelve a
planificar después de cada matcher. Las estrategias `call` y `let = call`
aceptan nombres literales o listas de nombres; una estrategia debe declarar
`sequence_safe` para aportar requisitos dentro de una secuencia de instrucciones.
`insert` conserva el caso de una única cláusula. No se extraen requisitos de
alternativas, negación o agregación. `source_coverage.py` comparte la política
de cobertura con BODY: owners incompletos y operaciones sin ocurrencia semántica
siguen siendo candidatos. Una relación positiva obligatoria vacía puede descartar
su conjunción completa, incluso antes de BODY; esa prueba nunca atraviesa ANY,
negación ni conteos.
Los tests comparan resultados, evidencia e incertidumbre con la referencia en
modo estricto y posible. Los dominios filtran candidatos; no sustituyen BODY.

### Recursos y preparación del proyecto

`ExecutionResources` comparte una vista fuente de un `FactIndex` entre las
consultas del catálogo. Presupuestos, bindings, evidencia y memoización de BODY
pertenecen a cada ejecución. No se permite reutilizar recursos con otro índice.

El catálogo y los planes de grafos de KQL2 leen un índice persistente SQLite.
Entidades tienen columnas de identidad, tipo, nombre, archivo, líneas, owner y
posición; operaciones tienen owner, parent, tipo, rol y rango. Los extremos de
las relaciones son referencias enteras a una tabla de cadenas únicas. Los
atributos escalares ocupan columnas de texto, entero o real, y sus contenedores
son filas de hijos ordenados. Evidencia y valores repetidos comparten almacenamiento.
La ejecución no descomprime ni parsea un documento del proyecto para consultar
esos campos. Los atributos y la evidencia se materializan para los candidatos
leídos; los índices SQL también permiten contar candidatos sin crearlos en Python.

`FactRows` declara su acceso físico explícitamente. Sujeto, objeto, relación y
atributos tienen índices propios; las alternativas finitas de tipo usan el índice
por objeto. Se evita que `ORDER BY` induzca un recorrido completo de la tabla en
una búsqueda puntual. Los joins y la semántica de BODY siguen en el executor;
SQLite planifica cada acceso y el planificador KQL2 elige el siguiente operador.
Los filtros semánticos, rangos y regex que no se bajan a SQL se verifican después;
su estimación es una cota de candidatos, no un conteo exacto del resultado.
Conteo, existencia y enumeración usan el mismo acceso físico. Con un sujeto
conocido, los atributos se verifican mediante EXISTS correlacionado con los hechos
seleccionados: no se materializa el conjunto global de atributos en cada join.
Un objeto ligado usa el mismo camino cuando una sonda de hasta 33 entradas
confirma un bucket pequeño. La sonda elige cómo ejecutar el filtro, no limita
los resultados.

Una vez materializado, abrir el índice lee su cabecera, inventario de relaciones
y marcador de intervalos. Los grafos anteriores reciben su proyección de intervalos
una vez: se leen IDs y padres desde columnas, sin cargar atributos ni el IR.
BODY carga nodos y operaciones del owner solicitado. Hay cachés acotadas de
IDs, listas pequeñas y valores: no reconstruyen índices globales en RAM.
`Executor.close()` libera callbacks y scratch de cada consulta; los recursos
compartidos pertenecen al batch. SQLite recibe un progress handler temporal para
interrumpir también conteos, ordenamientos y otros pasos internos prolongados.

Las migraciones 7 a 14 se ejecutan al abrir `Store`. La primera añade el grafo
normalizado; la segunda convierte las propiedades escalares antiguas de JSON a
valores SQLite nativos, preservando booleanos, enteros grandes y cero negativo.
La tercera sustituye la proyección JSON del AST canónico por columnas nativas:
regenera sólo esa proyección derivada a partir de las unidades conservadas.
Nodos, scopes, símbolos y referencias ya no contienen un campo `data` JSON;
las listas de flags y nombres son filas ordenadas y los strings se internan.
La migración descendente también descarta únicamente esta proyección derivada.
La migración 10 incorpora publicación por lotes con un estado READY: los lotes
confirmados permanecen ocultos hasta terminar y permiten checkpoints del WAL.
Un fallo normal descarta la publicación. Para el benchmark se admite reanudar
un snapshot idéntico y ordenado tras expirar el lease anterior; una normalización
nueva no usa esta opción porque el orden de sus filas puede ser distinto.
Cada checkpoint verifica el token del propietario bajo el lock de escritura.
Un lease vencido puede recuperarse si la publicación aún pertenece al mismo
escritor; si otro proceso la reclamó, el escritor anterior falla sin modificar
ni borrar esa publicación. Esto cubre pausas prolongadas y suspensión del equipo
sin debilitar los leases de lectores de snapshots.
Si otra escritura mantiene el lock más que `busy_timeout`, la publicación
reintenta sólo `BEGIN IMMEDIATE`, consultando la cancelación entre esperas.
Nunca repite el cuerpo de una transacción ni consume filas antes de adquirir
el lock; después vuelve a comprobar el propietario. Otros usuarios de Store
mantienen su política de timeout habitual.

La migración 11 convierte a IDs enteros los tipos y rutas de entidades; tipos,
tipos nativos y roles de operaciones; etiquetas de valores; claves y textos de
comparación de atributos. Comparten el diccionario de términos del grafo.
Los nombres y contenidos variables conservan su texto. La migración mantiene
los IDs existentes y admite volver al formato anterior. Las páginas liberadas
quedan reutilizables: reducir el tamaño físico del archivo requiere compactarlo,
no se ejecuta VACUUM durante cada búsqueda.

La migración 12 añade atributos de hechos OPERATION apoyados en las columnas
de su operación. El escritor comprueba `native_kind`, owner, role y límites;
conserva el kind normalizado por separado y almacena sólo atributos adicionales.
Los IDs negativos de atributos identifican esa representación; los positivos
mantienen el codec general. Orden de hechos, extremos, duplicados y evidencia
se conservan. Valores personalizados que no coinciden usan el codec general.
Los filtros por atributos combinan candidatos de ambas representaciones y usan
índices para las columnas nativas. La migración conserva los grafos existentes;
el ahorro se aplica al publicar un índice nuevo. Al bajar de versión se descartan
sólo los grafos derivados que necesitan este codec, conservando unidades fuente.
Los servicios de adquisición prefieren la generación 2 del índice de columnas,
para construir esta representación una vez después de actualizar. Las claves de
unidades fuente no cambian y los lectores activos pueden terminar con su revisión
anterior mientras se publica la nueva.

La migración 13 elimina los índices globales por role, start_byte y end_byte de
operaciones. Conserva los accesos por identidad, propietario, tipo, tipo nativo y
rango. Los filtros correlacionados usan la clave de la ocurrencia; BODY usa owner
e intervalos. Esto reduce escrituras por operación sin alterar datos ni invalidar
el índice existente. La migración descendente restaura esos tres índices.

La migración 14 elimina también el índice de miembros por `(parent,key)`, que
no participa en los accesos actuales, y el antiguo índice de rangos de bytes de
operaciones. Los contenedores se leen ordenados por su clave primaria, sus
predicados usan `(key,comparison,parent)` y los cuerpos usan los intervalos
sintácticos. Ambas migraciones sólo cambian índices, conservan las filas y
pueden revertirse.

Una adquisición incompleta no se conserva bajo
la clave de un manifiesto completo. Las revisiones anteriores se recolectan
respetando los leases de lectores. Cambiar sólo el compilador o una consulta
invalida resultados/planes, conservando el índice de datos cuando corresponde.

### Límites sintácticos y BODY

Cada nodo canónico tiene un ID de preorden y `subtree_end` exclusivo. Su último
nodo sintáctico es `subtree_end - 1`. `k2_ast_bodies` guarda por propietario y rama
la raíz, el límite y `final_node`; `View.bodies` y `View.body_nodes` permiten
consultarlos por clave y rango. Módulos, clases, métodos, bloques, bucles y ramas
conservan sus límites. `body` y `else` tienen entradas distintas. Los cuerpos
anidados permanecen contenidos sintácticamente, con scopes y owners separados.

El grafo ejecutable conserva también `(position, subtree_end, final_node)` por
operación en `k2_graph_syntax`, con índice por posición. La proyección usa enlaces
padre–hijo y admite operaciones fuera de orden; rechaza ciclos e IDs duplicados.
BODY consulta el intervalo de una región y restringe su owner, sin buscar todas
las operaciones del proyecto. Un operando de una función anidada se resuelve por
ID; no reconstruye un mapa global. El final sintáctico no es una salida de
control: `return`, excepciones, `break` y caminos alternativos siguen en CFG.

El índice del catálogo vive en `.ken/structural/v2/patterns.sqlite`. Su tamaño
representa datos de búsqueda y puede superar los 500 MB de caché de resultados.
Desactivar retención usa un índice SQLite temporal en disco. El store de artefactos
con cuota mantiene esa cuota; su mínimo persistente es ahora 512 KB por el costo
del esquema. Los límites de caché de resultados no limitan el índice persistente
del catálogo.

Las cachés de adquisición de IR y de resultados anteriores conservan JSON/zlib.
La adquisición fría todavía enlaza y normaliza el proyecto; las búsquedas siguientes
reutilizan el índice nativo. Modificar un archivo invalida el grafo de proyecto y
puede exigir su reconstrucción; la actualización incremental de las derivaciones
globales queda fuera de esta implementación. El backend tipado anterior conserva
sus contratos de operaciones/artefactos; sus propiedades escalares ya son nativas.

El servicio puede transferir sus unidades privadas a `link_project` sin duplicar
entidades. Otros llamadores conservan el aislamiento por defecto. La resolución
de imports Rust calcula la raíz común una vez por proyecto y las derivaciones
de concurrencia indexan testigos una vez, evitando recorridos completos por
cada llamada.

`normalize_query_graph` produce directamente el IR de publicación, sin construir
las listas globales de `FactIndex`. `query_graph` conserva esa fachada para los
llamadores en memoria. La publicación del servicio consume sus colecciones
privadas a medida que las confirma en disco; los llamadores con IR compartido
conservan el comportamiento no destructivo por defecto.

La caché de resultados sólo conserva respuestas completas. Una consulta agotada
o truncada no puede envenenar futuras ejecuciones con un presupuesto mayor. Una
respuesta completa con más hallazgos que el nuevo límite tampoco se reutiliza
saltándose ese límite. La versión de la caché se incrementó para invalidar los
resultados incompletos guardados por versiones anteriores.

`compilation.implementation_fingerprint` incluye los módulos KQL2,
`structural/relational*.py` y el backend `structural_store/graph_*.py`. Cambiar una estrategia extraída invalida los
artefactos igual que antes lo hacía editar el archivo monolítico.

## Validación reproducible

```console
.venv/bin/python -m pytest tests/kql2 tests/structural tests/common_ast
.venv/bin/python examples/bench/kql2_refactor.py --output /tmp/kql2-benchmark.json
```

El benchmark mide parsing, lookups, joins, filtros, propiedades y un join de
grafos. Con `--baseline-dir` puede cargar copias previas de `parser.py`,
`execution.py` y `relational.py` junto a la implementación actual, alternar el
orden de medición y verificar igualdad de resultados antes de medir. No usa
umbrales de tiempo como tests funcionales.

Los resultados de esta refactorización y las limitaciones observadas están en
[el registro de validación](../../structural-validation/kql2-refactor-2026-09-16/validation.md).

Para medir el catálogo sobre un repositorio real, sin escribir en ese repositorio:

```console
PYTHONPATH=src .venv/bin/python examples/bench/pattern_search.py ../codex \
  --artifacts /tmp/pattern-benchmark --backend sqlite \
  --snapshot /tmp/pattern-benchmark/graph.pickle
```

`--timeout-ms` permite diagnóstico acotado y `--profile` guarda perfiles de CPU
y operadores. Los tiempos de preparación y búsqueda se informan separados.
`--cold` exige un directorio de artefactos nuevo y omite las cachés de adquisición
del repositorio. El servicio informa `analysis.query_index.phase_ms` para separar
manifiesto, apertura, construcción de fuente, normalización y escritura. Las
etapas no ejecutadas en una reutilización no aparecen como tiempos heredados.
El snapshot pickle debe ser propio y confiable. La comparación conserva hallazgos,
incertidumbre y evidencia, normalizando sólo el orden de evidencia y el prefijo
versionado de los nombres de consultas compiladas. Un resultado interrumpido
no prueba equivalencia de resultados completos.

Las mediciones de repositorios reales y la migración de almacenamiento están en
[el informe de rendimiento](../../structural-validation/kql2-search-performance-2026-09-16/README.md).
