# Benchmark Codex/Ken/Infinidev — historial y piloto limitado

Fecha: 2026-09-07. **Estado histórico de los primeros intentos; véase actualización al final.** No se ejecutó la comparación: el modelo solicitado no está disponible con la autenticación actual. No hay mediciones de utilidad, tokens, calidad ni velocidad con/sin Ken.

## Entorno observado

- `codex --version`: `codex-cli 0.153.4`.
- `codex login status`: `Logged in using ChatGPT` (sin consultar ni copiar credenciales).
- `codex` y `ken` disponibles en `~/.local/bin`.
- Estado inicial del checkout: únicamente `?? .infinidev/`; no se modificó código del producto ni configuración global.
- `ken find --help` falla porque la CLI instalada no ofrece `find`; no equivale a que falte `ken_find` por MCP. No se evaluó esa integración porque falló el requisito previo del modelo.

## Probe ejecutado

Se interpretó provisionalmente «gpt astra» como el identificador `gpt-astra`, sin sustituirlo por otro modelo. Una sola petición en un directorio temporal vacío, timeout de 75 segundos, sin herramientas solicitadas:

```sh
WORK=$(mktemp -d)
codex exec --ignore-user-config --ignore-rules --ephemeral \
  --skip-git-repo-check --sandbox read-only --model gpt-astra \
  --json -C "$WORK" 'Reply only OK. Do not use tools or read files.'
```

La configuración de usuario se ignoró pero se utilizó la autenticación ChatGPT existente. No se copió el proyecto ni historial privado para este probe.

Resultado real: salida **1**, **3.107 segundos** de tiempo total del proceso (no latencia de inferencia). El CLI avisó de falta de metadata del modelo y el servidor rechazó la solicitud con HTTP 400:

```text
Model metadata for `gpt-astra` not found. Defaulting to fallback metadata; this can degrade performance and cause issues.
The 'gpt-astra' model is not supported when using Codex with a ChatGPT account.
```

El fallback anunciado es de metadata; no hubo inferencia exitosa ni evidencia de uso de otro modelo. El stream terminó en `turn.failed`.

## Evidencia cruda

Directorio local temporal (puede ser eliminado por el sistema):

`/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-codex-benchmark-gfxig1bc/`

- `probe.stdout.jsonl`: eventos crudos del CLI.
- `probe.stderr.txt`: stderr (`Reading additional input from stdin...`).
- `probe.metadata.json`: comando, versión, estado de autenticación, salida y duración.

## Límite y siguiente paso

Este resultado solo prueba el rechazo de **ese identificador** con **esta cuenta ChatGPT**, no la inexistencia de un modelo llamado Astra en otros contextos. Es necesario confirmar el identificador correcto o autorizar otro modelo disponible en la suscripción. No se utilizó API key ni un modelo sustituto.

Una vez resuelto, la campaña prevista usará varias tareas idénticas en copias nuevas del mismo snapshot: condición sin Ken y condición con instrucciones e integración Ken verificadas. Se conservarán prompts, logs JSONL, configuración efectiva, tiempos, uso de tokens y comprobaciones por tarea. El coste de indexación se separará del tiempo de tarea y se documentarán repeticiones y límites. Esto es metodología pendiente, **no resultados ejecutados**.


## Segundo preflight: identificador literal `gpu-6-astra`

A petición del usuario se probó exactamente `gpu-6-astra`, sin variantes ni sustitución. Se conserva arriba el intento anterior; este apartado añade una comprobación nueva, no un benchmark.

- CLI: `codex-cli 0.153.4`.
- Autenticación comprobada de nuevo: `codex login status` → `Logged in using ChatGPT`.
- Una petición, directorio temporal vacío, sandbox de solo lectura, configuración e instrucciones de usuario ignoradas, sesión efímera y límite de 75 segundos. Se eliminaron `OPENAI_API_KEY` y `CODEX_API_KEY` únicamente del entorno del subproceso; no se leyeron credenciales ni se cambió configuración global.

