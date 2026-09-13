# Patrones de arquitectura y web

El objetivo sigue abierto: ampliar y corregir GoF y cubrir patrones habituales
de aplicaciones web en varios lenguajes. El corpus independiente muestra que los
tests propios de los 23 conceptos no equivalen a cobertura de sus variantes reales.
Ver [resultados y problemas](structural-validation/labelled-corpus-v2/README.md).

La [revisión del catálogo con IR 1.47](structural-validation/multilanguage/modern-catalog-review.md)
comprueba los diez conceptos con positivos, negativos y ruido en tres lenguajes
por concepto. Añade 149 tests y la variante opt-in
`architecture.dependency-injection#retained-object`, que exige retención final
soportada de la dependencia. La consulta general conserva configuraciones no
lineales; el contrato preciso se solicita explícitamente. Unit of Work conserva
su variante transaccional en diseño: su query pública actual reconoce lotes por
clave, sin probar atomicidad ni rollback.

## Factories de subclases y mixins

IR 1.42.0 añade `architecture.subclass-factory`, el décimo detector moderno/web,
en `src/ken/structural/modern_patterns/subclass-factory.toml`. Expone los roles
`factory`, `derived` y `base`: un callable devuelve una clase local que extiende
su parámetro base. La consulta nombrada puede componerse con consultas de uso;
ver el [ejemplo ejecutable](structural-ir.md#class-expressions-base-values-and-erased-assertions).

```typescript
function withLogging(Base) {
  return class extends Base {
    log(message) { console.log(message); }
  };
}
```

La misma estructura tiene pruebas en Python, JavaScript y TypeScript, incluyendo
clases anónimas y nombradas, arrows concisas, retornos mediante aliases locales,
constructores variádicos y aserciones TypeScript. `BASE_VALUE` representa la base
léxica; `CLASS_EXPRESSION` conserva la identidad y el ámbito interno de cada
expresión JS/TS. Las aserciones TypeScript preservan su operando, sin inferir que
el tipo afirmado sea verdadero.

El cuerpo con statements requiere flujo de retorno soportado y un parámetro base
sin escrituras explícitas. Una arrow concisa puede devolver directamente la
expresión de clase. No se exige modificar métodos: una subclase vacía también
satisface este contrato. No prueba aplicación efectiva del mixin, compatibilidad
de tipos, forwarding, MRO ni intención GoF Decorator. Las bases mediante aliases
y las escrituras al parámetro posteriores a definir la clase son límites conocidos.
Ver [diseño](design/structural/class-expression-factories.md) y
[auditoría](structural-validation/multilanguage/class-expression-factories.md).

## Disponible

`architecture.dependency-injection`, en
`src/ken/structural/modern_patterns/dependency-injection.toml`, es una consulta
KenQL pública en las colecciones `architecture` y `modern`. No introduce otro
motor ni una categoría especial de ejecución.

La consulta canónica combina dos variantes del mismo TOML. `object-assignment`
conserva la regla anterior: un parámetro se escribe en un campo y otra operación
delega en ese mismo campo. `callable-input`, añadida con IR 1.40.0, reconoce la
función suministrada que se invoca directamente desde otro método. Reutiliza la
operación pública `strategy.supplied_policy` y exige una última escritura fuente
soportada o entrada final de constructor. Las dos exponen objeto, campo, punto
de inyección y consumidor; no exigen nombres de servicios o frameworks.

La nueva forma tiene pruebas en Python, JS, TS, Go, C#, C++ y Rust, incluyendo
funciones tipadas, punteros a función, campos privados, parámetros-propiedad,
renombrado, sobrescrituras y argumentos expandidos. Java invoca funciones a través
del método de una interfaz funcional y usa la variante por objeto. Son pruebas
de análisis estático, no compilación ni certificación de un contenedor DI.

Ejemplo:

```python
class Handler:
    def __init__(self, store):
        self.store = store

    def handle(self):
        return self.store.fetch()
```

No demuestra configuración de un contenedor, lifetimes ni composición efectiva
en runtime. En `object-assignment`, ASSIGNED_FROM mantiene evidencia histórica:
no prueba que el campo no se sobrescriba después. La garantía de última escritura
fuente de `callable-input` tampoco prueba almacenamiento de descriptores/setters
ni orden temporal entre los métodos. Se inspira en la separación de configuración y uso descrita por
[Fowler](https://martinfowler.com/articles/injection.html).

Una dependencia funcional puede proporcionar la creación de una aplicación,
conversión de datos o inicialización de una suscripción:

```python
class Endpoint:
    def __init__(self, read):
        self.read = read

    def handle(self, key):
        return self.read(key)
```

En Rust, invocar un campo función requiere la forma `(self.callback)(value)`.
IR 1.40.0 preserva CALLEE_VALUE a través de esos paréntesis, conservando los nodos
originales y sin reinterpretar casts. C# mantiene sus reglas de desambiguación.
La revisión externa confirma cuatro usos nuevos: ScriptInfo.create_app y
ConfigAttribute.get_converter en Flask; ColdObservable.#init y Connection.disconnect
en RxJS. Se conservan todas las coincidencias anteriores de los escaneos comparados.
Ver [auditoría y límites](structural-validation/multilanguage/callable-dependency-injection.md).

La configuración no lineal de callables y los factories Go/Rust que retornan
structs con campos función necesitan otras variantes. Aplicar ahora la restricción
lineal a toda la regla perdería tres usos válidos por objeto en Flask; ese probe
se registra y las garantías de ambas variantes permanecen separadas.

Uso desde Python:

```python
from ken.structural.rules import builtin_rules, select_rules, execute_rules

registry = builtin_rules()
selected = select_rules(registry, collections=["modern"])
result = execute_rules(graph, selected, registry=registry)
```

## Wrappers funcionales disponibles

`architecture.continuation-wrapper`, en su propio TOML, detecta una función que
recibe una continuación y devuelve un callable anidado que la invoca. Se validó
en Go, Python, JavaScript y TypeScript, con renombrado y negativos por llamada a
otro símbolo, ausencia de delegación y parámetro interior que oculta al exterior.
El IR 1.5.0 conserva la identidad del callable devuelto y su ámbito. `CALLEE_VALUE`
identifica el binding léxico invocado; no demuestra el valor runtime después de
reasignaciones. No se afirma orden, forwarding ni invocación exactamente una vez.

Desde IR 1.8.0 también se conserva la forma `next => request => next(request)`:
parámetros únicos sin paréntesis y retornos implícitos de cuerpos expresión en
JavaScript/TypeScript. Un cuerpo de bloque sin `return` no se interpreta como
retorno del último valor. Los modificadores async pertenecen a su propia función,
sin propagarse desde una arrow interior hacia la exterior. Doce regresiones
adicionales contrastan esas formas y el shadowing del parámetro recibido.

Esta firma es una pieza de middleware y decoradores funcionales. Todavía no prueba
registro HTTP ni reconoce por sí sola `http.HandlerFunc` y delegación `ServeHTTP`.
El [contrato de Alice](https://github.com/justinas/alice) ilustra por qué esas formas
necesitan variantes adicionales: la composición recibe y retorna `http.Handler`.

Validación externa: el escaneo de 52 archivos de Werkzeug detectó
`LocalManager.make_middleware`, su función devuelta `application` y el parámetro
capturado `app`. La revisión de las líneas 227–239 confirma que la aplicación se
invoca dentro del handler y se envuelve con `ClosingIterator` para limpieza.
El [reporte con commit, hashes y roles](structural-validation/labelled-corpus-v2/werkzeug-continuation-wrapper.json)
registra una coincidencia y enumeración completa. Esta muestra confirma un caso
WSGI; no mide recall de todos los middleware de Werkzeug.

## Handlers adaptados

`architecture.adapted-continuation-wrapper` reconoce una fábrica que devuelve
una llamada adaptadora cuyo argumento es un handler anidado. Ese handler invoca
la continuación recibida o un método de ella. Admite tanto argumentos directos
como una lectura de variable asignada al handler. Los 26 tests cubren Go,
Python, JavaScript y TypeScript, renombrado, shadowing, receptor distinto,
handler hermano y adaptación no devuelta. El TOML expone la consulta y sus límites.

```go
func Wrap(next http.Handler) http.Handler {
    fn := func(w http.ResponseWriter, r *http.Request) {
        next.ServeHTTP(w, r)
    }
    return http.HandlerFunc(fn)
}
```

[net/http](https://pkg.go.dev/net/http#HandlerFunc) define HandlerFunc como adaptación
de una función a Handler. La consulta genérica no resuelve esa API: descubre
la estructura y presenta el adaptador para revisión. No garantiza que un adaptador
arbitrario conserve el callback, que no haya reasignación, que se registre como
middleware HTTP o que invoque la continuación en todos los caminos.

El escaneo de chi encontró 37 combinaciones de evidencia en 31 fábricas, con
30 archivos analizados y ninguna consulta incompleta. La revisión de CleanPath,
GetHead y Timeout confirma casos reales; las demás coincidencias no constituyen
una auditoría exhaustiva de precisión. Ver [informe de chi](structural-validation/web-frameworks/chi.md).

## Tabla de despacho disponible

`architecture.dispatch-table` está en un TOML separado y comparte las colecciones
`architecture` y `modern`. Exige que un método registre dos parámetros distintos
(clave y handler) mediante escritura indexada, y que otro invoque una entrada
de la misma tabla usando una clave recibida. Devuelve registro, dispatch y tabla.
Hay 27 pruebas de parsing/IR/query en Python, JavaScript, TypeScript y Go, incluidos
negativos por tabla diferente, lectura sin llamada, roles invertidos, clave
constante y conversiones Go que no son llamadas indexadas.

Desde IR 1.23, el mismo TOML agrega la variante `adapted`: registro heredado,
clave derivada de un contexto y un adaptador resuelto cuyo resultado se invoca.
Tiene 62 tests en Python/JS/TS, incluidos imports entre archivos, y detecta el
despacho de Flask con evidencia revisada. Se agregaron 12 tests de argumentos
indexados en ocho lenguajes y wrappers nombrados/expandidos. Ver [auditoría de
Flask](structural-validation/web-frameworks/flask-adapted-dispatch.md).

```python
class Commands:
    def __init__(self):
        self.handlers = {}
    def register(self, key, handler):
        self.handlers[key] = handler
    def dispatch(self, requested, data):
        return self.handlers[requested](data)
```

El IR 1.10.0 conserva `CONTAINER` e `INDEX` de accesos y `STORES_VALUE` de escrituras
indexadas simples. En Go, tree-sitter puede parsear `r.table[key](data)` como una
conversión genérica; sólo se desambigua para un campo del receptor con declaración
explícita `map[...]func(...)` y clave léxica conocida. No se generaliza a aliases
de tipos, mapas dinámicamente inferidos o conversiones de paquetes homónimos.

Es la forma estructural de una tabla de despacho; no prueba un router HTTP, entrega
de eventos, autorización, existencia runtime de claves ni seguridad de threads.
La variante fue validada con fixtures propios; su generalización a frameworks
externos sigue limitada. La [auditoría de Flask](structural-validation/web-frameworks/README.md)
identificó un presupuesto agotado, corregido al reordenar joins, y tres relaciones
que ahora cubre la variante adaptada: campo heredado, clave derivada y evidencia
de adaptación del handler. Registro mediante decorators, `Map.set`,
handlers objeto y conversiones de framework necesitan variantes adicionales.

## Invocación de callables producidos

El IR 1.11.0 distingue las dos llamadas de `adapt(handler)(request)`, que comparten
byte inicial pero tienen finales distintos. Antes podían colisionar en un único
ID. La relación `INVOKES_RESULT_OF` va de la invocación exterior a la llamada que
produce el callable, sin afirmar que éste sea idéntico a su argumento original.

```text
query adapted_invocation {
 call() as $invoke;
 require $invoke INVOKES_RESULT_OF $producer;
 emit $producer, $invoke;
}
```

Veintiuna regresiones cubren Python, JavaScript, TypeScript, Go, Rust, C++ y C#,
con/sin paréntesis, y distinguen esa estructura de `adapt(adapt(request))`.
El [probe de Flask](structural-validation/web-frameworks/flask-call-identity-after.json)
confirma identidades diferentes para ensure_sync y la invocación del resultado en
dispatch_request. Esa corrección de identidad por sí sola no resolvía la herencia
del registro ni la clave derivada; IR 1.23 agrega esas relaciones y la variante
adaptada. No demuestra forwarding o equivalencia sync/async.

## Retry con excepciones disponible

`resilience.exception-retry`, en un TOML propio y las colecciones `modern` y
`resilience`, relaciona un intento retornado desde el cuerpo de un try, un
manejador de ese mismo try y un `continue` que apunta al mismo bucle. Reconoce
esta forma en Python, JavaScript, TypeScript, Java, C# y C++, incluidos retornos
con await en Python/JS/TS. Hay 32 tests positivos, negativos y de contexto.

IR 1.46.0 añade una segunda variante: el handler puede terminar normalmente
y el try debe ser la última instrucción del cuerpo del bucle. Usa
`HANDLER_FALLTHROUGH` y `LOOP_BODY_TAIL`, con 107 pruebas adicionales de control
en seis lenguajes. Recupera `Retry.perform` y `RetryExponentialBackoff.perform`
en iluwatar. No acepta finally ni recursos en esta variante. Ver
[auditoría y límites](structural-validation/multilanguage/instruction-core.md).

```python
def fetch():
    while True:
        try:
            return request()
        except TransientError:
            continue
```

El ejemplo muestra la forma mínima detectable; no propone una política de retry
para producción. La consulta no prueba errores transitorios, límites, backoff,
idempotencia, alcanzabilidad ni cancelación. Un finally puede modificar la salida.
El [patrón Retry de Azure](https://learn.microsoft.com/en-us/azure/architecture/patterns/retry)
describe esas decisiones adicionales. No se confunde un `continue` de un bucle
anidado ni un retorno de una función interior con el intento exterior.

La [auditoría de Tenacity](structural-validation/web-frameworks/tenacity.md)
confirma una limitación real: no detecta su máquina de estados con resultado o
excepción almacenado y acciones DoAttempt/DoSleep. La variante ejecutable no
equivale a cobertura completa de retry.

También puede coincidir con fallback: Flask `_get_source_fast` prueba distintos
loaders. Es una coincidencia de la firma léxica, pero un falso positivo si se
interpreta como reintento de la misma operación sobre el mismo destino. Esa
distinción requiere correlacionar el destino entre iteraciones.

## Cache-aside con miss nulo y Optional

`architecture.cache-aside` correlaciona una lectura `get/Get`, su variable de
resultado, una comparación de esa variable con null/None, una carga usando la
misma clave y una escritura `set/put/Set` en la misma caché dentro del brazo de
ausencia. Desde IR 1.34.0, CFG, conteos de escrituras y orígenes de retorno
correlacionan ambos caminos y admiten aliases locales del retorno. Hay 55 tests originales en Python,
JavaScript, TypeScript, Java y C#, incluidos negativos por clave, caché o valor
distintos, escritura fuera del brazo, comparación inversa y funciones interiores.

```python
def fetch(cache, source, key):
    value = cache.get(key)
    if value is None:
        value = source.load(key)
        cache.set(key, value)
    return value
```

Se detecta una forma del camino de lectura de
[Cache-Aside](https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside).
Los nombres de API filtran candidatos; no prueban un contrato de caché o que el
loader acceda a persistencia. El miss nulo exige dos escrituras explícitas al
binding y estabilidad de clave/caché, con caminos CFG acotados. Admite orígenes
posibles en joins; no demuestra efectos ocultos ni factibilidad global. La
[matriz de 90 casos en cinco lenguajes](structural-validation/multilanguage/cache-aside-flow.md)
pasa de 55 FP/5 FN a 30 TP/60 TN sin errores en esa muestra. Se agregan 104 tests
del flujo y 26 del inventario, además de un ejemplo ejecutable de documentación.
TTL, invalidación, coherencia,
idempotencia, single-flight y concurrencia siguen fuera de esta variante.
El fichero TOML expone esas limitaciones junto con la consulta.

La [auditoría de iluwatar](structural-validation/web-frameworks/iluwatar-caching.md)
encontró un cache-aside con `Optional.or` y lambdas que ahora reconoce la variante
`architecture.cache-aside#java-optional`. La consulta pública une ésta y `#null-miss`
mediante consultas nombradas, conservando los mismos roles. Ambas están en el mismo
fichero TOML.

La variante Java usa un modelo acotado de
[java.util.Optional](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/Optional.html):
`ofNullable` establece el contenedor, `or` recibe el proveedor para ausencia,
`ifPresent` recibe el consumidor del valor cargado y `orElse(null)` finaliza la
cadena. El modelo exige import explícito sin colisiones locales; no aplica esas
reglas a clases homónimas ni miembros como `other.Optional`. No demuestra el
contrato del cache/store ni el código del classpath completo. Su evidencia de
asignaciones mantiene el modelo anterior sin orden temporal general: las garantías
de conteos y caminos incorporadas en null-miss no se aplican a Java Optional.

Hay 19 tests de esta variante, además de 14 de ownership/parametrización de lambdas
Java/C#/C++. La revisión externa confirma `findAside` con cacheStore, userId,
lectura, carga y escritura correlacionados; es un positivo revisado, no una medida
global de precisión. También quedan pendientes serialización, APIs async, sentinels no nulos,
escrituras indexadas y el retorno temprano en caso de hit. Los tests propios
verifican esta forma; no constituyen una medida de recall en aplicaciones reales.

## Unit of Work con cambios diferidos

`persistence.unit-of-work` agrega una séptima regla moderna. La variante
`keyed-change-set` relaciona registro de entidades por clave, escritura del lote
y un coordinador con al menos dos acciones de persistencia sobre el mismo store.
La operación pública `persistence.unit-of-work.keyed_flush` expone los helpers y
elementos procesados. Ambas consultas viven en el mismo TOML.

80 pruebas cubren Python/JS/TS/Java/C#; otras 16 ejercitan las relaciones de
iteración en ocho lenguajes. Se revisó un TP en iluwatar y se escanearon Flask,
RxJS y Commons IO sin candidatos adicionales de esta regla. No implica
transacciones atómicas: commit/rollback correlacionados siguen pendientes.
Ver [evidencia y límites](structural-validation/multilanguage/unit-of-work.md).

## Lotes de trabajo almacenados

IR 1.30.0 agrega una octava regla moderna: `architecture.batch-work-queue`, en
[su propio TOML](../src/ken/structural/modern_patterns/batch-work-queue.toml).
Relaciona un parámetro insertado en un campo de colección con otro método que
itera ese mismo campo, activa el elemento sin argumentos y vacía la colección
posteriormente en el mismo bloque. La activación puede estar envuelta en await.

La operación pública `architecture.batch-work-queue.drain` expone registro,
colección, consumidor, iteración, elemento, llamada y reset. La variante GoF
`command#queued-object` la reutiliza y añade el contrato o caller observado de la
implementación concreta, junto con su receiver retenido. Son consultas guardadas
que comparten el motor y las primitivas públicas.

La evidencia de vaciado es sintáctica: literal vacío con asignación simple o APIs
clear/Clear sin argumentos en Python/Java/C#. No prueba identidad de bibliotecas,
FIFO, progreso, éxito, atomicidad, exactamente una vez ni ausencia de reentrancia.
Una lista de listeners persistente sin reset se descarta; una suscripción one-shot
puede compartir la estructura. Arrays JavaScript con huecos como `[,,]` no cuentan
como literales vacíos.

Los [tests de uso](../tests/structural/test_queued_commands.py) cubren cinco lenguajes,
positivos y negativos cercanos, y los [tests del IR](../tests/structural/test_collection_lifecycle.py)
verifican orden, scopes, resets y argumentos. TaskScheduler del ejemplo externo
TypeScript se reconoce como lote de trabajo. Ver [auditoría](structural-validation/multilanguage/queued-command.md)
para hashes, roles, mediciones y límites. Pop/shift/take, canales, colas concurrentes,
closures encoladas y procesamiento sin reset explícito requieren otras variantes.

## Read-Through Cache con hit temprano

Desde IR 1.33.0 hay **nueve reglas modernas/web**. La nueva
`architecture.read-through-cache` detecta una clase con almacenamiento de caché
construido localmente y un método que retorna lookup en hit, o carga, escribe y
retorna en un camino de miss. La operación pública `.read_fill` expone el recorrido
sin afirmar ownership; permite componer búsquedas con otras consultas nombradas.

El IR incorpora TRUTH_TEST para predicados simples y un inventario positivo de
escrituras por método: UNREASSIGNED_BINDING, UNIQUE_BINDING_WRITE y
BINDING_WRITE_STATUS. La query usa CFG y RETURN_ORIGIN para ordenar y correlacionar
los eventos; no acepta asignaciones históricas como prueba del valor retornado.

Los tests de fuente cubren cinco lenguajes, renombrados, controles y rebindings,
argumentos expandidos y caché externa. La revisión de iluwatar confirma los
recorridos de CacheStore.readThrough y readThroughWithWriteBackPolicy; no prueba
la política adicional de write-back. Ver [contratos y ejemplos](design/structural/read-through-cache.md)
y [auditoría](structural-validation/multilanguage/read-through-cache.md).

## Trabajo pendiente y evidencia exigida

Estas variantes adicionales siguen pendientes:

| Familia | Evidencia positiva necesaria | Negativos y variantes |
|---|---|---|
| Middleware / interceptores | Registro en una cadena, continuación recibida y llamada o handler envuelto | Callback cualquiera; middleware terminal válido; Express/Koa, ASGI, Go net/http, filtros Java/C# |
| Repository / Data Mapper | Operaciones sobre entidades delegadas a persistencia con transformación de filas | Clase llamada Repository sin persistencia; DAO frente a colección en memoria |
| Unit of Work adicional | Variantes transaccionales, ORM, colecciones separadas y commit/rollback correlacionados | Métodos homónimos sin transacción; transacciones anidadas y async |
| MVC / capas de servicio | Enlace de rutas, controladores, servicio, modelo y representación | Inferencia sólo por nombres/directorios; endpoints que mezclan responsabilidades |
| CQRS | Caminos de lectura y escritura separados, dispatch y efectos modelados | Dos métodos get/set no prueban CQRS; proyecciones/eventos opcionales |
| Event bus / Pub-Sub | Registro, clave de evento, publicación y consumo correlacionados | Colecciones distintas; Observer local frente a broker externo |
| Cache-aside adicional | Otras cadenas Optional, hit con retorno temprano, sentinels, async, serialización e indexación | Claves o cachés distintas, retorno de datos anteriores a la carga |
| Retry / circuit breaker | Protocolos resultado/error, políticas de bibliotecas; estado de fallos y recuperación de circuit breaker | Fallback sobre destinos distintos; bucle cualquiera; backoff async frente a bloqueo |
| Idempotencia / outbox | Clave de deduplicación, efecto protegido; escritura atómica de dato y evento | Guardar una clave no prueba atomicidad; publicación previa al commit |

Los [contratos de middleware de Express](https://expressjs.com/en/guide/using-middleware/)
sirven como referencia inicial. Cada variante necesita modelos de APIs con
identidad resuelta, fuentes externas fijadas, positivos, negativos próximos y
límites publicados. No se declarará arquitectura completa a partir de una firma
local o una coincidencia por nombre.

En paralelo siguen abiertos los fallos GoF: protocolos C++/Rust/Go, relaciones
entre archivos, callbacks Strategy, derive Clone, Observer con mapas/snapshots,
Builder idiomático y discriminación entre copia y creación de sucesores.
