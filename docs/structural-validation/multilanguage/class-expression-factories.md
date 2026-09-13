# IR 1.42: clases como valores y factories de subclases

La revisión corrige identidad y ámbito de expresiones de clase JS/TS, añade bases
léxicas Python/JS/TS y conserva valores bajo aserciones TypeScript. Incorpora
`architecture.subclass-factory` en un TOML independiente. El
[diseño](../../design/structural/class-expression-factories.md) se escribió antes
de implementar. La [guía IR](../../structural-ir.md#class-expressions-base-values-and-erased-assertions)
describe los contratos disponibles y contiene ejemplos ejecutados por tests.

## Verificación y catálogo

La [verificación final](ir142-checks.json) pasa **5.250 tests en 226.31 s**
y mypy en 101 archivos. Los 37 ejemplos KenQL de las guías parsean; los 32 de
la guía IR se ejecutan contra fuentes. El wheel coincide con los hashes del motor
escaneado y se probó fuera del checkout con expresión de clase, ámbito interno,
aserción TypeScript, factory Python, arrow JS, negativo, Singleton previo y roundtrip.

El catálogo tiene 23 conceptos GoF, 44 variantes ejecutables, 33 variantes aún de
diseño, 10 reglas modernas/web y ocho operaciones públicas. Una consulta
canónica disponible no significa cobertura de todas las variantes del patrón.
Se añaden 134 tests: 46 de expresiones de clase, 57 de factories de subclases,
28 de aserciones TypeScript y tres consultas de la guía.

## Exactitud medida

La [matriz nueva](subclass-factory-controlled.json) contiene 39 fuentes:
Python, JavaScript y TypeScript, con siete positivos y seis negativos por lenguaje.
Resultado: **21 TP, 18 TN, 0 FP, 0 FN** en esa muestra controlada. Incluye
renombrado, clase vacía, constructor variádico, base homónima, retorno mediante
alias y ramas; los negativos retornan una instancia u otra base, omiten la base
o el retorno, o sobrescriben el parámetro antes de construir la clase.
Esta regla no existía en IR 1.41: no se inventa una matriz anterior del detector.

La corrección de ámbito sí permite una comparación con la misma regla Singleton
anterior, sobre seis fuentes JS/TS y dos clases candidatas por fuente:

| Versión | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| [1.41](class-expression-attribution-before.json) | 0 | 6 | 2 | 4 |
| [1.42](class-expression-attribution-after.json) | 4 | 8 | 0 | 0 |

Antes, una expresión interna homónima podía atribuir sus campos y métodos a la
clase exterior. Con nombres distintos se perdía la instancia compartida interna.
Ahora se reconoce el sitio de definición correcto; el campo de instancia del
control negativo no se convierte en almacenamiento estático. Los conteos son por
clase candidata, no seis clasificaciones binarias ni precisión global GoF.

## Código externo revisado

Sólo se leyeron y parsearon fuentes. No se importó, compiló ni ejecutó código de
los repositorios analizados. Los JSON registran commits, hashes de cada fuente,
hashes del motor, presupuestos, diagnósticos y resultados completos.
Los [testigos](class-expression-factories-witnesses.json) conservan roles,
relaciones y ubicaciones que justifican los matches revisados.

Lit se obtuvo de [su repositorio](https://github.com/lit/lit), commit
`73a69f2e6eea02b37b389d13ec1b210520c0ca8f`. Se revisaron cuatro factories de
producción; cada uno define y retorna una clase que extiende su parámetro:

| Alcance | Archivos | Factory revisado | Matches de la nueva regla |
|---|---:|---|---:|
| [scoped-registry-mixin/src](ir142-lit-scoped-registry.json) | 1 | ScopedRegistryHost | 1 |
| [preact-signals/src](ir142-lit-preact-signals.json) | 4 | SignalWatcher | 1 |
| [signals/src](ir142-lit-signals.json) | 4 | SignalWatcher | 1 |
| [forms/src](ir142-lit-forms.json) | 3 | Arrow asignada a FormAssociated | 1 |
| [ssr-dom-shim/src](ir142-lit-ssr-dom-shim.json) | 8 | Control con expresiones de clase a nivel módulo | 0 |

SignalWatcher de signals y FormAssociated retornan la clase bajo `as Tipo`.
Preservar el operando de la aserción recupera ambos resultados. SignalWatcher
puede retornar la base original en una rama: el contrato detecta la posibilidad
de devolver una subclase, no afirma que ocurra en todas las ejecuciones.
FormAssociated conserva un nombre sintético para la arrow; no se inventa un
nombre de entidad a partir de su asignación.

Los [tres mixins JavaScript del analyzer de Lit](ir142-lit-js-fixtures.json)
son fixtures del proyecto y se cuentan aparte de producción. Los
[tres ejemplos de Pandovski](ir142-pandovski-mixins.json), MilkCoffe, WhipCoffe
y VanillaCoffe, también satisfacen la nueva regla. Son ejemplos de decoradores de
clase; estos tres matches modernos no recuperan por sí solos GoF Decorator.
Los seis alcances de Lit y el archivo Pandovski no producen diagnósticos y todas
sus consultas finalizan. Los resultados de otras reglas en estos nuevos alcances
quedan disponibles en los JSON, sin certificación individual en esta auditoría.

## Regresión y falso positivo de intención

La [regresión del corpus](ir142-corpus-regression.json) conserva exactamente los
matches anteriores: **73 presencias esperadas en 281 ejemplos**, 736 archivos
únicos, 745 ocurrencias de archivo y 6.463 consultas GoF completas. Las etiquetas
proceden de directorios upstream; las 208 ausencias no son una medición validada
de FN ni las 73 presencias una certificación de precisión.

Los escaneos comparables cubren Requests, Flask, RxJS, Commons IO, rust-log,
la caché de iluwatar, fmt y los alcances modernos de Requests, RxJS, rust-log y
Cobra. La [comparación](ir142-production-changes.json) no pierde matches y añade
uno: `Notification` de RxJS, en `packages/rxjs/src/notification.ts`.

El campo estático `completeNotification` inicializa un valor y `createComplete`
lo devuelve atravesando aserciones TypeScript. Es **TP del contrato de instancia
compartida**, pero **FP si se interpreta como Singleton GoF estricto**: el
constructor es público y `createNext`/`createError` construyen otras instancias.
La causa es la amplitud de `singleton#eager-shared`, ahora visible al conservar
los valores bajo `as`. Una corrección futura debe separar esa evidencia
reutilizable de una consulta canónica que exija exclusividad, con pruebas de
constructores y otras creaciones en varios lenguajes. No corresponde volver a
ocultar valores de aserciones válidas para eliminar el resultado.

Persisten los FP de intención anteriores. fmt conserva 677 diagnósticos al
interpretar explícitamente sus 16 headers como C++; sus cero matches no prueban
TN ni análisis completo de macros.

## Rendimiento

Las [mediciones](class-expression-factories-performance.json) usan 30 muestras
de consulta y diez de parseo/enlace por archivo:

| Archivo | Consulta 1.42, mediana ms | Parseo/enlace 1.41, mediana ms | Parseo/enlace 1.42, mediana ms |
|---|---:|---:|---:|
| pandovski/decorator-experimental.ts | 0.137 | 7.816 | 8.225 |
| lit/signal-watcher.ts | 0.092 | 40.776 | 41.378 |
| lit/form-associated.ts | 0.090 | 96.677 | 92.553 |
| rxjs/notification.ts | 0.251 | 22.918 | 24.730 |

La fila RxJS mide Singleton, cuya consulta pasa de 0,163 a 0,251 ms al
incorporar el resultado adicional. Las otras tres filas miden la nueva regla.
Los p95, estados y costos de proyección están en el JSON.

Las mediciones separan ejecución sobre índice preparado, parseo/enlace y
construcción de la vista. No miden CLI, arranque ni caché persistente; las cifras
son observaciones de esta máquina, no garantías. La regla nueva no existía en
1.41: su costo anterior se registra como no disponible, nunca como cero.
El límite configurable de caché, 500 MB por defecto, no cambia en esta revisión.

## Límites pendientes

- `BASE_VALUE` identifica una referencia léxica simple, no la identidad runtime
  de la base ni sustitución de parámetros genéricos. `implements` TS no es base
  runtime. Las bases mediante aliases o llamadas requieren otro modelo de flujo.
- La entidad CLASS identifica un sitio de definición; invocar dos veces el
  factory puede crear clases diferentes. No se resuelve automáticamente
  `new Alias()` o la construcción de resultados de factories.
- Un parámetro reasignado después de definir la clase puede ser válido; la regla
  lo excluye conservadoramente. Es una brecha de cobertura probada, no un TN.
- No se prueban forwarding, aplicación de decoradores, MRO, compatibilidad de
  tipos, temporal dead zones ni intención arquitectónica por esta estructura.
- Las aserciones TS conservan el valor sin validar el tipo afirmado. Los casts de
  C#, Java y C++ y la proyección de CALLEE_VALUE mantienen sus contratos propios.

La siguiente mejora de precisión debe abordar la diferencia entre instancia
compartida y exclusividad Singleton sin perjudicar la operación reutilizable.