```sh
codex exec --ignore-user-config --ignore-rules --ephemeral \
  --skip-git-repo-check --sandbox read-only --model gpu-6-astra \
  --json -C "$WORK" 'Reply only OK. Do not use tools or read files.'
```

**Resultado:** código de salida del CLI **1**, duración total del proceso **3.465 segundos**, HTTP **400**, evento final `turn.failed`. Error exacto del servidor:

```text
The 'gpu-6-astra' model is not supported when using Codex with a ChatGPT account.
```

También apareció el aviso `Model metadata for `gpu-6-astra` not found. Defaulting to fallback metadata; this can degrade performance and cause issues.` El fallback alude a metadata, no demuestra cambio de modelo ni inferencia exitosa.

### Evidencia persistida del segundo intento

- `docs/benchmark-evidence/2026-09-07-gpu-6-astra/probe.stdout.jsonl`: eventos crudos y error HTTP.
- `docs/benchmark-evidence/2026-09-07-gpu-6-astra/probe.stderr.txt`: stderr crudo.
- `docs/benchmark-evidence/2026-09-07-gpu-6-astra/probe.metadata.json`: comando exacto, versión, autenticación sin secretos, salida y duración.
- Original temporal: `/var/folders/35/r0y9sb516yqcycv3n7ls6y_c0000gn/T/ken-codex-gpu-6-astra-kv__8r4d/`.

Se detuvo tras el rechazo, sin reintentos ni modificaciones del producto. **La comparación con/sin Ken sigue bloqueada y no fue ejecutada**: no hay métricas de tokens, calidad o rendimiento. Los 3.465 segundos miden un proceso fallido, no inferencia ni efecto de Ken. El resultado limita la disponibilidad de este identificador con esta autenticación; no demuestra inexistencia en otros entornos. Para continuar hace falta un identificador aceptado o autorización explícita para otro modelo de la suscripción.


## Actualización: `gpt-6-astra` aceptado y piloto de tres condiciones

Tras la nueva indicación explícita del usuario se probó `gpt-6-astra` (no `gpu-6-astra`). Codex/ChatGPT respondió OK, salida 0, 5.559 s; usage: input 14713, cached input 11520, output 5. Evidencia: `docs/benchmark-evidence/2026-09-07-gpt-6-astra/`. Infinidev con `--provider openai_subscription --model gpt-6-astra --no-tui` respondió OK, salida 0, 26.506 s, con aviso de reintento por respuesta sin function call. Evidencia: `docs/benchmark-evidence/2026-09-07-infinidev-gpt-6-astra/`. Estos son preflights, no medidas comparables de implementación.

### Metodología realmente ejecutada

Seis corridas secuenciales, una por combinación de dos tareas pequeñas y tres condiciones, con límite de **90 segundos por proceso**. Copias temporales nuevas de archivos tracked del checkout actual, sin copiar `.git`, `.infinidev`, `.env`, `.ken`, `.codex`, `.claude`, `.mcp.json` ni `opencode.json`; repositorios nuevos inicializados sin commits. Sin cambios al producto del checkout original. Se limpiaron del entorno de ejecución prefijos INFINIDEV_, KEN_, OPENAI_ y ANTHROPIC_. No se copiaron credenciales; los clientes utilizaron la autenticación de suscripción disponible. Esto no equivale a un contenedor hermético ni a controles idénticos entre los dos clientes.

- **Codex sin Ken:** AGENTS.md eliminados de la copia; sin servidor MCP configurado.
- **Codex con Ken solicitado:** AGENTS.md del proyecto conservados; `ken install --no-wire "$WORK"` antes de la ejecución; servidor configurado solo mediante argumentos locales. **La llamada MCP fue rechazada en ambas tareas**, por lo que no representa Ken funcionando.
- **Infinidev nativo:** AGENTS.md conservados, configuración local nueva, provider subscription y modelo explícitos; inició índice/daemon Ken automáticamente, orquestador y trabajador. Su arranque/indexación está incluido en los 90 segundos, mientras el setup explícito Codex/Ken está fuera: los tiempos no aíslan el coste de inferencia ni normalizan arranque.

