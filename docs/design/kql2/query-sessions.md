# Consultas KQL2 con una revisión preparada

`QuerySession` mantiene un lector SQLite protegido sobre una revisión de fuentes.
La preparación captura bytes, valida el almacenamiento y carga las bibliotecas
empaquetadas una vez. Cada consulta compila su texto y ejecuta sobre esa revisión,
con bindings, evidencia y presupuesto propios. Se reutilizan planes inmutables;
las respuestas nunca se cachean.

```python
from pathlib import Path
from ken.kql2 import QuerySession

query = '''language "kql/2"; module app;
query q {class $c {name:"ArtifactCache";} select $c.name,$c.path;}
'''

# Preparación fuera del cronómetro de consultas.
with QuerySession(Path("/ruta/al/proyecto"), cache_mb=3000) as session:
    response = session.search(query, timeout_ms=10)
    encoded = session.search_json(query, timeout_ms=10)

    # Después de cambiar las fuentes; también cambia bibliotecas capturadas.
    session.invalidate()
    session.refresh()
    updated = session.search(query)
```

`cache_mb` limita retención de disco y la caché de compilación existente; no
significa cargar ese tamaño en RAM. Debe permitir retener el índice de fuentes.
Con retención insuficiente la preparación falla y pide aumentar el presupuesto.
El corpus medido de 500 archivos usa 3000 MB de retención; su base ocupa alrededor
de 1,06 GB. `path` y `source_paths` fijan el alcance de la sesión.

## Responsabilidades del integrador

- Preparar y actualizar antes de consultar. La sesión no recorre ni relee fuentes
  en cada petición: `analysis.freshness` indica `captured_snapshot`. El integrador
  notifica cambios con `invalidate()` y llama a `refresh()` en el hilo propietario.
- `invalidate()` admite llamadas desde un watcher. Rechaza consultas nuevas hasta
  completar el refresh. Si llega durante una consulta, la respuesta queda
  incompleta con `reason="snapshot_invalidated"`; sus filas pertenecen a la
  revisión anterior. Un cambio durante refresh impide adoptar la revisión nueva.
- Usar una sesión por hilo y proceso. Compartirla entre hilos o después de un fork
  produce un error claro. Lectores independientes conservan sus revisiones
  protegidas aunque otro lector actualice o se ejecute GC.
- Cerrar con `with` o `close()`. Si borrar el lease falla por contención, la
  conexión se cierra igualmente y el lease pendiente vence por su TTL normal.
- Para BODY y relaciones semánticas, llamar a `prepare_query(source, ...)` antes
  de medir. Resuelve también queries guardadas con `saved_query`/`query_name` y
  prepara sólo los hechos o el grafo que exige el plan. Devuelve el tiempo de esa
  preparación; la compilación sigue perteneciendo a la consulta. También están
  disponibles `prepare_semantics()` y `prepare_graph()` para integraciones que
  conocen de antemano qué representación necesitan.

Un refresh recaptura fuentes y bibliotecas. Si coinciden la base, snapshot,
frontend, presupuesto y manifiesto, y el lease anterior sigue vigente, conserva
el lector y sus índices inmutables. Una notificación de archivos que no cambia
esa identidad no obliga a enlazar BODY de nuevo. Una revisión distinta o un lease
vencido reemplaza el lector y libera sus índices anteriores.

El lector comprueba su lease por consulta. Renovaciones periódicas bajo otro
escritor se difieren únicamente mientras la protección persistida siga vigente;
no esperan cinco segundos ni resucitan leases expirados. Un lease vencido produce
`complete=False, reason="snapshot_expired"` y requiere refresh.

## Opciones y compatibilidad

`search()` conserva `query_name`, `libraries`, `reference`, `profile`,
`max_states`, `max_rows`, `timeout_ms`, `cancelled` e `include_entities`.
`search_json()` incluye compilación, ejecución, reporting y codificación en el
presupuesto. Los deadlines son cooperativos: detectar que se agotaron convierte
el resultado en incompleto; no interrumpe una llamada nativa arbitraria.
Un deadline heredado del supervisor se conserva hasta la entrega.

El formato compartido mantiene resultados, orden, evidencia, incertidumbre,
diagnósticos y profiling. Las bibliotecas suministradas y la query elegida forman
parte de la clave del plan. Las bibliotecas empaquetadas se vuelven a capturar
durante refresh. Los predicados anidados usan el mismo lector y runtime.

