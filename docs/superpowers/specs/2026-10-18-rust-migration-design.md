# Ken en Rust: contrato y etapas de migración

Fecha: 2026-10-18. Rama: `codex/rust-migration`.

Estado: especificación aprobada explícitamente por el usuario el 2026-10-18.
El [plan M0/M1](../plans/2026-10-18-rust-m0-m1.md) también fue aprobado y se
ejecutó de forma nativa. M0/M1 están aceptados en Linux aarch64 y macOS arm64,
con revisión independiente y correcciones TDD verificadas. El [registro de implementación](../../validation/rust-migration-2026-10-18/m1/IMPLEMENTATION.md)
identifica las pruebas y la matriz conjunta. M2–M8 siguen pendientes.
Este documento fija el programa completo. Cada subsistema tendrá una
especificación y un plan ejecutable propios.

## 1. Intención y condiciones del usuario

Reescribir la aplicación Ken en Rust, en una rama nueva, usando Superpowers para
documentar requisitos, diseño y etapas antes de implementar. Conservar los
archivos originales hasta que estén completamente migrados y funcionales.

Interpretación propuesta: el destino es una aplicación nativa que realiza sus
operaciones sin un intérprete Python. Bibliotecas nativas y archivos de modelos
siguen siendo dependencias posibles; llamar al programa Python desde un binario
Rust no constituye una migración terminada. Python seguirá disponible como
referencia y para validación durante la transición.

Se conserva el comportamiento público actual: CLI, herramientas MCP, instalación,
hooks, datos existentes, lenguajes, búsqueda, memoria y consultas estructurales.
Las APIs Python documentadas, en particular las sesiones de consultas, se
inventarían con sus consumidores: si requieren compatibilidad, usarán bindings
finos del motor Rust. No se presupone que los módulos internos Python sean una
API estable ni que puedan eliminarse antes de auditar sus consumidores.

## 2. Base observada y límites del análisis

- HEAD inicial: `96a9d2d5ed5b7a6dc51b13c8e97e290cae7c9908`.
- La referencia incluye cambios previos del worktree, también archivos de código
  y tests aún no versionados. HEAD por sí solo no reconstruye esta referencia.
- Inventario: **409 archivos Python / 76.926 líneas** en `src/ken`; **538 archivos
  Python / 70.075 líneas** en `tests`. Son líneas físicas, no tamaño funcional.
- Toolchain local observado: `rustc 1.95.0`, `cargo 1.95.0`.
- El [inventario](../../validation/rust-migration-2026-10-18/INVENTORY.md) y el
  [manifiesto](../../validation/rust-migration-2026-10-18/baseline.json) registran
  1.066 archivos de fuentes, recursos, pruebas y contratos mediante SHA-256.
- Se leyeron las entradas CLI/MCP, descubrimiento de proyecto, estado, conexiones
  SQLite, partes del indexador, registro de parsers, pipeline de búsqueda,
  políticas de embeddings, cliente del daemon y contratos de diseño. No se ha
  auditado línea por línea todo el motor. La suite completa se ha ejecutado;
  sus resultados y los fallos previos se conservan en los recibos M0/M1.

El manifiesto identifica contenidos; **no es un backup ni un recibo de pruebas**.
No incluye bases privadas, cachés descargadas ni secretos. Los cambios previos no
se resetean, stashean ni incluyen en commits propios de esta tarea.

## 3. Alternativas y elección propuesta

| Enfoque | Ventaja | Coste y riesgo |
| --- | --- | --- |
| Migración por capacidades con pruebas diferenciales — recomendado | Cada entrega hace trabajo real y permite comparar/volver a Python | Requiere mantener dos implementaciones y una matriz de paridad |
| Reescritura completa y sustitución al final | Evita convivencia en el diseño final | Acumula incompatibilidades y retrasa la primera validación útil |
| Rust como envoltorio permanente del motor Python | Inicio rápido y reutilización directa | Mantiene el runtime y los cuellos de botella; no satisface el destino propuesto |

Se elige la primera: implementación nueva junto al original, con el nombre
temporal `ken-rs`, sin sustituir el ejecutable `ken` instalado durante desarrollo.
No habrá fallback silencioso: un componente Rust sólo se acredita por trabajo
que realmente hace. Una capacidad pendiente sigue disponible en Ken Python.

