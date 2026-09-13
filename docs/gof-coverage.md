# Cobertura ejecutable de los 23 GoF

Estado comprobado con IR 1.47.0: 23 conceptos con query, 44 variantes ejecutables
y 33 variantes de diseño pendientes. Los diez detectores modernos/web se cuentan
por separado. La última [regresión externa](structural-validation/multilanguage/ir147-corpus-regression.json)
conserva 74 presencias esperadas en 281 ejemplos, sin cambios en matches ni
consultas incompletas respecto de 1.46. Tener una query no certifica cobertura de todas
las implementaciones del concepto ni convierte presencias de directorio en recall.

La suite completa de esta revisión pasa **7.257 tests**, con **149 expectativas
pendientes estrictas**; ese total incluye todo Ken, no sólo patrones. Mypy pasa
en 107 archivos y el wheel coincide con el motor escaneado. La
[continuación de catálogo y rendimiento](structural-validation/multilanguage/ir147-pipeline-review.md)
publica quince operaciones reutilizables, revisa los diez conceptos modernos y
comprueba caché e índices. Su auditoría focal del catálogo pasa 262 tests, incluido
un control agregado después de la colección de la suite completa.

IR 1.47.0 incorpora regiones para selección, cortocircuito e iteración al núcleo
de instrucciones y corrige siete consultas GoF. Los 23 conceptos tienen ahora un
[análisis del algoritmo](design/structural/algorithms/README.md), con invariantes,
variantes y pruebas de ruido/alteración. Sus 23 módulos suman 556 tests que pasan
y 149 pendientes; no equivalen a TP/TN globales. El corpus externo no gana cobertura
neta. Ver [auditoría y mediciones](structural-validation/multilanguage/gof-algorithm-review.md).

IR 1.46.0 inicia el núcleo de instrucciones: valores, bindings, memoria, regiones
y efectos. La matriz Builder tolera trabajo intermedio en seis lenguajes:
30 positivos y 18 negativos pasan con la query existente. Retry recupera dos
implementaciones Java externas mediante fallthrough. El buscador aún usa el grafo;
el rediseño no equivale a migración completa. Ver
[auditoría, resultados y límites](structural-validation/multilanguage/instruction-core.md).

IR 1.45.0 añade declaradores y valores iniciales de campos, separando operandos
explícitos, defaults por lenguaje y ausencia/unknown. Singleton lazy recupera
cuatro implementaciones Java y una C# con null implícito. Agrega 147 tests; la
matriz de 32 fuentes pasa de 2 TP/14 TN/2 FP/14 FN a 16 TP/16 TN. Los dos FP
corregidos son controles de declaraciones duplicadas, no programas compilados.
Ver [auditoría y rendimiento](structural-validation/multilanguage/field-initial-values.md).

IR 1.44.0 refuerza lazy-guarded con polaridad de nulidad y flujo directo de
escritura/retorno; añade `singleton.lazy_instance` y NULL_TEST bajo negaciones.
Agrega 222 tests y corrige 45 FP/cinco FN en 110 fuentes controladas de cinco
lenguajes. La matriz queda en 45 TP/65 TN sin errores; se documentan por separado
dos FN Java por inicialización null implícita. Hay nueve operaciones públicas.
Ver [auditoría y rendimiento](structural-validation/multilanguage/lazy-null-flow.md).

IR 1.43.0 distingue la instancia compartida de la variante eager de Singleton:
esta exige constructores explícitos de instancia privados y un único sitio de
creación resuelto. Agrega 90 tests y corrige 27 FP en 42 fuentes controladas,
conservando 15 TP. Elimina el FP canónico de RxJS y mantiene los tres ejemplos
Java revisados; la operación compartida y lazy conservan sus contratos.
Ver [auditoría y rendimiento](structural-validation/multilanguage/restricted-eager-singleton.md).

IR 1.42.0 añade expresiones de clase JS/TS, BASE_VALUE y valores bajo aserciones
TypeScript; incorpora el detector moderno `architecture.subclass-factory`.
Agrega 134 tests y revisa cuatro factories de producción de Lit, tres fixtures JS
y tres ejemplos Pandovski. Corrige dos FP/cuatro FN de atribución de Singleton
en doce candidatos controlados. RxJS expone una instancia compartida correcta
que sería FP si se interpretara como Singleton estricto; ese FP se corrige en
1.43. Ver [auditoría histórica](structural-validation/multilanguage/class-expression-factories.md).