Las tareas pidieron crear `socket_path` y añadir `must_exist` keyword-only al resolvedor de rutas. **Los prompts dieron archivo y símbolo exactos.** Por ello este es solo un piloto técnico, **no satisface la nueva petición de tareas que exijan explorar**. Los prompts literales y comandos completos están en cada `run.metadata.json` y en `run.py`. No se han ejecutado nuevas tandas tras esa aclaración.

Comandos efectivos (rutas concretas en metadata):

```sh
codex exec --ignore-user-config --ignore-rules --ephemeral \
  --skip-git-repo-check --sandbox workspace-write --model gpt-6-astra \
  --json -C "$WORK" "$PROMPT"
# En condición MCP, antes de PROMPT se añadieron:
-c 'mcp_servers.ken.command="ken"' \
-c 'mcp_servers.ken.args=["mcp", "<WORK>"]'
# Otro cliente:
infinidev --no-tui --provider openai_subscription --model gpt-6-astra -p "$PROMPT"
```

No se pasó un override de aprobación MCP. Error observado literal:

```text
MCP tool call requires approval, but approval policy is never
```

No se ha cambiado configuración global ni se han ampliado permisos para sortearlo. El diagnóstico es fallo de integración/permisos de esta campaña, **no un fallo de búsqueda ni una medición de utilidad de Ken**.

### Resultados crudos consolidados

| Tarea | Condición | Segundos | Terminación | Comprobación externa |
|---|---|---:|---|---|
| socket | Codex sin Ken | 87.693 | salida 0 | pasa |
| socket | Codex MCP solicitado, bloqueado | 86.402 | salida 0 | pasa |
| socket | Infinidev | 90.026 | timeout, salida -15 | pasa |
| must-exist | Codex sin Ken | 90.026 | timeout, salida -15 | pasa tras corregir arnés |
| must-exist | Codex MCP solicitado, bloqueado | 90.032 | timeout, salida -15 | pasa tras corregir arnés |
| must-exist | Infinidev | 90.020 | timeout, salida -15 | pasa tras corregir arnés |

**Pasar la comprobación externa no demuestra que el agente terminara ni ejecutara sus tests.** Cuatro procesos fueron interrumpidos. No se trata el timeout como tiempo de finalización ni como un cero de consumo.

| Tarea / condición | Input tokens | Cached input (incluidos en input) | Output | Comandos completados | MCP completados (fallidos) | Eventos file_change |
|---|---:|---:|---:|---:|---:|---:|
| socket / sin Ken | 216103 | 188160 | 1161 | 8 | 0 | 1 |
| socket / MCP bloqueado | 209911 | 185216 | 1327 | 9 | 1 | 1 |
| must-exist / sin Ken | no disponible | no disponible | no disponible | 7 | 0 | 1 |
| must-exist / MCP bloqueado | no disponible | no disponible | no disponible | 8 | 1 | 1 |

Tokens Codex proceden de `turn.completed.usage`; en los timeout no apareció ese evento. No se suman de nuevo cached input ni reasoning output al total. Reasoning output reportado en socket: 125 sin Ken, 159 MCP bloqueado. Input no cacheado por resta: 27943 y 24695, respectivamente. No es una estimación de factura ni ahorro atribuible a Ken.

Infinidev registró **15 líneas `running` en socket y 13 en must-exist**, incluyendo gestión de equipo y trabajador; son intentos visibles hasta el corte, no una métrica normalizada equivalente al stream Codex. Sus contadores `ktk` de consola son redondeados y por actor, no un total comparable. Las bases locales copiadas tras el timeout tienen `session_messages` vacío y únicamente tres eventos iniciales en `execution_events`; **no hay usage total verificable**. No se infiere que Infinidev consuma menos tokens a partir de esos datos.

### Calidad y verificaciones: alcance real

