# Declaraciones de métodos C++ y firmas virtuales — IR 1.37.0

## Qué cambió

Los prototipos de miembros C++ ahora tienen identidad de callable, parámetros y
contrato nominal de clase. Se conservan sobrecargas por ubicación, modificadores,
cualificadores cv/ref, tipos abstractos de parámetros y retorno, defaults y
parámetros sin nombre. Un callback sigue siendo
un campo; un pure-specifier `= 0` no es una asignación de ejecución.

Antes, OVERRIDES relacionaba métodos C++ por nombre. Ahora requiere una firma
soportada compatible y virtualidad explícita o heredada en la cadena nominal
resuelta. Los métodos no virtuales que ocultan nombres y las sobrecargas de otros
parámetros no adquieren un enlace de override. METHOD_SIGNATURE_STATUS distingue
firmas comparables y no disponibles; VIRTUAL_METHOD expone los slots establecidos.
No se infiere ejecución para un método sin cuerpo ni se resuelve una sobrecarga
de llamada con esta comparación. [Contrato y límites](../../design/structural/cpp-method-contracts.md).

La corrección de parámetros también quita sólo su identificador del declarador:
`Context *const context` conserva el nombre context y su tipo completo. Antes,
parte del declarador podía convertirse en el nombre de la variable y romper la
correlación de argumentos con el parámetro formal. TYPE_HEAD conserva receptores
nominales simples sin convertir arrays o doble indirección en tipos escalares.

## Matriz controlada

Se compararon las mismas 51 fuentes de Abstract Factory, Adapter, Factory Method,
Interpreter y Template Method contra el wheel IR 1.36 y el motor IR 1.37.
Las fuentes incluyen contratos sin cuerpo y definiciones inline, renombrado y
mutaciones de virtualidad, parámetros, cualificadores y conducta esencial.

| Versión | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| IR 1.36.0 | 4 | 27 | 6 | 14 |
| IR 1.37.0 | 18 | 33 | 0 | 0 |

[Referencia](cpp-method-patterns-before.json), [resultado](cpp-method-patterns-after.json).
Es una matriz de esos fixtures estructurales, no una estimación de precisión ni
recall de proyectos arbitrarios. Los seis FP anteriores dependen del enlace por
nombre de definiciones inline: cuatro sobrecargas/cualificadores incompatibles
y dos ocultamientos no virtuales.

Se agregan 182 tests de contratos y patrones C++, más un ejemplo KenQL en la guía.
Los contratos incluyen firmas const/volatile/ref, virtualidad transitiva, defaults,
arrays ajustados en firmas, campos callback, parámetros anónimos, tipos locales
homónimos, templates no soportados y acceso a la evidencia mediante KenQL.
Visitor agrega 12 casos con parámetros const y referencias, renombrado, falta de
self, tipo ajeno, falta de despacho y sobrecargas ambiguas. Sus casos se verifican
por separado y no se suman a la matriz histórica de 51 fuentes.

La [verificación final](ir137-checks.json) pasa **4.268 tests en 168,52 s**,
incluyendo el resto de Ken y las regresiones en los otros lenguajes. Mypy pasa
en 100 archivos. Se comprobaron todos los módulos y TOML del wheel contra los
hashes del motor; fuera del checkout se verificaron Factory Method positivo,
exclusión por sobrecarga, campos callback, doble indirección y roundtrip del IR.
Los 26 ejemplos KenQL de las guías operativas parsean; los 22 de la guía IR se
ejecutan contra fuentes en la suite. IR_VERSION cambia e invalida las entradas
de caché con la semántica anterior.

## Corpus abierto y revisión de cada cambio

La [comparación reproducible](ir137-corpus-regression.json) conserva commits,
archivos y hashes del corpus anterior. Las presencias de etiqueta esperada suben
de 62 a **68 entre 281 ejemplos**. Las etiquetas vienen de directorios upstream;
no convierten cada ausencia en FN ni cada coincidencia en TP. Se revisaron las
25 coincidencias agregadas: **13 TP estructurales, 11 FP de intención y una
ambigüedad**. No hay pérdidas de matches ni consultas incompletas.