IR 1.41.0 agrega Singleton `eager-shared` y la operación pública
`singleton.shared_instance`. Corrige la identidad de campos privados JS/TS y
el enlace de métodos static propios de receptores ya resueltos a clase en cuatro
lenguajes. Agrega 178 tests. La matriz de 56 fuentes recupera 24 FN y conserva
32 TN, sin errores en esa muestra. Se revisan tres TP estructurales externos,
incluido FileSystemProviders de Commons IO. RxJS conserva su match DI y mejora
la ubicación del campo #init. Ver [auditoría](structural-validation/multilanguage/eager-singleton.md).

IR 1.40.0 conserva CALLEE_VALUE al invocar identificadores, miembros o indexaciones
entre paréntesis. La regla moderna de inyección de dependencias incorpora una
variante funcional que reutiliza `strategy.supplied_policy`. La matriz de 98
fuentes pasa de 49 FN a 49 TP/49 TN sin errores en esa muestra. Se revisan cuatro
TP estructurales nuevos en Flask y RxJS, sin pérdidas en los escaneos comparados.
Agrega 210 tests, incluidos casos en ocho lenguajes contando interfaces funcionales
Java. La variante por objeto conserva su garantía más débil de escritura histórica.
Ver [auditoría y rendimiento](structural-validation/multilanguage/callable-dependency-injection.md).

IR 1.39.0 agrega FINAL_BINDING_INPUT/BINDING_FLOW_STATUS en ocho gramáticas y
la operación pública `strategy.supplied_policy`. Corrige Strategy para exigir
la última escritura fuente y un slot del contrato, preservando descriptores y
destinos runtime ambiguos con slot declarado. La matriz de 113 fuentes pasa de
46 FP a 45 TP/68 TN sin errores. Agrega 275 tests y corrige declaraciones sin
inicializador en seis gramáticas. Los cinco FP de intención C++ de 1.38 permanecen.
Commons IO completa dentro del presupuesto, con una pérdida por sobrecargas
sin resolver. Ver [auditoría y rendimiento](structural-validation/multilanguage/strategy-binding-inputs.md).

IR 1.38.0 incorpora inicializadores de constructor C++ y Command `retained-contract`,
con la operación pública `command.retained_dispatch`. Agrega 185 tests, incluidos
130 de Command en cinco lenguajes, 53 de inicializadores y dos ejemplos de la guía.
La matriz controlada de 120 fuentes recupera 20 FN: ahora tiene 20 TP/100 TN sin
errores. El corpus añade tres Commands y un Strategy correctos; aparecen cinco
FP de intención en la firma anterior de Strategy. Ver [auditoría y rendimiento](structural-validation/multilanguage/cpp-constructor-initializers.md).

IR 1.37.0 incorpora prototipos de métodos C++, firmas virtuales y parámetros con
cualificadores. Agrega 183 tests y recupera seis ejemplos de Abstract Factory,
Adapter, Factory Method, Interpreter, Template Method y Visitor. La matriz de
51 fixtures pasa de 6 FP/14 FN a 18 TP/33 TN sin errores. En el corpus hay 25
matches nuevos: 13 TP estructurales, 11 FP de intención y una ambigüedad.
Ver [auditoría y límites](structural-validation/multilanguage/cpp-method-contracts.md).

IR 1.36.0 conecta declaradores C++ con sus campos y conserva indirecciones,
cualificadores e inicializadores separados. Agrega 112 tests y recupera un Facade
estructural en el corpus, sin pérdidas; aparece un FP Decorator sobre una expresión
Interpreter. fmt expone una limitación de parsing con macros, sin evidencia de TN.
Ver [auditoría](structural-validation/multilanguage/cpp-field-declarators.md).

IR 1.35.0 incorpora Bridge refined-composition, raíces nominales explícitas y
la corrección de campos static/const de C#. Agrega 139 tests. Se revisaron cinco
TP nuevos en dos ejemplos Bridge y cuatro FP de intención en consumidores de
configuración. Los decoradores relacionados y la fábrica con un único subtipo
quedan fuera de la nueva variante. Ver [auditoría](structural-validation/multilanguage/refined-bridge.md).

IR 1.34.0 corrige Cache-Aside null-miss con conteos de escrituras por callable,
CFG y orígenes de retorno. Añade 131 tests y lleva la matriz controlada de 90
fuentes de 55 FP/5 FN a 30 TP/60 TN sin errores en esa muestra. El corpus y seis
escaneos externos no cambian. Ver [auditoría y rendimiento](structural-validation/multilanguage/cache-aside-flow.md).

