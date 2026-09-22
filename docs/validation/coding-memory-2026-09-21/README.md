# Memoria reutilizable para programar: integración y prueba con Codex CLI

2026-09-21. La integración permite conservar conclusiones con evidencia, supuestos
y dependencias, recuperarlas en otra sesión y advertir cuándo requieren revisión.
Ocho sesiones reales de Codex CLI sobre copias de Ken produjeron diagnósticos
correctos en los casos observados. **No demostraron un ahorro consistente de
tokens ni una mejora de exactitud frente a las memorias existentes.** Sí hicieron
visible una regresión en `ken_read`, corregida y cubierta por pruebas.

## Qué se implementó

Se extendieron `ken_remember` y `ken_recall`, la misma base SQLite y los hooks
existentes. El agente registra una conclusión breve y una `justification` con
motivo, evidencia de archivo, dependencias, supuestos y cómo revisarla. Recuperar
comprueba hashes de las entradas declaradas; no vuelve a ejecutar el razonamiento.
Los estados son `unchanged`, `stale`, `unknown` y `untracked`. El primero sólo
significa que esas entradas coinciden; no prueba la conclusión ni sus supuestos.

`ken_recall(detail="summary", max_chars=1800)` entrega contexto acotado; `full`
amplía la evidencia. Los hooks aportan resúmenes seleccionados por el ranking,
con vigencia y deduplicación durante la sesión. La captura sigue siendo explícita.
No se incorporan llamadas LLM ni NLP al camino de los hooks.

La integración opcional `textgraph.ken_memory.export_finding` exporta una respuesta
del nuevo grafo lingüístico, previamente verificada, como conclusión con recibo y
dependencias. No utiliza el almacén de ternas ni convierte las notas de programación
en ternas. El motor experimental conserva sus límites de interpretación y cobertura.
Esta evaluación de programación usa notas reales y pruebas de código; no supone
que el parser lingüístico entiende el código fuente.

Ver el [contrato y ejemplos de uso](../../design/justified-memory.md). El código
está integrado en el checkout. Los procesos MCP y daemon ya abiertos necesitan
reiniciarse para cargarlo; esta evaluación no reconfiguró esos procesos del usuario.

## Datos y método

El [manifiesto](manifest.json) registra las copias y los prompts. Se tomó una
copia SQLite consistente de la base real del proyecto, con:

| Dato | Cantidad |
|---|---:|
| Notas persistidas | 275 |
| Sesiones registradas | 60 |
| Contextos | 40.172 |
| Interacciones | 16.105 |
| Archivos indexados | 2.532 |
| Símbolos indexados | 8.432 |

Ambas variantes conservaban las mismas notas históricas y el mismo índice. En
la candidata se añadió justificación a la nota relevante, ligada a los archivos
de la copia y a una comprobación focal actual. No se convirtió retrospectivamente
todo el historial en conocimiento verificado. Las mutaciones se hicieron sólo
en las copias temporales.

Se ejecutó Codex CLI 0.153.4, con el modelo configurado `gpt-6-astra`, sesiones
efímeras, sandbox de sólo lectura y un servidor MCP Ken real apuntando a cada
copia. No se fijó un modelo diferente. Se pidieron diagnósticos y recomendaciones,
sin edición de código ni memorias. Las pruebas de pytest las ejecutó el evaluador,
no los agentes de diagnóstico.

La selección inicial de archivos y notas fue idéntica y prefijada para cada par.
El bloque de memoria se produjo con el renderizador usado por el hook y se añadió
al prompt de la candidata. **No fue una prueba de activación de hooks del host
Codex ni de precisión del ranking.** Los manejadores de hooks se verificaron por
separado en las pruebas de integración. Este control permite observar el uso de
la memoria, sin confundirlo con diferencias de recuperación.

La preparación guarda el código de un worktree con cambios locales, no una
versión publicada. Se conservaron las [huellas de los archivos relevantes](source-sha256.json).
Las seis primeras ejecuciones conservaron el lector anterior;
el último par incorporó su corrección y mantuvo los mismos prompts.

## Casos y comportamiento observado

1. **Ampliar una tool con `list[dict[str, Any]]`, tanto MCP como CLI.** Ambas
   variantes localizaron el registro, el esquema de elementos y la conversión
   JSON de argparse. Recomendaron probar `ken.cli.main`, porque llamar sólo al
   wrapper MCP no cubre el contrato CLI. El resultado se mantuvo tras corregir
   el lector. Respuestas finales: [clásica](mcp-baseline-fixed.answer.md) y
   [justificada](mcp-memory-fixed.answer.md).
