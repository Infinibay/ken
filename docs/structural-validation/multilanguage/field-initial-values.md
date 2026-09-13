# IR 1.45: valores iniciales de campos y defaults por lenguaje

Se recuperan implementaciones lazy que dependían de null implícito en un campo
referencia. El cambio añade FIELD_DECLARATION, FIELD_INITIAL_STATUS y
FIELD_INITIAL_VALUE, sin fabricar operaciones de asignación. El
[diseño](../../design/structural/field-initial-values.md) precedió a la implementación;
la [guía IR](../../structural-ir.md#field-declarations-and-initial-values) documenta
valores, fases y ejemplos ejecutables.

## Verificación

La [verificación final](ir145-checks.json) pasa **5.709 tests en 257.88 s**,
y mypy en 103 archivos. Los 43 ejemplos KenQL de las guías parsean; los 38
de la guía IR se ejecutan contra fuentes. El wheel coincide con los módulos y
TOML escaneados y pasa pruebas fuera del checkout: defaults Java/C#, undefined
JS, incertidumbre TS, anotación Python, tipo declarado frente a inferido y roundtrip.

Se agregan 147 tests: 108 de valores iniciales, 37 de integración lazy y dos
consultas de la guía. El catálogo conserva 23 GoF, 44 variantes ejecutables,
33 variantes de diseño, 10 reglas modernas/web y nueve operaciones públicas.

## Semántica y correcciones

Los declaradores directos se distinguen de referencias al miembro, locales,
asignaciones en métodos, propiedades y eventos. Los inicializadores explícitos
conservan su operando fuente. Los implícitos se interpretan según el lenguaje:
referencias Java y referencias C# soportadas usan NULL; primitivas usan cero,
false o U+0000. JS nativo usa UNDEFINED. TS sin política de emisión conocida es
unsupported; declare/abstract y anotaciones Python no asignan valor runtime.
Los campos C++/Go/Rust y defaults C# de value types no resueltos requieren otros
modelos. No se usan nombres de bibliotecas para adivinar una referencia C#.

El valor describe la **fase de declaración**, no el resultado final de todos los
inicializadores, constructores, setters o escrituras posteriores. No implica
inmutabilidad. Una declaración duplicada produce unsupported en vez de elegir
una ocurrencia; los errores de parsing también impiden publicar un valor conocido.

Las pruebas detectaron un error durante la implementación: TYPE puede describir
un tipo inferido por una asignación posterior, incluso cuando el tipo declarado
es distinto o no está resuelto. Usar ese TYPE para el default convertía un campo
int C# en null después de encontrar `value=new C()`. El pase corregido recibe el
mapa de tipos **declarados**, conserva cero para int y deja desconocido un tipo
no resuelto. Los parámetros genéricos C# que ocultan una clase homónima no heredan
su default de referencia. Hay regresiones específicas para ambos casos.

## Matriz de integración

Las mismas 32 fuentes Java/C# se analizaron con ambas versiones. Los positivos
incluyen campo implícito, null explícito, nombre distinto, comentarios, constructor
privado, retorno temprano, else y campo declarado como Object/object. Negativos:
polaridad incorrecta, OR forzado, resets, null sólo histórico, primitiva, valor
inicial no-null y declaración duplicada.

| Versión | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| [1.44](field-initial-values-before.json) | 2 | 14 | 2 | 14 |
| [1.45](field-initial-values-after.json) | 16 | 16 | 0 | 0 |

Se recuperan **14 FN** y se excluyen dos coincidencias indebidas en declaraciones
duplicadas de la muestra. Éstas son controles de evidencia ambigua, no ejemplos
certificados como programas compilables. Los resultados no miden precisión global
ni prueban exclusividad de Singleton. Los tests adicionales distinguen NULL,
UNDEFINED, absent y unsupported en Python/JS/TS; comprueban dimensiones por
declarador Java, defaults de tipos básicos, scopes, roundtrip y consultas.

## Fuentes externas revisadas

Los [cinco testigos](field-initial-values-witnesses.json) registran commits, hashes,
valores iniciales, constructores, CFG, escrituras, retornos y pruebas de consultas:

| Proyecto / archivo | Lenguaje | Evidencia revisada |
|---|---|---|
| Pandovski / SingletonSimple.java | Java | Campo privado sin inicializador, guardia null y retorno del slot |
| Pandovski / SingletonSynchronizedMethod.java | Java | Mismo flujo dentro de método synchronized |
| Pandovski / SingletonDesignPattern.java | Java | Clase anidada privada y campo INSTANCE con default null |
| Pandovski / SingletonDesignPattern.cs | C# | Campo obj implícito, creación en miss y retornos separados |
| iluwatar / ThreadSafeLazyLoadedIvoryTower.java | Java | Campo volatile implícito, constructor privado y accessor synchronized |

Son TP de la estructura lazy revisada. Las palabras synchronized/volatile y el
nombre de una clase no se convierten en pruebas de seguridad concurrente. La
consulta no valida reflexión, reentrancia ni la estabilidad del almacenamiento.
Los dos FN documentados en 1.44 se recuperan sobre las fuentes originales, sin
agregar `=null` al repositorio externo ni usar las copias de diagnóstico como TP.

La [regresión del corpus](ir145-corpus-regression.json) pasa de **73 a 74 presencias
esperadas en 281 ejemplos**, con cinco matches nuevos y ninguna pérdida. Cuatro
matches ocurren en directorios Java que ya tenían una presencia; la presencia
nueva corresponde al ejemplo C#. Se conservan 736 archivos únicos, 745 ocurrencias
y 6.463 consultas completas. Esto muestra por qué presencia por directorio no
equivale a recall por implementación ni a una matriz de TP/FN independiente.

Los [escaneos comparables](ir145-production-changes.json) no cambian matches en
Requests, Flask, RxJS, Commons IO, rust-log, la caché de iluwatar, fmt ni los
alcances modernos adicionales de Requests, RxJS, rust-log y Cobra. Tampoco cambian
los seis alcances de Lit y los mixins Pandovski. Todas las consultas finalizan;
fmt conserva 677 diagnósticos, por lo que cero matches allí no prueba TN.
Sólo se leyeron y parsearon fuentes: no se importó, compiló ni ejecutó código externo.

## Rendimiento

Las [mediciones](field-initial-values-performance.json) usan tres fuentes externas
revisadas y los mismos bytes en ambas versiones:

| Fuente | Consulta 1.44, mediana ms | Consulta 1.45, mediana ms | Parseo/enlace 1.45, mediana ms |
|---|---:|---:|---:|
| SingletonSimple.java | 0.204 | 0.314 | 1.155 |
| SingletonDesignPattern.cs | 0.216 | 0.382 | 2.953 |
| ThreadSafeLazyLoadedIvoryTower.java | 0.205 | 0.314 | 1.760 |

Cada fuente pasa de cero a un match. Se miden 30 consultas después de warmup
y diez muestras separadas de parseo/enlace y proyección. Singleton termina con
2078 estados en el alcance completo de Commons IO.
Los p95 y costos de proyección están en el JSON.

Se separan consulta sobre índice/registro preparados, parseo/enlace y proyección.
Las cifras son observaciones locales; no incluyen CLI, arranque ni caché
persistente. La caché configurable mantiene su valor por defecto de 500 MB.

## Límites pendientes

- Los defaults no describen el estado después de inicializadores posteriores,
  bloques estáticos, construcción, setters o escrituras de otros métodos.
- TS requiere política de emisión para afirmar el efecto de campos no inicializados.
  C# value types, aliases, constraints genéricos y tipos externos no resueltos
  necesitan evidencia propia; no se promueven por parecido de nombres.
- Anotaciones Python repetidas y declaraciones que comparten un slot se tratan
  conservadoramente. No se reconstruye la ejecución completa del cuerpo de clase.
- Se mantienen las restricciones del flujo lazy de 1.44. Logging intermedio,
  temporales y doble chequeo/once requieren otras variantes; thread safety y
  unicidad global no están demostradas por este detector.