IR 1.33.0 añade Read-Through Cache y su operación pública read_fill, con predicados
simples e inventarios positivos de escrituras. Se agregan 213 tests y se confirman
dos recorridos de una clase proveedora en iluwatar. Las coincidencias GoF y los
cinco proyectos de regresión permanecen estables. Ver [auditoría](structural-validation/multilanguage/read-through-cache.md).

IR 1.32.0 corrige la evidencia temporal de configuración de Builder: exige la
última escritura directa del parámetro, incorpora campos directos y cubre el pase
en ocho gramáticas. C++ conserva parámetros en retornos con punteros/referencias;
Go no confunde asignación múltiple con transferencia escalar. La matriz controlada
de 72 fuentes pasa de 33 FP/1 FN a cero; el corpus y cinco proyectos reales no
cambian. La ambigüedad Document/Memento permanece. Ver [auditoría](structural-validation/multilanguage/builder-input-writes.md).

IR 1.31.0 agrega Builder `stored-product` en seis lenguajes, con enlace nominal de
anotaciones Rust, inicializadores explícitos/shorthand y última escritura directa
a miembros. Reutiliza `prototype.derived_copy`. Se agregan 218 tests. log recupera
dos TP Builder y tres candidatos de copia Prototype; el corpus y los otros cuatro
proyectos no cambian. Ver [auditoría y rendimiento](structural-validation/multilanguage/stored-product-builder.md).

IR 1.30.0 agrega Command `queued-object` y una octava regla moderna, Batch Work
Queue. Ambas reutilizan la operación pública drain, con inserción/iteración/activación
y reset correlacionados. Se añaden 175 tests de análisis y un ejemplo ejecutable
de documentación. El corpus recupera tres comandos de TaskScheduler, un caso
esperado adicional, sin nuevos matches GoF fuera de ese caso. Ver [auditoría](structural-validation/multilanguage/queued-command.md).

Actualización IR 1.29.0: agrega State `context-transition` en cinco lenguajes, parámetros-propiedad
TypeScript y slots declarados de llamadas separados de destinos posibles. Se añaden
152 tests de análisis y un ejemplo de documentación. El corpus recupera State en
Order; también añade seis Adapters ambiguos en ejemplos State/Command y Strategy
sobre un callback de desconexión de RxJS. Se registran como problemas de intención,
no como mejoras de precisión. Ver [auditoría](structural-validation/multilanguage/state-context-transitions.md).

Actualización IR 1.28.0: agrega Memento `accessor-snapshot` en cinco lenguajes y bindings
correlacionados por llamada, argumento y parámetro. Se agregan 187 tests de
análisis y un ejemplo ejecutable de documentación. El corpus recupera Memento,
Strategy y Visitor TypeScript; también aparece una ambigüedad State/Strategy.
El FP Builder sobre Document sigue pendiente. Ver [auditoría y rendimiento](structural-validation/multilanguage/memento-accessors.md).

Actualización IR 1.27.0: conecta los orígenes de retorno con RETURNS_VALUE: Prototype y Builder
siguen construcciones devueltas mediante locales y aliases en ámbitos soportados.
Se agregan 115 tests y un ejemplo de documentación. El corpus conserva 54/281,
pero añade un **FP de Builder** sobre Document.save en un ejemplo Memento.
No se cuenta como mejora de cobertura; ver [auditoría](structural-validation/multilanguage/returned-query-values.md).

Actualización IR 1.26.0: Prototype agrega `field-copy` y 195 tests en cinco
lenguajes. Se revisaron dos TP nuevos: PreparedRequest en Requests y
MolecularSimulation en TypeScript. El segundo es la única coincidencia añadida
en el corpus; Requests es una validación independiente. Ver
[auditoría de copias](structural-validation/multilanguage/prototype-field-copy.md).

Actualización IR 1.25.0: Command distingue acciones y objetos retenidos, incluidos
cálculos puros. Se elimina el falso positivo de Requests y la evidencia de getter
de Cobra, conservando sus closures Command. Ver [auditoría](structural-validation/multilanguage/command-actions.md).