2. **El mismo problema con una regresión posterior a la memoria.** Se cambió
   `_tool_py_type("object")` para devolver `str`, reproduciendo el fallo que una
   nota histórica daba por resuelto. Ambas variantes detectaron el defecto actual.
   La candidata recibió el aviso `REVISAR` antes de leer y mencionó explícitamente
   que había cambiado `cli.py`. Es una señal útil de vigencia; no prueba una mejora
   de exactitud, porque el control también acertó. Respuestas:
   [clásica](mcp-stale-baseline.answer.md), [justificada](mcp-stale-memory.answer.md).
3. **Evaluar una optimización peligrosa de BODY.** Ambas variantes descartaron
   proyectar el entorno exclusivamente sobre `SourceExecutor._inputs`: el acceso
   a `current.values()` y las referencias de `Clause.name` requieren un contrato
   de dependencias más completo. Recomendaron comparación diferencial con cachés
   independientes. La nota menciona 109 regresiones históricas; esa cifra fue
   atribuida a la nota, **no vuelta a medir** en esta evaluación. Respuestas:
   [clásica](body-baseline.answer.md), [justificada](body-memory.answer.md).

La corrección de las respuestas se revisó manualmente contra estos criterios y
el código congelado. No hay un juez automático ni una puntuación estadística.
Los agentes continuaron consultando notas completas y leyendo código incluso con
el resumen disponible: añadir metadatos no basta para evitar repetir trabajo.

## Tokens y llamadas

Las cifras vienen de `turn.completed.usage` y de las llamadas terminadas en los
JSONL. Entrada es el consumo acumulado durante los turnos de herramientas, no el
tamaño máximo del contexto. «Sin caché» es entrada menos entrada cacheada; no es
una medición de coste monetario. [Resultados y trazas extraídas](agent-results.json).

| Caso | Memoria | Llamadas | Entrada | Cacheada | Sin caché | Salida |
|---|---|---:|---:|---:|---:|---:|
| MCP original | Clásica | 14 | 121.661 | 101.504 | 20.157 | 1.158 |
| MCP original | Justificada | 13 | 127.246 | 106.368 | 20.878 | 1.324 |
| MCP con regresión | Clásica | 10 | 132.263 | 109.952 | 22.311 | 1.430 |
| MCP con regresión | Justificada | 9 | 119.214 | 94.848 | 24.366 | 1.224 |
| BODY | Clásica | 6 | 113.746 | 99.840 | 13.906 | 1.169 |
| BODY | Justificada | 6 | 111.879 | 96.000 | 15.879 | 1.130 |
| MCP, lector corregido | Clásica | 7 | 98.909 | 72.320 | 26.589 | 1.179 |
| MCP, lector corregido | Justificada | 10 | 97.276 | 79.744 | 17.532 | 986 |

En los primeros tres pares, la candidata pasó de 30 a 28 llamadas y redujo la
entrada total un 2,54%, pero **aumentó la entrada sin caché un 8,42%**. En el par
con el lector corregido, redujo entrada un 1,65% y entrada sin caché un 34,06%,
pero aumentó de 7 a 10 llamadas. Esta variación impide atribuir un ahorro estable.
Hay una ejecución por condición, sin orden aleatorizado ni control de la caché.
No deben compararse esos porcentajes como una estimación causal del ahorro.

## Defecto encontrado en la experiencia real

`ken_read(include=["source"], qualname=...)` enviaba su valor centinela
`max_chars=0` al lector de fragmentos. Éste aplicaba un mínimo de un carácter:
el agente recibía sólo el primer dígito del número de línea y recurría a `sed`
para ver el código. También se enviaba `start_line=0` como límite explícito.

Se normalizaron los valores omitidos al adaptar los argumentos: presupuesto útil
de 12.000 caracteres y límites de línea `None`. Se conservan los presupuestos
positivos explícitos. Cuatro regresiones ejercitan lectura por símbolo, lectura
sin rango, límite explícito y el CLI real. El último par de Codex utilizó esta
corrección y produjo recomendaciones correctas. La reducción entre rondas no
puede atribuirse exclusivamente al fix debido a la variación de las sesiones.

## Validación de la implementación

- **248 pruebas pasaron**, incluyendo memoria, sesiones, hooks, MCP, CLI, ranking,
  esquemas existentes y el adaptador del grafo. [JUnit](tests.xml).
- Mypy focal: **sin errores en 7 archivos**. [Salida](mypy-memory.txt).
- Mypy global: **448 errores en 12 archivos de KQL2/structural ajenos a esta
  integración**, sobre 238 revisados. No se presenta el repositorio entero como
  validado. [Salida completa](mypy-full.txt).
