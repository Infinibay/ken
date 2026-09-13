# Command en lotes de trabajo — IR 1.30.0

## Cambio validado

`command#queued-object` conecta el contrato registrado con la implementación
concreta de la acción, su receiver retenido y la activación de elementos almacenados.
Reutiliza `architecture.batch-work-queue.drain`, una operación pública de la nueva
regla moderna `architecture.batch-work-queue`. Ambos TOML usan primitivas públicas.

El IR incorpora EMPTY_COLLECTION, CLEARS_COLLECTION, AFTER_ITERATION y el selector
`call(explicit_arguments: 0)`. El reset exige una asignación simple a literal vacío
o una forma de API clear/Clear sin argumentos. La relación con la iteración expresa
orden léxico de statements hermanos, con barreras directas de salida; no ejecución
exitosa, terminación ni ausencia de excepciones/reentrancia. `[,,]` en JavaScript no
es un literal vacío y `+= []` no es un reset.

El [diseño y las variantes por lenguaje](../../design/structural/queued-command.md)
publican los límites. Las entradas y elementos reasignados no sirven como testigos;
la activación debe descartar su resultado, permitiendo await. La variante dinámica
de Command exige un caller observado que suministre el tipo concreto al registro.

**176 tests nuevos**: 107 de Command/Batch Work Queue en cinco lenguajes, 68 de
relaciones/argumentos/orden y un ejemplo ejecutable de la guía IR. Incluyen campos
explícitos y parámetros-propiedad TypeScript, async Python/JS/TS/C#, renombrado,
colección/elemento equivocados, argumentos adicionales, ausencia de reset, reset
anterior/en otra rama/otro método, salidas intermedias, rebindings, spreads, arrays
con huecos y serialización. La suite completa pasa **3.151 tests en 107,40 s**;
mypy pasa en **96 archivos**. El wheel offline contiene todos los archivos del motor
y TOML verificados contra los hashes del manifiesto. No se ejecutó código objetivo.

## Corpus GoF repetido

El [reescaneo](ir130-corpus-regression.json) conserva commits y fuentes de IR 1.29:
281 casos, 736 archivos únicos (745 apariciones por caso), 6.463 consultas.
Todas terminan completas y no se pierde ninguna etiqueta esperada. La presencia
de la etiqueta esperada aumenta de **58 a 59 casos**. Sólo cambia el caso
`behavioral/command/task_scheduler/typescript/` de across-languages:

| Clase | Evidencia revisada | Clasificación |
|---|---|---|
| SendEmailCommand | Recibe servicio, destinatario, asunto y cuerpo; execute espera sendEmail con esos datos. El scheduler almacena Command y activa execute sobre los elementos. | TP Command |
| GenerateReportCommand | Retiene generador, tipo de informe y ruta; execute espera generateReport. Comparte el mismo protocolo de registro/consumo. | TP Command |
| RunDatabaseBackupCommand | Retiene servicio y nombre de backup; execute espera runBackup. Comparte el protocolo de registro/consumo. | TP Command |

TaskScheduler.addTask añade el parámetro recibido a tasks. runPendingTasks recorre
tasks, espera execute dentro de try/catch y luego asigna `tasks=[]`.
Los [testigos ampliados](queued-command-witnesses.json) conservan las tres clases
y el recorrido público drain, con el reset y la iteración correlacionados.
Son **tres clases TP en un caso de etiqueta recuperado**, no tres casos del corpus.

El commit es `efd075de92e42099e8ae24fc274dc0e7b86ba2f9`. Los tres archivos TypeScript
están fijados por hash. Los matches anteriores Adapter sobre esos comandos y
Observer sobre TaskScheduler permanecen: no se ocultan para presentar una mejora
de precisión. Sus problemas de intención siguen abiertos.

59/281 expresa presencia de etiquetas esperadas, no precisión o recall universal.
Los casos restantes no son automáticamente FN confirmados, y un repositorio sin
matches no es un verdadero negativo certificado.

## Regla moderna y proyectos reales

El [escaneo moderno del mismo ejemplo](queued-command-modern.json) reconoce
TaskScheduler/tasks/runPendingTasks como **un TP de lote de trabajo**. Analiza los
tres archivos TypeScript y jest.config.js, sin ejecutar la configuración. También
encuentra tres inyecciones de dependencias coherentes con los servicios que reciben
y usan los comandos; son otra vista estructural del ejemplo, no nuevos casos GoF.

[Requests](ir130-requests.json), 19 archivos; [Flask](ir130-flask.json), 24;
[RxJS](ir130-rxjs.json), 123; y [Commons IO](ir130-commons-io.json), 277,
conservan matches y roles anteriores sobre las mismas fuentes. Flask ejecuta ahora
las ocho reglas modernas y no tiene candidatos de Batch Work Queue. Todas las
consultas completan sus presupuestos. Esto es control de regresión, no una nueva
clasificación manual de todos sus resultados.

## Rendimiento observado

| Etapa | Muestras | Mediana | p95 de la muestra |
|---|---:|---:|---:|
| Query Command completa en el ejemplo TypeScript indexado | 30 | 0,944 ms | 1,008 ms |
| Query Batch Work Queue en el mismo índice | 30 | 0,175 ms | 0,223 ms |
| Construcción de vista de consulta de Requests | 5 | 223,705 ms | 310,273 ms |
| Query Prototype completa de Requests con índice/registro construidos | 30 | 1,079 ms | 1,115 ms |

Los tiempos de query excluyen parseo/enlace, construcción de índice, caché de disco
y CLI. La vista se mide aparte; p95 usa rango más cercano y describe sólo la muestra.
El total de pytest y los escaneos concurrentes dependen de la carga del host y no
son una comparación controlada de rendimiento entre versiones.

## Reproducción y pendientes

```sh
.venv/bin/python -m pytest tests/structural/test_queued_commands.py tests/structural/test_collection_lifecycle.py tests/structural/test_documented_ir_queries.py
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/mypy src/ken
.venv/bin/python examples/bench/validate_pattern_corpus.py --corpus /tmp/ken-pattern-corpus --output /tmp/corpus-ir130
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-pattern-corpus/across-languages --prefix behavioral/command/task_scheduler/typescript/ --exclude-glob '*.test.ts' --collection modern --output /tmp/task-scheduler-modern.json
```

La variante no cubre todavía pop/shift/take, canales, closures encoladas, listas
obtenidas por getters ni procesamiento sin reset explícito. La forma de API clear
no certifica implementación de biblioteca. Resetear el campo tampoco demuestra
que aliases del contenedor anterior se hayan vaciado. Las ambigüedades Adapter,
Observer y callbacks de ciclo de vida siguen en el [registro de problemas](problemas.md).