Actualización IR 1.22.0: Observer incorpora `snapshot-registry`, probado en Python,
JavaScript y TypeScript. La revisión de RxJS confirma tres clases y nueve llamadas
de notificación sobre copias del registro. Ver [snapshots de Observer](structural-validation/multilanguage/observer-snapshots.md).

Actualización IR 1.17.0: 34 variantes `ready` y 33 `design`. Command agrega
`stored-closure`, con 24 tests en cinco lenguajes y captura/asignación/invocación
correlacionadas. Cobra confirma cuatro closures RunE con out/noDesc capturados;
la firma anterior command-object aún tiene el testigo incorrecto de plantilla.
Ver [Command almacenado](structural-validation/multilanguage/cobra-stored-command.md).

Composite incorpora
`recursive-nominal`, con 22 tests en Go, Python, Java, TypeScript y C#. Correlaciona
una colección del propio tipo con una llamada a la misma operación sobre el hijo
iterado. Cobra confirma tres recorridos de su árbol de comandos; la revisión
también documentó evidencia incorrectamente clasificada como Command.
Ver [auditoría de Cobra](structural-validation/multilanguage/cobra-composite.md).

Cada concepto tiene una consulta KenQL en un archivo TOML separado. Las rutas por
defecto `patterns`, el ID corto y `gof.<id>` usan estas consultas. La firma anterior
sigue disponible únicamente como `legacy.gof.<id>` para comparación explícita.

**23/23 conceptos con tests de código fuente en Python, Java y TypeScript.**
Por cada combinación hay un positivo, un positivo con clases renombradas, un negativo
que sólo contiene el nombre del patrón y un negativo con una conducta esencial
eliminada: 276 casos. No se ejecutan los programas ni se afirma validación del
compilador de esos lenguajes: son fixtures de parsing, IR y búsqueda de extremo a extremo.

Los lenguajes usan formas distintas: protocolos dinámicos y anotaciones en Python,
interfaces/clases abstractas y colecciones tipadas en Java, interfaces, callbacks y
`yield*` en TypeScript. Otros tests ejercitan generadores async, C# `yield return`,
callbacks JS, aliases de `contextlib`, constructores explícitos y receptores compartidos.
Los tests anteriores de compatibilidad cubren además gramáticas C++, Go y Rust;
no certifican los 23 detectores nuevos en esos lenguajes.