También puede pasarse `session=session` a `ken.kql2.service.search()` cuando
coincidan proyecto, alcance y opciones de preparación. La búsqueda de una llamada
sin sesión mantiene su captura de fuentes y supervisor existente.

## Sesiones automáticas en CLI y MCP

`ken kql2 consulta.kql`, `python -m ken.kql2 consulta.kql`, `ken tools find`
y `ken_find(scope="structure", query_language="kql/2", ...)` usan automáticamente
el mismo servicio local de consultas por proyecto. El proceso conserva hasta
cuatro lectores por alcance y presupuesto, con un propietario estable; las
llamadas MCP de distintos hilos no comparten conexiones SQLite. Funciona también
para la CLI independiente en una raíz sin `.ken/meta.json`.

```sh
ken kql2 consulta.kql --root /ruta/al/proyecto --timeout-ms 10
ken tools --path /ruta/al/proyecto find --scope structure \
  --query-language kql/2 --query 'language "kql/2"; module app; query q {select 1;}'
```

La primera petición inicia el servicio y prepara el índice. Un watcher invalida
las revisiones cuando cambian las fuentes; el propietario las actualiza también
durante los períodos sin consultas. Antes y después de cada ejecución se
comprueba una cola de eventos de archivos, directorios e ignores en sistemas
con kqueue; si no puede registrarse completa, se comprueban sus metadatos. Esto cubre cambios
durante el debounce, archivos añadidos/eliminados y bytes modificados aunque se
restaure el mtime. Si cambia la revisión durante una consulta, se actualiza y
reintenta antes de entregar éxito. El resultado describe un snapshot verificado
al final de la ejecución; una edición posterior pertenece a la siguiente revisión.
Los destinos resueltos de los enlaces simbólicos se verifican por separado, para
cubrir cadenas intermedias y cambios entre rutas con hardlinks al mismo inode.
El propietario libera los descriptores nativos al actualizar, expulsar o cerrar
una sesión. La validez no depende únicamente del debounce del watcher.

Los procesos dedicados de consultas y MCP recogen basura de arranque y congelan
ese conjunto de objetos una vez, antes de crear lectores, watchers o el runtime
async. El GC de objetos nuevos continúa activo. Los entrypoints CLI recogen
basura de inicialización; las llamadas embebidas a `QuerySession` o al cliente
automático no cambian la política de GC del integrador.

El cliente espera preparación y actualizaciones. `analysis.total_ms` conserva
todo el tiempo desde que entra en el cliente; `startup_ms`, `preparation_ms` e
`index_wait_ms` muestran arranque, preparación y espera de preparación previa.
`prepared_query_ms` incluye verificación de fuentes, compilación, ejecución,
reporting y transporte TCP autenticado en localhost. La vista compacta MCP
también muestra estos tiempos. El reloj externo del gate añade entrega CLI y
transporte stdio/validación del SDK MCP. El arranque de un proceso Python nuevo
se mide aparte, según el contrato confirmado por el usuario.

El servicio renueva leases incluso sin consultas y termina tras diez minutos
sin peticiones. Un dueño caído se reinicia automáticamente. Los timeouts de
transporte de peticiones todavía vivas no se reenvían. Endpoint y token están
en `.ken/structural/v2/queries.json`, con permisos privados; el log está en el
mismo directorio. `ken.kql2.automatic.shutdown(root)` cierra los lectores antes
de detener el servicio.

La retención automática predeterminada es **3000 MB** de disco, respetando
`--cache-mb`, `.ken/structural.json` y `KEN_STRUCTURAL_CACHE_MB`. `cache_mb=0`,
retención insuficiente y el backend `exploration` conservan la ejecución de una
llamada; no tienen la certificación de la ruta preparada. Si un intento de sesión
falla por retención insuficiente, su tiempo previo aparece en `session_attempt_ms`
y permanece incluido en el total. `--explain` y `--capabilities` no inician el
servicio. Las relaciones de grafo se preparan cuando la consulta las requiere;
BODY también prepara automáticamente sus hechos semánticos antes de aplicar el
presupuesto de consulta. La compilación sigue dentro del tiempo de consulta.

