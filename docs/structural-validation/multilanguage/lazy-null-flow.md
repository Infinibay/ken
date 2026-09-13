# IR 1.44: inicialización lazy con polaridad y flujo directo

Se corrige la variante `singleton#lazy-guarded` y se añade la operación nombrada
`singleton.lazy_instance`. La condición debe distinguir null de no-null y sus
ramas deben llevar a la escritura y retornos correctos. El
[diseño](../../design/structural/lazy-null-flow.md) se escribió antes del código;
la [guía IR](../../structural-ir.md#lazy-initialization-and-negated-null-tests)
contiene los contratos y ejemplos ejecutables.

## Verificación

La [verificación final](ir144-checks.json) pasa **5.562 tests en 253.34 s**,
y mypy en 102 archivos. Los 41 ejemplos KenQL de las guías parsean; los 36
de la guía IR se ejecutan contra fuentes. El wheel coincide con los módulos y
TOML escaneados y pasa pruebas fuera del checkout, incluido roundtrip, operación
nueva, polaridad incorrecta, retorno temprano Python y controles eager/mixin.

Se agregan 222 tests: 140 de inicialización lazy, 80 de predicados negados y su
reutilización en Cache-Aside, y dos consultas ejecutables de la guía. El catálogo
conserva 23 GoF, 44 variantes listas, 33 variantes de diseño y 10 reglas modernas;
ahora expone **nueve operaciones públicas**.

## Qué corrige

Antes, GUARDS_WRITE sólo comprobaba que la condición mencionase el slot escrito.
La query aceptaba `value != null`, `!(value == null)` o `value == null || force`
aunque permitieran recrear un valor existente. Podía unir una escritura guardada
con un retorno sin demostrar el recorrido entre ambos.

Ahora la operación requiere campo static asignado explícitamente a NULL en el
cuerpo de la clase, CFG estructurado y una única escritura explícita del slot en
el accessor. La condición inicial es NULL_TEST. La rama no-null devuelve el slot
y termina; la rama null empieza con asignación de una construcción de esa clase,
seguida directamente por un retorno del mismo slot y terminación. Ambas
polaridades y retornos separados/tempranos tienen tests en cinco lenguajes.

NULL_TEST se extiende a negaciones lógicas explícitas, conservando `operator`,
`when` y la paridad `negated`. No descompone AND/OR ni confunde truthiness o negación
aritmética con nulidad. Se prueban 32 negaciones y el rechazo conservador al exceder
ese límite. Cache-Aside reutiliza la evidencia: reconoce `!(value != null)` como
miss y rechaza la polaridad opuesta. La sintaxis original permanece en el IR.

El pase RETURN_FLOW_STATUS puede seguir siendo unsupported por la escritura no
local. No se inventa un origen local para memoria compartida: la nueva consulta
usa CFG y RETURN_OPERAND directamente. GUARDS_WRITE conserva su significado
histórico, pero ya no alcanza para la variante canónica.

## Matriz comparable

Se escanearon las mismas 110 fuentes, con los mismos hashes: 22 casos en Python,
Java, JavaScript, TypeScript y C#. El oráculo describe inicialización lazy directa;
no valida unicidad global, privacidad ni concurrencia.

| Versión | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| [1.43](lazy-null-flow-before.json) | 40 | 20 | 45 | 5 |
| [1.44](lazy-null-flow-after.json) | 45 | 65 | 0 | 0 |

Se corrigen **45 FP y cinco FN en esa muestra**. Los FN recuperados son retornos
tempranos del valor no-null: la escritura válida ocurre después de la guardia,
por lo que GUARDS_WRITE no la enlazaba. Los positivos incluyen renombrado,
comentarios, comparación invertida, negaciones y else con retornos separados.
Los negativos cubren polaridad incorrecta, OR forzado, otro slot, escritura fuera
de la rama, reset previo/posterior, retorno distinto, null sólo histórico y
escritura duplicada. Otros tests cubren campo no static, parsing inválido,
composición de roles y 100 candidatos bajo presupuesto.

Logging intermedio, aliases de retorno y condiciones anidadas válidas se prueban
como brechas de cobertura. No se incluyen artificialmente como TN de esta matriz.

## Repositorios y brechas comprobadas

El [testigo externo](lazy-null-flow-witness.json) conserva el match de
ConfigurationManager TS de across-languages. Registra commit, hashes, roles,
inicialización, predicado, inventario de escrituras, aristas CFG y retornos.
La llamada a loadConfig desde su constructor no demuestra ausencia de reentrancia
ni efectos ocultos; la consulta no afirma esas propiedades.

La [regresión GoF](ir144-corpus-regression.json) conserva todos los matches:
**73 presencias esperadas en 281 ejemplos**, 736 archivos únicos, 745 ocurrencias
y 6.463 consultas completas. El directorio upstream no es un oráculo suficiente
para convertir las 208 ausencias en FN certificados ni las presencias en TP.

Los [escaneos comparables](ir144-production-changes.json) no cambian matches en
Requests, Flask, RxJS, Commons IO, rust-log, la caché de iluwatar, fmt ni los
alcances modernos adicionales de Requests, RxJS, rust-log y Cobra. Tampoco cambian
los seis alcances de Lit y los mixins Pandovski revisados en 1.42. Todas las
consultas finalizan. fmt conserva 677 diagnósticos; sus cero matches no son TN.

Se investigaron además [dos FN concretos de Pandovski](lazy-null-flow-gaps.json):
SingletonSimple.java y SingletonSynchronizedMethod.java. Ambos declaran el campo
referencia sin inicializador. Java lo inicializa a null según
[JLS 4.12.5](https://docs.oracle.com/javase/specs/jls/se17/html/jls-4.html#jls-4.12.5),
pero el IR no representa ese default como asignación explícita. Al agregar
`=null` **sólo a una copia en memoria**, ambos pasan de cero a un match. El JSON
conserva hashes originales y de las modificaciones de diagnóstico. No se editaron
los repositorios externos. El segundo ejemplo usa método synchronized; el match
contrafactual sólo establece el flujo, no certifica sincronización del sistema.

Sólo se leyeron y parsearon fuentes externas; no se importaron, compilaron ni
ejecutaron. Persisten los FP de intención y las brechas de otras variantes.

## Rendimiento

Las [mediciones](lazy-null-flow-performance.json) usan los mismos archivos/casos:

| Fuente | Consulta 1.43, mediana ms | Consulta 1.44, mediana ms | Parseo/enlace 1.44, mediana ms |
|---|---:|---:|---:|
| configuration_manager.ts | 0.225 | 0.413 | 5.805 |
| python-early-return | 0.127 | 0.334 | 1.344 |
| java-wrong-polarity | 0.175 | 0.281 | 1.332 |

ConfigurationManager es fuente externa; los otros dos casos son controlados.
El primero conserva un match, el retorno temprano pasa de cero a uno y la
polaridad incorrecta pasa de uno a cero. Las 30 muestras por query miden más
comprobaciones que antes; diez muestras separan parseo/enlace y proyección.
Singleton en Commons IO termina con 1151 estados.
El JSON incluye p95 y tiempos de proyección.

Las mediciones separan consulta sobre índice/registro preparados, parseo/enlace y
proyección. Son observaciones locales: no incluyen CLI, arranque ni caché
persistente. La caché configurable de 500 MB por defecto conserva su contrato.

## Pendiente

- Representar defaults de campos por lenguaje sin confundirlos con inicialización
  de locales, escritura histórica o ausencia de información. Los dos FN Java
  aportan casos concretos para esa extensión del IR.
- Modelar retornos a través de temporales, efectos intermedios y protocolos más
  complejos sin volver a aceptar escrituras o retornos en ramas incorrectas.
- Tratar doble chequeo, locks y primitivas once mediante identidad de APIs y
  contratos de concurrencia propios. Este análisis no prueba atomicidad.
- Distinguir privacidad/exclusividad, cambios en otros métodos, descriptores,
  reentrancia y memoria compartida. Operadores sobrecargados y comparaciones laxas
  JS limitan una interpretación runtime de NULL_TEST.
