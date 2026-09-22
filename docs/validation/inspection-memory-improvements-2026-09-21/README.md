# Inspección bajo demanda y memoria escalonada — 2026-09-21

Se implementaron las dos mejoras pendientes del informe anterior: consultar
desde la identidad solicitada y recuperar primero una conclusión reutilizable.
La implementación está en `src/ken/`, compartida por CLI y MCP.

## Comportamiento implementado

- `related` localiza la declaración y adquiere una frontera de imports por vez.
  Las consultas de llamadas y usos llevan las identidades del objetivo y sus
  ocurrencias. `impact` sólo continúa hacia llamadores cuando observa un retorno
  que conserva el resultado. `roles` recorre ambas direcciones; `available` sólo
  necesita declaraciones. `who` adquiere las salidas de sus candidatos.
- El planner distingue imports nominales, alias y referencias estáticas a miembros
  de módulos. Un archivo que importa otro miembro no obliga a adquirir su grafo
  de comportamiento. KQL sigue resolviendo las llamadas; el planner no crea aristas.
- Las ubicaciones se recuperan por identidad dentro del snapshot. Las declaraciones
  son nodos de función; las ocurrencias de llamada permanecen en las aristas.
- Se conserva evidencia coherente cuando una consulta queda incompleta. Si cambian
  las fuentes entre pasos, se descartan los hechos para no mezclar revisiones.
  `acquisition` informa archivos y límites; `--full` añade pasos y consultas.
- `ken_recall(detail="answer")` entrega conclusión completa, tipo, fuentes,
  supuestos, vigencia y referencia para ampliar. Con tópico exacto evita recorrer
  sus vecinos. No ejecuta KQL ni relee automáticamente toda la evidencia.
- `answer` conserva las advertencias `stale`, `unknown` e hipótesis. `unchanged`
  sólo acredita coincidencia de las entradas declaradas. Una conclusión que no
  cabe se sustituye por una referencia explícita, nunca por un prefijo ambiguo.
- El bloque de los hooks y `AGENTS.md` orientan a comenzar por `answer`. `summary`
  añade explicación breve; `full` sigue como default de la API por compatibilidad.

Conceptos separados: `Explorer` coordina adquisición, `Imports` descubre archivos,
`Observations` conserva testigos y cobertura, `Program` representa funciones y
llamadas. El engine es dueño de resolución y usos; la capa de contexto es dueña
de la proyección de memoria. [Guía de inspección](../../design/code-inspection.md),
[guía de memoria](../../design/justified-memory.md).

## Rendimiento sobre el código real de Ken

Se copiaron **271 archivos Python de `src`**, con huellas de contenido. Cada
estrategia empezó en un proyecto independiente, sin índice previo. Mismo objetivo,
alcance `src`, profundidad 2, límite de salida y presupuesto de **30 segundos**.
El baseline conserva el plan anterior de observaciones generales y filtrado
posterior, con la selección previa por imports. No se ejecutó el código analizado.

| Objetivo | Plan anterior, caché nueva | Bajo demanda, caché nueva | Repetición | Archivos de comportamiento | Llamadores |
| --- | ---: | ---: | ---: | ---: | ---: |
| `vectors.py::_atomic_write` | timeout a 30,03 s | **2,87 s** | **1,28 s** | 1 | 2 |
| `checks/report.py::query_view` | timeout a 30,03 s | **10,32 s** | **11,72 s** | 5 | 3 |

[Métricas finales](inspection/result.json), [huellas de fuentes](inspection/source-manifest.json).
El tiempo incluye el worker, inventario de fuentes, adquisición, consultas y
normalización. El baseline fallido no produjo un inventario de consumidores;
sus ceros no son evidencia de ausencia. No se le atribuye una duración de respuesta
exitosa ni un factor exacto de aceleración. No se repitió ese baseline caliente:
un publisher interrumpido puede dejar una lease pendiente y contaminar el reintento.