Los hechos BODY se retienen por revisión, separados de bindings, cancelación y
presupuestos de cada ejecución. `analysis.semantic_storage` indica `shared_disk`
cuando caben en la caché persistente, o `session_disk` cuando usan una base SQLite
temporal privada de la sesión. El segundo caso conserva la cuota de la caché
compartida y evita reconstruir los mismos hechos por petición; consume espacio
temporal adicional. Se libera al reemplazar la revisión, expulsar el lector o
cerrar el servicio. Tras reiniciar el servicio necesita prepararse otra vez;
los hechos que caben en almacenamiento compartido pueden reutilizarse desde disco.
La caché SQLite del spill está limitada a 64 MiB; la adquisición semántica inicial
todavía puede usar bastante más RAM y tiempo. Esto no es caché de respuestas.

## Medición reproducible

El gate público está en `examples/bench/kql2_session.py`. Verifica el manifiesto
congelado de 500 archivos antes de preparar; luego cronometra hasta que vuelve el
JSON de la API pública. Exige respuestas completas, valores literales esperados,
500 unidades retenidas, ausencia de caché de respuestas y máximo **<=10 ms**.
Incluye siete consultas —negativo, selección, método, parámetro, ordenación,
existencia y tres niveles de predicados— tanto con textos nuevos como con planes
reutilizados. Con 30 repeticiones son 420 consultas.

```sh
.venv/bin/python -m examples.bench.kql2_session /ruta/al/corpus-500 \
  docs/validation/kql2-performance-2026-10-14/public-session.json \
  --manifest docs/validation/kql2-performance-2026-10-14/medium500.json
```

El corpus es una extracción Python fija; no certifica cada repositorio de 500
archivos ni todos los operadores de grafo, BODY, AST o recursión. El reloj externo
del gate es la medida de aceptación; `analysis.total_ms` es el diagnóstico tomado
tras codificar los campos y justo antes de componer el JSON final.

El diagnóstico anterior y sus resultados de unos 135 ms se conservan en
`docs/validation/kql2-performance-2026-10-14/README.md`. Su búsqueda sin sesión
incluye recaptura por petición y sigue siendo un camino de compatibilidad.

El gate de entradas automáticas es `examples/bench/kql2_frontends.py`, con las
mismas siete consultas y el mismo manifiesto. Mide 420 peticiones por cada ruta:
handler CLI KQL2 en procesos nuevos, handler `ken tools find` en procesos nuevos
y SDK MCP real sobre stdio. Conserva
la primera consulta de cada ruta y los textos nuevos dentro del cronómetro;
inicialización del proceso y descubrimiento de schemas ocurren antes. El reloj
CLI llega hasta recibir stdout por una tubería; la espera del cierre del proceso
ocurre después de entregar la respuesta y se registra fuera del tiempo de consulta.

```sh
.venv/bin/python -m examples.bench.kql2_frontends /ruta/al/corpus-500 \
  /ruta/al/recibo-frontends.json \
  --manifest docs/validation/kql2-performance-2026-10-14/medium500.json
```

El usuario aceptó unas pocas excedencias si la gran mayoría queda dentro de
10 ms. La matriz automática de 1260 peticiones registró 1257 dentro del objetivo
(99,76 %), con medianas de 3,980 ms en CLI KQL2, 4,458 ms en tools CLI y
3,123 ms en MCP. MCP tuvo cero excedencias; las CLIs tuvieron tres en conjunto.
El verificador conserva su criterio histórico estricto y el recibo original.
Dos peticiones agotaron el timeout explícito del ensayo; sin `timeout_ms` las
consultas conservan su ejecución ilimitada por defecto. Tolerar una excedencia
de rendimiento no modifica un deadline solicitado expresamente por el caller.

La evidencia de integración se guarda en
`docs/validation/kql2-frontends-2026-10-14/`. Las medidas de la fase anterior se
conservan como histórico con sus hashes; no se actualizan para aparentar que
fueron tomadas con fuentes nuevas.

La corrección de preparación y retención BODY y de CFG parcial se valida con las
consultas reales guardadas de Ken en
`docs/validation/kql2-body-cfg-2026-10-15/`. Conserva las preguntas originales,
oráculos AST, respuestas, esperas y excedencias; distingue preparación de latencia
con el índice listo y verifica CLI y un servidor MCP nuevo.
