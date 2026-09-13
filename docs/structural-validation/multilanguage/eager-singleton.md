# Singleton eager, campos privados y llamadas estáticas — IR 1.41.0

## Cambio y límites del contrato

`singleton#eager-shared` pasa de diseño a consulta ejecutable en el TOML de
Singleton. Reutiliza la nueva operación pública `singleton.shared_instance`,
que expone unit, storage, accessor y creation. Una declaración de campo estático
construye su propia clase y un método estático sin argumentos comienza devolviendo
ese mismo almacenamiento. La consulta combina operandos, propietario y CFG;
no se agregó una relación del IR exclusiva de Singleton.

La variante de módulo queda separada como `module-shared` en diseño. Las formas
Python de módulo, C++ local static, inicialización mediante holder y primitivas
once Go/Rust requieren otros modelos. El catálogo tiene **23 conceptos GoF,
44 variantes ejecutables, 33 propuestas, nueve reglas modernas y ocho operaciones
públicas**. Una variante disponible no certifica todas las implementaciones.

La firma no prueba constructor privado, almacenamiento inmutable, unicidad global,
ausencia de reset ni seguridad de threads. Un shared default puede tener la misma
estructura sin intención Singleton. Esas restricciones se conservan en el TOML,
en los tests y en el [diseño](../../design/structural/eager-singleton.md).

## Correcciones generales del IR

Las pruebas encontraron dos causas de omisiones adicionales:

- Los identificadores privados de JS/TS se convertían en VALUE al inicializarse,
  pero en STORAGE al accederlos como `Class.#field`. Ahora la declaración,
  inicialización y acceso comparten el slot. La declaración conserva identidad
  propia ante un método homónimo o un campo léxico exterior.
- El linker buscaba el tipo de una instancia cuando RECEIVER ya era una clase.
  Ahora enlaza sus métodos static propios en Java/C#/JS/TS mediante TARGET/CALLS
  con `basis=direct-class-static`. Las sobrecargas conservan MAY_TARGET/MAY_CALLS;
  no se añade DELEGATES_TYPE. Campos o propiedades homónimos JS/TS bloquean esa
  selección. Un getter que devuelve una función no es el destino directo de la
  invocación posterior.

