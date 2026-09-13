# Validación en código real — 12 de septiembre de 2026

Este documento conserva la línea de base histórica. Ver los [resultados posteriores
con las consultas canónicas](canonical.md) para el estado actual.

La validación **no permite afirmar que Ken detecte correctamente todos los GoF**.
El lowering de generadores Python pasó el contraste independiente en los cuatro
corpus Python. Sin embargo, las firmas antiguas producen falsos positivos claros,
faltan variantes idiomáticas y algunas búsquedas quedan incompletas por presupuesto.

## Alcance y resultados

Se leyó código; no se importaron módulos, instalaron dependencias ni ejecutaron tests
de los repositorios analizados. Los proyectos locales no fueron modificados.
`infinidev`: `src/`; `SENN`: `senn_byte/` (incluye experimentos, no `new_research/`
ni `new_model/`). Werkzeug y Blinker: `src/`. Zap: archivos Go del proyecto.
Se excluyeron componentes `tests`, `testdata`, `benchmarks`, `tools`, `internal`,
`zaptest`, `target`, `node_modules`, `.venv`, `__pycache__` y sufijos `_test.go`.
No es una auditoría de todo el contenido de los dos proyectos locales.
Los manifiestos actuales incluyen archivos Git rastreados y no ignorados sin rastrear,
su SHA-256 y lenguaje. HEAD por sí solo no reproduce los proyectos locales modificados.

| Repositorio | Archivos analizados | Generadores Python detectados / AST | Consultas incompletas | Evidencia |
|---|---:|---:|---|---|
| infinidev | 485 | 13/13 | facade, gof.builder | [infinidev.json](infinidev.json) |
| SENN | 275 | 31/31 | builder, facade, gof.builder | [senn.json](senn.json) |
| Werkzeug | 53 | 25/25 | gof.builder | [werkzeug-after.json](werkzeug-after.json) |
| Blinker | 3 | 3/3 | ninguna | [blinker-after.json](blinker-after.json) |
| Zap | 45 | — | ninguna | [zap-after.json](zap-after.json) |

Cero diagnósticos de parsing en estos alcances no implica resolución semántica completa.
El oráculo recorre `ast` de Python, atribuyendo `yield`/`yield from` a su función
propietaria y aislando funciones anidadas, clases y lambdas. Compara ubicación,
nombre y línea con la unión de las dos variantes generadoras. No prueba progreso,
agotamiento, efectos de decoradores ni intención del patrón Iterator. No hubo
omisiones ni coincidencias inesperadas frente a ese oráculo sintáctico.

Cada consulta tiene 100.000 estados, 500.000 filas, 1.000 resultados y 5 segundos.
`complete: false` significa resultado inconcluso; cero resultados allí **no** significa
ausencia del patrón. Se recorrieron las 23 firmas antiguas, Iterator/Builder compuestos
y, en las ejecuciones del runner actual, las dos variantes generadoras por separado.
Zap fue ejecutado con el runner inicial (25 consultas, sin oráculo Python).

## Revisión manual: evidencia e interpretación

Esta muestra es deliberada, no aleatoria. No se calcula precisión global ni recall GoF
sobre repositorios cuyo conjunto completo de patrones reales no está etiquetado.

| Caso revisado | Resultado del motor | Evaluación |
|---|---|---|
| infinidev `tool_inspect.py:80`, `iterate_messages_tool_calls` | Iterator generador | Correcto: recorre mensajes y produce llamadas normalizadas. |
| infinidev `_best_effort.py:43`, `best_effort` | Iterator generador | Forma generadora correcta, interpretación GoF incorrecta: `@contextmanager` delimita una operación y maneja excepciones. |
| infinidev `staged_planning.py:225`, `add_evidence` | Observer antiguo | Falso positivo: compara fingerprints para deduplicar evidencia; no notifica suscriptores. |
| infinidev `verification_result.py:40`, `format_for_developer` | Observer antiguo | Falso positivo: recorre resultados de comandos para formatear texto. |
| SENN `fresh_evaluation_corpus.py:217`, `iter_pinned_fineweb_documents` | Iterator generador | Correcto: produce documentos de un stream. No se ejecutó la descarga del dataset. |
| SENN `hf_long_stream.py:156`, `closing_stream` | Iterator generador | Forma sintáctica correcta, pero el decorador construye un context manager de limpieza. |
| Werkzeug `structures.py:665`, `CombinedMultiDict.getlist` | Observer antiguo | Falso positivo: agrega valores de diccionarios. |
| Werkzeug `formparser.py:365`, `MultiPartParser.__exit__` | Observer antiguo | Falso positivo: cierra archivos ante un error. |
| Werkzeug `wsgi.py:268`, `ClosingIterator`; `:344`, `FileWrapper` | Firma antigua sí; Iterator compuesto omite | Falsos negativos del compuesto: avance delegado a otro callable o a `file.read`; no hay escritura local de estado que satisfaga explicit-cursor. |
| Blinker `base.py:24`, `Signal`, `connect:91`, `send:204` | Observer: cero | Falso negativo: registro de receptores, referencias débiles y notificación mediante callbacks; requiere flujo entre almacenamiento, iteración indirecta e invocación. |
| Zap `zapcore/hook.go`, `hooked` | Decorator: cero | Falso negativo: envuelve `Core` y añade hooks. El contrato embebido Go no está resuelto suficientemente. |
| Zap `zapcore/tee.go`, `multiCore` | Composite: cero | Falso negativo: delega operaciones a varios `Core`; el tipo Go nombrado sobre slice no recibe la representación necesaria. |

