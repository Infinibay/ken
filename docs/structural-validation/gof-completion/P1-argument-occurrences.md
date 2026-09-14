# P1.2 / P1.3 / P1.4 — Argumentos por ocurrencia, IR 1.48

Base revisada: `5d2486c`, posterior a las entregas `ee8605b`, `aff9320` y
`4b7a557`. Esta entrega corrige y amplía esas implementaciones; no añade una
variante GoF ni declara P1 completo.

## Problema reproducido

El código previo agrupaba resultados por CALLEE_VALUE/CALLEE_NAME y elevaba
ASSIGNED_FROM a must cuando el callee coincidía. Eso confundía estas dos llamadas:

```python
x = make(1)
x = make(2)
return take(x)
```

Ambos resultados aparecían como flujo cierto. Sólo el segundo es el origen de x
al consumirlo. También había FN para `saved=x; x=make(2); take(saved)`.
El conjunto inicial de 61 pruebas nuevas dio **36 failed, 25 passed** antes del
cambio (una vez corregida la sintaxis de la query del propio test).

La búsqueda de operaciones por sufijo de byte offsets recorría todas las entidades
para cada llamada y podía enlazar una llamada del archivo B con una entidad de A.
Además, la lista de eventos no incluía CALL: el código que pretendía capturar
argumentos independientes nunca se ejecutaba; sólo se capturaba el call de un
return directo. UNIQUE_BINDING_WRITE ocultaba parte de esa falta de análisis.

## Contrato y corrección

- Mapa por `(owner, start_byte, end_byte)` con índices directos en ambas direcciones.
  El owner preserva archivo/ámbito; no se buscan sufijos globales.
- Eventos CALL de expresiones eager admitidas, antes de store/return envolvente.
  Los estados continúan después de una llamada y terminan después de un retorno.
- Análisis también para callables sin retorno explícito.
- Snapshot por `(call, posición, operando)` con orígenes exactos, unknown y casos
  origen/escritura correlacionados. El nombre del callee no identifica un valor.
- Proyección de VALUE_FLOW desde orígenes vivos, incluso por alias. Las asignaciones
  históricas conservan may para descubrimiento possible; no prueban must.
- Eliminado el fallback de UNIQUE_BINDING_WRITE como prueba de flujo temporal.
- IR_VERSION pasa a 1.48.0 para invalidar cachés con la semántica anterior.

Dos llamadas en ramas excluyentes al mismo método no son un único valor conocido.
La expectativa anterior de `test_algorithm_facade_branches.py` se corrigió para
exigir may/possible. No se debilitó un contrato para ocultar un FN: la query emite
una **llamada concreta**, y ninguna de esas dos llamadas llega en todos los caminos.
La nueva matriz incluye el positivo legítimo: llamada previa cuyo mismo resultado
se asigna por ambos brazos; ese origen sí es must.

## Archivos

- `src/ken/structural/return_flow.py`: análisis y mapa de ocurrencias.
- `src/ken/structural/kenql.py`: proyección de orígenes exactos a VALUE_FLOW.
- `src/ken/structural/model.py`: versión persistida.
- `tests/structural/test_argument_occurrence_flow.py`: regresiones fuente en cinco lenguajes.
- `tests/structural/test_algorithm_facade_branches.py`: corrección de expectativa.
- `docs/structural-ir.md`, `docs/structural-implementation-guide.md`, `PLAN.md`.

## Límites y siguiente paso

La garantía es de origen del **binding**, no de contenido inmutable del objeto.
Las exclusiones del pase de locales siguen vigentes: efectos indirectos, bucles,
try/await, closures/dinámica y lenguajes no admitidos no reciben prueba inventada.
Call wrappers admitidos son eager; las regiones expresivas/cortocircuitos necesitan
P1.5. Callee/receptor, shadowing completo y conexión de Program al buscador siguen
pendientes de P1.1/P1.3/P3.

No se afirma precisión/recall global de GoF con esta matriz: son regresiones de
procedencia fuente con oráculo explícito. El inventario original sigue en 44 ready
y 33 design, sujeto al recuento real del catálogo.

## Validación ejecutada

- Matriz nueva final: **72 passed** (cinco lenguajes; incluye posiciones, lecturas
  repetidas, aliases, ramas, orden, JSON y archivos con offsets idénticos).