## 4. Conceptos y responsabilidades

| Concepto | Responsabilidad | Hogar actual a inspeccionar al migrarlo |
| --- | --- | --- |
| Proyecto | Resolver raíz, identidad, rutas y confinamiento de archivos | `_paths.py`, `tool_paths.py`, instrucciones de proyecto |
| Inventario de fuentes | Decidir qué archivos pertenecen al análisis y detectar cambios | `gitignore_filter.py`, `indexer.py`, watcher |
| Modelo de programa | Representar símbolos, imports, cuerpos, valores y evidencias con identidad estable | `parsers/`, `common_ast/`, `structural/`, `structural_store/` |
| Almacén | Persistir snapshots, vectores, historial y memoria sin pérdida | `db.py`, `schema.sql`, `vectors.py`, `structural_store/`, `knowledge/` |
| Recuperación | Seleccionar y ordenar piezas del código para una petición | `retrieval/`, `ranker/`, `search.py`, encoders |
| Consulta estructural | Compilar y ejecutar KQL con cobertura, presupuestos e incertidumbre | `kql2/`, consulta y ejecución en `structural/` |
| Conocimiento | Guardar conclusiones, verificar dependencias y decidir su entrega | `memory.py`, `findings_graph.py`, `knowledge/`, `reasoning/` |
| Contrato de código | Componer descubrimiento y comprobación de una afirmación sobre código | `code_reasoning/`, `checks/`, `inspection/`, `responsibility/` |
| Servicio local | Coordinar snapshots, sesiones, colas y ciclo de vida | `daemon/`, `serve.py`, `hook.py`, `session_brief.py` |
| Adaptadores públicos | Convertir CLI/MCP/hooks a peticiones y presentar respuestas | `cli.py`, `mcp/`, `presentation*.py`, plantillas e instalación |

Los adaptadores no contienen reglas del dominio. Un servicio coordina conceptos;
no absorbe los algoritmos de cada uno. La representación Rust se decide por
responsabilidad: no se crea un trait o crate por cada archivo Python.

### Dirección de dependencias

`CLI / MCP / hooks -> servicios de aplicación -> conceptos y operaciones`.
Los servicios reciben explícitamente almacenamiento, reloj, modelos y revisión
de fuentes cuando los necesitan. El núcleo no importa adaptadores de transporte.
Los resultados conservan evidencia y estado de completitud hasta su presentación.

El workspace crecerá sólo cuando exista un límite real. La primera entrega
necesita un crate de biblioteca `ken-core` y un binario `ken-rs`; motores y
adaptadores mayores se separarán cuando sus contratos estén definidos. No se
crearán crates vacíos para representar etapas futuras.

## 5. Uso representativo y equivalencia

El usuario podrá ejecutar ambos programas sobre fixtures equivalentes:

```sh
ken status /ruta/al/fixture --json
ken-rs status /ruta/al/fixture --json

ken search-symbols "Read a stored setting by key" --path /ruta/al/fixture --json
ken-rs search-symbols "Read a stored setting by key" --path /ruta/al/fixture --json
```

El segundo par se habilitará cuando se migre búsqueda, no en la primera entrega.
La matriz también invocará MCP mediante un cliente stdio real y CLI mediante
procesos reales: no basta comparar funciones internas.

Cada caso compara entradas, resultado, stdout/stderr, exit code, efectos sobre
datos, evidencia, orden y completitud según su contrato. Sólo se normalizan
directorios temporales, identificadores de fixture y valores dinámicos declarados
antes del ensayo. No se ordenan arbitrariamente los resultados ni se eliminan
campos para ocultar diferencias.

Una diferencia numérica de inferencia necesita tolerancia justificada por modelo
y dispositivo, fijada antes del ensayo. No autoriza cambios de ranking o fallos
de calidad; esos resultados se validan por separado. Las colecciones sin orden
contractual se comparan como conjuntos, conservando multiplicidad cuando exista.

## 6. Contratos que la migración debe conservar

1. **Interfaz:** nombres, argumentos, defaults, validación y errores de comandos,
   esquemas MCP, JSON, presentación compacta, límites de salida y exit codes.
   `tools/list` y el parser completo se capturan dinámicamente en M0: las
   declaraciones estáticas del inventario son sólo un punto de partida.