- Las comprobaciones focales del experimento pasaron: una prueba de conversión
  CLI y seis de inicializadores BODY. La variante deliberadamente rota de CLI
  hizo fallar su prueba, como se esperaba. [Evidencia](checks.json).
- Cada copia del último par pasó las cuatro regresiones del lector y la prueba
  de conversión CLI: [clásica](mcp-baseline-fixed.checks.txt),
  [justificada](mcp-memory-fixed.checks.txt).

Se cubrieron reapertura de sesiones, cambios relevantes e irrelevantes, archivos
nuevos dentro de un alcance, evidencias alteradas, dependencias ausentes, límites
de lectura, hipótesis, atomicidad ante carreras, compatibilidad con notas antiguas,
deduplicación y reaparición de avisos. En la reutilización de un recibo del grafo,
los métodos de parseo, consulta y verificación se sustituyeron por funciones que
fallan si se llaman: recuperar la conclusión no volvió a ejecutar el motor.

Comando del lote principal:

```sh
.venv/bin/python -m pytest \
  tests/test_justified_memory.py tests/test_structural_memory_bridge.py tests/test_mcp_read.py \
  tests/test_search_cli.py tests/test_session_brief.py tests/test_findings_graph.py \
  tests/test_embedding_spaces.py tests/test_mcp_schema.py tests/test_daemon_rank_mcp.py \
  tests/test_daemon_helpers.py tests/test_daemon_state.py tests/test_daemon_http_resilience.py \
  tests/test_hook.py tests/test_codex_hooks_template.py tests/test_hooks_template.py \
  tests/test_reasoning_memory.py -o addopts='' -q
```

## Repetir el experimento

El [evaluador](../../../scripts/evaluate_coding_memory.py) prepara seis condiciones
desde el estado actual de Ken. Usar otra carpeta conserva esta evidencia histórica:

```sh
.venv/bin/python scripts/evaluate_coding_memory.py --out /tmp/ken-memory-new-eval
.venv/bin/python scripts/evaluate_coding_memory.py --out /tmp/ken-memory-new-eval --run mcp-baseline
.venv/bin/python scripts/evaluate_coding_memory.py --out /tmp/ken-memory-new-eval --run mcp-memory
.venv/bin/python scripts/evaluate_coding_memory.py --out /tmp/ken-memory-new-eval --run mcp-stale-baseline
.venv/bin/python scripts/evaluate_coding_memory.py --out /tmp/ken-memory-new-eval --run mcp-stale-memory
.venv/bin/python scripts/evaluate_coding_memory.py --out /tmp/ken-memory-new-eval --run body-baseline
.venv/bin/python scripts/evaluate_coding_memory.py --out /tmp/ken-memory-new-eval --run body-memory
.venv/bin/python scripts/evaluate_coding_memory.py --out /tmp/ken-memory-new-eval --collect
```

`--run` usa la autenticación y el modelo configurados de Codex y consume su cuota.
Prepara un MCP Ken por copia y desactiva los otros MCP configurados para esa
ejecución. Los agentes trabajan en modo de sólo lectura. El código actual incluye
el fix del lector: una nueva preparación no reproduce el defecto anterior.
Los dos runs `*-fixed` archivados son una repetición adicional sobre las copias
originales con ese parche y las nuevas pruebas; no los crea la preparación normal.
Las respuestas archivadas incluyen comentarios de progreso además del cierre.

## Qué conviene mejorar después

1. **Resumen orientado a una decisión reutilizable.** Guardar conclusión, alcance,
   por qué se descartó una alternativa y comprobación mínima. Evitar volcar una
   explicación extensa que el agente termine leyendo completa de nuevo.
2. **Ampliación gradual mejor guiada.** El bloque actual ofrece `detail="full"`;
   puede inducir más lecturas. Probar primero una expansión resumida con presupuesto
   y acceso puntual a evidencia cuando haga falta. Medir el comportamiento antes
   de cambiar el contrato por defecto.
3. **Contratos de aplicabilidad.** Los hashes de archivos son conservadores y
   no descubren dependencias transitivas, entorno ni configuración. Añadir tipos
   concretos de evidencia de código y comprobaciones reutilizables permitiría
   distinguir un comentario editado de un cambio que realmente invalida la decisión.
4. **Repeticiones con tareas de edición reales.** Alternar orden, ampliar casos,
   medir calidad del parche y tests finales, latencia, lecturas, contexto máximo
   y tokens cacheados/sin caché. Esta prueba demuestra integración y señales de
   vigencia; queda por demostrar ahorro sostenido y menos trabajo de implementación.

La dirección útil para Ken es una memoria de decisiones y resultados comprobables,
con contexto breve y revisión selectiva. Con estos datos todavía no corresponde
tratarla como un sistema que evita automáticamente volver a razonar.
