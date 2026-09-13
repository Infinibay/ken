# Cache-Aside: orden de escrituras y retornos — IR 1.34.0

## Qué cambia

La variante `architecture.cache-aside#null-miss` requiere dos asignaciones explícitas
al binding consultado, clave/receptor de caché sin reasignación y caminos CFG que
conecten lectura, prueba de ausencia, carga, escritura y retorno. El nuevo hecho
BINDING_WRITE_COUNT conserva callable, binding y cantidad de eventos escritos en
la fuente. No mide ejecuciones ni efectos ocultos. Ver [contrato y ejemplos](../../design/structural/cache-aside-flow.md).

RETURN_ORIGIN admite alternativas explícitas al confluir hit y miss en el mismo
return. Un alias del resultado puede conservar esos orígenes; la escritura anterior
a load o la sobrescritura posterior del valor no satisfacen la nueva query.
La variante Java Optional mantiene su modelo anterior de asignaciones, sin las
nuevas garantías temporales de null-miss.

## Matriz controlada comparada con el wheel anterior

Las mismas 90 fuentes —18 casos por cada uno de Python, JavaScript, TypeScript,
Java y C#— se analizaron con el wheel IR 1.33.0 y el motor IR 1.34.0. Se compararon
hashes, etiquetas, resultados y completitud. Los programas objetivo no se ejecutan
ni se compilan. Son fixtures de forma estructural, con APIs ilustrativas.

| Versión | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| IR 1.33.0 | 25 | 5 | 55 | 5 |
| IR 1.34.0 | 30 | 60 | 0 | 0 |

Datos por caso: [referencia anterior](cache-aside-flow-before.json) y
[resultado actual](cache-aside-flow-after.json).

Los seis positivos por lenguaje cubren la forma básica, renombrado, retorno mediante
alias, retorno propio del brazo de miss, tercer argumento TTL y llamada de logging.
Los doce negativos cubren set anterior a load, cambio de clave en tres posiciones,
receptor de caché reasignado, valor sobrescrito en cuatro posiciones, retorno antes
de cargar/escribir y retorno de otro símbolo. El anterior FN era el alias de retorno.
La llamada logging es un control sintáctico; no se demuestra que carezca de efectos.

**No es una estimación de precisión o recall global.** La matriz se construyó para
los problemas del modelo de asignaciones y no representa todas las implementaciones
de caché. Cero FP/FN sólo describe estos 90 casos. No se atribuyen las garantías del
miss nulo a Optional, APIs async, sentinels o invalidación.

## Pruebas y empaquetado

Se agregan **131 tests**: 104 del flujo Cache-Aside, 26 de conteos por callable y
un ejemplo ejecutable de la guía. Los 104 incluyen los 90 casos, nueve expansiones
de argumentos y cinco uniones de retorno con dos orígenes may. Los conteos prueban
cero/uno/dos/tres, ramas mutuamente excluyentes, código muerto, campos compartidos
por varios métodos y ausencia de conteos exactos en cuerpos no soportados.

La suite final, el chequeo de tipos y el wheel se registran al pie de esta auditoría.
Se verifican todos los módulos/TOML del wheel contra los hashes del motor, y el
paquete extraído fuera del checkout reconoce nueve reglas modernas, cinco positivos
con alias y cinco negativos con escritura adelantada. Los cinco fragmentos fuente y
las dos consultas KenQL del capítulo de diseño también se analizaron y completaron.
Los [testigos](cache-aside-flow-witnesses.json) muestran ambas asignaciones, count=2,
los roles y el mismo return con dos orígenes posibles; no se convierten en must.

## Regresión externa

La [regresión GoF](ir134-corpus-regression.json) conserva todos los matches y
**59/281 presencias esperadas**, con 736 archivos únicos, 745 apariciones por caso
y 6.463 consultas completas. Esa cifra cuenta ejemplos con al menos un match del
concepto esperado; no certifica todos los roles ni convierte cada ausencia en FN.

Los mismos archivos, commits y roles permanecen en [Requests](ir134-requests.json),
19 archivos; [Flask](ir134-flask.json), 24; [RxJS](ir134-rxjs.json), 123;
[Commons IO](ir134-commons-io.json), 277; [log](ir134-rust-log.json), nueve; e
[iluwatar caching](ir134-iluwatar-caching.json), 14. Todas las consultas terminan
completas. Flask e iluwatar ejecutan la colección modern; los otros conservan su
selección GoF anterior. Esto comprueba regresiones en esos alcances, no todo catálogo
en todos los archivos de los proyectos.

En iluwatar se conserva un Cache-Aside Optional, dos recorridos Read-Through de una
misma clase y doce matches de inyección de dependencias. No son nuevos TP externos
de null-miss. No se recupera ningún caso GoF nuevo y las ambigüedades anteriores,
como Builder sobre Document.save, siguen pendientes.

## Rendimiento

Se midieron las mismas dos fuentes Python con cada motor, una consulta de warmup
y 30 muestras sobre índice/registro ya construidos. La vista y parseo/enlace se
midieron aparte con diez muestras. Las mediciones son ilustrativas del host, sin
CLI ni caché persistente; no son un benchmark de repositorios grandes.

| Fuente / etapa | Mediana IR 1.33 | Mediana IR 1.34 | p95 IR 1.34 |
|---|---:|---:|---:|
| Positivo / query | 0,319 ms | 0,623 ms | 0,687 ms |
| Set anterior a load / query | 0,323 ms | 0,562 ms | 0,679 ms |
| Positivo / vista | 0,190 ms | 0,199 ms | 0,269 ms |
| Positivo / parseo y enlace | 1,420 ms | 1,476 ms | 1,607 ms |

[Resultados y protocolo](cache-aside-flow-performance.json). La consulta actual
cuesta más porque comprueba relaciones adicionales; la anterior acepta el negativo.
Los caminos a retornos se consultan antes de combinar sus operaciones, para evitar
un producto cartesiano de operaciones de la callable. Los límites de caminos se
mantienen explícitos en el TOML. No se alteran el presupuesto de caché por defecto
ni el backend de ejecución.

## Problemas que siguen abiertos

- Exactamente dos asignaciones es una restricción conservadora: código válido con
  escrituras redundantes o muertas puede quedar fuera.
- Un camino CFG y un origen posible no prueban factibilidad ni ejecución obligatoria.
- Rebindings explícitos no cubren cambios por aliases, setters o llamadas externas.
- Optional conserva evidencia de asignaciones sin orden temporal general.
- La identificación de APIs sigue siendo por forma y nombres; faltan contratos de
  bibliotecas, sentinels, serialización, asincronía e invalidación.

## Comprobaciones finales

La versión optimizada pasa **3.834 tests en 152,16 s** con
`.venv/bin/python -m pytest -o addopts='' -q`; son todos los tests de Ken.
`.venv/bin/mypy src/ken` pasa en **98 archivos**. Se construyó el wheel offline,
se compararon sus módulos y TOML byte por byte con el manifiesto y se repitieron
las diez comprobaciones fuera del checkout. La referencia wheel IR 1.33 también
coincide byte por byte con su manifiesto anterior.

Los ocho documentos actualizados tienen enlaces locales válidos. La guía operativa
mantiene sus ejemplos bajo pytest y el capítulo nuevo verifica sus cinco lenguajes
y dos consultas contra el IR real. [Registro de comprobaciones](ir134-checks.json).