2. **Persistencia:** `.ken/meta.json`, SQLite, migraciones aditivas, WAL,
   referencias a vectores inline y por slot, metadatos de modelo/dimensión,
   formatos estructurales y registros de consultas. No se cambia motor o formato
   por preferencia de lenguaje. Datos persistentes y cachés reconstruibles se
   distinguen explícitamente; una invalidación de caché siempre es visible.
3. **Integridad:** escrituras transaccionales/atómicas, reutilización de slots,
   consistencia de snapshots, recuperación tras interrupción y compatibilidad de
   versiones. Python y Rust se prueban con copias independientes; no son dos
   escritores de producción sobre la misma base durante la migración.
4. **Lenguajes y análisis:** mismas extensiones, rangos, resolución, identidades,
   test discovery, KQL1/2, bibliotecas, planes guardados y consultas preparadas.
   Se conservan evidencia, cobertura y estados desconocido/incompleto. Un timeout
   no se transforma en una ausencia confirmada.
5. **Flujo de programas:** cuerpos, valores, excepciones, finally, generadores y
   continuaciones conservan la semántica implementada y sus límites declarados.
   La migración no acredita capacidades aún no implementadas en Python.
6. **Modelos:** mismo modelo/revisión, tokenizer, prompts, truncado, pooling,
   normalización, dimensiones, selección por proyecto y caché. No se mezclan
   espacios vectoriales ni se reembeddea silenciosamente al actualizar defaults.
   Los backends opcionales también cuentan en el inventario de capacidades.
7. **Memoria:** notas, justificaciones, anchors, hashes, validez, límites de
   comprobación y deduplicación por sesión/generación de contexto.
8. **Operación:** autenticación y protocolo local, orden/cierre de colas,
   watcher, concurrencia, arranque y parada. Los hooks conservan su degradación
   tolerante a fallos y no bloquean el trabajo del asistente.
9. **Distribución:** recursos, skills, reglas, modelos empaquetados, instalación
   y desinstalación conservadora en hosts compatibles. El binario final se
   prueba sin Python y fuera del checkout.

Para formatos que Python ya no pueda leer después de un cambio, el rollback
exige una copia anterior verificada; no se promete reversión sólo cambiando el
binario. Antes de promover escrituras Rust se demuestra lectura cruzada cuando
el formato se conserva y recuperación desde copia cuando sea necesario migrar.

## 7. Calidad y rendimiento vigentes

`CONSTRAINTS.md` sigue siendo la autoridad: prevalecen sus aclaraciones más
recientes y no sus cláusulas históricas reemplazadas. No se modifica para hacer
pasar la migración.

- Búsqueda: conservar el contrato vigente de pieza correcta en top1 >=90%,
  Recall10 >=95% y la pertenencia top10 nativa de los 197/200 casos donde se
  exige. La suficiencia de contexto se informa aparte. Las cifras publicadas de
  otro corpus no certifican estos objetivos.
- Recursos: CPU obligatoria; ninguna dependencia de GPU para funcionar. Medir
  respuesta completa, arranque, preparación/indexación y RSS por separado; se
  conserva la referencia de aproximadamente 1 s por 100 archivos indexables.
- KQL2 preparado: gran mayoría de consultas simples dentro de 10 ms; anidadas
  habituales <2000 ms; muy complejas se clasifican antes de medir. No se inventa
  un percentil ni un SLA nuevo donde el usuario no lo fijó. Incluye transporte
  local y entrega de respuesta; arranque de proceso se informa aparte.
- Se conservan fallos y recibos históricos. La reserva privada no se abre para
  diseñar el port. Los diagnósticos se repiten con corpus, modelos, equipo y
  revisión identificados; no se presupone una aceleración por usar Rust.
- No se debilitan tests, aserciones, análisis estático ni presupuestos. Los
  fallos preexistentes se registran y no cuentan como equivalencia aprobada.

## 8. Etapas y condiciones de salida

Una etapa terminada produce software funcional, pruebas y un recibo; no se mide
por porcentaje de líneas traducidas. Los motores grandes se dividen en planes
independientes. El orden establece dependencias, no una promesa de duración.