| Patrón | Variantes ejecutables | Evidencia exigida |
|---|---|---|
| [Abstract Factory](../src/ken/structural/patterns/abstract-factory.toml) | `nominal-families` | Dos slots sobrescritos construyen productos de familias distintas. |
| [Adapter](../src/ken/structural/patterns/adapter.toml) | `object-adapter` | Implementa un contrato y delega a otro tipo mediante un slot de nombre distinto. |
| [Bridge](../src/ken/structural/patterns/bridge.toml) | `runtime-composition`, `refined-composition` | Delegación en base o derivada; la segunda exige otro subtipo de abstracción y dos implementaciones, con raíces nominales distintas y campo de instancia. |
| [Builder](../src/ken/structural/patterns/builder.toml) | `mutable-product`, `director`, `stored-product` | Estado usado al construir el producto retornado; director que coordina pasos; o producto construido internamente, configurado por miembros y retornado directamente/por copia derivada Rust. |
| [Chain of Responsibility](../src/ken/structural/patterns/chain-of-responsibility.toml) | `linked-handlers` | Un handler sobrescribe un slot y reenvía condicionalmente a otro handler del mismo contrato. |
| [Command](../src/ken/structural/patterns/command.toml) | `retained-contract`, `command-object`, `stored-closure`, `retained-object`, `queued-object` | Acción delegada, closure capturada u objeto retenido; la variante encolada conecta registro, contrato, activación iterada y reset posterior del lote. |
| [Composite](../src/ken/structural/patterns/composite.toml) | `recursive-contract`, `recursive-nominal` | Un componente sobrescribe una operación y recorre hijos tipados con el contrato del componente. |
| [Decorator](../src/ken/structural/patterns/decorator.toml) | `object-wrapper` | Implementa el contrato del objeto envuelto, reenvía el mismo slot y añade otra llamada. |
| [Facade](../src/ken/structural/patterns/facade.toml) | `object-surface` | Una operación coordina dos campos de tipos de servicio distintos. |
| [Factory Method](../src/ken/structural/patterns/factory-method.toml) | `virtual-slot` | Un slot sobrescrito retorna un objeto construido. |
| [Flyweight](../src/ken/structural/patterns/flyweight.toml) | `explicit-interning` | Una consulta de un pool inserta y retorna elementos; el producto se construye usando la clave recibida. |
| [Interpreter](../src/ken/structural/patterns/interpreter.toml) | `expression-objects` | Una expresión delega al mismo slot de una expresión hija pasando el contexto recibido. |
| [Iterator](../src/ken/structural/patterns/iterator.toml) | `external-cursor`, `generator`, `delegated-generator`, `explicit-cursor`, `paired-cursor`, `delegated-cursor` | Suspensión generadora, protocolo Python con estado/delegación, o next/hasNext con cursor compartido. |
| [Mediator](../src/ken/structural/patterns/mediator.toml) | `direct-colleagues` | Dos tipos de colegas llaman al coordinador y éste delega operaciones en ambos tipos. |
| [Memento](../src/ken/structural/patterns/memento.toml) | `accessor-snapshot`, `snapshot-object` | Acceso directo o getter con constructor correlacionado; restauración al mismo campo a través de tipo concreto, contrato nominal o caller observado. El modelo de accessors es lineal y no prueba pureza ni deep copy. |
| [Observer](../src/ken/structural/patterns/observer.toml) | `listener-registry`, `map-key-registry`, `snapshot-registry` | Una operación registra un parámetro en la misma colección recorrida para notificar métodos o callbacks. |
| [Prototype](../src/ken/structural/patterns/prototype.toml) | `field-copy`, `derived-clone`, `explicit-copy` | Clone derivado Rust invocado, construcción desde estado, o copia directa de campos a una asignación del mismo tipo que alcanza un retorno. |
| [Proxy](../src/ken/structural/patterns/proxy.toml) | `guarded-access` | Sobrescribe el contrato del objeto representado y reenvía el mismo slot bajo una condición. |
| [Singleton](../src/ken/structural/patterns/singleton.toml) | `eager-shared`, `lazy-guarded` | Construcción lazy guardada o inicialización de campo estático con su propia clase y accessor directo; no prueba unicidad global. |
| [State](../src/ken/structural/patterns/state.toml) | `state-object`, `context-transition` | Una operación delega en estado tipado y una transición no constructora almacena una nueva implementación. |
| [Strategy](../src/ken/structural/patterns/strategy.toml) | `strategy-object`, `strategy-callable` | Un parámetro inyecta una estrategia almacenada; se delega en ella y existen dos implementaciones de su contrato. |
| [Template Method](../src/ken/structural/patterns/template-method.toml) | `virtual-skeleton` | Una operación base llama otro slot que una subclase sobrescribe. |
| [Visitor](../src/ken/structural/patterns/visitor.toml) | `named-dispatch` | accept pasa su receptor al método resuelto del visitante; el parámetro del visitante tiene el tipo del elemento. |

## Alcance de las afirmaciones

Hay 44 variantes ejecutables y 33 variantes de diseño pendientes. «Los 23 patrones
implementados» significa cobertura de los 23 conceptos mediante las consultas y
formas de la tabla, no todas las implementaciones posibles de cada concepto.

Las colaboraciones estructurales pueden compartir forma e intención distinta:
un método de comprobación que devuelve un resultado puede parecer Factory Method,
un objeto mutable que convierte estado en otro objeto puede parecer Builder y
un cache de objetos puede parecer Flyweight. Los resultados necesitan revisión
antes de clasificarlos como decisiones de diseño. No se publica una precisión global
GoF basada en fixtures seleccionadas.

Las variantes futuras (typestate y movimientos Rust, buses de eventos, eventos C#,
ADT, protocolos estructurales Go, etc.) conservan `status = "design"`; no se presentan
como implementadas. Los tests de ausencias conocidas ya corregidas están en
`tests/structural/test_real_world_gaps.py`, sin xfail.

## Nuevos hechos de IR y límites

- `MEMBER_OF`: base de un acceso a miembro; permite vincular restauración con el snapshot.
- `INSERTS_INTO` / `INSERTED_VALUE`: inserción mediante APIs comunes (`append`, `add`,
  `push`, `push_back`, `Add`); el modelo representa forma de API, no prueba del comportamiento
  de un método de usuario con ese nombre.
- `ITERATES_CALLS`: conserva también la colección de un callback invocado directamente.
- `ADVANCES_ITERATOR`: llamada al builtin Python `next` sin binding léxico que lo oculte.
- `context_manager`: decorador importado de contextlib, con aliases locales; se evita
  aplicar el modelo si su nombre está redefinido. No resuelve reexports arbitrarios.
