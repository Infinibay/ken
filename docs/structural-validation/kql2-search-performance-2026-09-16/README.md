# KQL2: planificación, almacenamiento nativo y mediciones

Trabajo del 16–17 de septiembre de 2026. Objetivo: acelerar tanto la construcción
del índice como los 23 patrones GoF sobre `../codex`, evitar reconstruir el grafo completo en cada búsqueda y conservar
hallazgos, evidencia, incertidumbre y límites de ejecución.

## Resultados comprobados

El SDK TypeScript de Codex contiene 26 archivos analizados, 5.098 entidades y
94.197 hechos. Todas las consultas siguientes terminaron sin límite de tiempo y
sin caché de resultados. Sus hashes de hallazgos, evidencia e incertidumbre coinciden.

| Implementación | Tiempo del batch de 23 patrones |
|---|---:|
| Referencia anterior | 23,519 s |
| Planificación optimizada, índice en memoria | 11,097 s |
| Columnas SQLite, rangos y cobertura compartida, primera medición v9 | 16,886 s |
| Columnas SQLite, segunda medición v9 | 17,319 s |
| Columnas SQLite y diccionario entero v11 | 16,833 s |
| Columnas SQLite, atributos de operaciones compartidos v12 | 15,745 s |
| Índices reducidos v14, filtros correlacionados | 15,117 s |
| v14, sonda acotada para objetos ligados | 15,398 s |

La apertura v9 del índice existente tomó 22,1 ms y el índice ocupó
45.002.752 bytes. La medición anterior incluía la proyección inicial de intervalos
sobre un índice ya existente y abrió en 97,4 ms. Estos tiempos de apertura no
incluyen descubrimiento/hashing de archivos ni adquisición de fuente.

Con v11, la apertura tomó 35,4 ms y el archivo compactado ocupa **32.092.160 bytes**:
**28,7 % menos**. La migración del SDK tomó 2,59 s; después se ejecutó VACUUM para
medir la reducción física. La migración automática por sí sola deja páginas libres
para reutilizar y no garantiza que el archivo se achique inmediatamente.
La repetición v11 completó los 23 patrones y conserva todos los hashes de referencia.

Son muestras diagnósticas en una máquina con otros procesos activos, no una
estimación estadística de latencia. El backend en memoria sigue siendo más rápido
en este conjunto pequeño una vez construido. El índice persistente evita volver
a materializar todo el proyecto para consultar y mantiene memoria acotada para
lectura de atributos y listas pequeñas.

Evidencia: [referencia SDK](sdk-baseline.json), [planificación en memoria](sdk-candidate.json),
[primera medición SQL](sdk-native-v9-first.json), [segunda medición SQL](sdk-native-v9.json).
La [medición v11](sdk-native-v11.json) y el [desglose de espacio](dictionary-size.json)
registran el cambio de tipos.

Una [construcción nueva v11 desde el snapshot del SDK](sdk-native-v11-cold.json)
publicó el grafo en 4,15 s y ejecutó los 23 patrones en 15,75 s, conservando los
hashes. El archivo recién escrito ocupa 34.283.520 bytes sin VACUUM. Esta prueba
no incluye parsear/enlazar código fuente: parte de un IR preparado.

En v12, los 15.398 hechos OPERATION del SDK reutilizan columnas de sus operaciones:
el índice recién escrito ocupa **26.406.912 bytes** y compactado **23.470.080 bytes**.
Es un **26,9 % menos que v11 compactado**, y **47,8 % menos que los 45 MB de v9**.
La publicación desde el mismo IR tomó **3,23 s**, frente a 4,15 s de v11.
Las consultas tardaron 15,745 s y completaron los 23 patrones con idénticos hashes.
Evidencia: [ejecución v12](sdk-native-v12.json), [espacio por tabla](operation-attribute-size.json).

Con v14, la publicación desde el mismo IR tomó **2,99 s** y el índice nuevo ocupa
**23.900.160 bytes**; compactado, **21.254.144 bytes**. La reducción respecto de
v11 nuevo es 30,3 %, y respecto de v9 compactado es 52,8 % comparando ambos
compactados. Los 23 resultados siguen coincidiendo con la referencia.
Evidencia: [v14](sdk-native-v14.json), [última búsqueda](sdk-native-selective.json),
[tamaños](native-sdk-v14-size.json).