Ambos recorridos bajo demanda leyeron las 271 estructuras de imports para encontrar
llamadores; la reducción se refiere a construir sus grafos de comportamiento,
no a evitar toda lectura de los restantes archivos. La repetición no garantiza
una mejora: `query_view` fue algo más lento. Son observaciones individuales en
una máquina compartida, no un estudio estadístico ni una promesa para cualquier
símbolo. Su presupuesto default de 10 s puede ser insuficiente para ese segundo caso.

La respuesta de `_atomic_write` identifica `compact` y
`VectorStore._load_or_create`; conserva dos usos desconocidos (`source_body:unknown`).
La de `query_view` identifica `integration.search`, `ken_find` y `structure.enrich`;
observa un retorno en `ken_find`, pero conserva `usage_inventory_open`. Una respuesta
`observed` puede tener cobertura parcial. Cero evaluaciones en una categoría
significa que no se solicitó una consulta de ese tipo, no prueba de ausencia global.

Se conserva una [medición inicial](inspection-initial/result.json), anterior al
ajuste que separa funciones y sitios de llamada. Dio 2,66/1,29 s y 9,90/11,27 s.
La tabla principal corresponde al código posterior al ajuste.

## Ocho sesiones reales con Codex CLI

Se probaron dos preguntas en copias de `vectors.py`, `_paths.py` y sus tests:
ubicación/permisos de manifiestos y comportamiento de `find_project_root` ante
un override inválido. El baseline lee fuente; la variante de memoria empieza con
el tópico conocido y `detail="answer"`. No exige `impact` ni lecturas redundantes.
Se mantuvo el modelo configurado por el usuario.

Hubo un piloto de cuatro sesiones y una repetición de cuatro. El piloto mostró
que un `rg --hidden` del baseline también encontraba reglas y recibos de `.ken`.
Se conservan sus [trazas y métricas](agents/pilot/result.json); la repetición limitó
el baseline a `src/` y `tests/`. La siguiente tabla corresponde a esa repetición:

| Pregunta / modo | Tools | Caracteres de resultados | Tokens de entrada | Entrada cacheada | Tokens de salida | Segundos |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Manifiestos / fuente | 5 | 31.079 | 58.020 | 39.424 | 927 | 39,85 |
| Manifiestos / memoria | **1** | **1.954** | **48.648** | 35.328 | 800 | 37,18 |
| Raíz / fuente | 2 | 3.591 | 48.549 | 30.592 | 300 | **19,05** |
| Raíz / memoria | **1** | **1.546** | 48.581 | 39.040 | 471 | 26,94 |

[Resultados](agents/source-scoped/result.json), [ocho sesiones consolidadas](agents/metrics.json),
[fuentes copiadas](agents/source/src/ken/vectors.py).

En manifiestos hubo **16,2% menos tokens de entrada**, **93,7% menos caracteres
de herramientas** y cinco llamadas se redujeron a una. En la pregunta de raíz
hubo **57,0% menos caracteres**, pero los tokens quedaron prácticamente iguales
(0,07% más) y la variante de memoria tardó 41,4% más. Menos texto recuperado no
equivale necesariamente a menor latencia ni menor consumo total.

Revisé respuestas y trazas. Las cuatro recuperaciones de memoria fueron una sola
llamada exitosa, recibieron entradas `unchanged` y no releyeron fuente. Las respuestas
mantuvieron los símbolos correctos, la ausencia de fallback con override inválido
y el límite de garantías de permisos. `compact` quedó como función global, sin el
error de identidad del informe anterior. Una respuesta empleó enlaces relativos
a los archivos; conserva atribución, pero el formato de enlaces no fue uniforme.
Todas las sesiones terminaron con código 0; la revisión de contenido fue manual.

Límites de la comparación:

- Evalúa la reutilización de conclusiones **ya revisadas y suficientes**, con el
  tópico indicado en el prompt. No mide descubrimiento automático del tópico,
  captura autónoma de memoria, ni calidad del ranking.
- Preparación, revisión de conclusiones, indexación y primer check quedan fuera
  del coste de las sesiones. El baseline no recibe esa explicación previa.