Los tres diffs socket implementan el mismo cuerpo de función. Los tests producidos por Infinidev comprueban además que no se crean rutas; los dos Codex comprueban composición absoluta/relativa. En la traza Infinidev/socket fallaron intentos de ejecutar tests: `python: command not found`, luego `No module named pytest`, luego `No module named 'ken'`. Esto revela entorno de tests no preparado en el piloto, no un defecto de la función. No se reparó el producto para acomodar el experimento.

En must-exist los tres diffs añaden el parámetro keyword-only y comprueban existencia después de rechazar escapes. Los dos Codex incluyen cambios de tests; el diff Infinidev al corte solo contiene implementación. Esto es una observación puntual de trabajo incompleto, no un ranking general de calidad.

El verificador original must-exist falló en las tres copias por un error del **arnés**: comparaba `Path('/var/...')` con rutas resueltas a `/private/var/...` en macOS. Se corrigió solo el root esperado con `Path(d).resolve()` y se repitieron los tres checks, todos salida 0. Se conservaron `verify.*` originales y `verify-corrected.*`; no se borraron fallos ni se reejecutaron modelos. El check corregido verifica archivo/directorio existente, missing por defecto, FileNotFoundError con true, y ValueError para escape inexistente antes de comprobar existencia. El check socket verifica composición absoluta y relativa. Son comprobaciones focalizadas, no suite completa ni garantía de ausencia de regresiones.

### Artefactos y conclusión

Base: `docs/benchmark-evidence/2026-09-07-three-way/`:

- `run.py`: runner y prompts usados, incluyendo arnés original para conservar historia.
- `summary.json`: métricas consolidadas por seis condiciones/tareas; null significa no disponible.
- Carpetas `{socket,must-exist}--{codex-no-ken,codex-ken,infinidev}/`: `run.stdout`, `run.stderr`, `run.metadata.json`, `changes.diff`, `status.txt`, `verify.*`; correcciones en `verify-corrected.*`; setup MCP en `setup.*`.
- `session.db` de cada Infinidev: snapshot de sesión nueva del experimento, no historial previo. No se necesita distribuir estas bases para leer las conclusiones.

**No hay ganador demostrable en tokens, tool-calls ni calidad.** Faltan Ken MCP funcional, tareas exploratorias, entorno de tests preparado, ejecuciones completas y repeticiones. Las diferencias pequeñas entre los dos socket Codex no miden beneficio de Ken, porque su única llamada falló. El piloto aporta comandos, bloqueos y diffs verificables; no debe presentarse como la comparación solicitada ya resuelta. Siguiente campaña pendiente de revisión: instrucciones de alto nivel sin ruta/símbolo, permiso MCP local mínimo comprobado, límites suficientes y medidas homogéneas; sin mejoras de producto.


## Preparación posterior (sin nueva campaña)

Se comprobó el permiso MCP local mínimo y luego se corrigió el argumento al schema instalado (`query`, no `task`). El preflight corregido terminó en 15.852 s, salida 0; la llamada no dio error, pero devolvió `content=[]`, por lo que aún no demuestra búsqueda útil. Se conserva el intento de schema fallido. Propuesta de dos tareas exploratorias sin rutas/símbolos, versiones, plan de métricas y bloqueos pendientes en [preparación](benchmark-evidence/2026-09-07-exploratory-preparation.md). Tokens exactos Infinidev siguen sin fuente comprobada. No se lanzó campaña; ejecución siempre secuencial.

## Campaña exploratoria posterior: resultados y repeticiones

Este apartado actualiza las afirmaciones históricas de «sin nueva campaña»: sí se ejecutaron después las tareas exploratorias A (seguridad de rutas) y B (descubrimiento del proyecto y conexión al daemon), sin dar archivos ni símbolos en el prompt. Prompts, rúbrica no entregada a los agentes y runner: `docs/benchmark-evidence/2026-09-07-exploratory/{prompts.json,rubric.private.json,run.py}`. Modelo explícito `gpt-6-astra`, suscripción en ambos clientes; no sustituye el resultado negativo de `gpu-6-astra`.

