# Últimas entradas de bindings y políticas Strategy — IR 1.39.0

## Corrección y contrato

Strategy aceptaba cualquier ASSIGNED_FROM histórico. Una política que recibía un
parámetro y después se sobrescribía seguía apareciendo como inyectada. La variante
por objeto también aceptaba delegación sin comprobar que la llamada perteneciera
al contrato nominal del campo.

Las dos variantes ahora reutilizan `strategy.supplied_policy`. Esta consulta
correlaciona el campo con un parámetro de su configurador mediante la última
escritura fuente soportada o una entrada final de constructor. El objeto debe
invocar un slot del contrato desde otro método, mediante DECLARED_TARGET o TARGET.
La variante callable exige CALLEE_VALUE del mismo campo. Una llamada con varios
MAY_TARGET puede conservar un slot declarado único; no se exige seleccionar una
implementación runtime.

El IR añade FINAL_BINDING_INPUT y BINDING_FLOW_STATUS en ocho gramáticas. La
última escritura fuente es distinta de retención del valor en el heap: Python
puede ejecutar un descriptor, y cualquier lenguaje puede tener efectos ocultos.
FINAL_MEMBER_INPUT conserva su contrato anterior. Las declaraciones sin valor de
JS/TS/Java/C#, las anotaciones Python sin asignación y los let de Rust sin
inicializador dejan de ser ASSIGN sin operandos: se clasifican como DECLARATION.
No se modela por ello la inicialización implícita ni la validez del programa.
Ver [diseño](../../design/structural/strategy-binding-inputs.md) y
[relaciones y ejemplos](../../structural-ir.md#last-binding-inputs-and-supplied-policies).

## Matriz antes/después

Se compararon las mismas 113 fuentes con IR 1.38 y 1.39, usando la regla canónica
Strategy: objetos en Python, TypeScript, Java, C# y C++; callables en Python,
JavaScript, TypeScript y Go. Se preservan renombrado, escritura anterior y posterior,
rebindings, retorno antes/después de la asignación, política distinta, segundo
parámetro como entrada final, ausencia de invocación y llamada fuera del contrato.

| Versión | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| IR 1.38.0 | 45 | 22 | 46 | 0 |
| IR 1.39.0 | 45 | 68 | 0 | 0 |

[Referencia](strategy-binding-inputs-before.json),
[resultado](strategy-binding-inputs-after.json). Es una matriz de contrastes
controlados, no precisión global. Los casos con configuración no lineal se prueban
por separado como análisis unsupported y no se suman como TN a esta matriz.
Algunas mutaciones son código deliberadamente incompleto; no se compilan.

Se agregan 150 tests de Strategy, 123 del pase de bindings y dos ejemplos
ejecutables de la guía. Incluyen políticas de constructor C++/TypeScript,
descriptores Python, destinos runtime ambiguos con slot declarado, bindings
locales/static, campos distintos, variádicos como valores sin expansión, retornos,
declaraciones sin inicializador y una regresión de presupuesto con 120 consumidores.
La [verificación final](ir139-checks.json) pasa **4.728 tests en 194,54 s** y mypy
en 101 archivos. Los 30 ejemplos KenQL de las guías parsean; los 25 de la guía IR
se ejecutan contra fuentes. El wheel coincide con los hashes del motor escaneado
y se probó fuera del checkout: política positiva, sobrescritura negativa, operación
pública, roundtrip del IR, binding static separado de miembro, declaración JS sin
valor e inicializador C# cuyo valor no tiene field name en la gramática.

## Corpus abierto y cambios revisados

La [comparación](ir139-corpus-regression.json) mantiene las mismas fuentes y commits,
281 ejemplos, 736 archivos únicos, 745 apariciones por alcance y 6.463 consultas.
Las presencias esperadas permanecen en **71/281**. No se añaden matches; se eliminan
dos candidatos Strategy por configuración fuera del pase lineal:

| Fuente y unidad | Revisión de la pérdida |
|---|---|
| cpp-patterns builder/Builder.cpp — Director | La firma anterior señalaba como Strategy la inyección del Builder: FP de intención. El setter contiene una rama que destruye el builder anterior antes de la asignación. Se deja de emitir porque BINDING_FLOW_STATUS es unsupported, no porque la nueva consulta demuestre intención Builder. |
| cpp-patterns state/State.cpp — Context | El cliente sustituye externamente el estado y Context delega handle; su intención Strategy/State era ambigua. El setter contiene una rama para liberar el estado anterior. La nueva ausencia es una limitación de cobertura lineal, no un TN demostrado. |

Los cinco FP de intención nuevos registrados en IR 1.38 se mantienen:
Switch/Command y CandyDecorator de Pandovski; RefinedAbstraction/Bridge, Decorator
y NonterminalExpression/Interpreter de cpp-patterns. Sus relaciones de inyección
y despacho son reales. La corrección de escrituras no basta para distinguir sus
roles de algoritmos intercambiables; no se ocultan por nombres o categorías.

Se preservan Context del ejemplo C++ Strategy y Order de python-patterns. En Order,
la asignación al atributo con descriptor es evidencia fuente; no se afirma que
el descriptor conserve o devuelva exactamente el parámetro. Se preservan también
Mammoth y Order de los ejemplos State Java/TypeScript: sus calls tienen destinos
posibles múltiples, pero conservan el slot nominal declarado. No se cuentan como
nuevos TP ni se resuelve por ello su ambigüedad Strategy/State.
Los [testigos](strategy-binding-input-witnesses.json) conservan hechos, roles,
ubicaciones y hashes de las pérdidas y de los controles seleccionados.

## Bibliotecas reales y límites de resolución

[Requests](ir139-requests.json), [Flask](ir139-flask.json), [RxJS](ir139-rxjs.json),
[log](ir139-rust-log.json) e [iluwatar caching](ir139-iluwatar-caching.json) conservan
las coincidencias de sus alcances anteriores: 19, 24, 123, nueve y 14 archivos.
[Commons IO](ir139-commons-io.json), sobre 277 archivos, conserva AbstractPathCounters
y pierde el candidato Strategy de NotFileFilter. Las consultas terminan dentro
de los mismos presupuestos. Los demás resultados de Commons IO se conservan.

NotFileFilter conserva el filtro recibido y niega el resultado de accept; su uso
es de decoración/composición de filtros. La pérdida ocurre porque accept tiene
sobrecargas y no se obtiene un slot nominal único para esas llamadas. Esto es una
limitación de resolución que también podría ocultar estrategias válidas con
sobrecargas, no evidencia de una discriminación perfecta entre patrones.

[fmt](ir139-fmt.json) conserva cero matches y 677 diagnósticos en 16 cabeceras con
override .h→cpp. La ausencia de expansión de macros impide interpretarlo como TN.
No se compiló ni ejecutó código de los repositorios analizados.

## Rendimiento y presupuesto

La primera consulta de supplied_policy enumeraba campos, métodos y parámetros
antes de verificar escrituras. Commons IO agotó **100.000 estados** y devolvió
un resultado incompleto. El orden corregido empieza en FINAL_BINDING_INPUT o
CONSTRUCTOR_FIELD_INPUT y después resuelve campo y propietario. No cambian los
bindings aceptados y no se aumenta el presupuesto.

La consulta Strategy optimizada de Commons IO completa con **8.039 estados**.
El test de 120 consumidores, cada uno con ocho campos y ocho parámetros explícitos,
produce los 120 matches dentro de 10.000 estados. Es una regresión de trabajo
realizado, no una aserción frágil sobre tiempo de reloj.

Las [mediciones](strategy-binding-inputs-performance.json) separan consulta sobre
índice/registro precalculados (30 muestras después de warmup), parseo/enlace y
proyección (diez muestras cada uno), en las mismas fuentes Strategy C++ y Python.
Se ejecutaron las versiones secuencialmente después de los otros trabajos.

| Fuente | Consulta 1.38, mediana ms | Consulta 1.39, mediana ms | Parseo/enlace 1.39, mediana ms |
|---|---:|---:|---:|
| cpp-patterns Strategy.cpp | 0,175 | 0,247 | 5,679 |
| python-patterns strategy.py | 0,176 | 0,222 | 12,233 |

Ambas versiones producen un match en cada archivo. La comprobación adicional
tiene un costo pequeño medido en estas fuentes; no es una mejora global de velocidad.
Los p95 y la proyección están en el JSON. Son
observaciones de este host, sin caché persistente; no estiman latencia de CLI ni
memoria global. La caché mantiene **500 MB decimales configurables por defecto**.

## Pendientes

- Distinguir intención de algoritmo de otras colaboraciones requiere más evidencia
  de uso; las relaciones compartidas no justifican excluir patrones entre sí.
- La configuración con ramas, bucles o efectos no modelados necesita un análisis
  de flujo más amplio. Una ausencia por unsupported no es prueba de que no exista
  una política inyectada.
- La resolución de slots sobrecargados sigue limitada. Debe distinguir contrato
  declarado y destinos runtime, preservando posibilidades cuando faltan tipos.
- Los descriptores, setters, aliases y mutaciones ocultas necesitan sus propios
  modelos. FINAL_BINDING_INPUT describe una escritura fuente, sin prometer el valor
  almacenado o una invocación futura de esa misma instancia.
