# Estado de la implementación KQL 2

14 de septiembre de 2026. El usuario autorizó implementar después del encargo
inicial de documentación. **Implementación experimental parcial**, accesible
por API Python y `python -m ken.kql2`. El catálogo activo de 33 TOML usa KQL 2.
KQL1 mantiene compatibilidad sobre el ejecutor relacional compartido.

## Estado por componente

| Componente | Implementado | Pendiente |
|---|---|---|
| AST genérico | Normalización de 9 lenguajes, árbol, scopes/namespace, símbolos/referencias, persistencia y consultas | Resolver todas las formas nativas, tipos/dispatch/alias y disponibilidad runtime completos |
| Definición KQL2 | Especificación documentada y parser amplio; compilador valida el subconjunto ejecutable | Conformidad completa entre especificación y ejecución, recovery/fuzzing ampliados |
| Almacenamiento y parseo | Tree-sitter, AST común, SQLite schema 6, índices, migraciones, reutilización y cache en disco | Cuotas globales RAM/temporales, spill y segmentos semánticos restantes |
| Búsqueda | Estructura/AST, composición, alternativas, recursión, negación, cálculos, valores producidos y BODY parcial | BODY/control completo, alias/heap/preserve completos, efectos, protocolos y concurrencia |

**Actualización 15/09, IR 1.84: migración parcial del catálogo.** El
[inventario por entrada](../../structural-validation/kql2-catalog-rewrite-2026-09-15/migration-status.md)
cuenta consultas raíz, variantes y operaciones de los 23 GoF y 10 patrones modernos.
Todavía quedan consultas con operadores internos; no se ha completado su autoría
en el lenguaje fuente. Los selectores anidados y BODY ya se integran con el
ejecutor relacional del catálogo. BODY conserva un verificador de flujo por
candidato; la [generalización de su planificación mediante joins](body-relational-planning.md)
está pendiente y se difiere para priorizar corrección.

Se admiten valores producidos por llamadas/construcciones, orígenes por ocurrencia,
condiciones, intervalos sin escrituras, yield y recorridos seleccionados, dentro
del [contrato ejecutable](saved-body-execution.md). Esto no significa cobertura
completa de alias, efectos, flujo nativo o concurrencia, ni certifica intención de
diseño. La sintaxis parseable y la existencia de un TOML no bastan para afirmar
que un patrón funciona.

La [segunda revisión](../../structural-validation/xfail-second-review-2026-09-14/README.md)
agrega 15 contratos seleccionables y la variante de Interpreter sin contexto.

## Uso ejecutable

Guardar como `workers.kql`:

```kql2
language "kql/2";
module examples.workers;

pattern Worker(out TypeDecl $worker, out Callable $work) {
    class $worker {
        when $worker.language in ["python", "java"] {
            method $work { name: "work"; }
        } else when in_directory($worker, "adapters") {
            method $work { name: "execute"; }
        } else {
            { method $work { name: "work"; } }
            or { method $work { name: "run"; } }
        }
    }
}
query workers {
    use Worker(worker: $worker, work: $work);
    select $worker, $work;
}
```

```sh
python -m ken.kql2 workers.kql --root /path/to/project --cache-mb 500
```

API: `ken.kql2.service.search(root, source, query_name=None, path=".",
cache_mb=None, timeout_ms=None, max_states=None, max_rows=None)`.

La API, CLI y entrada MCP no imponen límites de tiempo, estados o filas por
defecto. `None` desactiva cada presupuesto de ejecución, también en uniones y
consultas relacionales. Los límites explícitos y la cancelación siguen activos;
la cuota de caché configurable permanece independiente.
También se puede ejecutar `ken kql2 workers.kql --root /path/to/project`.
`--library file.kql` carga módulos explícitos; sus contenidos participan de las
claves de compilación. En MCP: `ken_find(scope="structure", query_language="kql/2",
query=source, libraries={module: source})`. Las reglas TOML declaran `query_language="kql/2"`; el API del catálogo conserva sus IDs.

`when` es una condición de la búsqueda; el `if` dentro de BODY describe código
fuente. Se admiten alternativas `either { ... } or { ... }` y `{ ... } or { ... }`.
Cada invocación de un patrón elige sus alternativas independientemente. Los roles
que se proyectan deben estar ligados en todas las ramas. Las ramas no combinan
campos de testigos incompatibles. `in_directory(node, "abc")` compara un componente
de directorio del path relativo al proyecto: acepta `a/abc/b.py`, no `abcdef/b.py`
ni un archivo que se llame `abc`. No compara directorios absolutos fuera del root.