| Etapa | Entrega | Dependencias | Condición de salida |
| --- | --- | --- | --- |
| M0 — Referencia y contratos | Captura reproducible del worktree, interfaces dinámicas, fixtures y baseline de pruebas | Especificación revisada | Fuentes verificadas; inventario de capacidades sin áreas omitidas; resultados originales y fallos conocidos registrados |
| M1 — Proyecto y estado | Workspace mínimo, descubrimiento de raíz, confinamiento y `ken-rs status` real | M0 para este alcance | Toda la matriz de la especificación de M1 pasa contra Python; ninguna fuente original modificada |
| M2 — Datos y modelos | Conexiones/esquemas/vectores nativos y prueba de inferencia de los perfiles actuales | M1 | Ida/vuelta de datos; recuperación; tokenizer y embeddings equivalentes; ninguna dependencia runtime de Python en los perfiles acreditados |
| M3 — Fuentes e indexación | Exclusiones, parsers, símbolos/imports, modelo común e índices incrementales | M2 | Todos los lenguajes y recursos inventariados; equivalencia de índices y de altas/cambios/bajas; casos de Unicode y errores |
| M4 — Búsqueda | Recuperación, ranking, modelos, presentación, consultas por archivo/símbolo y canales históricos | M2 + M3 | CLI y MCP reales equivalentes; calidad/recursos vigentes; fixtures de exact match, frescura y límites |
| M5a — Modelo estructural | Almacén de programa, identidades, relaciones, CFG/IR, evidencia y versiones | M3 | Snapshots reproducibles y equivalencia del corpus estructural, incluidos formatos anteriores admitidos |
| M5b — Lenguajes de consulta | KQL1, KQL2, compilador, operadores, bibliotecas, registro y sesiones | M5a | Pruebas positivas/negativas, presupuestos y consultas guardadas; matriz de frontends preparada |
| M5c — Flujo y completitud | Valores, efectos, excepciones, recursos y continuaciones | M5b | Regresiones actuales y oráculos runtime; repetir comparación aislada Django con resultados y cobertura explícitos |
| M6 — Conocimiento y contratos | Memoria justificada, razonamiento, checks, inspection y responsabilidad | M2 + M4 + M5 | Casos de anchors, vigencia, entrega, límites, incógnitas y comprobaciones con evidencia equivalentes |
| M7 — Servicio e integraciones | Daemon, cola, watcher, lifecycle, CLI restante, MCP completo, hooks y hosts | M3 + M4 + M5 + M6 | Pruebas de transporte y concurrencia, reinicio/cierre, errores tolerados, instalación/desinstalación en fixtures |
| M8 — Sustitución y entrega | Paquetes nativos, CI, compatibilidad de usuarios, promoción y rollback | Todas las anteriores | Matriz completa sin pendientes; binario autónomo; pruebas en plataformas soportadas; ensayo de upgrade y rollback |

La viabilidad de los runtimes de modelos se comprueba al inicio de M2, antes de
invertir en la migración masiva. Un backend sin solución nativa es una capacidad
pendiente y bloquea el cierre global. M5 requiere varios planes: no se traduce
`body.py` ni el motor completo en una sola tarea.

La [especificación de M1](2026-10-18-rust-foundation-status-design.md) concreta el
primer corte. Después de su revisión se escribirá el plan de implementación de
M0/M1 con archivos, pasos TDD, comandos y criterios verificables. Cada etapa
posterior pasa por el mismo ciclo especificación → plan → implementación → revisión.

## 9. Verificación y registro de progreso

La matriz de paridad tendrá una fila por capacidad pública y plataforma/perfil
aplicable, con referencia Python, implementación Rust, casos, comando, recibo y
estado. Estados: `inventariada`, `contrato_fijado`, `implementada`,
`paridad_verificada`, `promovida`. Sólo el penúltimo acredita migración funcional;
el último añade integración predeterminada. No se marcan áreas no revisadas como
no aplicables para reducir el denominador.

Los tests se diseñan desde llamadas públicas y límites de responsabilidad.
Rust usa pruebas de unidad sólo para reglas, integración para datos y procesos,
y comparación diferencial para compatibilidad. Los tests Python se conservan y
siguen ejecutándose. `cargo fmt --check`, `cargo clippy` y `cargo test --locked`
se incorporan al introducir el workspace, con dependencias y toolchain fijados.
Los comandos exactos y targets se decidirán en el plan de la etapa, no se
presentan ahora como verificadores ya existentes.