- `arity`: cantidad de parámetros explícitos, excluyendo receptor; desconocida ante
  diagnósticos de análisis. Incluye un parámetro variádico como tal, no cero argumentos.

La etapa IR 1.17.0 ya conservaba funciones locales C#, literales Go/JS y `INDEX` de
escrituras indexadas y `ITERATES_KEYS_CALLS` para el primer binding de `range` Go.
La variante Observer `map-key-registry` exige un campo de tipo mapa, escritura
con el listener recibido como clave y notificación sobre claves del mismo mapa.
No equipara las claves con los valores ni prueba el ciclo completo de suscripción.
Los impls Rust conservan su propietario nominal al incluir parámetros de tipo,
lifetime o const; no se asocian rutas calificadas externas por coincidencia del
nombre final. Esto repara la pérdida de métodos en RecordBuilder y MetadataBuilder
de rust-lang/log. IR 1.31.0 añade la variante Builder de producto almacenado y
recupera ambos tipos; las anotaciones con lifetime conservan el tipo nativo al enlazarlo.
La variante Iterator `external-cursor` cubre el protocolo C++ next/isDone/currentItem
con un campo de posición compartido. Se conservan lecturas/escrituras sintácticas
de incremento y decremento, y se declaran campos C++ antes de analizar métodos.
No se demuestra terminación ni el efecto runtime de operadores sobrecargados.
`strategy#strategy-callable` reconoce una función recibida, almacenada en un campo
y llamada desde otro método, sin exigir subtipos nominales. Hay pruebas Python,
JavaScript, TypeScript y Go. `CALLEE_VALUE` conserva también el acceso a miembro
invocado; no certifica valores runtime ni el comportamiento de descriptors.
La búsqueda reordena sólo joins positivos adyacentes; no cruza barreras de negación,
agregados o consultas dependientes. El enlace de argumentos ahora usa índice por callsite.

Consultar también el [informe sobre repositorios reales](structural-validation/2026-09-12/canonical.md).

La [validación externa ampliada](structural-validation/labelled-corpus-v2/README.md)
obtuvo matches de la etiqueta esperada en 38 de 281 ejemplos independientes.
Esto muestra límites importantes de generalización de los fixtures, especialmente
en C++, Go, Rust y colaboraciones entre archivos. No es una medida de precisión.
La ampliación a [patrones modernos y web](modern-patterns.md) está en curso.

El [reescaneo con IR 1.8.0](structural-validation/labelled-corpus-v3/README.md)
alcanza 44 de los mismos 281 ejemplos, sin perder los 38 anteriores. También
revela un nuevo falso positivo Builder sobre un snapshot Memento y tres
clasificaciones ambiguas; se conservan como problemas de precisión pendientes.

El [reescaneo v4](structural-validation/labelled-corpus-v4/README.md) alcanza 52 de
281 tras resolver tipos Java entre archivos mediante paquetes, imports explícitos
y nombres calificados. Wildcards, tipos anidados importados y classpath externo
siguen pendientes. Las cifras son presencia de etiquetas esperadas, no precisión.

La variante mutable Builder ahora exige configuración directa desde un parámetro
del paso, además de construcción desde ese campo. Esto elimina el falso positivo
del lector de bloques de Commons IO. Los constructores C++ se excluyen como pasos.
El [reescaneo v5](structural-validation/labelled-corpus-v5/README.md) conserva los
52 positivos etiquetados; snapshots mutables y otras ambigüedades siguen pendientes.

Prototype incorpora `derived-clone` para structs Rust con `#[derive(Clone)]` y una
invocación clone sobre una instancia de ese tipo sin destino explícito resuelto.
`DERIVE_NAME` preserva el nombre escrito, no la expansión de macros. El selector
de llamadas `resolution` distingue `resolved`, `ambiguous` y `unresolved` respecto
de los destinos explícitos conocidos. No significa que se haya resuelto un builtin.
Nueve regresiones cubren atributos múltiples, comentarios, receptores diferentes,
ausencia de llamada, cfg_attr y un método clone explícito que no debe confundirse
con el derivado. No se afirma copia profunda ni se resuelven derives importados.
La [documentación de Clone](https://doc.rust-lang.org/std/clone/trait.Clone.html)
explica que campos como Arc pueden conservar datos compartidos al clonar.