También se midió una [adquisición fría real del SDK](sdk-cold-v13.json), con cero
hits de caché y sin snapshot: fuente/enlace **1,217 s**, normalización **0,086 s**,
escritura **3,226 s**, intervalos **0,063 s** y los 23 patrones **14,995 s**. Esa
medición usa v13; las anteriores escrituras desde un IR preparado no incluyen
parsear ni enlazar fuente. Ninguna cifra del SDK representa todo Codex.

## Repositorio Codex completo

El snapshot analizado tiene 5.295 archivos soportados, 2.620.444 entidades,
8.756.899 operaciones y 47.154.730 hechos. El pickle local ocupa aproximadamente
7 GiB; deserializar ese artefacto de diagnóstico no representa abrir el índice SQL.

La referencia anterior no completó ninguna de las primeras siete consultas con
un presupuesto nominal de 5 s: algunas tardaron entre 59 y 64 s porque trabajo
interno no consultaba el presupuesto. La siguiente consulta se interrumpió tras
más de 231 s. **No existe un tiempo total válido de los 23 patrones anteriores**.
Tampoco se puede afirmar equivalencia usando resultados vacíos interrumpidos.

La primera publicación SQL se interrumpió a los 44 min 20 s. Había terminado
entidades y operaciones y seguía insertando hechos. Usaba una transacción única
y la configuración anterior de 2 MiB de page cache. El perfil nativo mostró
lecturas y búsqueda de páginas dentro de un WAL de varios GiB. No produjo una
medición de consultas. Se conserva [el registro del intento](native-full-single-transaction-abort.json).

La repetición con transacciones acotadas y 64 MiB de page cache confirmó todas
las entidades y operaciones, y 5.275.648 hechos. Se detuvo para migrar y reanudar
el mismo snapshot con v11 y liberación progresiva de registros en memoria.
El proceso anterior retenía unos 36 GiB de memoria física según `sample`.
Este intento reanudado no representa una medición fría de principio a fin.
El [punto de reanudación](native-full-resume-point.json) conserva los contadores.
La reanudación se interrumpió después por expiración del lease de escritura;
el manejo del fallo descartó sus filas y no llegó a ejecutar consultas.
Se conserva [el error](native-full-lease-expired.txt). La corrección comprueba
el propietario bajo el lock de escritura y recupera un lease vencido sólo si
la publicación sigue siendo suya. Un escritor obsoleto tampoco puede borrar
una publicación reclamada por otro proceso. Una construcción nueva está en curso.
Conservó 2.523.136 entidades confirmadas al pasar de v11 a v12, antes de escribir
operaciones o hechos. Se guarda [ese punto de continuación](native-full-resume-v12.json).
Sus resultados deben incorporarse aquí antes de afirmar una aceleración sobre
el repositorio completo.

Se aplicó la eliminación de índices de v13/v14 durante ese intento. Conservó
las filas y liberó 1.270.292.480 bytes en páginas reutilizables, pero el lock duró
39,5 s y superó el timeout de 5 s del escritor. El proceso terminó con SQLITE_BUSY;
se preservaron 2.620.444 entidades, 8.756.899 operaciones y 16.449.536 hechos.
El [registro de migración](native-full-live-index-trim.json) y el
[punto de reanudación](native-full-resume-v14.json) documentan el incidente.
La publicación ahora reintenta sólo adquirir el lock, sin repetir ni consumir
filas, y respeta cancelación y propiedad. Se reanudó el mismo snapshot ordenado
con esa corrección. Este recorrido mixto sigue sin ser un benchmark frío limpio.

La cobertura de adquisición no es total: quedaron 11 archivos C/header sin
frontend y errores de parseo en `codex-rs/app-server/src/main.rs:89` y
`codex-rs/utils/pty/src/process.rs:387`. Esas omisiones deben acompañar cualquier
interpretación de ausencia de patrones.

## Cambios que reducen trabajo

- El parser público pasó de 972 a 318 líneas; las producciones se separaron por
  familia con checkpoints, precedencia y validación existentes.