## Capacidades actuales

* Lexer/parser: declaraciones, tipos genéricos, selectores, expresiones de
  consulta/fuente separadas, BODY, control, intervalos, iteración y concurrencia
  como **sintaxis**. AST inmutable, spans UTF-8, límites de tamaño/profundidad y
  diagnósticos. No hay recuperación para editor todavía.
* Compilador/ejecutor: selección estructural de tipos/clases/interfaces/traits,
  módulos, campos, callables, métodos anidados, constructores, parámetros y
  receptores; dominios finitos correspondientes, `where`, proyección, orden/limit
  también sobre alternativas, named patterns con renombrado interno, ramas y
  condiciones por lenguaje/path. El orden dentro de un grupo relacional no implica
  ejecución de código fuente.
* Cálculos: `bind`, aritmética, `exists`/`forall` y agregaciones sobre los dominios
  estructurales finitos. `sum` elimina valores repetidos; `sum_by` conserva una
  contribución por tupla. `min`/`max`/`avg` devuelven Option, incluido el caso vacío.
  Los dominios incompletos no certifican ausencia. Los filtros no se adelantan a
  cálculos que podrían fallar y ocultar sus errores.
* Predicados tipados con recursión positiva por componentes, evaluación de tuplas
  demandadas y propagación de cambios a dependientes. Hay pruebas de recursión
  mutua y cadenas de más de 32 saltos. Se rechazan ciclos negativos, agregados y
  comparaciones no monótonas. `enum` aporta dominios cerrados propios.
* Firmas/modelos con especialización estática y forwarding de argumentos; módulos
  explícitos con imports transitivos y cíclicos, nombres cualificados e invalidación
  por contenido. No existe aún un gestor de paquetes/exports/lockfile del diseño.
* `not exists` correlacionado y `optional` sobre selectores/from/where; las capturas
  internas no escapan. La evidencia opcional informa matched/absent/unknown y no
  filtra filas obligatorias. `fields exact` y `parameters exact` comparan inventarios
  distintos; este último excluye receptores. Los grupos exactos requieren selectores
  directos. Composición arbitraria dentro de estos grupos aún está pendiente.
* Enlace global bajo demanda para `possible_call(Callable,Callable)` y
  `returns_new(Callable,TypeDecl)`. Persiste hechos contextuales por snapshot y
  reutiliza el linker existente; ausencia de destino resuelto sigue siendo unknown.
  Una consulta puramente estructural no dispara este análisis.
* Propiedades ejecutables: name/path/language/native_kind; static/async/generator
  en callables; position/native_position en parámetros/receptores; type/type_status
  en campos, parámetros y variables; return_type/return_type_status en callables.
  Tipos básicos y contenedores genéricos usan descriptores, distinguiendo any,
  unknown explícito y falta de información. Tipos nominales completos, subtipado,
  assignability y familias de comportamiento siguen pendientes. El compilador
  rechaza propiedades fuera de este subconjunto, incluso si están en el diseño.
  Position ordinaria excluye receptores; native_position preserva el dato original.
* SQLite: namespace propio, schema bootstrap versionado/checksummed, validación
  de ownership/DDL, up/down transaccional, unidades reutilizadas por contenido,
  snapshots publicados por comparación del padre, índices por kind/name/owner y
  extremos de hechos. Los atributos contextuales de hechos se conservan completos.
* Performance: filtros exactos enviados a SQL, planes según bindings/selectividad,
  condiciones ligadas evaluadas antes de ampliar joins. Escaneo de referencia
  comparable por conjuntos, métricas de candidatos/estados y tiempos separados.
* BODY ejecutable sobre CFG de sentencias: declaración `var`, asignación con
  operandos/literales/operadores, `read($binding)`, retorno, llamada a un Callable
  ligado con argumentos por posición/nombre/any y evidencia de operación.
  Admite ruido intermedio, `adjacent`, `where` y `gap until next` con
  `forbid write(binding(...))` y `forbid call(..., through: direct)`.
  Un pack no expandido no acredita una posición efectiva. El análisis de intervalos
  considera todos los caminos conectores y excluye los extremos. No combina
  instrucciones de ramas incompatibles; un contexto de iteración no resuelto
  dentro de un intervalo produce unknown.
* Dominios Binding y Operation: variables declaradas y operaciones con kind,
  native_kind, language, path, line y execution. Una lectura sin declaración no
  inventa una declaración. Operation incluye operaciones fuente inalcanzables;
  un selector Operation por sí solo no exige ejecución.