### Controles y cambios de protocolo

Corridas siempre secuenciales: nunca se lanzó otra celda mientras quedaba un Codex/Infinidev de benchmark activo. Cada celda utiliza un snapshot nuevo de archivos tracked, manifiesto SHA-256 y repositorio nuevo sin historial privado. Sin Ken se eliminan AGENTS y no se configura MCP; con Ken se entrega guía de esquemas instalados, se prepara índice mediante `ken install --no-wire --embed` y Codex recibe aprobación MCP local. No es una comparación de instrucciones idénticas: se mide el conjunto guía+herramientas+índice. Ken instalado/servido es el paquete instalado, no una implementación modificada del checkout. Setup explícito queda fuera del tiempo de tarea y se conserva por separado en `setup.metadata.json`.

Hubo cambios de protocolo que impiden tratar todas las corridas como réplicas equivalentes. Los intentos Infinidev iniciales se cortaron por timeout; se conservaron. Se repitieron sin límite a petición del usuario. A sin límite finalizó en 345.070 s, pero no consiguió ejecutar internamente su comprobación; su script entregado sí pasó después una comprobación externa de 12 casos (salida 0, 0.043 s). B sin límite se detuvo explícitamente para activar autoaprobación local (salida -15, 238.979 s, no timeout; `intervention.autoapprove.json`). No son tiempos de tareas exitosas comparables.

Para las repeticiones `--autoapprove` se escribieron únicamente en la copia temporal los cuatro permisos `EXECUTE_COMMANDS_PERMISSION`, `FILE_OPERATIONS_PERMISSION`, `TOOL_EFFECTS_PERMISSION` y `MCP_PERMISSION` con valor `auto_approve`; la carga mediante el Python instalado se verificó antes de lanzar cada proceso (`permissions-check.*`). No se cambió configuración global. No se aplicó deadline a estas repeticiones. La configuración actual del runner refleja esta última fase; los metadatos e intervenciones conservan las diferencias de intentos anteriores.

### Codex: cuatro respuestas completas

| Tarea / condición | Tiempo proceso (s) | Input | Cache incluido en input | Output | Shell completados | MCP completados | Calidad /10 | Check externo |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| A / sin Ken | no disponible | 218899 | 170368 | 3037 | 9 | 0 | 10 | salida 0 |
| A / con Ken | 156.818 | 282690 | 253184 | 3597 | 8 | 6 | 10 | salida 0 |
| B / sin Ken | 211.765* | 247004 | 208896 | 4968 | 7 | 0 | 10 | salida 0 |
| B / con Ken | 164.270 | 317115 | 274304 | 4012 | 8 | 6 | 10 | salida 0 |

A sin Ken tiene `turn.completed` y respuesta, pero se perdió la medición fiable de pared al morir el supervisor a los 120 s. *En B sin Ken se suspendió el supervisor para evitar el corte mientras Codex continuaba y se reanudó tras su final natural: 211.765 s mide el supervisor intervenido, no una latencia exacta comparable. A con Ken incluye además un evento de cambio de archivo en la copia aislada. Tokens salen de `turn.completed.usage`; cache es parte del input, no sumando adicional. No equivalen a factura ni coste monetario.

Las cuatro finales se puntuaron manualmente con la misma rúbrica privada de cinco criterios (0/1/2); `codex-quality.json` detalla razones y límites. Se cotejaron citas nucleares con el snapshot y se ejecutaron externamente las comprobaciones entregadas, preservando script, stdout, stderr y metadata `external-check.*`. Son checks focalizados: A comprueba helpers (en una condición mediante AST y SQLite en memoria); B simula HTTP/procesos. No son transporte MCP/daemon end-to-end ni suite completa, y 10/10 no implica perfección en toda afirmación accesoria.