## Corrección realizada y regresiones

La evaluación de joins positivos seguía el orden textual: primero combinaba cada
generador con operaciones de todo el proyecto y recién después comprobaba
`HAS_OPERATION`. Ahora selecciona el cruce con menos candidatos indexados dentro
de cada bloque positivo, aprovechando bindings existentes. No mueve cláusulas a
través de negación, agregados ni llamadas a consultas nombradas.

En Werkzeug, `gof.iterator` pasó de agotar 100.000 estados sin resultados a completar
con 28 resultados y 16.414 estados, con los mismos límites. En Zap, `gof.builder`
pasó de incompleto a completo sin coincidencias. Builder sigue agotando el presupuesto
en Werkzeug y ambos proyectos locales; el cambio no resuelve todos los problemas de escala.
Los tiempos en JSON incluyen condiciones de esta máquina y ejecuciones concurrentes;
no son un benchmark controlado ni representan latencia con cache caliente.

`test_kenql.py` añade una regresión de 400 generadores con presupuesto acotado y dos
casos de equivalencia de joins con variables repetidas y atributos.
`test_real_world_gaps.py` conserva tres comportamientos deseados como **xfail strict**:
limpieza no debe ser Observer, suscripción de callbacks sí debe serlo y un cursor
delegado debe detectarse. Son limitaciones pendientes explícitas; no tests aprobados.
Las reducciones fueron escritas para Ken, no copiadas de los repositorios.

## Reproducción

Desde la raíz de Ken, con sus dependencias instaladas:

```sh
.venv/bin/python examples/bench/validate_structural_repo.py ../infinidev --prefix src/ --output /tmp/infinidev.json
.venv/bin/python examples/bench/validate_structural_repo.py ../SENN --prefix senn_byte/ --output /tmp/senn.json
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/werkzeug --prefix src/ --output /tmp/werkzeug.json
.venv/bin/python -m pytest tests/structural/test_kenql.py tests/structural/test_real_world_gaps.py
```

Los repositorios públicos se clonaron con `git clone --depth 1` desde sus proyectos
oficiales. Para reproducir una versión exacta, usar los commits siguientes (un clon
nuevo superficial podría requerir obtener ese commit explícitamente). Los JSON
`*-before.json` conservan la ejecución anterior al cambio de orden de joins.

- [werkzeug `f27af2652a798931aa00c2476a4de130f597c1d3`](https://github.com/pallets/werkzeug/tree/f27af2652a798931aa00c2476a4de130f597c1d3)
- [blinker `c3364059663df1ddce32799d6b1922af89a345f6`](https://github.com/pallets-eco/blinker/tree/c3364059663df1ddce32799d6b1922af89a345f6)
- [zap `bb1a55dd13257cf7cbd06b4146674c67ca614dea`](https://github.com/uber-go/zap/tree/bb1a55dd13257cf7cbd06b4146674c67ca614dea)

## Consecuencia para el catálogo

`ready` significa que una variante tiene consulta ejecutable y fixtures; no que
se haya validado universalmente. `design` carece todavía de implementación ejecutable.
La consulta raíz antigua de cada fichero representa una firma aproximada, no una
prueba de la intención GoF. Antes de usar esto para clasificar directorios o detectar
bugs con confianza, hace falta separar explícitamente forma/evidencia de intención,
resolver decoradores y protocolos delegados, fortalecer Observer y modelar tipos
Go embebidos y colecciones nombradas. Estas brechas permanecen abiertas.