* [AST común y contextos](common-ast.md): implementado en schema 6 para los nueve
  lenguajes del frontend. Árbol propio, hijos ordenados, scopes/namespace, símbolos,
  referencias y consultas node/expression/statement; relaciones de contención,
  identidad de símbolo, visibilidad e inicialización sintáctica conservadora.
  Reutiliza la proyección de operaciones de schema 5, sin volver a parsear.
  Resolución semántica y disponibilidad runtime completas siguen pendientes.

El parser no autoriza el runtime. Las partes aún no implementadas de BODY
(`let`/valores producidos, if/while/for/try explícitos, yield/await, iteración y
concurrencia), familias de comportamiento, preserve, efectos transitivos y
fragmentos producen un error de compilación **antes de escanear/crear DB**.
No interpretar las
construcciones sintácticas aceptadas como análisis implementados.

`complete` informa terminación de la evaluación. `coverage_complete` describe
cobertura de captura/frontend; no garantiza análisis semántico universal.
`unknown_candidates` conserva candidatos con propiedades no disponibles: no son
negativos certificados. `results_truncated` es independiente de esos estados.
El snapshot representa los bytes capturados; no promete snapshot atómico del FS
ni `live_verified` mientras otros procesos editan archivos.

## Caché: alcance real

Se reutilizan unidades por path/lenguaje/hash de contenido/fingerprint de frontend.
Este último incluye IR_VERSION, versiones de grammars e implementación fuente.
Cada adquisición lee los bytes para descubrir cambios; mtime no prueba igualdad.
El store conserva proyecciones indexadas y blobs de unidades para roundtrip,
pero una búsqueda selectiva no descomprime el proyecto entero.

El presupuesto se resuelve con configuración existente/env/override, default
500 MB decimales. La cuenta persistente usa páginas asignadas, incluidos índices.
Cache 0 o presupuesto menor que el overhead mínimo usa SQLite efímero. Si la
inserción/publicación excede el presupuesto, la búsqueda cambia a un store de
trabajo temporal sin eliminar hechos necesarios. Ese espacio es trabajo, no
retención. WAL/RSS y temporales no están incluidos en ese límite de retención.

**C10 no está terminado:** faltan cuotas compartidas
con KQL1,
spill del evaluador, presupuesto global de memoria y disco temporal. No usar esta
entrega como garantía de un límite total de 500 MB de RSS/directorio. Un store
previo mayor que una cuota reducida descarta artefactos y snapshots no fijados y
compacta páginas libres bajo presión. Conserva lectores y adquisiciones activos:
si éstos exceden la cuota, la retención puede seguir excediéndola temporalmente.
La compactación necesita espacio temporal de SQLite. `analysis.quota_reclamation`
informa bytes anteriores/posteriores y si debió postergarse. Las consultas
activas conservan sus snapshots mediante leases renovables. GC conserva dos
snapshots recientes, el publicado y los fijados por lectores; difiere la limpieza
mientras otro proceso captura unidades. Las páginas liberadas se reutilizan, no
se compacta todo el fichero en cada petición. Un lease vencido cancela la evaluación
con `snapshot_expired`, nunca con un negativo exitoso. Un lock de adquisición
evita parseos duplicados entre procesos; se libera antes de ejecutar la consulta.

### Recuperación entre procesos

El grafo, los planes compilados y los resultados se guardan en
`.ken/structural/v2/store.sqlite`. No hace falta exportar ni guardar manualmente.
La migración 1→2 agrega artefactos, 2→3 agrega leases, 3→4 agrega hechos de análisis
global, 4→5 agrega contextos de operaciones indexados y 5→6 agrega AST común,
scopes, símbolos, referencias e índices. La proyección común se reconstruye desde
el IR almacenado cuando falta; downgrade 6→5 conserva esas unidades. Unidades de schema 4 se
proyectan al primer acceso, sin reparsing. Los downgrades eliminan la capa correspondiente y conservan las unidades
fuente mientras se mantenga el schema 1.

Los planes usan claves con el texto de la consulta, la selección de query, el modo
de ejecución y un fingerprint de implementación. Su codec JSON tiene tipos
cerrados y validación de estructura, tamaño y checksum. Un artefacto incompatible
o corrupto se descarta y se recalcula. Los resultados dependen además del snapshot;
solo se guardan ejecuciones completas con cobertura de captura completa.
El código fuente se vuelve a leer para comprobar su hash antes de recuperar un
resultado: recuperar directamente no significa ignorar cambios en archivos.

