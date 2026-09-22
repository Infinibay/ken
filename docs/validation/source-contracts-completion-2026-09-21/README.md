# Integración de KQL 2 para tareas de programación — 2026-09-21

La implementación vive en `src/ken/`. Comparte el engine KQL existente y no
depende de `experiments/`. Se verificaron contratos reutilizables, búsqueda de
responsables, inspección de llamadas y resultados, memoria con dependencias,
hooks y ejecución desde CLI/MCP. Hay límites de cobertura y rendimiento que
se detallan abajo; estas pruebas no certifican un analizador universal.

## Qué quedó disponible

| Necesidad | Interfaz y comportamiento |
| --- | --- |
| Recordar una regresión | `rule`: consulta, ejemplos positivos/negativos, validación y adopción explícita. |
| Detectar que reaparece | `check`: evidencia, estado, comparación y recibos reproducibles. |
| Encontrar responsables | `who`: documentación y mapa de roles estructurales hipotéticos. |
| Seguir llamadas y resultados | `related` con `roles`/`impact`: identidades, importadores, usos y propagación por retorno. |
| Encontrar código reutilizable | `related(..., available, from_path=...)`: expresiones de acceso Python y obligaciones pendientes. |
| Buscar por una propiedad | `find` con KQL 2 o reglas registradas. |
| Guiar debugging | Consumidores, candidatos inciertos y tests conectados por llamadas/usos. |
| Revisar una migración | Comparación de estados, ubicaciones y cantidades de coincidencias antes/después. |
| Reutilizar contexto arquitectónico | `remember` con evidencia/recibo; `recall` con vigencia por regla y archivos cambiados. |
| Comprobar automáticamente | Hooks para reglas adoptadas como automáticas; agrupación de ediciones y deduplicación de avisos. Adaptador CI con salidas 0/1/2/3. |

El seguimiento entre archivos aplica el criterio de imports explícitos propuesto
por Andrés: un nombre coincidente no establece una llamada. La adquisición lee
imports y conserva ubicaciones originales. Recorre dependencias e importadores
por separado; compartir una dependencia no conecta entre sí a todos sus usuarios.

## Validación automatizada

| Conjunto | Aprobados | Evidencia |
| --- | ---: | --- |
| KQL 2 completo | 1.533 | [JUnit](tests/kql2.xml) |
| Resolución semántica afectada | 266 | [JUnit](tests/semantics.xml) |
| Integración de tools, memoria, hooks y daemon | 183 | [JUnit](tests/integration.xml) |
| Total | **1.982** | [Metadatos](tests/summary.json) |

No hubo fallos ni tests omitidos en estas ejecuciones finales. No se ejecutó
toda la suite histórica del repositorio. Ruff (`F`) pasó en los módulos nuevos
y modificados de esta integración; mypy pasó en 33 archivos de checks,
inspection, knowledge y responsibility; `git diff --check` pasó en los archivos
tracked revisados.

Los casos cubren tres archivos con propagación de retorno, alias, imports
relativos y disposición `src/`, homónimos sin import, bindings ocultados,
imports condicionales ambiguos, ciclos, dos llamadas al mismo método,
transformaciones que rompen la identidad del resultado, presupuestos y rutas
fuera del proyecto. También selección de reglas por dependencias, nuevos
destinos de imports, vigencia por regla, conclusiones completas dentro del
presupuesto y una sesión MCP stdio real con los nuevos modos.

Las pruebas sobre código real detectaron y corrigieron dos errores adicionales:
una referencia a un import dentro de un diccionario se confundía con una variable
local que lo ocultaba; y la normalización de nombres omitía la clase cuando su
identificador no incluía un desplazamiento de bytes. Se añadieron regresiones
para ambos, conservando incertidumbre ante shadowing real y valores transformados.

La CLI encontró el llamador `integration.search` de `report.query_view` entre
archivos reales de `src/ken/checks`, y los dos llamadores de `_atomic_write` dentro
de `vectors.py`. [Resultados sobre el repositorio](real-project/README.md).
Hay cobertura parcial de usos: se conservan los motivos `source_body:unknown`
y `budget:max_rows`, sin presentar estas salidas como inventarios exhaustivos.

El [ciclo sobre código de Ken](cycle/result.json) conserva la secuencia
`pass → fail → pass`, comparación de regresión, memoria `stale` y aviso del
hook. Se usó una copia exacta de un módulo y una mutación deliberada aislada.

## Tres bugs históricos reales

[Resultados y huellas de los blobs](history/result.json). Cada regla tiene
cuatro casos: antes, después, después con distractor y antes con una operación
correcta en otro lugar. Los **12 casos** y las seis comprobaciones antes/después
pasaron. Cada directorio incluye una definición JSON importable y recibos.

| Fix histórico | Guarda estructural | Límite explícito |
| --- | --- | --- |
| `e67c744` — permisos de manifiestos | `_atomic_write` contiene `chmod` | No demuestra el modo ni que el SO aplique el permiso. |
| `1736a1e` — recuperación de espacio | `_vectors_cli` invoca `reclaim_database` | No demuestra el branch de migración, VACUUM ni espacio recuperado. |
| `7d8a195` — gitignore anidado | `iter_files` delega a `is_ignored` | No demuestra el algoritmo interno del matcher. |

Esto demuestra discriminación de regresiones concretas mediante reglas escritas
para ellas, no descubrimiento autónomo de bugs ni precisión general del catálogo.

## Pruebas con Codex CLI

