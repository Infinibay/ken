# IR 1.47: revisión algorítmica de los 23 GoF

La [revisión central](../../design/structural/gof-algorithm-contracts.md) escribe
cada algoritmo en palabras antes de identificar valores, objetos, almacenamiento,
operaciones e invariantes. Los [contratos por patrón](../../design/structural/algorithms/README.md)
añaden variantes, queries de uso donde son posibles y limitaciones reproducibles.
Tres subagentes revisaron un patrón por asignación; los cambios comunes del IR
se integraron y comprobaron conjuntamente.

## Qué cambió en la representación

- choose expresa un resultado seleccionado entre regiones alternativas;
  short_circuit conserva la evaluación condicional del operando derecho y su
  política de resultado, sin convertir and/or de Python en booleanos forzosamente.
- iterate conserva el iterable evaluado una vez y el valor del elemento por
  vuelta. Una reasignación del binding se representa separadamente; representar
  esa escritura aún no implica que todas las queries comprueben su efecto.
- while, do y for clásico tienen órdenes regionales distintos; init sólo ocurre
  una vez, continue alcanza el lugar correspondiente y una condición omitida de
  for se representa explícitamente como true sintético.
- elif mantiene condiciones posteriores dentro de alternativas anteriores. Los
  temporales locales de un brazo no pueden escapar como si estuvieran definidos
  incondicionalmente. El verificador comprueba layouts y resultados regionales.
- Los constructores Java ya no se exportan como un cuerpo opaco seguido de un
  retorno implícito. C# conserva receptores this explícitos que la gramática
  guardaba como tokens. El límite de anidamiento no se reinicia entre helpers.
- KenQL expone `operation(role: ...)`, el campo sintáctico preservado del AST.
  Permite distinguir la condición de los brazos de un branch; no demuestra
  dependencia de control, polaridad ni alcanzabilidad por sí solo.