La caché en memoria de compilación tiene LRU y single-flight dentro del proceso.
Reserva hasta el 20% del presupuesto, con techo de 100 MB; el resto corresponde
al store persistente. Con el default de 500 MB son 100 MB de memoria retenida y
400 MB de store. Los artefactos persistidos tienen LRU dentro de una cuota del
20% del store; no expulsan hechos del grafo. `cache_mb=0` desactiva la reutilización
persistente y en memoria. Estas cuotas no son un límite de RSS ni de archivos WAL.

`analysis.compilation_cache.status` distingue `hit`, `disk_hit`, `miss`, `shared`
y `disabled`. `analysis.result_cache` informa `disk_hit` o `miss`. Con resultado
recuperado, `query_ms` es null y `result_lookup_ms` mide la lectura; no se presenta
la recuperación como una nueva ejecución del buscador de cero milisegundos.

## Tareas del plan y pendientes

| Tarea | Estado actual | Lo que falta para cerrarla |
|---|---|---|
| I00 | Baseline sintético y búsqueda real registrados | Congelar corpus completo y baseline equivalente KQL1 |
| P10 | Parser experimental y pruebas de ejemplos/familias | Auditoría completa de gramática, recovery de editor y fuzzing |
| P11 | Tipado estructural, bibliotecas explícitas, enums y modelos | Tipos fuente completos, paquetes/exports/lock y contratos restantes C001–C020 |
| P12 | Selectores, use y ramas convertidos en planes | Núcleo completo y autómatas BODY |
| S10 | Migraciones 1↔2↔3↔4↔5↔6, checksum/rollback aislados | Recovery de epochs y herramientas de mantenimiento |
| S11 | Unidades, nodos, hechos y snapshots persistidos | Términos/n-arias/cobertura semántica/segmentos globales del diseño completo |
| S12 | AST común, scopes y símbolos propios; adaptación legacy y enlace global bajo demanda | Tipos/dispatch entre módulos, lifetime y garantías semánticas completas |
| E10 | Ejecutor, cálculos, anti-joins, optional, exact y full-scan diferencial | Álgebra sin expansión distributiva y evidencia completa |
| O10 | Índices y heurística de orden; medición selectiva | Estadísticas/NDV, DP de joins y todos los access paths |
| C10 | Unidades, planes/resultados, LRU, GC/leases, compactación bajo presión y adquisición coordinada | Cuotas globales, memoria/spill y mantenimiento |
| S13 | Edit/add/delete/frontends comparados contra rebuild fuente | Dependencias globales, modelos, resolución y negación |
| E11 | Predicados recursivos finitos, estratos, enums y modelos | Auditoría completa de firmas/dominios y corpus de rendimiento |
| E12 | BODY secuencial/CFG, llamadas, argumentos e intervalos de slots/llamadas directas | Valores producidos, control completo, puntos, alias/heap, preserve, efectos transitivos |
| E13 | Sintaxis disponible | Iteraciones/protocolos, estados, excepciones/suspensión y concurrencia |
| O11 | Pendiente | Optimización de SCC/BODY con equivalencia demostrada |
| V10 | 33 TOML / 138 queries migradas, comparación congelada y matriz adversarial | Mejorar precisión y migrar a BODY de alto nivel cuando existan sus capacidades |
| V11 | Mediciones iniciales | Matriz completa, Linux/macOS, recovery y packaging final |

Los schema/módulos de esta entrega son un bootstrap, no materializan todavía
las tablas/garantías completas de [storage-plan.md](storage-plan.md).
El catálogo de 33 TOML se migró explícitamente a KQL 2. Véase [perfil ejecutable](graph-queries.md) y [reporte de migración](../../structural-validation/catalog-kql2-migration-2026-09-14/README.md).

Pruebas y muestras reproducibles: [reporte](../../structural-validation/kql2-bootstrap/README.md).

### Ejemplo BODY ejecutable

```kql2
language "kql/2";
module examples.calls;
query call_then_return {
    callable $consumer { name: "consume"; }
    callable $f {
        param $input { name: "input"; }
        body {
            call $consumer { argument $input at 0; } as $invocation;
            gap until next {
                forbid write(binding($input));
                forbid call($consumer, through: direct);
            }
            return read($input) as $returned;
        }
    }
    select $f, $invocation, $returned;
}
```

Este ejemplo preserva el slot del parámetro entre anclas. No acredita que el objeto
apuntado por ese slot sea inmutable. Un CFG parcial o alias de slot no resuelto
produce candidatos unknown, no negativos certificados.

Extensión posterior solicitada: [disponibilidad contextual y recomendaciones](availability-proposal.md). Es una propuesta separada, aún sin API ejecutable.