- Argumentos + caché: **96 passed**.
- Suite completa: **7.346 passed, 146 xfailed**, 268,16 s, sin fallos.
- `.venv/bin/python -m mypy src/ken`: **107 archivos, sin errores**.
- Inventario recalculado: **44 ready / 33 design GoF**.

Comandos:

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_argument_occurrence_flow.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_argument_occurrence_flow.py tests/structural/test_cache_service.py tests/structural/test_graph_cache_invalidation.py
.venv/bin/python -m pytest -o addopts='' -q --junitxml=/tmp/ken-p1-final-tests.xml
.venv/bin/python -m mypy src/ken
```

La primera ejecución estructural amplia encontró dos fallos de roundtrip: tuplas
en `cases` se convertían en listas al pasar por JSON. Se corrigió almacenando listas
desde el inicio y se reforzó el test de igualdad del grafo restaurado. La suite
completa indicada arriba se ejecutó después de esa corrección.

[Resumen y hashes de validación](P1-argument-checks.json). La matriz verifica parsing
sin diagnósticos y análisis; no se ejecutó compilación de fixtures con toolchains
externos. Los negativos de código muerto/indefinido prueban además entradas que
pueden ser rechazadas por el compilador de un lenguaje estático.

## Benchmark comparativo sobre repositorios externos

Se ejecutó el mismo runner con un snapshot de `5d2486c` en un directorio temporal
(`git archive HEAD src/ken`) y con el código actual. Cinco muestras por caso,
parsers calientes, caché de disco vacía para cold y reutilizada para warm; sin
suite en paralelo y con `--no-diagnostics --require-stable`.
Son **39 archivos**, no repositorios completos: Retry Java (8), Flask (24) y Chain
of Responsibility Rust (7). Los hashes de las fuentes, catálogo y runner coinciden;
los hashes del motor identifican ambos estados. Ninguno cambió durante su medición.

Medianas en milisegundos, antes → después:

| Scope | Linking | Proyección de consulta | Búsqueda cold | Búsqueda warm |
|---|---:|---:|---:|---:|
| Retry Java | 32,09 → 29,53 | 4,12 → 3,19 | 165,25 → 165,58 | 67,08 → 66,65 |
| Flask Python | 1.188,90 → 1.010,32 | 206,84 → 168,81 | 4.639,44 → 4.964,97 | 2.039,52 → 1.639,92 |
| Chain Rust | 8,72 → 7,37 | 2,04 → 1,77 | 93,30 → 94,83 | 47,00 → 49,43 |

Flask warm mejora 19,6%, pero cold empeora 7,0%; Rust warm empeora 5,2%.
No se afirma una mejora uniforme ni se atribuye todo el delta a una sola función.
El mapa de llamadas ahora evita el recorrido cuadrático anterior; los nuevos
hechos también agregan bytes al grafo (Flask fuente JSON: 52.180.267 → 52.344.466).
No se midió memoria con tracemalloc en esta comparación; las etapas se miden por
separado y sus tiempos no deben sumarse.

Las 33 raíces mantienen fingerprints de matches entre versiones; batch/prepared/
cold/warm coinciden y terminan completos en las cinco muestras. Un smoke separado
comprueba **104 definiciones × 3 scopes = 312 ejecuciones completas**. Esto valida
regresión de ejecución; no sustituye revisión semántica TP/FP de cada match externo.

Evidencia reproducible:

- [Antes: IR 1.47](P1-pipeline-before.json).
- [Después: IR 1.48](P1-pipeline-after.json).
- [Smoke de todas las definiciones](P1-all-definitions.json).

```sh
# Mismos argumentos en ambos motores; para baseline usar PYTHONPATH del snapshot.
.venv/bin/python examples/bench/validate_search_pipeline.py --case retry-java /tmp/ken-pattern-corpus/java-patterns retry/src/main/java/ --case flask-python /tmp/ken-real-repos/flask src/flask/ --case chain-rust /tmp/ken-pattern-corpus/guru-rust behavioral/chain-of-responsibility/ --repeats 5 --no-diagnostics --require-stable --output /tmp/ken-p1-current-pipeline.json
# Repetir esos --case con --all-definitions-only para el smoke separado.
```