Ken registró seis llamadas MCP completadas en cada tarea; una llamada completada no garantiza por sí sola utilidad de cada resultado. En ambas tareas el input total con Ken fue mayor. El input no cacheado fue menor solo en A (29506 con Ken frente a 48531 sin Ken), y mayor en B (42811 frente a 38108). Las cuatro puntuaciones iguales no demuestran una ventaja de calidad. Una corrida por tarea y condición, tiempos intervenidos y diferencias de herramientas/prompts no permiten declarar un ganador general.

### Infinidev con autoaprobación: resultados finales

A terminó naturalmente, CLI salida 0, 424.454 s. Sin embargo, `engine_runs` marca `blocked`: apareció `discovery_suppressed` por repetición/recuperación, no una petición de aprobación manual. Su final exacta (`A--infinidev--autoapprove/answer.extracted.md`) promete referencias y script que no contiene. Evaluada la entrega real, no la investigación interna: **3/10**, criterios `[1,0,1,1,0]`; no hay script entregado que se pueda verificar externamente. Los contadores observados del engine son 745679 prompt tokens, 9770 completion tokens y 39 tool calls; cache no disponible. Son métricas observadas de esa fuente, no un total de proveedor normalizado contra Codex ni garantía de cobertura de todos los actores. `engine-metrics.extracted.json`, `quality.json` y reportes extraídos conservan la evidencia.

B con autoaprobación terminó naturalmente: **salida 0, 504.528 s, sin timeout**, engine `completed`. La respuesta final sí aporta recorrido, citas y script reproducible. Se cotejaron en su snapshot `_paths.py:69-85`, `daemon/client.py:83-142` y `mcp/server.py:91-106`; evaluación con la misma rúbrica **10/10**, `[2,2,2,2,2]`. Su script exacto se ejecutó externamente en esa copia: **salida 0, seis PASS**, HTTP y spawn simulados; no prueba integración de red ni pytest. Evidencia: `B--infinidev--autoapprove/{answer.extracted.md,quality.json,external-check.sh,external-check.stdout,external-check.stderr,external-check.metadata.json}`.

| Infinidev autoapprove | Tiempo proceso (s) | Prompt observado | Completion observado | Tool calls observadas | Estado engine | Calidad /10 | Check externo |
|---|---:|---:|---:|---:|---|---:|---|
| A | 424.454 | 745679 | 9770 | 39 | blocked | 3 | No disponible: final sin script |
| B | 504.528 | 1260888 | 12637 | 50 | completed | 10 | salida 0; seis PASS |

Los contadores proceden de `engine_runs` y se preservan en `engine-metrics.extracted.json`; cache no disponible en ambas celdas. No deben dividirse contra los tokens Codex como si fueran mediciones homogéneas: Infinidev añade orquestación y trabajadores internos, y no se ha demostrado cobertura/semántica equivalente. Un único proceso Infinidev puede crear actores internos; la ejecución secuencial controlada se refiere a no solapar celdas del benchmark.

### Conclusión de esta campaña

Las seis entregas finales de esta fase están evaluadas: cuatro Codex 10/10, Infinidev A 3/10 y B 10/10. Pasaron cinco comprobaciones externas entregadas; la sexta no existe en la final de A autoapprove. Los intentos anteriores, cortes e intervenciones se conservan, no se reemplazan por las mejores respuestas. La autoaprobación local no evitó el bloqueo de recuperación de A: salida CLI 0 no significa tarea completada. B sí completó la tarea y su comprobación focalizada pasó fuera del agente.

En estas dos tareas Ken no mejoró la puntuación observada y aumentó input total; redujo input no cacheado solo en A. No puede afirmarse ventaja general de velocidad, calidad o coste: muestra de una corrida por celda, tiempos Codex incompletos/intervenidos, cambios de protocolo, herramientas/prompts distintos y métricas Infinidev no normalizadas. No se lanzaron más corridas tras B. No se modificó código del producto original ni configuración global; los cambios de esta campaña son informe y artefactos bajo `docs/benchmark-evidence/`. `.infinidev/` del espacio principal no es evidencia publicable y no se incorporó al informe como historial privado.