- Se alternó el orden entre preguntas (fuente→memoria y memoria→fuente), pero no
  se equilibraron todas las repeticiones de cada pregunta ni se controló la caché
  del proveedor. El piloto tuvo un prompt de baseline distinto.
- Los tokens de entrada son acumulados del CLI e incluyen entrada cacheada. No
  son tamaño máximo del contexto ni coste facturado. No demuestran ahorro general
  entre sesiones. Sí muestran reutilización sin repetir la lectura en estos casos.
- Las recuperaciones terminaron antes del ajuste de nodos de inspección. Sus
  recibos conservan la huella del engine usado entonces; no se reescribieron para
  aparentar una comprobación sobre código posterior. La evidencia de esas memorias
  (`vectors.py` y `_paths.py`) no cambió.

## Corrección y validación

| Suite | Tests aprobados | Evidencia |
| --- | ---: | --- |
| KQL 2 completo | 1.534 | [JUnit](tests/kql2.xml) |
| Resolución semántica afectada | 266 | [JUnit](tests/semantics.xml) |
| Tools, memoria, hooks y daemon | 194 | [JUnit](tests/integration.xml) |
| Total de esos conjuntos | **1.994** | [Metadatos](tests/summary.json) |

Se verificaron también las [tres regresiones históricas](history/result.json):
12 variantes y seis comprobaciones antes/después, con transición fail→pass.
Ruff `F` pasó en los módulos de esta integración; mypy pasó en 36 archivos.
No se ejecutó toda la suite histórica del repositorio.

Las regresiones nuevas cubren imports de otro miembro, alias, alternativas ausentes,
usos distintos de una misma función, 100 resultados irrelevantes que antes podían
consumir el presupuesto, retorno transformado, interrupción, mezcla de versiones,
cache de ubicaciones y recuperación exacta sin vecinos. MCP stdio publica y ejecuta
`answer` además de los modos de inspección; se preserva compatibilidad de CLI/full.

Dos detalles de corrección merecen conservarse:

1. Adquirir sólo una alternativa de un import condicional no la convierte en un
   destino cierto. El engine conserva el origen de las otras alternativas aunque
   no pueda resolverlas, y publica `MAY_TARGET` para el candidato conocido.
2. Una ubicación de llamada también tiene identidad canónica, pero no es una
   declaración de función. Se añadieron pruebas que fallaban al consultar roles
   por archivo y por `file::symbol`; ambas pasan tras separar esos conceptos.

## Límites que permanecen

No se sigue identidad arbitrariamente dentro de un receptor de argumentos.
Imports dinámicos, miembros calculados y dispatch de runtime no están trazados.
Otros frontends sin cobertura explícita de imports conservan el alcance completo.
Los roles siguen siendo hipótesis; una conexión con un test no prueba suficiencia
de sus assertions. Una comprobación de presencia de `chmod` no prueba su modo ni
que el sistema operativo aplique los permisos.

El watchdog puede terminar un worker antes de que entregue evidencia parcial;
si corta una publicación, un reintento inmediato puede encontrar su lease activa.
Quedan como oportunidades acotar esa recuperación y reducir el coste de cambios
de snapshot entre fronteras. No se alteró el protocolo de publicación en este trabajo.

## Cómo probarlo

Desde la raíz del proyecto:

```sh
.venv/bin/python -m ken tools related 'src/ken/vectors.py::_atomic_write' impact --path src --timeout-ms 30000
.venv/bin/python -m ken tools related 'src/ken/checks/report.py::query_view' impact --path src --timeout-ms 30000
.venv/bin/python -m ken tools recall --topic 'inspeccion-bajo-demanda' --detail answer
.venv/bin/python scripts/evaluate_inspection.py --output /tmp/ken-inspection-new --baseline
.venv/bin/python scripts/evaluate_contract_agent.py --output /tmp/ken-memory-new --run-agents --case both
```

Las evaluaciones requieren directorios de salida nuevos; la de agentes necesita
Codex CLI y acceso al modelo. Los procesos MCP/daemon ya iniciados deben reiniciarse
para cargar el código nuevo. La CLI del checkout lo carga al invocarla.