IR_VERSION cambia a **1.41.0** y la caché anterior se invalida. No se agregó
resolución general de overloads, accesibilidad, herencia estática, monkey patching
o receptores importados todavía sin entidad de clase. Las expresiones `class`
de JS/TS siguen siendo una limitación; la prueba anidada usa una declaración
dentro de un método. Ver [contrato y consultas](../../structural-ir.md#shared-class-storage-and-static-calls).

El probe inicial intentó exigir cardinalidad exacta de escrituras sobre relaciones
abiertas. KenQL devolvió `cardinality:open_world`, correctamente. La consulta final
usa evidencia positiva de declaración y retorno directo; no interpreta ausencia
de escrituras conocidas como prueba de retención durante toda la vida del proceso.

## Matriz y pruebas

Se comparó la regla canónica Singleton sobre las mismas 56 fuentes en Java, C#,
TypeScript y JavaScript: renombrado, comentarios, paréntesis, bloques, campos
adicionales, tipo o retorno distinto, fresh allocation en el accessor, campos de
instancia, métodos de instancia y expresiones calculadas.

| Versión | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| IR 1.40.0 | 0 | 32 | 0 | 24 |
| IR 1.41.0 | 24 | 32 | 0 | 0 |

[Referencia](eager-singleton-before.json), [resultado](eager-singleton-after.json).
Son contrastes controlados del contrato, no precisión global. Algunas mutaciones
son deliberadamente incompletas o inválidas para un compilador; los tests analizan
la fuente sin ejecutarla. Las omisiones de accessors con aliases, ramas, parámetros
o trabajo previo se prueban aparte como límites de cobertura y no se suman como TN.

Se agregan **178 tests**: 98 de Singleton y composición, 58 de llamadas estáticas,
20 de almacenamiento privado y dos ejemplos ejecutables de documentación.
Incluyen getters de JS/TS, varios declaradores Java/C#, declaraciones privadas sin
inicializador, campos homónimos, shadowing, sobrecargas, retornos inalcanzables,
argumentos explícitos y roundtrip. Un test de 150 clases verifica el costo de
joins con un presupuesto de 15.000 estados, sin una aserción de tiempo frágil.

La [verificación final](ir141-checks.json) pasa **5.116 tests en 218.38 s**
y mypy en 101 archivos. Los 34 ejemplos KenQL de las guías parsean; los 29 de
la guía IR se ejecutan contra fuentes. El wheel coincide con los hashes del motor
escaneado y se probó fuera del checkout con campo privado TS, llamada estática,
consulta nombrada, factory negativa, control lazy y roundtrip.

## Tres coincidencias revisadas

| Fuente y unidad | Evidencia | Revisión |
|---|---|---|
| Pandovski — SingletonEager | Campo static instance construido con SingletonEager; constructor privado; getInstance devuelve instance. | TP estructural de Singleton eager. |
| iluwatar — IvoryTower | Campo static final INSTANCE construido con IvoryTower; constructor privado con comprobación defensiva; getInstance devuelve INSTANCE. | TP estructural. La comprobación en el constructor no prueba por sí sola inmunidad frente a reflexión. |
| Commons IO — FileSystemProviders | Campo static final INSTALLED construido con la lista de providers; constructor privado; installed devuelve INSTALLED. | TP de instancia compartida inicializada con la clase. No se certifica identidad global entre loaders. |

Los [testigos](eager-singleton-witnesses.json) conservan commits, hashes, campos,
accessors, construcciones, CFG y pruebas de las consultas. No se compiló, importó
ni ejecutó código de los proyectos examinados.

La [regresión del corpus](ir141-corpus-regression.json) compara las mismas fuentes:
**281 ejemplos, 736 archivos únicos, 745 apariciones por alcance y 6.463 consultas
completas**. Añade los dos primeros matches, sin pérdidas; las presencias esperadas
suben de **71 a 73/281**. Las etiquetas upstream indican presencia esperada, no
una matriz TP/TN/FP/FN. Los FP de intención y otros límites anteriores permanecen.

## Alcances de bibliotecas

[Requests](ir141-requests.json), [Flask](ir141-flask.json), [RxJS](ir141-rxjs.json),
[log](ir141-rust-log.json) e [iluwatar caching](ir141-iluwatar-caching.json)
conservan sus matches en 19, 24, 123, nueve y 14 archivos.
[Commons IO](ir141-commons-io.json), sobre 277 archivos, añade únicamente
FileSystemProviders. Las consultas completan dentro de los presupuestos originales.

Las colecciones modernas de [Requests](ir141-modern-requests.json),
[RxJS](ir141-modern-rxjs.json), [log](ir141-modern-rust-log.json) y
[Cobra](ir141-modern-cobra.json) conservan las mismas presencias. RxJS tiene una
corrección de ubicación: la dependencia #init de ColdObservable ahora señala
su declaración, línea 98, en lugar de su primera escritura, línea 102. Es el mismo
match DI; no es un TP nuevo ni una pérdida. Los [cambios](ir141-production-changes.json)
guardan ambos registros para que la diferencia no quede oculta.

[fmt](ir141-fmt.json) conserva cero matches y 677 diagnósticos en 16 cabeceras.
Las macros no expandidas impiden considerar esa ausencia un TN.

## Rendimiento

Las [mediciones](eager-singleton-performance.json) separan las fases:

| Archivo | Consulta 1.40, mediana ms | Consulta 1.41, mediana ms | Parseo/enlace 1.41, mediana ms |
|---|---:|---:|---:|
| SingletonEager.java | 0.041 | 0.204 | 0.943 |
| IvoryTower.java | 0.042 | 0.201 | 1.510 |
| FileSystemProviders.java | 0.047 | 0.212 | 8.605 |

La variante adicional encuentra un match por archivo, frente a cero antes.
El alcance completo de Commons IO finaliza Singleton con 1079 estados
dentro del presupuesto de 100.000. Los p95 y costos de proyección están en el JSON.

Las cifras de consulta usan índice y registro precalculados, 30 muestras después
de warmup; parseo/enlace y proyección tienen diez muestras separadas. Las versiones
se ejecutan secuencialmente después de los tests y escaneos. Son observaciones de
este host, sin caché persistente, no estimaciones de latencia de CLI ni de memoria
total. La caché mantiene 500 MB decimales configurables por defecto.

## Pendientes

- Distinguir Singleton de un default compartido requiere evidencia adicional de
  construcción y uso; no se resuelve imponiendo nombres.
- El accessor directo no cubre todas las formas con aliases, ramas o efectos
  previos. El CFG y RETURN_OPERAND no se presentan como prueba de heap estable.
- Module singleton, holder, local static, Lazy/OnceLock/sync.Once y seguridad
  concurrente necesitan variantes y modelos propios.
- Los receptores de clase importados aún no resueltos, statics heredados y
  expresiones de clase JS/TS son límites de cobertura, no ausencias demostradas.
