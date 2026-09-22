# Validación del AST común — 14 de septiembre de 2026

[Contrato ejecutable y límites](../../design/kql2/common-ast.md).
[Estado por componente](../../design/kql2/implementation-status.md).
Esta entrega implementa el AST común consultable y persistido para el frontend
actual. No declara terminados todos los motores KQL2 ni migrado el catálogo TOML.

## Pruebas enfocadas

```sh
.venv/bin/pytest tests/common_ast tests/kql2 tests/structural/test_lazy_fact_index.py tests/structural/test_graph_cache_invalidation.py tests/structural/test_documented_kenql_queries.py tests/test_mcp_schema.py tests/test_tools_cli.py -q -o addopts=''
.venv/bin/mypy src/ken/common_ast src/ken/kql2 src/ken/structural_store
```

**501 pruebas pasan:** 111 del AST común, 338 KQL2, 37 de compatibilidad estructural
anterior y 15 CLI/MCP. Mypy: 39 módulos sin errores.

| Archivo de pruebas | Obligación cubierta |
|---|---|
| `test_normalization.py` | Árbol/roles/operadores en 9 lenguajes, identidad, UTF-8, roundtrip, yield/await, for con step, opacos |
| `test_scopes.py` | Lookup y shadowing, namespaces, imports, var/let/TDZ, Rust let, Python global/nonlocal/clases/comprensiones |
| `test_language_features.py` | Parámetros y packs, receptores, aliases, defaults, literales, any/unknown/tipos básicos, bloques Ruby, async Rust, sintaxis concurrente Go, excepciones |
| `test_store.py` | Roundtrip indexado de 9 lenguajes sin leer IR legacy, índices, strings internados, cascadas, migración 5↔6 y fallback de cuota |
| `test_queries.py` | Misma consulta en 9 lenguajes, identidad/contención, anti-joins, opacos→unknown, posiciones inciertas, índices contra full scan, invalidación y rechazo temprano |

Cada uno de Python, JavaScript, TypeScript, Java, C#, C++, Go, Rust y Ruby tiene
pruebas del árbol común, resolución parámetro/local, roundtrip de almacenamiento y
la misma consulta de retornos. Las variantes adicionales se distribuyen según el
feature del lenguaje. No afirmar que cada regla léxica tiene todas las variantes
en todos los lenguajes; no es la matriz de precisión del catálogo GoF.

## Problemas descubiertos y corregidos

* Defaults Python resolvían el parámetro recién declarado; ahora se evalúan en el
  ámbito de definición. Primer iterable de una comprensión usa el ámbito exterior.
* global/nonlocal no sobrevivían como reglas de lookup al consumir el AST desde
  SQLite. Ahora son datos de Scope; identidad e inicialización siguen separadas.
* Distintos let Rust podían quedar unificados por STORAGE legacy. El AST común
  mantiene símbolos propios y resuelve el binding anterior en el inicializador.
* Separadores de parámetros contaminaban las posiciones. Se conserva posición
  nativa y se calcula ordinal ordinario excluyendo receptores y separadores.
* Packs podían dar una posición falsa a argumentos posteriores. La posición
  efectiva queda desconocida y la consulta lo conserva como unknown.
* Etiquetas de argumentos named aparecían como lecturas. Se excluyen esas etiquetas.
* Imports Rust agrupados perdían nombres y aliases C# se confundían con el target.
  Se conservan bindings correctos; Go sin alias no inventa el package por el path.
* Cada comparación de símbolos reconstruía sus mapas. Ahora se reutilizan dentro
  de las dos unidades retenidas por la vista de consulta.
* Las negaciones podían certificar ausencia sobre dominios con sintaxis opaca.
  Su clasificación se considera incompleta, conservando unknown.
* La tabla de normalización carecía de indexación, slices, fragmentos de string,
  aliases de recursos y otras formas presentes en el corpus real. Se añadieron
  sus formas comunes conservando hijos, roles y diferencias nativas.

## Medición reproducible en infinidev

```sh
.venv/bin/python examples/bench/common_ast.py /Users/andres/Projects/infinidev/src/infinidev/code_intel --output docs/structural-validation/common-ast-2026-09-14/infinidev.json
```