Se pidió identificar dónde se escriben los manifiestos vectoriales, cómo trata
el código sus permisos y quién llama al escritor. Se usaron copias del código
real, sin modificar producción. El baseline inspecciona fuente; la variante
de memoria empieza por `recall` e `impact`. No se eligió un modelo distinto del
configurado por el usuario. La preparación e indexación quedan fuera del tiempo
de las sesiones; no hay una estimación completa de coste de adopción.

| Ejecución | Tools | Caracteres de resultados | Tokens de entrada | Entrada cacheada | Segundos |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ronda 1, fuente | 6 | 23.612 | 117.779 | 90.240 | 66,13 |
| Ronda 1, memoria escueta | 6 | 35.418 | 160.457 | 140.288 | 77,98 |
| Ronda 2, fuente | 4 | 20.945 | 73.143 | 62.336 | 44,45 |
| Ronda 2, memoria revisada | 11 | 17.517 | 117.371 | 105.984 | 87,88 |
| Ronda 3, conclusión completa | 6 | 9.358 | 131.159 | 109.696 | 80,95 |

[Métricas consolidadas](agents/metrics.json), [ronda 1](agents/round-1-sparse/result.json),
[ronda 2](agents/round-2-reviewed/result.json),
[ronda 3](agents/round-3-whole-summary/result.json). Los directorios conservan
respuestas, eventos, errores y huellas del código analizado. El primer intento
no pudo iniciar Codex dentro del sandbox; se conserva en
`agents/initial-sandbox-failure/` y no se cuenta como respuesta del agente.

La ronda 1 tenía una memoria escueta y faltaba `_paths.py` en la copia. La ronda 2
añadió ese archivo, una explicación revisada y lecturas por símbolo. Reveló un
defecto: el resumen de memoria cortaba la conclusión a 320 caracteres, perdiendo
los llamadores y una advertencia sobre permisos. El agente tuvo que ampliar la
memoria después de varias lecturas de fuente.

La ronda 3 repitió solamente la variante de memoria, con los mismos archivos y
pregunta de la ronda 2, después de corregir ese recorte. Recibió un **55,3% menos
de caracteres de herramientas** que el baseline de la ronda 2, pero usó más
tokens y tardó más. Las respuestas conservaron la distinción entre código
observado y garantías de ejecución. La resolución exacta de `KEN_DIR_NAME` quedó
limitada por su ausencia en el índice de símbolos; se respondió mediante el
helper y la constante, sin inventar su valor.

La respuesta de la ronda 3 sí cometió una imprecisión de identidad: llamó
`VectorStore.compact` a la función global `compact`. La traza original se conserva;
no se cuenta como exactitud perfecta. La memoria del script de reproducción ahora
explicita que `compact` es global. Ese ajuste posterior no se volvió a medir con
agentes y no se atribuye una mejora de precisión sin una nueva ejecución.

**No se demostró ahorro de tokens entre sesiones.** Son cinco sesiones exitosas,
con prompts diferentes por condición y una repetición no emparejada. Los tokens
de entrada son acumulados reportados por el CLI e incluyen entrada cacheada;
no equivalen al tamaño máximo del contexto ni al coste facturado. Haría falta
repetir tareas y equilibrar orden/caché para estimar una mejora estable.

## Límites y próximos pasos concretos

- `impact` propaga identidad a través de retornos observados. Un argumento se
  informa como uso; no se sigue arbitrariamente dentro del receptor.
- Roles son hipótesis de estructura; tests conectados no demuestran assertions
  suficientes. La documentación aporta intención, no prueba de implementación.
- `available` cubre accesos Python explícitos. Tipos, inicialización, efectos,
  shadowing en el punto de uso y sustitución segura siguen siendo obligaciones.
  El builtin general de disponibilidad continúa como propuesta separada.
- El agente escribe e interpreta consultas. No se implementó un compilador
  general de lenguaje natural ni generación/adopción autónoma de nuevas reglas.
- En el Ken completo, el recorrido inicial adquiría 264 de 268 archivos de `src`
  por alternar direcciones. Separarlas redujo la selección a 40, pero `impact`
  sobre ese alcance todavía agotó 30 segundos. El resultado fue `unknown`, no
  ausencia de consumidores. La siguiente mejora de rendimiento es empujar la
  identidad del objetivo a las consultas y adquirir vecinos bajo demanda, en
  vez de recolectar todas las observaciones antes de filtrar el grafo.
- Para reducir contexto, conviene evaluar recuperación escalonada: usar la
  conclusión vigente y ampliar sólo la parte faltante. Menos texto de resultados
  por sí solo no garantiza menos tokens ni latencia.

## Cómo repetirlo

```sh
.venv/bin/python scripts/evaluate_historical_contracts.py --output /tmp/ken-history
.venv/bin/python scripts/evaluate_source_contracts.py --output /tmp/ken-cycle
.venv/bin/python scripts/evaluate_contract_agent.py --output /tmp/ken-agent --run-agents
.venv/bin/python scripts/check_contracts_ci.py --root .
```

El último comando ejecuta las reglas que ya se hayan adoptado; no registra ni
habilita reglas automáticamente. Salidas: 0 pass, 1 fail, 2 unknown y 3 sin reglas
aplicables. CLI usa el código actual; los procesos MCP/daemon ya abiertos deben
reiniciarse para cargar la implementación nueva.

La [guía de uso](../../design/code-inspection.md) explica los conceptos,
interfaces y límites. La [guía de contratos](../../design/source-contract-tools.md)
incluye la definición completa de una regla y ejemplos CLI/MCP.