El recibo de cada etapa registra revisión y huellas, entorno/modelos, resultados,
casos omitidos o incompletos, cambios de contrato y mediciones. Un fallo abre una
corrección; no se suaviza la comparación. Antes de cada commit se revisan sólo
los archivos propios de la entrega.

### Puerta de retirada de originales

No se elimina, renombra ni vacía ningún archivo original durante M0–M7. Tampoco
se reemplazan los entrypoints o configuración instalada para aparentar progreso.
La retirada de un archivo sólo puede plantearse al finalizar M8, cuando:

1. Todas sus responsabilidades y consumidores tienen dueño Rust y evidencia.
2. La matriz global está completa, sin fallbacks Python, stubs ni capacidades
   opcionales pendientes presentadas como terminadas.
3. Tests de regresión, persistencia, CLI/MCP, hosts y rendimiento están aprobados
   para las revisiones y plataformas declaradas.
4. Los recursos necesarios siguen empaquetados y los tests originales conservan
   un hogar recuperable para reproducir la referencia.
5. Se ha ensayado una vuelta a la versión anterior con datos recuperables.

Cumplir estas condiciones no obliga a borrar los originales: conservarlos en el
historial o como referencia versionada sigue siendo válido. Esta preparación no
autoriza ni realiza su eliminación.

## 10. Riesgos y decisiones pendientes por etapa

| Riesgo | Resolución exigida antes de avanzar |
| --- | --- |
| La referencia tiene cambios sin commit | M0 comprueba hashes y prepara copia local reproducible sin commitear cambios ajenos; cualquier cambio de base queda registrado |
| Python y Rust resuelven rutas o números de forma distinta | M1/M2 fijan casos Unicode, symlinks, redondeo, buffers y errores antes del port |
| Tokenizers/runtimes opcionales sin equivalente | M2 demuestra la inferencia real por perfil; una sustitución requiere evidencia y decisión explícita de compatibilidad |
| Pérdida de comportamiento en IR/KQL | M5 conserva incertidumbre y usa los corpus actuales más oráculos independientes |
| Corrupción por concurrencia o formatos | M2/M7 validan aislamiento, atomicidad, interrupción y versiones sobre copias |
| Alcance grande y progreso aparente | Entregas verticales, inventario completo y recibos; no porcentaje por líneas ni wrappers como sustituto |
| Rust cambia el resultado o no mejora recursos | Se mide antes de promover; diferencias y regresiones quedan visibles |

Los crates externos, sus versiones/MSRV, el runtime de inferencia y la matriz
final de distribución se fijarán en los planes correspondientes después de
verificar documentación oficial y compatibilidad real. No son decisiones
resueltas por este inventario. El mínimo de plataformas a conservar es el de CI
actual, Linux y macOS; Windows se audita en M0 según el soporte prometido.

## 11. Estado del proceso Superpowers

- [x] Clasificación arquitectónica y lectura del contexto del proyecto.
- [x] Rama propia y registro de cambios previos sin alterarlos.
- [x] Alternativas, conceptos, contratos y etapas documentados.
- [x] Primera capacidad definida en especificación separada.
- [x] Revisión del usuario de las especificaciones escritas: aprobadas el 2026-10-18.
- [x] Plan detallado M0/M1 escrito y autorrevisado.
- [x] Revisión del usuario del plan y elección de ejecución nativa; petición posterior de continuar hasta terminar.
- [ ] Implementación con TDD, verificación y revisión de cada entrega.
- [ ] Matriz de paridad completa y sustitución final.

M0/M1 y el primer perfil Potion de M2 ya tienen recibos Linux/macOS y revisión
independiente. La tabla NPZ también pasó su gate multiplataforma y la revisión
con tres correcciones TDD verificadas; los demás perfiles
y datos siguen pendientes. Cada entrega conserva especificación, plan, TDD y
revisión. La orden de continuar hasta terminar mantiene el alcance completo y
el método nativo aprobado; no convierte entregas parciales en cierre M2/M8.