- Los operadores, la planificación, los presupuestos, los recursos compartidos
  y la presentación de resultados tienen módulos y contratos propios.
- La planificación usa cardinalidades de accesos indexados, aplica filtros con
  entradas ya ligadas y adelanta prerrequisitos seguros de BODY. Preserva barreras
  de negación, agregación, evidencia y dependencias.
- SQLite guarda tipos, nombres, propietarios, ubicaciones, extremos y relaciones
  en columnas. Atributos/evidencia extensibles usan valores nativos y filas hijas,
  con deduplicación y lectura diferida; no documentos JSON que deban decodificarse.
- Los accesos por extremos eligen índices forward/reverse explícitos: `ORDER BY
  ordinal` podía inducir a SQLite a recorrer el grafo entero por su clave primaria.
- Conteos y pruebas de existencia usan ahora ese mismo índice. Con extremos
  selectivos, los filtros de atributos son correlacionados; evitan materializar
  todos los atributos coincidentes del proyecto por cada fila del join.
- Los cuerpos guardan raíz, rango y nodo final. `body` y `else` se mantienen
  separados. Los rangos sintácticos no sustituyen las salidas de control de CFG.
- Resolver una operación anidada usa su ID y deja de materializar un mapa de
  todas las operaciones del proyecto. La poda obtiene propietarios por ID y
  comparte cobertura CFG dentro del índice inmutable.
- La publicación por lotes conserva el grafo oculto hasta la transición READY;
  SQLite puede realizar checkpoints mientras se construye el índice.

La planificación es heurística por selectividad y dependencias. No garantiza
el óptimo global ni que toda consulta arbitraria termine en un tiempo pequeño.

## Migraciones y persistencia

Las migraciones son automáticas al abrir `Store`:

- 7: tablas del grafo normalizado y valores nativos.
- 8: propiedades escalares heredadas convertidas de JSON a tipos SQLite.
- 9: AST canónico en columnas, cuerpos y rangos del grafo. Sólo invalida la
  proyección derivada del AST; conserva las unidades de código fuente.
- 10: publicación en lotes con estado de disponibilidad. Los grafos completos
  de versiones anteriores se marcan disponibles durante la migración.
- 11: diccionario compartido para tipos, roles, rutas, etiquetas de valor,
  claves de atributos y comparaciones repetidas; las columnas contienen enteros.
- 12: los hechos OPERATION reutilizan columnas de la operación, conservando
  atributos adicionales, evidencia y ordinales. Los datos antiguos siguen
  legibles; el ahorro se aplica a publicaciones nuevas. La migración descendente
  descarta sólo grafos derivados con el codec nuevo y conserva las unidades fuente.
- 13: elimina índices globales de operaciones por role, start_byte y end_byte.
- 14: elimina índices redundantes de miembros por parent/key y operaciones por
  rango de bytes. La clave primaria, los predicados de atributos y los intervalos
  sintácticos conservan sus accesos. Ambas migraciones preservan todas las filas.

`structural patterns` usa `.ken/structural/v2/patterns.sqlite` dentro del repositorio
analizado. `analysis.query_index.backend` vale `sqlite_columns`; `hit` distingue
reutilización de construcción y `persistent` informa retención en disco.
El tamaño del índice no está restringido por los 500 MB de caché de resultados.
Desactivar retención utiliza una base temporal en disco.
Los servicios pasan a la generación 2 del índice: tras actualizar construyen
una revisión con el codec nuevo, reutilizando las unidades fuente que sigan en
caché. Las ejecuciones posteriores reutilizan ese índice.

Las cachés de adquisición y resultados aún pueden usar JSON/zlib. Una adquisición
fría todavía enlaza y normaliza el proyecto; cambiar una fuente puede requerir
reconstruir derivaciones globales. Actualización incremental completa no está
implementada en este cambio.

## Pruebas y experimentos

La suite conjunta de KQL2, structural y common_ast completó **13.052 passed y
10 xfailed** sobre v12 en 421,48 s; [salida conservada](tests-v12.txt). Se ejecutaron
además [siete pruebas de publicación](tests-publication-v12.txt), incluyendo la regresión
que impide reusar ordinales de una normalización diferente. Se verifican
equivalencia, lectores concurrentes, cancelación tras un lote confirmado y
recuperación de publicaciones abandonadas. Ruff y mypy de los módulos de esta
fase pasaron; no se atribuye esa comprobación estática al proyecto entero.