[Datos, hashes de archivos/implementación y muestras](infinidev.json). Se leen los
fuentes; no se ejecuta código del proyecto. La base de medición es temporal y no
modifica su repositorio.

Consulta: todos los nodos `return`, proyectando path, byte UTF-8 de inicio y línea.
Oráculo independiente: `ast.Return` del parser de Python, comparado por conjunto
exacto. **396 esperados, 396 encontrados, 0 FP y 0 FN para esta consulta.** No es
una medición de precisión GoF, flujo de valores o resolución de símbolos.

35 archivos, 39.266 nodos, 377 scopes, 2.179 símbolos y 6.705 referencias.
Todas las formas nativas presentes tienen una clasificación en este corpus;
eso no prueba cobertura universal ni semántica completa de Python.

| Medida | Resultado |
|---|---:|
| Extracción Tree-sitter/IR | 0,719 s |
| Normalización y persistencia | 3,260 s |
| Consulta indexada, mediana de 5 | 43,30 ms |
| Escaneo completo, mediana de 5 | 390,99 ms |
| Reapertura y consulta | 46,91 ms |
| Store completo, IR anterior + AST e índices | 68.517.888 bytes |

La última medición se ejecutó después de terminar la suite ampliada, sin otro
benchmark o pytest lanzado por esta tarea en paralelo. El escaneo indexado entrega
396 candidatos, frente a 39.266 en el escaneo completo. La mejora de unas 9× aplica
a esta consulta concreta, no a todos los patrones/joins.

Los tiempos y su separación están en el JSON: extracción, normalización/persistencia,
consulta con índices, full scan y reapertura desde disco. Se ejecutan cinco muestras
por plan; no se utiliza caché de resultados. El full scan consulta el mismo AST
sin filtros de kind/name enviados a SQL, no es el motor KQL1. La consulta reabierta
prohíbe deserializar el IR legacy. No se vacía la caché de páginas del sistema.

El store completo incluye tanto el IR/proyecciones anteriores como el AST común
y sus índices; no confundir su tamaño con el coste exclusivo de esta nueva capa.
La cuota default de 500 MB limita retención, no garantiza ese límite para RAM,
WAL y espacio temporal del trabajo.

## Pendientes que no se ocultan con un árbol normalizado

Resolver tipos/dispatch/imports entre unidades y todas las reglas de scope;
macros y sintaxis aún opaca; disponibilidad runtime completa, borrow/move/lifetime;
BODY/control completo, produced values, alias/heap/preserve y efectos transitivos;
protocolos/iteraciones/concurrencia; optimizador de costes y cuotas globales/spill.
El catálogo sigue en su dialecto anterior y requiere su propia migración/validación.


## Regresión ampliada del catálogo anterior (corregida posteriormente)

Se ejecutó además `tests/structural` completo junto con AST/KQL2 y CLI/MCP. La
corrida terminó con un fallo: `test_map_api_shape.py::test_the_canonical_java_pool_is_detected_end_to_end`.
También se mantienen los xfail declarados previamente en el catálogo; no se
presentan como casos aprobados ni como cobertura completa GoF.

La variante `flyweight#explicit-interning` exigía que el objeto de `NULL_TEST`
tenga directamente `CONTAINER`/`INDEX`. En la forma Java del test, NULL_TEST apunta
al STORAGE local `result`; `result ASSIGNED_FROM lookup` y es ese lookup el que
tiene CONTAINER. El query descartaba una implementación que su claim decía aceptar.
No basta agregar ASSIGNED_FROM sin más: como result también recibe la construcción
nueva, la corrección debe acreditar el valor que llega al guard mediante
flujo/orden y evitar aceptar una reasignación entre lookup y guard.

Se verificó en un proceso aislado que el IR de este ejemplo es idéntico restaurando
la condición anterior de captura de literales en `Lowerer.operation`, y el mismo
test falla con ese comportamiento anterior. Este defecto del TOML no fue causado
por los cambios del AST común. Se corrigió después en el TOML, con 44 pruebas
nuevas y 169 casos de regresión aprobados: [detalle de la corrección](../flyweight-local-guard-2026-09-14.md).
No se modificó el test original ni se añadió xfail para ocultarlo.
