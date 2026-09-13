# Inyección de funciones y callee entre paréntesis — IR 1.40.0

## Cambio y garantías

La regla moderna `architecture.dependency-injection` ahora une dos variantes
en su propio TOML. `object-assignment` conserva la consulta anterior, basada en
escritura histórica y delegación. `callable-input` reutiliza
`strategy.supplied_policy`: un parámetro suministra la última escritura fuente
soportada o una entrada final de constructor; otro método invoca ese campo.
Las dos conservan los roles unit, dependency, inject y operation.

La nueva variante inicialmente omitía Rust: `(self.callback)(value)` conservaba
el parámetro almacenado pero perdía CALLEE_VALUE. El lowering ahora proyecta el
binding a través de paréntesis alrededor de identificadores, miembros e índices,
sin eliminar los nodos sintácticos ni reinterpretar casts u otros operadores.
IR_VERSION sube a 1.40.0, invalidando la caché de hechos anterior.
Ver [diseño](../../design/structural/callable-dependency-injection.md) y
[contrato con consultas ejecutables](../../structural-ir.md#parenthesized-callee-bindings-and-callable-dependencies).

Esto demuestra suministro y uso estructural de una colaboración funcional.
No demuestra contenedor DI, lifetimes, identidad en el heap, orden temporal entre
configuración y consumo ni intención exclusiva de un patrón. La misma estructura
puede intervenir en Strategy, Command o en el ciclo de vida de una suscripción.

## Matriz controlada y tests

Las mismas 98 fuentes se consultaron con la regla canónica antes y después:
14 contrastes en Python, JavaScript, TypeScript, Go, C#, C++ y Rust.

| Versión | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| IR 1.39.0 | 0 | 49 | 0 | 49 |
| IR 1.40.0 | 49 | 49 | 0 | 0 |

[Referencia](callable-dependency-injection-before.json),
[resultado](callable-dependency-injection-after.json). Los contrastes incluyen
renombrado, paréntesis, escrituras anteriores y posteriores, rebindings del input,
retornos, otro campo, segundo parámetro como entrada final y ausencia de llamada.
Es una matriz de fixtures para este contrato, no precisión global ni cobertura
completa de los lenguajes. Algunas mutaciones son deliberadamente incompletas o
inválidas para un compilador; se comprueba su análisis fuente, sin ejecutarlas.
La configuración no lineal se prueba aparte como unsupported y no se suma como TN.

Se añaden **210 tests**:

- 148 de inyección funcional y controles: siete lenguajes con callables, más Java
  mediante interfaz funcional en la variante por objeto. Incluyen constructores,
  argumentos expandidos, consumidores async o condicionales, campos privados TS,
  parámetros-propiedad, descriptores Python, funciones locales y correlación de roles.
- 60 de bindings invocados: paréntesis anidados, comentarios, índices, shadowing,
  roundtrip y expresiones no transparentes. C# conserva la desambiguación de cast;
  el índice con un solo paréntesis tiene una limitación del parser registrada.
- Dos ejemplos ejecutables de la guía IR.

La [verificación](ir140-checks.json) pasa **4.938 tests en 206,68 s** y mypy en
101 archivos. Los 32 ejemplos KenQL de las guías parsean; los 27 de la guía IR
se ejecutan contra fuentes. El wheel coincide con los hashes del motor escaneado
y se probó fuera del checkout: inyección Rust positiva, sobrescritura negativa,
operación nombrada reutilizada, roundtrip, cast C# y control de inyección
condicional por objeto. El paquete continúa siendo Python con Tree-sitter.

## Cuatro coincidencias nuevas revisadas

Los [cambios externos](ir140-production-changes.json) contienen cuatro adiciones,
sin pérdidas. Los [testigos](callable-dependency-injection-witnesses.json) guardan
commits, hashes de fuentes, localizaciones, hechos y pruebas de las consultas.

| Proyecto y unidad | Evidencia revisada | Interpretación |
|---|---|---|
| Flask — ScriptInfo | `__init__` guarda create_app; `load_app` la invoca si está presente y tiene otros caminos para localizar la aplicación. | TP de colaboración factory suministrada. No prueba qué camino toma una ejecución. |
| Flask — ConfigAttribute | `__init__` guarda get_converter; `__get__` lee configuración e invoca el conversor cuando existe. | TP de conversor suministrado; el descriptor no implica identidad de valores en el heap. |
| RxJS — ColdObservable | El constructor guarda init en `#init`; `subscribe` crea el suscriptor e invoca el campo dentro de try/catch. | TP de inicializador suministrado. No certifica cantidad de ejecuciones ni ciclo de vida. |
| RxJS — Connection | El parámetro-propiedad privado disconnect se invoca desde `unsubscribe`, pasando la conexión. | TP de callback de desconexión suministrado; puede compartir estructura con otros patrones. |

Flask pasa de cinco a siete matches DI en 24 archivos. RxJS pasa de uno a tres
en 123 archivos; el control anterior incluye otra dependencia de Connection.
Los archivos `*.spec.ts` y `*/testing/*` de RxJS están excluidos igual que en
la referencia. No se presume haber revisado todas las coincidencias anteriores.

Un [probe de restricción lineal general](callable-dependency-injection-linear-probe.json)
perdería tres colaboraciones por objeto de Flask: AppContext.app,
AppContext._request y BlueprintSetupState.app. Sus configuradores incluyen ramas
fuera del pase de última escritura. La implementación final conserva esos casos
y documenta que `object-assignment` sólo acredita asignación histórica. Este probe
no es una pérdida de la versión final ni una mejora demostrada de precisión.

## Regresión externa

El [corpus](ir140-corpus-regression.json) conserva exactamente los matches de
IR 1.39 sobre las mismas fuentes: **281 ejemplos, 736 archivos únicos, 745
apariciones por alcance y 6.463 consultas completas**. Las presencias esperadas
siguen en **71/281**. Son etiquetas de presencia del ejemplo upstream, no una
matriz TP/TN/FP/FN. Persisten los FP de intención y límites de configuración y
sobrecargas documentados en las revisiones anteriores.

Los alcances comparables de [Requests](ir140-requests.json),
[Flask](ir140-flask.json), [RxJS](ir140-rxjs.json),
[Commons IO](ir140-commons-io.json), [log](ir140-rust-log.json) e
[iluwatar caching](ir140-iluwatar-caching.json) tienen 19, 24, 123, 277, nueve y
14 archivos. Sólo añaden los dos matches DI de Flask; los alcances GoF no cambian.
Las colecciones modernas se comparan además en
[Requests](ir140-modern-requests-after.json), [RxJS](ir140-modern-rxjs-after.json),
[log](ir140-modern-rust-log-after.json) y [Cobra](ir140-modern-cobra-after.json):
19, 123, nueve y 19 archivos. Sólo RxJS añade los dos matches descritos arriba.
Todas las consultas comparadas completan con los presupuestos originales.

[fmt](ir140-fmt.json) mantiene cero matches y 677 diagnósticos en 16 cabeceras
con override .h→cpp. Las macros no expandidas impiden tratar esa ausencia como TN.
No se compiló, importó ni ejecutó código de los repositorios escaneados.

## Rendimiento

Las [mediciones](callable-dependency-injection-performance.json) separan consulta
sobre índice y registro ya preparados (30 muestras tras warmup), parseo/enlace y
proyección (diez muestras cada uno). Se midieron las versiones secuencialmente,
después de los tests y escaneos, sobre cuatro archivos que contienen los nuevos
matches. Este microbenchmark no enlaza sus imports; los escaneos de proyecto
anteriores sí analizan los alcances completos indicados.

| Archivo | Consulta 1.39, mediana ms | Consulta 1.40, mediana ms | Parseo/enlace 1.40, mediana ms |
|---|---:|---:|---:|
| flask — cli.py | 0.669 | 0.887 | 243.868 |
| flask — config.py | 0.135 | 0.428 | 43.461 |
| rxjs — cold-observable.ts | 0.141 | 0.370 | 51.867 |
| rxjs — connectable.ts | 0.154 | 0.311 | 34.978 |

La consulta canónica ahora evalúa dos variantes y su dependencia nombrada: hace
más trabajo para producir más resultados. En los escaneos completos, DI termina
con 3.489 estados en Flask y 2.532 en RxJS, debajo del límite de 100.000.
Los p95, conteos de matches y estados están en el JSON. Son observaciones de este
host sin caché persistente; no estiman latencia de CLI ni consumo global de memoria.
La caché conserva **500 MB decimales configurables por defecto**.

## Pendientes

- Configuración funcional con ramas/bucles y factories Go/Rust que devuelven
  structs con funciones necesitan modelos adicionales. Su ausencia no demuestra
  que no exista inyección.
- La variante por objeto aún acepta escrituras históricas: una sobrescritura
  posterior puede invalidar la interpretación. No se le atribuye la garantía
  más fuerte de la variante funcional.
- CALLEE_VALUE no resuelve cualquier método parentizado, overload, alias de
  función o callable obtenido con casts/indirecciones. El índice C# con un solo
  paréntesis permanece como límite explícito de la gramática.
- Los tests de argumentos expandidos acreditan que la invocación usa el campo;
  no añaden bindings precisos argumento→parámetro para la expansión.
- Los patrones solapados y el comportamiento de descriptores, setters, efectos
  ocultos y orden temporal necesitan evidencia adicional. Los cuatro nuevos TP
  corresponden al contrato estructural delimitado arriba.