## Temporales

La [limpieza registrada](temporary-cleanup.json) liberó **18,99 GiB** de 138
artefactos descartados: bases de experimentos, la base vacía tras el fallo del lease, instalaciones de versiones de
prueba y resultados de corpus antiguos. Se conservan temporalmente el snapshot
y el índice que sigue en construcción para terminar la medición de Codex.

La matriz de catálogo compara positivos y negativos de los 23 GoF en Python,
Java y TypeScript: 138 casos comparan resultados y evidencia con la referencia.
Las pruebas de almacenamiento deshabilitan `json.loads` durante la lectura,
verifican tipos, límites, ramas, migraciones y uso de índices mediante EXPLAIN.

Experimentos auxiliares, sin extrapolarlos al repositorio completo:

| Caso | Antes | Después |
|---|---:|---:|
| Fixture dispatch, 150 métodos irrelevantes | 8,185 s | 0,0127 s |
| Estados de ese fixture | 1.486.879 | 867 |
| Filas examinadas en ese fixture | 683.778 | 46 |
| Resolución Rust, fixture de 1.500 imports | 1,132 s | 0,0162 s |
| Serialización de 30.000 hechos | 0,781 s | 0,273 s |
| Pico Python de esa serialización | 16,6 MB | 0,52 MB |

La caché adicional por identidad de objetos no mostró una mejora consistente
([muestras](writer-value-cache-experiment.json)) y se descartó. El experimento
[de page cache](writer-page-cache.json) mostró una mejora modesta en el SDK; la
motivación adicional para aumentarla fue el perfil de I/O del grafo grande.

Una [prueba de 100.000 operaciones](index-write-probe.json) mostró cerca de 30 %
menos tiempo al retirar tres índices, con page cache de 1 MiB. Otra prueba de
[200.000 metadatos distintos](redundant-index-probe.json) pasó de 41,7 a 36,6 s
al retirar los otros dos índices y redujo 44.118.016 bytes. Son fixtures, no
mediciones completas de Codex.

En una [búsqueda puntual](correlated-lookup-probe.json), conteo más lectura
pasaron de 220.232 instrucciones SQLite a 218 entre 10.000 operaciones. Entre
1.000 operaciones el camino nuevo también usa 218: el trabajo queda acotado al
candidato. Las pruebas comprueban además existencia, filtros nativos y atributos
adicionales, fallbacks y sondas por objeto ligado.

Se descartaron [huellas compactas para términos](term-index-probe.json): ahorraron
26 % de espacio en la muestra pero aumentaron 45 % la escritura. Cambiar
[sincronización y checkpoints del WAL](wal-write-probe.json) no dio una mejora
consistente. Tampoco aumentar de 64 a 256 MiB la [page cache en la muestra de
200.000 metadatos](page-pressure-probe.json). La muestra mayor sigue en evaluación.

## Reproducir

Desde la carpeta de Ken, usar el código de este checkout:

```bash
PYTHONPATH=src .venv/bin/ken structural patterns --path ../codex --full > /tmp/codex-patterns.json
```

Para empezar por el SDK, añadir `--scope sdk/typescript`. Sin `--pattern` se
seleccionan los 23. `--timeout-ms 5000` limita cada consulta, no la adquisición;
un resultado con `complete=false` no certifica ausencia.

Para medir sin caché de resultados ni escrituras dentro de Codex:

```bash
PYTHONPATH=src .venv/bin/python examples/bench/pattern_search.py ../codex \
  --backend sqlite --artifacts /tmp/ken-codex-benchmark \
  --timeout-ms 5000
```

El harness guarda tiempos por patrón, resultados canónicos, estadísticas de
trabajo e información de preparación. `--profile` añade perfiles de CPU y
operadores. `--snapshot` permite reutilizar un pickle **propio y confiable** de
preparación; no se deben cargar pickles recibidos de terceros. Cada directorio
de artefactos debe corresponder a un único repositorio/snapshot.