| Fuente / unidades nuevas | Evaluación y causa |
|---|---|
| cpp-patterns/abstract-factory: ConcreteFactoryX/Y, dos Abstract Factory y cuatro Factory Method | TP: slots virtuales crean productos de dos familias distintas. Las fábricas específicas también contienen métodos fábrica. |
| cpp-patterns/adapter/ObjectAdapter.cpp: Adapter | TP: request implementa Target y delega a specificRequest del adaptee. El ejemplo tiene un puntero inicializado con (), por lo que no se certifica seguridad al ejecutarlo. |
| cpp-patterns/factory-method: dos métodos de ConcreteCreator | TP: implementan slots de Creator y retornan nuevas instancias de productos concretos. |
| cpp-patterns/interpreter: NonterminalExpression | TP: reenvía el mismo parámetro context a los hijos y combina los resultados. La normalización de `Context *const context` recupera esa identidad. El FP Decorator anterior permanece. |
| cpp-patterns/template-method: AbstractClass | TP: templateMethod llama hooks virtuales implementados en ConcreteClass. |
| cpp-patterns/visitor: ConcreteElementA/B | TP: accept recibe Visitor por referencia y pasa this a la operación con parámetro del tipo del elemento. Los nombres de visita son distintos; no se resolvió despacho por overload. |
| cpp-patterns/bridge: RefinedAbstraction, señalado como Adapter | FP de intención: la delegación entre las dos familias cumple la firma débil de Adapter. Bridge sigue sin detectar este ejemplo porque exige otro refinamiento de la abstracción observado. |
| cpp-patterns/command: ConcreteCommand; Pandovski Command: FlipUpCommand/FlipDownCommand, señalados como Adapter | Tres FP de intención: envolver acciones y delegarlas a un receptor también cumple el cambio de nombre de método exigido por Adapter. Faltan discriminantes de uso como comando. |
| cpp-patterns/iterator: ConcreteIterator; Pandovski Iterator: ListIterator, señalados como Adapter | Dos FP de intención: las operaciones del cursor consultan el agregado mediante una API con nombres distintos. Esa delegación no distingue adaptación de recorrido. |
| cpp-patterns/prototype: ConcretePrototypeA/B, señalados como Factory Method | Dos FP de intención: clone sobrescribe un slot y construye una instancia de su propia clase. La regla no separa ese papel del de un creador de productos. |
| Pandovski Interpreter: Plus/Minus; Builder: Cook, señalados como Strategy | Tres FP de intención: hijos de expresión y pasos de construcción son colaboradores polimórficos inyectados. La firma no establece intención de algoritmo intercambiable. |
| cpp-patterns/state: Context, señalado como Strategy | Ambiguo: el cliente sustituye externamente el estado y Context delega handle. No hay transición interna; su estructura también es compatible con Strategy. |

Los [testigos](cpp-method-contract-witnesses.json) conservan roles, hechos, firmas,
ubicaciones y hashes para cada alcance cambiado. Los IDs de clase Visitor toman
la ubicación de la primera declaración adelantada (líneas 14/15), aunque las
implementaciones de accept estén más abajo. Mejorar la ubicación principal de
tipos con varias declaraciones queda anotado como problema de presentación.

## Regresión en bibliotecas reales

[Requests](ir137-requests.json), [Flask](ir137-flask.json), [RxJS](ir137-rxjs.json),
[Commons IO](ir137-commons-io.json), [log](ir137-rust-log.json) e
[iluwatar caching](ir137-iluwatar-caching.json) conservan sus fuentes y coincidencias
en los alcances previamente medidos: 19, 24, 123, 277, nueve y 14 archivos.
Las consultas terminan dentro de sus presupuestos.

[fmt](ir137-fmt.json) mantiene cero matches y 677 diagnósticos en 16 cabeceras,
usando el mismo override explícito .h→cpp en el runner. No se expanden macros:
esto sigue siendo un bloqueo de cobertura semántica, no evidencia de TN.
No se compiló ni ejecutó código de ninguno de los proyectos analizados.

## Rendimiento

Las [mediciones](cpp-method-contracts-performance.json) usan cinco archivos
individuales del corpus: 30 consultas por regla después de warmup sobre índice y
registro precalculados; diez muestras separadas de parseo/enlace y de proyección.
Se ejecutaron las dos versiones secuencialmente al terminar los otros trabajos.

| Regla | Consulta 1.36, mediana ms | Consulta 1.37, mediana ms | Parseo/enlace 1.37, mediana ms |
|---|---:|---:|---:|
| Abstract Factory | 0,038 | 0,170 | 10,247 |
| Adapter | 0,038 | 0,080 | 3,578 |
| Factory Method | 0,018 | 0,036 | 7,764 |
| Interpreter | 0,132 | 0,171 | 11,092 |
| Template Method | 0,019 | 0,042 | 3,637 |

La versión anterior devolvía cero matches en esas consultas; la nueva completa
las búsquedas y produce los matches revisados. El trabajo adicional tiene un
costo medido, no una mejora de velocidad. Los p95 y tiempos de proyección están
en el JSON. Son observaciones del host sobre esos archivos, sin caché persistente,
y no representan latencia de CLI, rendimiento global ni un benchmark de memoria.
El límite de caché sigue siendo configurable, con 500 MB decimales por defecto.

## Pendientes

No están resueltos namespaces/aliases C++ completos, firma de destructores,
sustitución de templates, punteros a función en firmas, validación de covarianza,
noexcept/final/deleted, fusión de definiciones fuera de clase ni inicializadores
de constructor. La firma sólo compara tipos primitivos modelados y nominales
locales resueltos: algunas grafías primitivas compuestas quedan fuera.

En clases template, la comparación de firma está deshabilitada. La resolución
nominal general anterior todavía puede confundir un parámetro de template con
un tipo global homónimo; el estado de firma evita OVERRIDES por esa coincidencia,
pero no debe interpretarse como una solución del enlace genérico de TYPE.
La siguiente revisión de precisión debe distinguir usos Adapter/Command/Iterator,
Strategy/expresiones y Factory Method/Prototype con evidencia de comportamiento,
sin excluirlos por nombres de clases o carpetas.
