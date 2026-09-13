# State mediante transiciones en el contexto — IR 1.29.0

## Implementación y tests

`state#context-transition` conecta una construcción inicial almacenada en el campo
de estado, el contexto que se pasa y retiene, una acción delegada y la instalación
de un sucesor mediante el setter del mismo campo. Python/JS/TS/Java/C# tienen
fixtures propios con positivos, renombrado y negativos cercanos.

El [diseño implementado](../../design/structural/state-context-transitions.md)
describe cuatro relaciones genéricas nuevas: INSTANCE_RECEIVER,
PARAMETER_INITIALIZES_FIELD, CONSTRUCTOR_FIELD_INPUT y DECLARED_TARGET.
Los parámetros-propiedad TypeScript conservan identidades distintas de campo y
parámetro. La inicialización implícita precede a escrituras del cuerpo en el modelo
lineal, sin inventar statements de AST. El slot nominal declarado de una llamada
se conserva separado de sus destinos concretos posibles: no se elige arbitrariamente
un TARGET para eliminar una ambigüedad.

**153 tests nuevos**: 113 para State en cinco lenguajes, 31 para parámetros-propiedad,
ocho para slots declarados y un ejemplo ejecutable de la guía IR. Cubren posiciones
reales/formales, constructor y setter con varios argumentos, receptor incorrecto,
construcción abandonada, otro contrato, acción no delegada, overwrites, rebindings,
spreads, modifiers en comentarios/defaults, firmas sin cuerpo, overloads y
serialización. La suite completa pasa **2.975 tests en 92,86 s**; mypy pasa en
**95 archivos**. El wheel offline coincide con los hashes de todos los archivos
estructurales del manifiesto. No se ejecutó el código analizado.

## State recuperado y otros matches añadidos

El [corpus repetido](ir129-corpus-regression.json) conserva los mismos commits,
736 archivos únicos y 281 casos de IR 1.28. Las 6.463 consultas terminan completas,
sin perder etiquetas esperadas. La presencia de la etiqueta esperada pasa de
**57 a 58 casos**. Dos casos cambian sus matches:

| Caso de across-languages | Match añadido | Revisión |
|---|---|---|
| State / order_processing / TypeScript | State: Order | **TP revisado**. Order instala NewOrderState(this); NewOrderState guarda order y sus acciones processPayment/cancel llaman setState con PendingPaymentState/CancelledState. El setter escribe el campo que utiliza el dispatch. |
| El mismo caso State | Adapter: NewOrderState, PendingPaymentState, ShippedState | Tres FP respecto de intención / solapamientos estructurales. Los métodos del contrato de estado llaman métodos distintos del contexto; la firma Adapter acepta esa delegación sin exigir adaptación de argumentos/resultados. |
| Command / task_scheduler / TypeScript | Adapter: SendEmailCommand, GenerateReportCommand, RunDatabaseBackupCommand | Tres FP respecto de intención / solapamientos estructurales. execute envuelve trabajo del receiver. Los campos de receiver/datos ya son visibles, pero la intención principal es encapsular comandos que el scheduler almacena y ejecuta después. |

Se conservan dos [testigos ampliados de State](state-context-transitions-witnesses.json),
para processPayment y cancel, incluyendo declaración del slot, campo retenido,
bindings de construcción y setter, sucesor y escritura. Son **dos pruebas del mismo
TP de contexto**, no dos contextos nuevos. El Strategy previo sobre Order permanece;
reconocer State no elimina automáticamente otros patrones compatibles.

El FN de Command en TaskScheduler sigue pendiente. El scheduler recibe el contrato
Command, lo añade a una colección, itera tareas y espera execute(). Las variantes
actuales no conectan ese protocolo de colección con las implementaciones concretas.
El match Observer previo tampoco constituye prueba de la intención Command.

El commit de across-languages es `efd075de92e42099e8ae24fc274dc0e7b86ba2f9`.
Todos los hashes de fuentes están en el corpus. **58/281 no es precisión ni recall
global**; los casos restantes no son automáticamente FN verificados. Los seis
Adapters nuevos no se cuentan como mejora de cobertura esperada.

## Proyectos reales

[Requests](ir129-requests.json), 19 archivos; [Flask](ir129-flask.json), 24; y
[Commons IO](ir129-commons-io.json), 277, conservan exactamente sus matches y roles.
Flask usa la colección modern. Todas las consultas completan sus presupuestos.
Los FP previos, incluido Prototype FilePart.rollOver en Commons IO, siguen abiertos.

[RxJS](ir129-rxjs.json), 123 archivos, conserva sus matches anteriores y añade
Strategy sobre Connection (`packages/rxjs/src/connectable.ts:27`). Connection
recibe y guarda un callback disconnect como parámetro-propiedad y unsubscribe lo
invoca con this. ConnectableObservable.connect suministra una closure que llama
al método privado de desconexión. La composición por callback es real, pero la
intención observada es una acción de ciclo de vida; **Strategy es una interpretación
ambigua/demasiado amplia**, no un nuevo TP de algoritmo intercambiable certificado.
La diferencia de roles queda guardada en el JSON de testigos.

## Rendimiento observado

| Etapa | Muestras | Mediana | p95 de la muestra |
|---|---:|---:|---:|
| Query State completa sobre el ejemplo TypeScript indexado | 30 | 1,046 ms | 1,120 ms |
| Construcción de la vista de consulta de Requests | 5 | 236,173 ms | 263,429 ms |
| Query Prototype completa de Requests con índice/registro construidos | 30 | 1,128 ms | 1,198 ms |

Los tiempos de query excluyen parseo/enlace, construcción del índice, caché de disco
y CLI. La vista se mide por separado. El p95 usa rango más cercano y describe esta
muestra, no un SLO. Las corridas externas bajo carga variable son controles
funcionales; sus tiempos no demuestran mejoras o regresiones de rendimiento.

## Límites y siguiente trabajo

La correlación del setter y constructor es lineal; no establece identidad runtime
entre todos los callers ni estabilidad global del campo retenido. La asignación
inicial se reconoce sintácticamente y aún no se comprueba que sea la última antes
del primer dispatch. Estado enum/match, transiciones directas a campos, constructores
heredados y callbacks de estado requieren otras variantes.

El [registro de problemas](problemas.md) incorpora las colisiones Adapter/Command,
Adapter/State y Strategy/callback de ciclo de vida. Las correcciones deben mejorar
la evidencia de uso, sin ocultar relaciones de IR correctas ni filtrar nombres de
clase o directorio.

```sh
.venv/bin/python -m pytest tests/structural/test_state_context_transitions.py tests/structural/test_parameter_properties.py tests/structural/test_declared_dispatch.py tests/structural/test_documented_ir_queries.py
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/mypy src/ken
.venv/bin/python examples/bench/validate_pattern_corpus.py --corpus /tmp/ken-pattern-corpus --output /tmp/corpus-ir129
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-real-repos/rxjs --prefix packages/rxjs/src/ --exclude-glob '*.spec.ts' --exclude-glob '*/testing/*' --output /tmp/rxjs-ir129.json
```