La [referencia IR](../../structural-ir.md#instruction-core-and-algorithm-contracts)
detalla los lenguajes y exclusiones. El núcleo sigue siendo un adaptador de
migración: el matcher usa el grafo, y los contratos de copia/alias/colecciones,
resolución de destinos y concurrencia siguen siendo parciales.

## Correcciones de consultas motivadas por las pruebas

| Patrón | Defecto corregido en la muestra propia |
|---|---|
| Visitor | Self se pasaba en otra llamada distinta de la operación tipada seleccionada |
| Memento | Estado descartado por constructor, campo restaurado distinto y sobrescritura posterior |
| Proxy | Otra llamada prestaba el guard; forwarding se ejecutaba dentro de la condición |
| Adapter | Una interfaz marker ajena suministraba un contrato distinto sin ser dueña del slot sobrescrito |
| Flyweight | Clave distinta al insertar/devolver y creación que no era el valor almacenado |
| Chain of Responsibility | Guard de una llamada distinta o forwarding durante la evaluación de condición |
| Iterator | Logging local confundido con estado persistente; se correlaciona la asignación concreta al campo |

Son correcciones a firmas concretas; no certifican la intención del diseño ni
prueban todos los requisitos de sus algoritmos. Cada test mantiene la distinción
entre detección de la definición y un contrato más fuerte de uso.

## Qué enseñan las limitaciones

Los xfail estrictos expresan expectativas pendientes y fallan si una mejora
inesperada requiere revisarlos. No se cuentan como cobertura correcta. Algunos
son errores o ausencias de la firma actual; otros pertenecen a refinamientos
opcionales, como transparencia de retorno, aislamiento histórico o exclusividad.
No se debe endurecer una firma general con todos esos requisitos a la vez.

El límite compartido principal es la definición que alimenta cada ocurrencia de
lectura/argumento. Facade muestra un caso concreto: un resultado directo entre
llamadas puede correlacionarse, pero un local intermedio tiene evidencia may;
aceptar may sin más también acepta sobrescrituras y producción posterior al uso.
Composite/Builder/Visitor muestran rebindings que invalidan identidades y todavía
no filtran todos los matches. El núcleo conserva ahora mejor esas instrucciones,
pero sigue faltando conectar sus definiciones y estados al buscador.

También faltan contratos de efectos para aceptar trabajo independiente con una
garantía estricta: Singleton pierde algunos casos con aritmética local porque
exige adyacencia CFG. Cambiarla por un camino arbitrario admitiría resets y efectos.
Copy/sharing, dispatch, captures, caminos excepcionales y suspensión necesitan
modelos independientes; nombres como clone, log o once no constituyen pruebas.

## Exportación y rendimiento del núcleo

Los [fixtures](ir147-core-fixtures.json) contienen 69 fuentes propias: 23 GoF por
Python/Java/TypeScript. Se comparan los mismos hashes en
[1.46](ir147-core-before.json) y [1.47](ir147-core-after.json). Todas exportan,
verifican y conservan ocurrencias fuente; esto no acredita compilación de las
fuentes ni detección semántica completa de los patrones.

El [runner](../../../examples/bench/validate_instruction_ir.py) toma diez muestras
de exportar/verificar después de dos warmups sobre un grafo ya preparado. Excluye
parsing, consultas, impresión, caché y arranque. No es un benchmark de velocidad
del buscador ni una matriz de precisión. Los nodos native y las funciones partial
se conservan en el reporte; reducir opacidad no equivale a resolver todos sus efectos.

## Auditoría independiente del adaptador

Una revisión separada encontró cinco representaciones incorrectas, corregidas
antes del cierre: while-else omitido, inicialización exterior al cuerpo de un
constructor omitida, optional chaining evaluado incondicionalmente, operadores
como %= o <<= convertidos en asignaciones simples y parámetros callable
representados sólo como símbolos estáticos.

Las primeras cuatro formas ahora quedan native/partial cuando no existe una
traducción completa. La última usa un slot.load del parámetro/storage como callee
por valor. Los accesos de miembro conservan su receiver y no se reinterpretan
como un parámetro homónimo. Hay regresiones en
[test_instruction_audit.py](../../../tests/structural/test_instruction_audit.py).
Esto preserva incertidumbre explícita; no es soporte completo de esas operaciones.

## Regresión externa y un fallo intermedio

La [comparación final](ir147-corpus-regression.json) conserva **74 presencias
esperadas en 281 ejemplos**, sin cambios en los conjuntos de matches y con
**6.463 consultas completas**. Los commits, scopes y hashes de los archivos son
idénticos a IR 1.46. No se produjo una mejora neta de cobertura en este corpus.

El [escaneo intermedio](ir147-corpus-intermediate.json) había bajado a 73: el
ajuste de Iterator excluía NumberWords de faif/python-patterns. Su avance
`self.start += 1` tenía ASSIGNMENT_TARGET, pero faltaba en el inventario grueso
WRITES. La query final usa la asignación concreta al campo y recupera ese ejemplo;
conserva el rechazo del ruido local que no modifica el estado del iterator. Las
[regresiones](../../../tests/structural/test_iterator_augmented_state.py) cubren
asignación aumentada/simple y logging. No se alteró el repositorio externo.

El [wheel](ir147-wheel.json) coincide byte a byte con los 67 módulos/TOML del
motor final. Fuera del checkout exporta/verifica los 69 fixtures y encuentra el
NumberWords original. Las fuentes externas sólo se leyeron y parsearon.

## Matriz propia por patrón

Este cierre corresponde a la revisión GoF, anterior a la optimización posterior
del buscador y a las nuevas operaciones públicas. La
[auditoría del catálogo](catalog-ir-contracts.md) y la
[revisión moderna](modern-catalog-review.md) registran esa continuación.

La [validación sellada](ir147-checks.json) termina con **6.731 passed y 149 xfailed**
en 373,80 segundos para todo Ken. Mypy pasa en 107 archivos. Se verificaron ocho
ejemplos documentados contra consultas de pruebas o fragmentos del catálogo.
El [detalle por patrón](ir147-pattern-tests.json) corresponde al mismo JUnit.

Los 23 módulos nuevos tienen 556 casos que pasan y 149 expectativas pendientes
estrictas. Son resultados de tests, no TP/TN globales: algunos controles comprueban
explícitamente los límites del modo possible y no representan detecciones correctas.

| Patrón | Pasan | Pendientes (xfail) |
|---|---:|---:|
| [abstract-factory](../../design/structural/algorithms/abstract-factory.md) | 18 | 3 |
| [adapter](../../design/structural/algorithms/adapter.md) | 30 | 9 |
| [bridge](../../design/structural/algorithms/bridge.md) | 18 | 3 |
| [builder](../../design/structural/algorithms/builder.md) | 24 | 6 |
| [chain-of-responsibility](../../design/structural/algorithms/chain-of-responsibility.md) | 12 | 12 |
| [command](../../design/structural/algorithms/command.md) | 53 | 13 |
| [composite](../../design/structural/algorithms/composite.md) | 24 | 9 |
| [decorator](../../design/structural/algorithms/decorator.md) | 30 | 12 |
| [facade](../../design/structural/algorithms/facade.md) | 18 | 3 |
| [factory-method](../../design/structural/algorithms/factory-method.md) | 30 | 0 |
| [flyweight](../../design/structural/algorithms/flyweight.md) | 15 | 9 |
| [interpreter](../../design/structural/algorithms/interpreter.md) | 24 | 12 |
| [iterator](../../design/structural/algorithms/iterator.md) | 21 | 6 |
| [mediator](../../design/structural/algorithms/mediator.md) | 27 | 9 |
| [memento](../../design/structural/algorithms/memento.md) | 27 | 3 |
| [observer](../../design/structural/algorithms/observer.md) | 30 | 6 |
| [prototype](../../design/structural/algorithms/prototype.md) | 24 | 6 |
| [proxy](../../design/structural/algorithms/proxy.md) | 33 | 6 |
| [singleton](../../design/structural/algorithms/singleton.md) | 8 | 7 |
| [state](../../design/structural/algorithms/state.md) | 9 | 9 |
| [strategy](../../design/structural/algorithms/strategy.md) | 30 | 0 |
| [template-method](../../design/structural/algorithms/template-method.md) | 21 | 0 |
| [visitor](../../design/structural/algorithms/visitor.md) | 30 | 6 |
