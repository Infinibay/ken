# Corpus externo etiquetado: segunda delimitación

Fecha: 2026-09-12. Se escanearon **281 ejemplos, 736 archivos únicos dentro de cada repositorio**, con las 23 consultas GoF canónicas. **38 ejemplos produjeron al menos un match del patrón etiquetado por upstream**. No es una medida de precisión: falta revisar cada rol; tampoco los 243 restantes son automáticamente falsos negativos. Cinco ejemplos tienen diagnósticos de parsing. Todas las consultas terminaron dentro del presupuesto; no hubo excepciones del runner.

| Repositorio | Ejemplos | Etiqueta encontrada | Archivos |
|---|---:|---:|---:|
| [across-languages](https://github.com/Eng-Elias/design-patterns-across-languages) | 69 | 17 | 174 |
| [cpp-patterns](https://github.com/JakubVojvoda/design-patterns-cpp) | 24 | 0 | 24 |
| [python-patterns](https://github.com/faif/python-patterns) | 22 | 5 | 22 |
| [java-patterns](https://github.com/iluwatar/java-design-patterns) | 23 | 1 | 174 |
| [guru-rust](https://github.com/RefactoringGuru/design-patterns-rust) | 31 | 1 | 107 |
| [pandovski](https://github.com/ZoranPandovski/design-patterns) | 110 | 14 | 233 |
| [go-patterns](https://github.com/tmrts/go-patterns) | 2 | 0 | 2 |
| [php-patterns](https://github.com/DesignPatternsPHP/DesignPatternsPHP) | 0 | 0 | 0 |
| [swift-patterns](https://github.com/ochococo/Design-Patterns-In-Swift) | 0 | 0 | 0 |

## Reproducción y límites

El [manifest](manifest.json) fija commits, hashes del motor, presupuesto, inventario y licencias localizadas. Los JSON por repositorio contienen hashes de fuentes, scopes, roles con líneas y outcomes de todas las consultas. Las copias temporales están en `/tmp/ken-pattern-corpus`; no se ejecutó código externo ni se incorporaron fuentes externas a Ken.

Comando: `.venv/bin/python examples/bench/validate_pattern_corpus.py --corpus /tmp/ken-pattern-corpus --output /tmp/ken-pattern-results`.

- Cada ejemplo tiene un grafo independiente. Across-languages se divide por escenario y lenguaje; Java sólo incluye src/main/java de los 23 directorios GoF; Pandovski sólo ejemplos planos para evitar unir implementaciones alternativas.
- Rust se divide por binario Cargo y agrega dependencias locales declaradas. Las bibliotecas no cuentan como ejemplos independientes. La primera exploración en `../labelled-corpus` tenía 284 unidades: incluía tres bibliotecas de Abstract Factory como ejemplos y omitía sus relaciones con las aplicaciones. Esa cifra preliminar queda sustituida por esta delimitación.
- Los 24 casos C++ incluyen variantes bajo los directorios etiquetados; no significan 24 patrones distintos. Las etiquetas provienen de rutas upstream, no de buscar palabras en el código.
- PHP y Swift fueron descargados e inventariados, pero sus frontends estructurales no existen. No se cuentan como misses. Tmrts contiene principalmente Markdown: aquí sólo se escanearon sus dos programas Go etiquetados GoF, no se extrajeron bloques de documentación.
- No se compiló el corpus. No se afirma precisión global, cobertura de todos los lenguajes ni análisis exhaustivo de todos los archivos descargados.

## Problemas y siguientes regresiones

| ID | Evidencia revisada | Observación y causa posible | Próxima prueba |
|---|---|---|---|
| CORPUS-01 | [guru-rust: creational/prototype/main.rs](https://github.com/RefactoringGuru/design-patterns-rust/blob/f4a1499d13e8b27fa75e4e8ff9fd9bed645d23ca/creational/prototype/main.rs) | Prototype no detectado. Usa derive(Clone) y una llamada clone; no hay cuerpo explícito de copia. Falta un modelo de derive que conserve la distinción entre copia y alias. | Derive Clone positivo; método homónimo sin contrato negativo; Arc::clone no debe inferir copia profunda. |
| CORPUS-02 | [python-patterns: patterns/behavioral/strategy.py](https://github.com/faif/python-patterns/blob/47f7390d01f5d69a15fba915fb50e257b13d7864/patterns/behavioral/strategy.py) | Strategy no detectado. El algoritmo es un Callable almacenado, validado mediante descriptor; la variante lista requiere subtipos nominales. El descriptor agrega resolución dinámica que necesita evidencia separada. | Inyección de función y consumo; callback no almacenado y descriptor que transforma/rechaza la función. |
| CORPUS-03 | [cpp-patterns: iterator/Iterator.cpp](https://github.com/JakubVojvoda/design-patterns-cpp/blob/4fae40666a970dc4c7901df54964d6ebcd80ba5c/iterator/Iterator.cpp) | Iterator no detectado. Protocolo first/next/isDone/currentItem con índice compartido. La variante pareada sólo consulta next/hasNext, y hay límites de declaraciones y métodos C++ fuera de clase. | Cursor con protocolo C++ y estado correlacionado; homónimos sin avance negativos. |
| CORPUS-04 | [go-patterns: behavioral/observer/main.go](https://github.com/tmrts/go-patterns/blob/f978e420361704bd7531e2b57905a308a3a012c8/behavioral/observer/main.go) | Observer no detectado. Registro en claves de map[Observer]struct{} y notificación mediante range. La query requiere INSERTS_INTO de una llamada de inserción; no representa este registro por asignación indexada. | Registro por clave y notificación por la misma clave; iterar valores o un mapa distinto negativos. |
| CORPUS-05 | [guru-rust: creational/builder/builders/car.rs](https://github.com/RefactoringGuru/design-patterns-rust/blob/f4a1499d13e8b27fa75e4e8ff9fd9bed645d23ca/creational/builder/builders/car.rs) | Builder Rust continúa pendiente: tipos asociados, impl y composición entre archivos necesitan resolución adicional. Esta ruta debe verificarse antes de convertirla en fixture. | Impl genérico, associated OutputType, construcción por fases y negativo fluent sin producto. |

Estos son casos abiertos con observación de código y posibles causas; no una auditoría manual de los 281 ejemplos. Matches de otras consultas no se etiquetan automáticamente como falsos positivos: patrones distintos pueden coexistir.

## Corrección contrastada en producción

CS-01 del [informe anterior](../multilanguage/problemas.md): se reconocen las funciones locales C# como callables independientes. El reescaneo de Serilog produce Iterator en MapToDictionaryElements (189), MapToSequenceElements (238) y Tokenize (48); elimina TryConvertEnumerable. Evidencia: [serilog-local-functions.json](serilog-local-functions.json). Persisten los problemas de parsing condicionado y otros casos abiertos del informe anterior.

## Otros recursos solicitados

### Corrección posterior: CORPUS-04

La variante `observer#map-key-registry` ahora detecta `eventNotifier` en el mismo
commit de tmrts/go-patterns, sin cambiar el ejemplo. El
[reescaneo](go-map-observer-after.json) conserva hashes y roles. Se agregaron seis
tests: positivo con renombrado y negativos por invocación del valor, mapa distinto,
registro en otro mapa, eliminación y lookup sin escritura. La tabla inicial sigue
siendo la línea base anterior a esta corrección; no se recalculó todo el corpus.
Los nuevos hechos conservan la escritura indexada y la invocación del primer
binding de range por separado. La consulta exige que el contenedor sea un mapa.

### Referencias

### Corrección posterior: CORPUS-02

`strategy#strategy-callable` encuentra Order en el ejemplo Python original, que
almacena e invoca el algoritmo de descuentos recibido. El
[reescaneo](python-callable-strategy-after.json) registra la evidencia y el commit.
Dieciséis tests cubren Python, JavaScript, TypeScript y Go, renombrado y negativos
por llamada a otro campo, lectura sin invocación y almacenamiento en otro campo.
La interpretación del descriptor DiscountStrategyValidator sigue fuera del modelo:
el match demuestra la forma de asignación/invocación, no su equivalencia runtime.

### Corrección posterior: CORPUS-03

`iterator#external-cursor` detecta ConcreteIterator en el ejemplo C++ original.
El [reescaneo](cpp-iterator-after.json) conserva el commit y los roles.
El IR 1.6.0 reconoce actualizaciones ++/-- y declara campos antes de analizar
los cuerpos, incluyendo campos escritos después de los métodos en el archivo.
Trece regresiones contrastan incremento/decremento prefijo y sufijo, orden de
declaración, lectura sin avance, campos diferentes y una variable local homónima.
El scope local sigue siendo de función: no se afirma resolución completa de
shadowing entre bloques C++ ni semántica de operadores sobrecargados.

### Corrección posterior: RUST-01 del corpus de producción

El IR 1.5.1 resuelve el propietario nominal de `impl Store<T>`, incluyendo lifetimes
y parámetros const, sin eliminar calificadores de rutas externas. Nueve pruebas
cubren esas formas, declaraciones posteriores al impl y un tipo externo homónimo.
El [probe sobre rust-lang/log](rust-generic-impl-after.json) recupera 13 métodos en
RecordBuilder y cinco en MetadataBuilder, frente a cero en el informe original.
Esto corrige la asociación de métodos; no resuelve todavía RUST-02 (Builder con
producto almacenado, campos anidados y finalización por clone).

- [Refactoring Guru Rust](https://refactoring.guru/design-patterns/rust) y [Go](https://refactoring.guru/design-patterns/go): catálogos consultados; Rust se escaneó desde el repositorio oficial. Go se contrastó con programas descargados de otros autores; no se presenta como escaneo de los ejemplos de la web.
- [Otros lenguajes de Guru](https://refactoring.guru/design-patterns/examples): C#, C++, Go, Java, PHP, Python, Ruby, Rust, Swift y TypeScript. Ruby, PHP y Swift aún quedan fuera del frontend estructural. El Builder Rust distingue fluent interface de construcción GoF, una distinción que nuestras reglas deben conservar.
- [Awesome Design Patterns](https://github.com/DovAmir/awesome-design-patterns): índice de recursos para ampliar el corpus, no un conjunto independiente de programas ya escaneados.
- [Agentic Design Patterns](https://github.com/xindoo/agentic-design-patterns): material sobre sistemas de agentes; taxonomía distinta de GoF y de patrones web. Se revisó como referencia, sin contar el libro como código analizado.

La incorporación permanente de ejemplos externos deberá respetar la licencia de cada fuente. Por ahora los reportes conservan referencias y hashes, no copias del código.
