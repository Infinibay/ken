# Auditoría adversarial del catálogo GoF y moderno — 14 de septiembre de 2026

> **Baseline histórico IR 1.76.** Los problemas medidos aquí se conservaron como
> evidencia. Las correcciones y el estado actual están en
> [el reporte IR 1.77](../catalog-corrections-2026-09-14/README.md).

**Ampliación final del corpus.** La [matriz verificable](COVERAGE.md) incorpora **2.060 casos** (cinco por cada una de **412 combinaciones declaradas de variante/lenguaje**), más los **252 casos dirigidos** descritos aquí. Las **90 variantes ready** y los tres roots sin variantes tienen al menos un control positivo detectado; tres celdas concretas de lenguaje todavía fallan su control. Totales de las queries seleccionadas en este corpus: **1.358 TP, 860 TN, 52 FP y 42 FN**. Son casos revisados, varios con la misma causa y algunos bajo un contrato de implementación más fuerte que el claim actual; no son una estimación de precisión de repositorios reales.

El [ledger de regresiones](../../../tests/structural/catalog_matrix/known_failures.json) mantiene **94 desacuerdos esperados por ID exacto**, con causas y propuestas de mejora. El inventario compara los TOML con las celdas requeridas; los lenguajes no anunciados (incluido Ruby) y Unit of Work transaccional en design quedan visibles en el conteo, sin contarlos como cobertura aprobada. Los tests nuevos verifican también que una corrección obligue a retirar el pendiente correspondiente.

Validación final: **2.945 tests pasan y 94 quedan xfail**, cero fallos inesperados, en los cinco módulos seleccionados (3.039 tests totales, 49,706 s). Después se corrigieron tipos/sintaxis de tres snapshots de fixtures y se repitieron los 20 casos seleccionados afectados y los tres checks de inventario; todos pasan. [Detalle reproducible de validación](validation.json).

La revisión encuentra mejoras reales en los contratos locales de flujo, pero el catálogo todavía mezcla firmas de estructura, pruebas parciales de implementación y nombres de patrones que sugieren garantías mayores. Hay contraejemplos reproducibles incluso en variantes `ready`. Esta entrega audita y añade evidencia; **no modifica las queries ni el motor**.

Base: `353fc1444823bded9e04b465e7ee64b3809bb043`, IR **1.76.0**. Se leyeron los **33 TOML**: **23 GoF y 10 modernos**, sus **90 variantes ready** (78 GoF, 12 modernas), **15 operaciones** y la variante moderna `transactional-change-set` que permanece en `design`. Son 138 definiciones ejecutables contando raíces. No quedan variantes GoF en design en este snapshot.

## Evidencia y cómo leer los resultados

El corpus inicial contiene **252 fuentes autocontenidas en ocho lenguajes**. Se ejecuta cada raíz y todos sus hijos ready sobre sus propias fuentes: **1.081 ejecuciones de query**, con presupuesto explícito y modo strict. Las 138 definiciones se ejecutaron; eso no significa que todas recibieran un positivo propio. En este corpus, **42 de las 90 variantes** tienen un control positivo que las matchea. Las otras tienen revisión de cláusulas y ejecución sobre fuentes de su raíz, pero no una prueba positiva dirigida nueva aquí. La ampliación solicitada por variante/lenguaje se documenta por separado, sin atribuirle retrospectivamente cobertura a esta medición.

Los oráculos están fijados en `cases.json` antes de evaluar: positivo canónico, negativo de contraste, transformación que debe preservar el algoritmo, ruptura de un enlace del algoritmo o frontera de protocolo. **No son un dataset aleatorio ni una estimación de precisión/recall de proyectos reales.** Los snippets se parsean y enlazan; no se ejecutan ni se certifica su compilación/typechecking en los ocho compiladores.

| Familia de ensayo | TP | TN | FP | FN | Qué significa |
|---|---:|---:|---:|---:|---|
| control | 123 | 30 | 0 | 0 | Fixtures positivas/negativas existentes usadas como controles. |
| metamorphic | 32 | 0 | 0 | 5 | Código inocuo o reescritura equivalente del control; debería seguir apareciendo. |
| contract | 0 | 0 | 21 | 1 | Enlace concreto del algoritmo bajo auditoría; no todos son promesas literales del query_claim. |
| behavioral | 0 | 7 | 29 | 0 | Se exige comportamiento del patrón; varias queries declaran expresamente una firma más débil. |
| protocol | 0 | 0 | 1 | 0 | Convención nativa del lenguaje. |
| coverage | 0 | 0 | 0 | 3 | Implementación válida fuera de las formas representadas actualmente. |
| **Total del corpus** | **155** | **37** | **51** | **9** | **60 desacuerdos caso/oráculo, con causas y alcance distintos.** |

**No son 60 bugs independientes.** Siete fuentes remotas reproducen el mismo enlace faltante; 17 cuerpos operativos muertos muestran una limitación transversal; otras discrepancias son alcance declarado. No se debe publicar “51 falsos positivos del motor” sin esta separación. Un match es existencia de evidencia y una ausencia de match no prueba inexistencia universal del patrón.

No hubo búsquedas incompletas ni diagnósticos de parsing. Hay `cardinality:open_world` en 14 resultados seleccionados: diez contienen matches y cuatro no (tres controles negativos de Unit of Work y `bridge-generic-U`). Sus TN significan ausencia de match en el grafo finito examinado; no una prueba global de ausencia. El runner conserva `unknown`, `complete`, bindings y estadísticas de cada definición, incluidas las alternativas no seleccionadas.

**Lenguajes del corpus:** cpp: 3, csharp: 3, go: 4, java: 28, javascript: 28, python: 131, rust: 1, typescript: 54. Rust tiene sólo un control remoto en esta medición: no se afirma cobertura adversarial Rust general.

## Fallos prioritarios con testigos pequeños

### 1. Testigos desconectados dentro de la misma query

Estas queries juntan hechos verdaderos sobre objetos o llamadas distintos; el conjunto satisface las cláusulas aunque falte el enlace que define el algoritmo. La mayor prioridad es fijar **la ocurrencia** del valor/call/iteration antes de buscar sus argumentos y resultados.

| Variante | Testigo | Resultado y causa | Cambio concreto |
|---|---|---|---|
| `adapter#functional-adapter` | `adapter-ignores-request-*` (Python/JS/TS) | Tres FP: invoca el callable con `[10,20][0]` y `[10,20][1]`; request no participa. Contradice el claim de indexar el input. | Enlazar CONTAINER/origen de cada lectura indexada al parámetro del wrapper; no basta con declarar $request. |
| `builder#immutable-product` | `immutable-disconnected-copy-*` (Python/JS/TS) | Tres FP: logging usa input/estado, pero el builder retornado usa constantes. Contradice el claim del constructor sucesor. | Unir argumentos a la construcción cuyo resultado realmente retorna el paso; repetir para finish. |
| `command#command-closure` | `command-unrelated-context-*` (Python/JS/TS) | Tres FP: action recibe 0 y audit recibe context. Contradice invocar cada elemento con el contexto recibido. | ITERATION_INVOKES_VALUE y ARGUMENT_ORIGIN sobre la misma llamada. |
| `observer#event-bus` | `eventbus-unrelated-payload` | FP: un registro recibe constantes y otro recibe payload. Contradice el enlace registro/topic/invocación/payload prometido. | Unir iteration source al bucket y la invocación al binding de esa iteración. |
| `proxy#remote-subject` | `remote-unrelated-response-*` (siete lenguajes) | Siete FP de algoritmo: transporte y decoder no comparten respuesta. Los hechos actuales prueban dos mitades separadas del flujo. | Argumento de decoder originado en el resultado de ese transporte, incluyendo wrappers modelados. |
| `memento#serialized-snapshot` | `serialized-discards-snapshot` | FP de algoritmo: save codifica pero devuelve una constante. El claim literal sólo garantiza presencia de codec, más débil que round-trip. | Retorno de save desde encode; input de decode desde snapshot recibido. |
| `proxy#lazy-subject` | `lazy-proxy-unrelated-construction` | FP conductual: construcción descartada y escritura de None. El claim es más débil que inicialización lazy. | Enlazar valor escrito al resultado de la construcción y valor delegado a esa definición vigente. |

```python
# Contraejemplo Command: no entrega el contexto al comando.
def audit(context):
    pass

class Dispatcher:
    def __init__(self):
        self.pending = []
    def submit(self, payload):
        def action(context):
            return payload + context
        self.pending.append(action)
    def run(self, context):
        audit(context)
        for action in self.pending:
            action(0)
```

El código tiene tanto una iteración de pending como una llamada con context. Son ocurrencias distintas. El arreglo no requiere inventar una instrucción `command`: requiere la igualdad adecuada entre roles del grafo.

### 2. Identidad de tipos, protocolo y publicación

`bridge-generic-T` matchea y `bridge-generic-U` no: sólo cambia un parámetro de tipo de una clase **ajena**. Se usa `Box<T extends Driver>` para que el acceso a driver.run sea válido; el conteo por spelling de T no demuestra dos dimensiones de Bridge. Se necesitan entidades de parámetro de tipo con ámbito y relaciones de sustitución/constraint; esto sí requiere extensión del modelo de tipos, además de cambiar la query.

`module-shared-two-writes` demuestra una contradicción literal: el claim dice que el slot se escribe una vez pero la query acepta dos escrituras visibles. Comprobar una escritura requiere un resumen completo de escrituras del ámbito; no sirve asumir que no hay otra porque se encontró una.

`once-java-always-new` acepta `updateAndGet(prev -> new Config())`, que reemplaza el valor cada vez. Además, el operador de actualización puede reintentarse por contención: retener una instancia publicada y ejecutar una única vez la fábrica son garantías diferentes. [API oficial AtomicReference.updateAndGet](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/concurrent/atomic/AtomicReference.html#updateAndGet(java.util.function.UnaryOperator)).

`go-callback-wrong-polarity` admite `if yield(x) { return }`. El claim permite ambas polaridades, pero Go exige no volver a invocar yield una vez que devuelve false; para esta variante de protocolo, permitir la polaridad contraria es un error de especificación del detector. [Especificación Go, range](https://go.dev/ref/spec#For_range).

`async-yield-no-await` es un async generator válido con consumidor async for. La variante async no lo encuentra porque exige await explícito; Python define el generador asíncrono mediante async def y yield. La raíz iterator sí lo encuentra por generator: no es un FN de raíz. [Referencia oficial Python](https://docs.python.org/3/reference/expressions.html#asynchronous-generator-functions).

### 3. Distancia sintáctica confundida con orden relevante

`noise-singleton` añade una asignación local inocua antes de la guarda y pierde el match. `long-noise-cache-aside` y `long-noise-read-through-cache` introducen veinte asignaciones entre pasos y superan CFG_NEXT{…,16}. `early-exit-proxy` y `early-exit-chain-of-responsibility` cambian una delegación dentro del if por una guarda de salida equivalente y también se pierden.

No alcanza con aumentar 16 a 64: sólo mueve la frontera del FN y eleva el coste. La mejora es alcanzabilidad dentro de un ámbito con resumen de efectos relevantes al valor protegido, con presupuesto y estado incomplete/unknown explícitos. Una escritura a ese valor debe invalidar el match; logging independiente debe atravesarse.

### 4. Evidencia histórica frente a estado vigente

Los negativos `di-overwritten-input`, `dispatch-overwritten-handler`, `continuation-rebound`, `queue-cleared-before-drain` y `uow-erases-before-commit` matchean aunque el dato recibido/registrado se sustituye antes de usarlo. `flyweight-replaces-every-read` no comparte ninguna instancia entre accesos. Son límites de los contratos históricos o léxicos, varios declarados. `architecture.dependency-injection#retained-object` ya ofrece una opción más estricta y no forma parte de la raíz débil.

No debe borrarse toda firma débil: tiene valor exploratorio. Debe exponerse el contrato que la produjo y permitir seleccionar evidencia de origen/retención/control más fuerte. Si una raíz es una disyunción, añadir una variante fuerte no fortalece los matches que aún entran por una variante débil.

### 5. Intención y falsos positivos discutibles

`facade-basic-arithmetic` y `decorator-pass-through` exponen firmas demasiado amplias para afirmar subsistemas o responsabilidad adicional. Un emisor de eventos puede ser Observer y un servicio que coordina dos subsistemas puede ser Facade; su nombre o directorio no constituye un oráculo negativo. Conviene guardar evidencia de estructura e intención por separado y permitir etiquetas múltiples cuando la colaboración tenga varios papeles.


## Hallazgos adicionales de la matriz ampliada

La lectura inicial y los 252 casos dirigidos no agotaban las variantes. La matriz añadió cinco formas a cada combinación anunciada y confirmó estas causas nuevas:

- **Builder mutable, Go y Rust:** están FINAL_MEMBER_INPUT y RETURNS_NEW, pero la query requiere enlaces de valor/argumento de construcción que no se completan para inicializadores por campos. Falla el control y ambas variantes con ruido. Extender la proyección de construcción nombrada; no cambiar la fixture a una forma posicional sólo para que pase.
- **Composite recursive-nominal, TypeScript:** el campo conserva `native_type: Node[]` y la llamada conserva ITERATED_CALL, pero falta ELEMENT_TYPE hacia Node. El mismo ejemplo con otro nombre de clase falla también. Normalizar `T[]` mediante el modelo de tipos/colecciones.
- **Rust con `let _ = 1 + 2`:** un descarte puro vuelve BINDING_FLOW_STATUS `unsupported/unmodeled-write` y RETURN_FLOW_STATUS `unsupported/nonlocal-or-nested-write`. Se pierden Template Method composed-skeleton, DI callable-input, Facade module-surface y Builder stored-product. Modelar el wildcard como descarte de valor, sin convertirlo en escritura desconocida sobre bindings retenidos.
- **Singleton en todos los lenguajes anunciados para eager/lazy:** el problema de adyacencia se reproduce con ruido en Java, C#, JS/TS y Python según la variante. No era sólo la fixture Python inicial.
- **Prototype language-copy C++:** se conserva match tras reemplazar el cuerpo del constructor de copia por una excepción. Corresponde a su contrato de firma; registrar esa diferencia antes de presentar el resultado como prueba de implementación de copia.

También apareció deuda en las propias fixtures previas: Python higher-order-traversal tiene indentación inválida que Tree-sitter no denunció en la proyección; Java functional-adapter indexaba un `int` declarado por IntUnaryOperator; TypeScript module-shared anotaba `number` aunque devolvía Config; y Rust lazy-subject comparaba Option<RealSubject> con None sin PartialEq. Las copias de la matriz corrigen estos cuatro casos. No se modificaron los tests de origen ni se certificó el resto con los ocho compiladores: el runner es de análisis estático, CPython comprueba sintaxis Python y Tree-sitter parsea el resto.

El detalle de cada celda, incluidos los casos dirigidos de esa misma variante y los ensayos de raíz por separado, está en [COVERAGE.md](COVERAGE.md). Los cinco casos uniformes son un mínimo de regresión; para próximas ampliaciones, añadir por variante casos de alias/rebind, control, homónimos, colecciones, suspensión y protocolos nativos según las causas de las fichas siguientes, sin usar sólo stubs o renombrados como sustituto de negativos semánticos.

## Qué sirve del IR/KQL actual y qué falta

| Necesidad | Disponible y reutilizable | Límite / trabajo recomendado |
|---|---|---|
| Origen de resultado/argumento | RETURN_ORIGIN, ARGUMENT_ORIGIN, RETURN_FLOW_STATUS y relaciones por ocurrencia. | Aplicarlos en Builder, Remote Proxy y Memento; respetar estado supported y wrappers conocidos. No equiparar un path histórico con valor vigente. |
| Parámetros, constructores y campos | CALL_BINDING, BINDING_PARAMETER/VALUE, FINAL_FIELD_INPUT/VALUE, FINAL_MEMBER_INPUT, CONSTRUCTOR_FIELD_INPUT, CALL_RECEIVER_INPUT. | Reusar resúmenes finales para retención y paso de self; ampliar regiones/aliases de heap sólo con cobertura declarada. |
| Colecciones e invocación del elemento | ITERATION_SOURCE/BINDING/INVOKES_VALUE, INSERTED_INPUT, COLLECTION_SNAPSHOT_OF. | Conectar queries que hoy usan ITERATES_CALLS de forma demasiado amplia; falta versión de contenido del mapa/lote entre métodos. |
| Control y pruebas | CFG_STATUS, CFG_NEXT, BRANCH_TRUE/FALSE, NULL_TEST, TRUTH_TEST, PARAMETER_TEST, normal completion/handler fallthrough. | Polaridad nativa, salida efectiva tras finally y alcanzabilidad relevante sin límite fijo de statements. No inferir factibilidad global de un CFG estructurado. |
| Tipos | TYPE_REF, TYPE_ARGUMENT, TYPE_KIND, TYPE_HEAD; rasgos nativos y tipos básicos. | BINDS_TYPE_PARAMETER aún sirve un nombre: falta identidad con ámbito, sustitución, associated types e instanciaciones. |
| Protocolos de biblioteca | Modelos locales para copy, iteration, Optional, etc., de cobertura desigual. | Resolver símbolo/API y contrato por biblioteca; separar once, CAS, ensure-entry y overwrite. await no significa thread; no inferir locks ni ownership a partir de nombres. |
| Composición | match de named queries y roles explícitos, any, count, path, filtros y modos/presupuestos. | Añadir operaciones genéricas para las garantías, no etiquetas GoF al IR. Definir el tipo semántico de cada rol para que la composición no mezcle productor/consumidor o slot/tipo de producto. |

Código de referencia: [KenQL](../../../src/ken/structural/kenql.py), [origen de retornos/argumentos](../../../src/ken/structural/return_flow.py), [campos](../../../src/ken/structural/field_transfers.py), [miembros](../../../src/ken/structural/member_transfers.py), [CFG](../../../src/ken/structural/control_flow.py), [colecciones](../../../src/ken/structural/collection_snapshots.py).

El [núcleo de instrucciones](../../design/structural/instruction-ir.md) conserva regiones y operaciones de implementación, pero no se debe presentar el diseño de `preserve` o macros `%map` como sintaxis KQL ejecutable. El buscador de estas queries utiliza la proyección de hechos y sus resúmenes. Ver [referencia IR](../../structural-ir.md), [queries](../../structural-queries.md), [operaciones](../../design/structural/pattern-operations.md) y [contratos de algoritmos GoF](../../design/structural/gof-algorithm-contracts.md).

## Revisión de cada patrón y variante

Cada ficha combina lectura de cláusulas y ensayos dirigidos. **Riesgo de lectura** o una recomendación sin testigo listado no es un FP/FN confirmado. La tabla por variante muestra cuántos controles positivos de este corpus la encuentran y cuántos casos la seleccionan directamente. Cero no significa que el repositorio entero carezca de tests: significa que este corpus inicial aún no aporta ese testigo dirigido.

### abstract-factory

TOML auditado: [abstract-factory.toml](../../../src/ken/structural/patterns/abstract-factory.toml).

**Algoritmo:** Un proveedor ofrece varios slots de creación; cada implementación produce una familia de productos compatibles con esos slots.

**Corpus dirigido inicial:** 4 TP, 1 TN, 0 FP, 1 FN.

**Desacuerdos reproducidos:** `abstract-factory-object-literals` (FN).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `nominal-families` | ready | 3 | 0 |
| `structural-families` | ready | 0 | 1 |
| `associated-products` | ready | 0 | 0 |

**nominal-families.** Comprueba dos creadores sobrescritos y dos familias nominales. Riesgo de lectura: el contrato del proveedor se selecciona aparte de los slots sobrescritos; la herencia múltiple puede aportar slots de bases no relacionadas. Tampoco prueba compatibilidad funcional de los productos.

**Cómo mejorar:** Unir cada slot a la interfaz efectiva del proveedor y el tipo retornado al contrato de producto de ese slot. Probar dos mixins ajenos y una familia válida repartida entre ficheros.

**structural-families.** Sólo admite proveedores CLASS y correlaciona nombres/arity de dos métodos, sin sustitución de productos. FN reproducido con dos literales de objeto TS. Igual nombre y aridad no bastan para asegurar que dos productos cumplen el mismo protocolo; el claim ya limita esto.

**Cómo mejorar:** Añadir proveedores como valores estructurales y slots de objetos; validar firmas de entrada y contratos de salida por slot. Conservar una modalidad de candidato cuando los tipos sean unknown.

**associated-products.** Dos implementaciones Rust de un trait y creadores con productos CLASS; no resuelve sustitución de associated types. Riesgo declarado: alias, wrappers o productos que no sean clases se pierden; la consulta no demuestra igualdad de familias asociadas.

**Cómo mejorar:** Modelar el binding de cada associated type por impl y su uso en el retorno del slot. Probar Self::Product, alias y Box<dyn Trait>, además del producto nominal directo.

### adapter

TOML auditado: [adapter.toml](../../../src/ken/structural/patterns/adapter.toml).

**Algoritmo:** Una interfaz de entrada se transforma para invocar otra interfaz, conservando la relación entre solicitud y argumentos o entre respuesta y resultado.

**Corpus dirigido inicial:** 4 TP, 0 TN, 4 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-adapter` (FP), `adapter-ignores-request-python` (FP), `adapter-ignores-request-javascript` (FP), `adapter-ignores-request-typescript` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `object-adapter` | ready | 3 | 0 |
| `functional-adapter` | ready | 0 | 3 |
| `class-adapter` | ready | 0 | 0 |

**object-adapter.** Exige contrato nominal, adaptee por campo y delegación desde un override; además compara nombres distintos. Una adaptación de unidades o argumentos puede conservar el mismo nombre: FN potencial. La delegación muerta sigue dando match en el ensayo conductual.

**Cómo mejorar:** Correlacionar receptor, argumentos adaptados y retorno; dejar el cambio de nombre como evidencia opcional. Probar conversión Celsius/Fahrenheit en métodos ambos llamados convert, más reordenamiento de argumentos.

**functional-adapter.** FP confirmado en Python/JS/TS: el parámetro request queda sin usar y dos índices sobre constantes satisfacen la query. Existen $request e índices pero falta el enlace CONTAINER/origen hacia ese parámetro; contradice el claim de indexar el único input.

**Cómo mejorar:** Unir ambas ocurrencias de argumento a lecturas del mismo input con índices pertinentes; ARGUMENT_ORIGIN y CONTAINER permiten expresar buena parte sin una sintaxis nueva. Añadir negativos con índices ajenos, input reasignado y logging que use request.

**class-adapter.** Liga dos bases, un override de una y una llamada resuelta a un método de la otra. El claim reconoce que mismo nombre con calificación explícita y MRO completo quedan fuera.

**Cómo mejorar:** Resolver llamada calificada y receptor/base efectiva; probar Adaptee.request(self), Adaptee::request(), orden de bases y homónimos ambiguos. Mantener unknown si la resolución es ambigua.

### bridge

TOML auditado: [bridge.toml](../../../src/ken/structural/patterns/bridge.toml).

**Algoritmo:** La abstracción y su implementación tienen dimensiones de variación separadas; una operación usa la implementación elegida.

**Corpus dirigido inicial:** 4 TP, 1 TN, 2 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-bridge` (FP), `bridge-generic-T` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `runtime-composition` | ready | 3 | 0 |
| `generic-composition` | ready | 0 | 2 |
| `refined-composition` | ready | 0 | 0 |

**runtime-composition.** Evidencia nominal de abstracción refinada y contrato de implementación con varias realizaciones. La independencia nominal adicional se trata de forma diferente en C++; en otros lenguajes hay riesgo de solapamiento con wrappers de la misma jerarquía. No comprueba retención temporal del campo.

**Cómo mejorar:** Uniformar NOMINAL_ROOT y receptor efectivo donde la cobertura lo permita; contrastar un Decorator de la misma jerarquía y dos dimensiones separadas. No exigir varias implementaciones observadas para ofrecer al menos un candidato parcial.

**generic-composition.** FP metamórfico confirmado: Box<T extends Driver> más Unrelated<T> matchea; cambiar sólo T por U en la clase ajena elimina el match. Cuenta declaraciones con igual string de parámetro de tipo, que no identifica una misma abstracción ni un mismo binding. El claim describe el conteo pero su interpretación como independencia no se sostiene.

**Cómo mejorar:** Dar identidad de ámbito a cada parámetro de tipo y relacionar uso/constraint/instanciación. No arreglarlo exigiendo otro spelling ni aumentando el conteo. Añadir renombrado alfa de tipos ajenos como invariante.

**refined-composition.** Usa raíces nominales distintas, variantes pares e instance slots: mejor separación estructural. No prueba inyección, valor actual del campo ni independencia de evolución; herencia dinámica y código generado siguen limitados.

**Cómo mejorar:** Reutilizar resúmenes de retención cuando sean soportados, conservar la evidencia nominal separada y probar campo heredado, doble herencia y sustitución del receptor.

**Raíz / operaciones reutilizables:** returned_primitive liga una llamada delegada con lo retornado: útil como evidencia adicional. Revisar aliases y origen del receptor; que la raíz matchee no implica que esta operación más fuerte también lo haga.

### builder

TOML auditado: [builder.toml](../../../src/ken/structural/patterns/builder.toml).

**Algoritmo:** Los pasos configuran una construcción y la finalización entrega un producto que conserva ese estado, con formas mutables, inmutables y de estados de tipo.

**Corpus dirigido inicial:** 9 TP, 1 TN, 3 FP, 0 FN.

**Desacuerdos reproducidos:** `immutable-disconnected-copy-python` (FP), `immutable-disconnected-copy-javascript` (FP), `immutable-disconnected-copy-typescript` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `mutable-product` | ready | 3 | 0 |
| `immutable-product` | ready | 5 | 8 |
| `consuming-typestate` | ready | 0 | 0 |
| `director` | ready | 0 | 0 |
| `stored-product` | ready | 0 | 0 |

**mutable-product.** FINAL_MEMBER_INPUT y retorno de una construcción conectada al campo ofrecen una garantía local útil. El control muerto se rechaza en el corpus de raíz. Los presets sin argumento, normalizaciones y pasos bajo control no soportado son FN de alcance explícito.

**Cómo mejorar:** Mantener el contrato directo y añadir variantes para presets y transformaciones con origen/effect summary. Probar setter normalizador, rebind de input y escritura posterior que invalida la configuración.

**immutable-product.** FP confirmado en tres lenguajes: el paso hace audit(input, old_state) y devuelve Builder(0,0). HAS_CALL elige el logging, mientras RETURNS_NEW elige otra construcción. La finalización repite el riesgo de testigos independientes.

**Cómo mejorar:** Fijar primero la ocurrencia de la construcción retornada y exigir que SUS argumentos reciban input y estado; usar RETURN_ORIGIN/RESULT y CALL_BINDING. Probar testigos decorativos desconectados tanto en paso como en finish.

**consuming-typestate.** Detecta distintos argumentos genéricos de retorno y devolución del slot acumulado. El claim declara que no prueba move ni que finish exista sólo en estado Ready; el nombre no debe presentarse como validación de ownership.

**Cómo mejorar:** Separar transición de tipo y consumo del receptor. Modelar identidad de instanciación y disponibilidad de métodos por impl especializado. Negativo: finish disponible también en Empty; positivo: Builder<Ready> sin construcción final.

**director.** Correlaciona receptor de dos pasos que escriben estado y de la finalización retornada, pero no orden ni estabilidad de esa instancia. Pasos después de return o un receptor sustituido pueden satisfacer evidencia histórica.

**Cómo mejorar:** Exigir pasos alcanzables antes de la finalización sobre el mismo origen de instancia; permitir logging entre ellos. Añadir negativo con pasos posteriores al retorno y dos builders alternados.

**stored-product.** Inicialización por construcción, escritura final del input en un miembro del producto y retorno del campo o copia modelada. Ya declara que no garantiza estabilidad desde la inicialización ni aislamiento del producto.

**Cómo mejorar:** Seguir la definición vigente del campo producto hasta step/finish; probar reset intermedio y dos instancias. Conservar referencias de heap desconocidas como incertidumbre.

**Raíz / operaciones reutilizables:** directed_state compone director y mutable-product. La composición hereda la falta de orden del director; no proporciona por sí sola un contrato de secuencia ni de ciclo de vida.

### chain-of-responsibility

TOML auditado: [chain-of-responsibility.toml](../../../src/ken/structural/patterns/chain-of-responsibility.toml).

**Algoritmo:** Un participante maneja o deriva una solicitud al siguiente; el camino elegido decide quién procesa la solicitud y cuándo termina la cadena.

**Corpus dirigido inicial:** 4 TP, 0 TN, 1 FP, 1 FN.

**Desacuerdos reproducidos:** `dead-chain-of-responsibility` (FP), `early-exit-chain-of-responsibility` (FN).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `linked-handlers` | ready | 3 | 0 |
| `middleware-closures` | ready | 0 | 0 |

**linked-handlers.** La query tiene la misma forma que proxy#guarded-access: delegación condicional a campo del mismo contrato/nombre. No distingue cadena de política de acceso. FN confirmado al reescribir if request: forward como if not request: return; forward.

**Cómo mejorar:** Separar evidencia común de delegación guardada de la evidencia de cadena. Modelar sucesor, solicitud transmitida y salida sin derivación con CFG; aceptar guardas tempranas y varias instancias enlazadas.

**middleware-closures.** Relaciona continuación y rama de salida, más una cota sobre llamadas con el mismo nombre. El spelling del callee no identifica una continuación; aliases generan FN o cuentan llamadas ajenas. Caminos de longitud cuatro son frágiles ante ruido.

**Cómo mejorar:** Contar ocurrencias con el mismo origen de callable dentro del ámbito y usar alcanzabilidad resumida. Probar alias de next, función ajena homónima, logging largo y next invocado dos veces.

### command

TOML auditado: [command.toml](../../../src/ken/structural/patterns/command.toml).

**Algoritmo:** Una acción y sus datos quedan retenidos para que otro participante los active; el contexto suministrado debe llegar a esa acción concreta.

**Corpus dirigido inicial:** 7 TP, 0 TN, 4 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-command` (FP), `command-unrelated-context-python` (FP), `command-unrelated-context-javascript` (FP), `command-unrelated-context-typescript` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `retained-contract` | ready | 0 | 0 |
| `command-object` | ready | 3 | 0 |
| `stored-closure` | ready | 0 | 0 |
| `retained-object` | ready | 0 | 0 |
| `command-closure` | ready | 3 | 6 |
| `queued-object` | ready | 0 | 0 |

**retained-contract.** Inyección/retención de contrato, override de aridad cero y trabajo delegado con resultado descartado. Es razonable como firma de acción, pero un objeto de consulta almacenado o despacho dinámico distinto puede compartirla.

**Cómo mejorar:** Conservar el carácter de candidato; añadir resumen de efectos cuando se pretenda afirmar acción con efectos y comprobar retención de la instancia en el punto de despacho.

**command-object.** Objeto con operación sin parámetros e invocador separado; los caminos aceptados no prueban necesariamente cola ni retención. Un getter o Strategy de aridad cero puede parecerse; el claim formal falta.

**Cómo mejorar:** Documentar qué forma concreta se ofrece, vincular receptor/datos al comando observado y añadir positivos con contexto y resultados, sin exigir efectos a todos los Commands.

**stored-closure.** Almacena un cierre que captura una dependencia y otro método llama el campo. ASSIGNED_FROM y CAPTURES conservan historia aunque luego se sustituya el campo/captura; el claim declara ese límite temporal.

**Cómo mejorar:** Exigir origen vigente al invocar en una variante estricta; probar overwrite del slot y rebind de la captura. Distinguir contrato de acción diferida de intención Command/Strategy.

**retained-object.** Invocador conserva objeto y activa su delegación sin parámetros. El claim admite consultas puras y no garantiza orden ni aliases.

**Cómo mejorar:** Usar retención final y origen del receptor; ampliar de aridad cero a argumentos de contexto correlacionados cuando existan. Negativos: invocador que reemplaza el objeto y getter sin activación diferida.

**command-closure.** FP confirmado en Python/JS/TS: la cola invoca action(0), mientras audit(context) satisface el argumento de ejecución. Falta unir $dispatch a la invocación del elemento de esa iteración.

**Cómo mejorar:** Reusar ITERATION_SOURCE, ITERATION_BINDING e ITERATION_INVOKES_VALUE y exigir ARGUMENT_ORIGIN del contexto en ESA invocación. Mantener un negativo con logging que recibe el argumento correcto.

**queued-object.** Compone drain con contrato nominal y receptor retenido; identifica mejor el elemento activado. Hereda el reset léxico y no la conservación del lote, además de requerir operaciones sin parámetros.

**Cómo mejorar:** Aplicar las mejoras de batch-work-queue y probar cancelación previa, rebind del elemento, contexto explícito y métodos async. No prometer exactly-once.

**Raíz / operaciones reutilizables:** retained_dispatch es una pieza de correlación reutilizable; revisar estabilidad entre retención y llamada. Unir operaciones por roles ayuda sólo si cada rol nombra el mismo valor/ocurrencia, no cualquier campo del mismo nombre.

### composite

TOML auditado: [composite.toml](../../../src/ken/structural/patterns/composite.toml).

**Algoritmo:** Hojas y grupos ofrecen una operación común; el grupo aplica esa operación a sus hijos recursivamente.

**Corpus dirigido inicial:** 4 TP, 0 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-composite` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `recursive-contract` | ready | 3 | 0 |
| `recursive-nominal` | ready | 0 | 0 |
| `algebraic-tree` | ready | 0 | 0 |
| `higher-order-traversal` | ready | 0 | 0 |

**recursive-contract.** Colección de elementos del contrato y operación de override que itera/delega. Riesgo de lectura: la llamada iterada no queda necesariamente fijada al mismo slot del componente. El algoritmo muerto sigue dando match.

**Cómo mejorar:** Enlazar el TARGET de cada llamada al slot de operación o a su override efectivo y comprobar receptor iterado; contrastar llamada a debug() en lugar de operation().

**recursive-nominal.** La colección contiene elementos de la propia jerarquía y se invoca el mismo nombre. No demuestra existencia de hoja ni resolución exacta por overload/receptor.

**Cómo mejorar:** Usar contratos efectivos cuando estén disponibles y permitir candidato en una biblioteca donde no se observa la hoja. Probar colección heterogénea y otro objeto con método homónimo.

**algebraic-tree.** Exige dos campos recursivos y llamadas con el mismo nombre bajo una prueba de campo. Es una firma de árbol binario, no un modelo general de sum types. Enums Rust, discriminated unions TS o grupos de N hijos quedan fuera.

**Cómo mejorar:** Modelar variantes/casos y payloads recursivos; distinguir rama hoja de rama compuesta. Compartir esa estructura con Interpreter sin confundir recorrido y evaluación.

**higher-order-traversal.** La query actual usa iteración y asignación del resultado del hijo al valor retornado; el nombre no implica soporte de map/reduce general. Sobrescribir con el último resultado tampoco demuestra acumulación.

**Cómo mejorar:** Separar traversal de fold y expresar dependencia del acumulador previo y resultado del hijo. Añadir map, reduce, generadores y el negativo que calcula un hijo y retorna una constante.

### decorator

TOML auditado: [decorator.toml](../../../src/ken/structural/patterns/decorator.toml).

**Algoritmo:** Un wrapper conserva el contrato delegado y añade una responsabilidad alrededor de esa delegación.

**Corpus dirigido inicial:** 4 TP, 0 TN, 2 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-decorator` (FP), `decorator-pass-through` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `object-wrapper` | ready | 3 | 0 |
| `callable-wrapper` | ready | 0 | 1 |

**object-wrapper.** Exige una llamada adicional además de la delegación. Logging muerto puede completarla y decoración mediante aritmética pura puede no hacerlo. Por tanto llamada adicional no equivale a responsabilidad añadida.

**Cómo mejorar:** Usar CFG y datos/efectos observables alrededor de la llamada; admitir transformación del resultado sin una llamada extra. Contrastar una suma al resultado y logging después de return.

**callable-wrapper.** La identidad funcional def wrapper(x): return inner(x) matchea sin añadir comportamiento. FP respecto del algoritmo Decorator; firma de wrapper válido dentro del alcance débil.

**Cómo mejorar:** Exponer wrapper transparente como building block y una variante de Decorator con efecto o transformación observable; definir si sólo logging alcanza. No depender del nombre de la fábrica.

### facade

TOML auditado: [facade.toml](../../../src/ken/structural/patterns/facade.toml).

**Algoritmo:** Una superficie simplifica una colaboración con varios subsistemas; la intención de simplificación requiere evidencia de frontera además de llamadas.

**Corpus dirigido inicial:** 4 TP, 0 TN, 2 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-facade` (FP), `facade-basic-arithmetic` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `object-surface` | ready | 3 | 0 |
| `module-surface` | ready | 0 | 1 |

**object-surface.** Dos campos con tipos diferentes y delegación a ambos desde una operación. Un servicio de aplicación puede ser efectivamente una Facade: no es automáticamente FP. Requiere dos tipos nominales, por lo que módulos o dos instancias de un tipo quedan fuera.

**Cómo mejorar:** Presentarlo como coordinación de servicios candidata a Facade; añadir evidencias de módulos/dependencias y uso externo, sin convertir métricas de acoplamiento en prueba de intención.

**module-surface.** increment/double/calculate matchea: cualquier composición exportada de dos llamadas con flujo puede cumplirla. FP respecto de una Facade con subsistemas; el flujo local sí existe y no es un fallo de ARGUMENT_ORIGIN.

**Cómo mejorar:** Factorizar composición de llamadas como query base; añadir fronteras de módulos o interfaces de subsistemas para una variante más precisa. Probar composición aritmética y API agregadora real.

### factory-method

TOML auditado: [factory-method.toml](../../../src/ken/structural/patterns/factory-method.toml).

**Algoritmo:** Un slot de creación permite variar el producto usado por una colaboración sin fijar la clase concreta en el consumidor.

**Corpus dirigido inicial:** 4 TP, 1 TN, 0 FP, 0 FN.

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `virtual-slot` | ready | 3 | 0 |
| `contract-slot` | ready | 0 | 0 |

**virtual-slot.** Override que retorna una construcción: evidencia de creación polimórfica, pero no exige un consumidor/algoritmo del creador. El negativo con retorno prematuro se rechaza en este corpus.

**Cómo mejorar:** Mantener firma de slot y ofrecer evidencia adicional del cliente que consume el producto; probar retorno por alias, método helper y creación a través de constructor genérico.

**contract-slot.** Cliente tipado por contrato, llamada al slot y realizaciones Go/Rust que crean productos. No garantiza que el valor retornado llegue a otro uso ni qué implementación se elige en ejecución.

**Cómo mejorar:** Correlacionar origen del resultado con consumo cuando se solicite una prueba de colaboración; ampliar punteros/traits/associated products sin confundir constructores comunes con slots polimórficos.

**Raíz / operaciones reutilizables:** client_flow añade consumo del producto: debe verificarse por separado. Ampliar aliases/transformaciones con origen por ocurrencia; ausencia de esta operación no invalida por sí sola una firma de creación polimórfica.

### flyweight

TOML auditado: [flyweight.toml](../../../src/ken/structural/patterns/flyweight.toml).

**Algoritmo:** Una clave identifica estado compartido: se reutiliza el objeto retenido y sólo una ausencia justifica crearlo; estado extrínseco puede venir del usuario.

**Corpus dirigido inicial:** 4 TP, 0 TN, 2 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-flyweight` (FP), `flyweight-replaces-every-read` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `explicit-interning` | ready | 3 | 1 |
| `entry-api` | ready | 0 | 0 |

**explicit-interning.** FP conductual confirmado: get lee el pool, lo sustituye siempre por Product(key) y retorna pool[key]. El claim declara que no prueba miss-only creation ni identidad temporal; la firma demuestra almacenamiento/retorno, no interning.

**Cómo mejorar:** Añadir hit→retorno existente y miss→construcción→inserción→retorno con clave estable. Reusar los resúmenes de cache-aside y contrastar reemplazo en cada acceso, key rebind y dos funciones de clave incompatibles.

**entry-api.** Reconoce nombres computeIfAbsent/GetOrAdd/try_emplace/insert_or_assign/entry, sin resolver biblioteca ni exigir un inicializador concreto. insert_or_assign incluye reemplazo y entry puede devolver una entrada, no el producto compartido. Riesgo de clasificación por API.

**Cómo mejorar:** Modelos separados por API y resultado retenido; distinguir ensure-entry de overwrite y no inferir exactly-once del callback. Probar API local homónima y el camino Rust or_insert_with completo.

### interpreter

TOML auditado: [interpreter.toml](../../../src/ken/structural/patterns/interpreter.toml).

**Algoritmo:** Cada variante de una expresión aplica una regla de evaluación; las expresiones compuestas usan evaluaciones de subexpresiones bajo un contexto.

**Corpus dirigido inicial:** 4 TP, 0 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-interpreter` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `expression-objects` | ready | 3 | 0 |
| `expression-sum` | ready | 0 | 0 |

**expression-objects.** Recursión por métodos homónimos y paso del contexto. Un walker que visita nodos sin usar sus resultados puede cumplirlo; el programa con métodos inalcanzables también matchea.

**Cómo mejorar:** Separar recorrido genérico de evaluación: correlacionar resultados de hijos con operación semántica y resultado final. Probar visita sólo para logging y evaluación de un árbol aritmético.

**expression-sum.** Reutiliza la estructura binaria de composite y exige contexto en ambas llamadas, pero no combina resultados ni representa todas las variantes de un enum.

**Cómo mejorar:** Añadir casos de sum type y dependencia de resultados; no exigir aritmética si el lenguaje interpretado es booleano o imperativo. Probar operadores distintos, terminales y contexto actualizado.

### iterator

TOML auditado: [iterator.toml](../../../src/ken/structural/patterns/iterator.toml).

**Algoritmo:** El productor o cursor proporciona elementos según un protocolo; la sintaxis de suspensión y la corrección del avance son afirmaciones separadas.

**Corpus dirigido inicial:** 5 TP, 0 TN, 2 FP, 1 FN.

**Desacuerdos reproducidos:** `dead-iterator` (FP), `async-yield-no-await` (FN), `go-callback-wrong-polarity` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `external-cursor` | ready | 0 | 0 |
| `generator` | ready | 0 | 0 |
| `delegated-generator` | ready | 1 | 0 |
| `explicit-cursor` | ready | 1 | 0 |
| `callback-iterator` | ready | 1 | 2 |
| `async-iterator` | ready | 0 | 1 |
| `paired-cursor` | ready | 1 | 0 |
| `delegated-cursor` | ready | 0 | 0 |

**external-cursor.** API C++ next/isDone/currentItem con estado compartido. Firma útil y acotada; otros nombres, begin/end y operadores quedan fuera, y no prueba agotamiento.

**Cómo mejorar:** Variantes de protocolo resueltas por tipos/operadores; probar un cursor válido sin esos nombres y un contador que jamás se agota.

**generator.** Presencia de yield y forma generadora, excluyendo contexto manager modelado. Es un claim sintáctico coherente: yield inalcanzable todavía puede definir un generador vacío.

**Cómo mejorar:** Mantener esta firma; no convertir ausencia de elementos o generador vacío en FP. Separar una operación opcional para procedencia de elementos/progreso.

**delegated-generator.** Detecta suspensión delegada mediante el protocolo nativo. No implica que el iterable delegado se agote o que los elementos no cambien.

**Cómo mejorar:** Probar yield from/yield*, aliases del iterable, return value delegado y throw/close cuando se amplíe el contrato.

**explicit-cursor.** Protocolo Python __iter__/__next__ con escritura de campo; no valida procedencia ni agotamiento. El __iter__ que retorna None antes de return self aún matchea: fallo conductual claro del protocolo, aunque la firma histórica siga presente.

**Cómo mejorar:** Usar origen de retorno vigente y escritura alcanzable; aceptar next delegado sin contador propio mediante la variante correspondiente. Probar StopIteration y retorno prematuro.

**callback-iterator.** FP de protocolo confirmado: if yield(x): return se admite igual que if not yield(x): return. El claim permite ambas polaridades, pero la interfaz de range-function de Go exige detenerse cuando yield devuelve false.

**Cómo mejorar:** Normalizar la polaridad del test y exigir que false llegue a salida antes de otra invocación. Probar if/else, negación, break y retorno, y distinguir callback genérico de iterador Go.

**async-iterator.** FN confirmado para async def con yield y consumidor async for pero sin await explícito. La query exige await innecesariamente. La raíz iterator sí lo detecta mediante generator: es FN de variante y de su evidencia async, no de toda la raíz.

**Cómo mejorar:** Basar el protocolo del productor en async+yield y el consumo en async for/for await, sin exigir await en el cuerpo. Separar rol productor y consumidor en exports.

**paired-cursor.** Dos métodos de siguiente/disponibilidad comparten estado; el estado compartido no prueba fin ni elemento correcto.

**Cómo mejorar:** Modelar el contrato de hasNext/next cuando se conoce la API y mantener candidato estructural en el resto. Probar always-true, avance sin devolución y cursor delegado.

**delegated-cursor.** next sobre cursor almacenado, ADVANCES_ITERATOR y __iter__ que devuelve self. Mejor evidencia de protocolo nativo, limitada a los modelos disponibles.

**Cómo mejorar:** Ampliar protocolos por lenguaje y origen vigente del cursor; probar reemplazo del campo y shadowing del builtin next.

**Raíz / operaciones reutilizables:** iterate_over expone relaciones de iteración, binding y cuerpo. No existe por ello una macro ejecutable %iterate_over ni %map; es composición de query. Probar identidad del elemento cuando se reasigna dentro del cuerpo.

### mediator

TOML auditado: [mediator.toml](../../../src/ken/structural/patterns/mediator.toml).

**Algoritmo:** Los participantes envían eventos a un coordinador y éste dirige la colaboración entre participantes, sin que cada uno conozca a todos los demás.

**Corpus dirigido inicial:** 4 TP, 0 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-mediator` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `direct-colleagues` | ready | 3 | 0 |
| `message-coordination` | ready | 0 | 0 |
| `tag-dispatch` | ready | 0 | 0 |

**direct-colleagues.** Campos de dos tipos distintos y referencias/delegaciones de vuelta. Puede solaparse con ciclos de servicios y pierde dos colegas del mismo tipo.

**Cómo mejorar:** Usar identidades de instancia/rol y flujo de evento, no sólo tipos diferentes; probar dos botones del mismo tipo y un ciclo de servicios sin coordinación.

**message-coordination.** Observa un coordinador que delega con payload y notifiers que pasan self. Riesgo de lectura: el holder receptor de esa notificación no queda unido al coordinador elegido; el nombre de operación puede completar la consulta con una colaboración ajena.

**Cómo mejorar:** Unir holder/contrato del mediador y TARGET de la notificación con el método coordinador; luego ligar payload a las llamadas salientes. Añadir dos grupos independientes con nombres coincidentes.

**tag-dispatch.** PARAMETER_TEST añade evidencia de comparar un tag: mejora sobre tener cualquier if. Hereda la unión débil de notifiers y no basta por sí solo para vincular cada tag con la rama de destino correcta.

**Cómo mejorar:** Correlacionar test, rama factible, participante seleccionado y mediador receptor. Probar comparación de un parámetro de logging y rutas que envían siempre al mismo colega.

### memento

TOML auditado: [memento.toml](../../../src/ken/structural/patterns/memento.toml).

**Algoritmo:** Guardar produce una representación del estado y restaurar consume esa representación para restablecer el estado del originador.

**Corpus dirigido inicial:** 7 TP, 1 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `serialized-discards-snapshot` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `accessor-snapshot` | ready | 0 | 0 |
| `snapshot-object` | ready | 3 | 0 |
| `serialized-snapshot` | ready | 3 | 4 |

**accessor-snapshot.** Constructor explícito, CALL_BINDING, FINAL_FIELD_INPUT y getter/restore correlacionados ofrecen evidencia más fuerte de flujo local. Ya excluye efectos ocultos y no promete aislamiento profundo.

**Cómo mejorar:** Mantener los checks de escritura final; probar alias mutable en el snapshot, getters que transforman y restore con rebind. Definir por separado copia somera y aislamiento histórico.

**snapshot-object.** Constructor de snapshot y escritura final de restauración desde el mismo miembro. La identidad nominal es útil, pero no demuestra que se conserve una fotografía inmutable ni excluye todos los rebindings de restore.

**Cómo mejorar:** Seguir el origen vigente del parámetro snapshot y modelar mutación de campos cuando se pretenda aislamiento. No exigir deep copy para todos los usos legítimos de Memento.

**serialized-snapshot.** FP confirmado: save llama al encoder pero descarta su salida y retorna una constante. HAS_CALL encode no está unido al retorno; la entrada del decoder tampoco se ata completamente al parámetro snapshot.

**Cómo mejorar:** Exigir retorno cuyo origen sea el encoder de state y argumento del decoder originado en el snapshot recibido; preservar el write final del decode. Probar ambos extremos desconectados y codec homónimo.

### observer

TOML auditado: [observer.toml](../../../src/ken/structural/patterns/observer.toml).

**Algoritmo:** Registrar retiene observadores; notificar activa los observadores de ese mismo registro y, cuando el contrato lo pide, les entrega el evento correspondiente.

**Corpus dirigido inicial:** 5 TP, 0 TN, 2 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-observer` (FP), `eventbus-unrelated-payload` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `listener-registry` | ready | 3 | 0 |
| `map-key-registry` | ready | 0 | 0 |
| `snapshot-registry` | ready | 0 | 0 |
| `language-event` | ready | 0 | 0 |
| `event-bus` | ready | 1 | 2 |

**listener-registry.** Inserción del listener recibido e invocación al recorrer la misma colección. Es una firma razonable para event emitters; llamarlos código ordinario no los convierte en negativos. No valida todo payload/ciclo de vida y admite cuerpo muerto.

**Cómo mejorar:** Añadir evidencia opcional de payload por ocurrencia y estabilidad del registro. Probar colección borrada antes de notificar y altas por helper.

**map-key-registry.** Variante Go con listeners como claves e invocación de esas claves. No modela necesariamente valores booleanos usados para habilitar/deshabilitar ni baja.

**Cómo mejorar:** Correlacionar presencia/estado del registro si se promete entrega activa. Probar claves deshabilitadas, borrado y snapshots de claves.

**snapshot-registry.** Usa snapshot modelado y el valor realmente invocado; cubre copia defensiva de listeners. No prueba cuándo corre un callback que registra ni identidad bajo alias/efectos ocultos.

**Cómo mejorar:** Conservar el enlace a snapshot e invocación; probar copia de colección ajena, snapshot antes de alta y rebind del elemento.

**language-event.** C# add, remove y raise sobre un mismo event: relación fuerte de storage. Exigir un método explícito de baja pierde emisores válidos con sólo alta y emisión.

**Cómo mejorar:** Dejar remove como operación/capacidad opcional y probar emisor sin unsubscribe, evento heredado y handlers que reciben distintos payloads.

**event-bus.** FP confirmado: el bucket del topic invoca handler("wrong") y un segundo loop sobre spare invoca unrelated(payload). La query mezcla ITERATES_CALLS del primero con invocación/payload del segundo. El topic como campo también limita topics dinámicos por parámetro.

**Cómo mejorar:** Unir ITERATION_SOURCE al bucket publicado y ITERATION_INVOKES_VALUE a ESA iteración. Exigir ARGUMENT_ORIGIN del payload allí; añadir variante de topic por parámetro con identidad de clave.

### prototype

TOML auditado: [prototype.toml](../../../src/ken/structural/patterns/prototype.toml).

**Algoritmo:** Una operación de copia produce un objeto nuevo a partir del estado del objeto fuente, con profundidad de copia explícita o desconocida.

**Corpus dirigido inicial:** 4 TP, 1 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `prototype-discarded-copy` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `field-copy` | ready | 0 | 0 |
| `derived-clone` | ready | 0 | 0 |
| `explicit-copy` | ready | 3 | 0 |
| `language-copy` | ready | 0 | 1 |

**field-copy.** Correlaciona allocation retornada y al menos un campo del receptor conservado; excluye ciertos escapes y respeta alternativas de rama. Es una garantía parcial de copia, no de todos los campos.

**Cómo mejorar:** Conservar la correlación allocation/write y ofrecer cobertura de campos como evidencia adicional. Probar field copy parcial válido, setter con efectos y alias del receptor devuelto.

**derived-clone.** Rust derive(Clone) más uso clone sobre el tipo sin target explícito. La capacidad declarada sin sitio de uso queda fuera; macros propias y trait resolution están excluidos.

**Cómo mejorar:** Separar capacidad de clonación declarada de uso observado; identificar derive estándar por resolución cuando sea posible y probar impl manual coexistente.

**explicit-copy.** Construcción del mismo tipo con estado del receptor y retorno con origen local. Puede ser sucesor inmutable más que clon, algo declarado por el claim.

**Cómo mejorar:** Mantener candidato y describir qué estado se conserva; aliases y escrituras finales ya tienen soporte que no debe perderse al generalizar. No inferir deep copy.

**language-copy.** copy.copy(self); return 0 matchea. La primitiva sí copia el objeto, pero no existe una operación de clonación que entregue esa copia; es evidencia de uso de copia, más débil que Prototype. Constructor de copia sólo por firma tampoco prueba su implementación.

**Cómo mejorar:** Separar usage de operación de clonación retornada y usar RETURN_ORIGIN para ésta. Resolver API/constructor y probar copia descartada, constructor vacío y función local llamada copy.

**Raíz / operaciones reutilizables:** derived_copy expone uso de Clone; no debe interpretarse como prueba de profundidad ni de implementación del método cuando el derive no se resuelve.

### proxy

TOML auditado: [proxy.toml](../../../src/ken/structural/patterns/proxy.toml).

**Algoritmo:** Un representante del subject controla o media su acceso, preservando la relación entre petición, operación delegada y resultado.

**Corpus dirigido inicial:** 13 TP, 0 TN, 9 FP, 1 FN.

**Desacuerdos reproducidos:** `dead-proxy` (FP), `remote-unrelated-response-python` (FP), `remote-unrelated-response-javascript` (FP), `remote-unrelated-response-typescript` (FP), `remote-unrelated-response-java` (FP), `remote-unrelated-response-csharp` (FP), `remote-unrelated-response-cpp` (FP), `remote-unrelated-response-go` (FP), `early-exit-proxy` (FN), `lazy-proxy-unrelated-construction` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `guarded-access` | ready | 3 | 0 |
| `lazy-subject` | ready | 1 | 2 |
| `remote-subject` | ready | 8 | 15 |

**guarded-access.** Coincide estructuralmente con linked-handlers y exige delegación dentro de la condición. FN confirmado para guarda temprana equivalente; admite delegación inalcanzable.

**Cómo mejorar:** Expresar condición que puede impedir acceso mediante CFG, incluyendo return/throw previos, y unir argumentos y resultado con el subject. Mantener roles de política separados de topología de cadena.

**lazy-subject.** FP conductual confirmado: descarta RealSubject(), asigna None al campo bajo su guarda y luego delega a ese campo. La query exige una construcción en el método, sin ligar esa construcción a la escritura. El claim literal describe una firma más débil que lazy initialization.

**Cómo mejorar:** Fijar valor de la escritura al origen de construcción y garantizar que la delegación use esa definición; modelar null/miss con polaridad. Probar creación ajena, reemplazo y condición invertida.

**remote-subject.** FP confirmado en siete lenguajes: transport(encode(request)) seguido de return decode("unrelated"). Codificador y transporte se conectan, decoder y retorno también, pero falta el tramo respuesta→decoder. No es incertidumbre sobre red/codec: los valores están visiblemente desconectados.

**Cómo mejorar:** Unir argumento del decoder con origen del resultado de ESA llamada de transporte; manejar unwrap/await mediante modelos explícitos. Añadir transport equivocado y respuesta sobrescrita como negativos.

### singleton

TOML auditado: [singleton.toml](../../../src/ken/structural/patterns/singleton.toml).

**Algoritmo:** Un ámbito definido publica una instancia compartida y los accesos retornan esa misma instancia; unicidad global y sincronización son contratos adicionales.

**Corpus dirigido inicial:** 5 TP, 1 TN, 2 FP, 1 FN.

**Desacuerdos reproducidos:** `noise-singleton` (FN), `once-java-always-new` (FP), `module-shared-two-writes` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `eager-shared` | ready | 0 | 0 |
| `module-shared` | ready | 1 | 2 |
| `lazy-guarded` | ready | 3 | 0 |
| `once-primitive` | ready | 1 | 2 |

**eager-shared.** Campo inicializado, inventario de constructores privados, un sitio de allocation y accessor con retorno directo en CFG_ENTRY. Es conservador en closed-world pero la forma directa del accessor pierde logging previo.

**Cómo mejorar:** Separar alcanzabilidad/origen del retorno de adyacencia a entry; preservar checks de constructor/scope. No convertir un sitio observado en unicidad universal.

**module-shared.** FP de claim confirmado: dos shared = Config() visibles se aceptan aunque promete written once. No hay restricción equivalente de número de escrituras en la query. Compartir el último valor puede ser válido como alcance más débil, pero no cumple esa promesa.

**Cómo mejorar:** Comprobar conteo/estado de escrituras de módulo con cobertura completa; si aún no existe ese resumen, implementarlo o reducir explícitamente el claim. Probar asignación posterior dentro y fuera del accessor.

**lazy-guarded.** FN confirmado con una sola asignación aritmética independiente al inicio del accessor: exige que CFG_ENTRY sea la rama y otras aristas directas. Los checks de null, write y return son útiles pero la adyacencia no es esencial al algoritmo.

**Cómo mejorar:** Usar alcanzabilidad relevante, origen de storage y ausencia de escrituras invalidantes; no sólo subir un límite de path. Probar logging antes/después y rebind real que debe ser rechazado.

**once-primitive.** FP confirmado con AtomicReference.updateAndGet(prev -> new Config()): cambia instancia en cada acceso. La query no resuelve ni filtra adecuadamente la API de once; updateAndGet por sí sola no es inicialización única.

**Cómo mejorar:** Modelos por símbolo de biblioteca y contrato de publicación/retención. Para CAS exigir conservación de prev no nulo y distinguir instancia publicada de número de ejecuciones del inicializador. Probar API homónima y acceso repetido.

**Raíz / operaciones reutilizables:** shared_instance/lazy_instance/observed_lazy_use exponen almacenamiento y uso observado. Revisar que las raíces y sus aliases exporten el mismo tipo de rol; no sumar esas evidencias como tres pruebas independientes ni inferir thread safety.

### state

TOML auditado: [state.toml](../../../src/ken/structural/patterns/state.toml).

**Algoritmo:** El comportamiento de un contexto depende de su estado actual y ciertas operaciones producen transiciones que cambian el comportamiento posterior.

**Corpus dirigido inicial:** 4 TP, 0 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-state` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `state-object` | ready | 3 | 0 |
| `state-enum` | ready | 0 | 0 |
| `context-transition` | ready | 0 | 0 |

**state-object.** Campo del contrato State, delegación y construcción de nuevo estado. Strategy con cambio de política comparte esa forma; la query no demuestra que una transición gobierne la siguiente operación.

**Cómo mejorar:** Ligar transición al contexto actual y a futuras delegaciones mediante resumen de campo; mantener ambigüedad State/Strategy donde no haya evidencia de transición causada por el estado.

**state-enum.** Dos valores distintos y escritura guardada de un campo. Un flag de configuración o reset de contador puede cumplirlo sin máquina de estados; el claim reconoce que no prueba una máquina completa.

**Cómo mejorar:** Exigir tests sobre el estado vigente y transición condicionada por evento que cambie la selección posterior. Añadir negativos de umbral/contador y positivos de máquinas con match/switch.

**context-transition.** Usa constructor, referencia al contexto, setters y tipos de estados distintos: mejor evidencia de colaboración. No cierra dispatch dinámico ni identidad runtime; lambdas o tablas de transiciones pueden quedar fuera.

**Cómo mejorar:** Reusar CALL_BINDING/FINAL_FIELD_INPUT y ampliar a representación por tags/tablas con el mismo contrato de transición. Probar contexto ajeno pasado a un setter.

### strategy

TOML auditado: [strategy.toml](../../../src/ken/structural/patterns/strategy.toml).

**Algoritmo:** Una política suministrada o elegida aporta un algoritmo que el contexto usa sin fijar su implementación.

**Corpus dirigido inicial:** 4 TP, 0 TN, 1 FP, 1 FN.

**Desacuerdos reproducidos:** `dead-strategy` (FP), `strategy-static-no-field` (FN).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `strategy-object` | ready | 3 | 0 |
| `strategy-callable` | ready | 0 | 0 |
| `static-policy` | ready | 0 | 1 |

**strategy-object.** supplied_policy correlaciona input, campo y uso, con dos implementaciones nominales. DI ordinaria puede tener ese papel; una sola implementación presente en una biblioteca genera cobertura parcial, no ausencia demostrada de Strategy.

**Cómo mejorar:** Ofrecer niveles de evidencia para contrato frente a múltiples implementaciones; comprobar origen vigente al usar el campo. Probar inyección condicional y un único plugin externo desconocido.

**strategy-callable.** Callable recibido, retenido y llamado en otro método: forma válida de política funcional. Retención histórica no garantiza que siga siendo el callable recibido en el momento de uso.

**Cómo mejorar:** Reutilizar resúmenes de retención y distinguir función de política de notificación por uso de resultado cuando la búsqueda lo requiera. Probar callback sustituido y política pura retornada.

**static-policy.** FN confirmado para Algorithm<P>::run que llama P::apply(x) sin campo. Exigir campo de tipo P contradice la generalidad esperada de política estática; el caso actual sólo cubre composición genérica con campo.

**Cómo mejorar:** Añadir resolución de callee por parámetro de tipo y especialización sin objeto runtime. Probar política por método estático, free function parametrizada y campo genérico sin uso algorítmico.

**Raíz / operaciones reutilizables:** supplied_policy/consumed_policy permiten pedir evidencia más fuerte sobre input y consumo del resultado. Documentar alcance lineal/origen directo y no aplicar una exigencia de resultado a políticas cuyo resultado legítimo son efectos.

### template-method

TOML auditado: [template-method.toml](../../../src/ken/structural/patterns/template-method.toml).

**Algoritmo:** Un esqueleto controla una secuencia de pasos personalizables, preservando las dependencias relevantes entre ellos.

**Corpus dirigido inicial:** 4 TP, 0 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-template-method` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `virtual-skeleton` | ready | 3 | 0 |
| `trait-default` | ready | 0 | 0 |
| `composed-skeleton` | ready | 0 | 0 |

**virtual-skeleton.** Método que llama un slot sobrescrito. No fija suficientemente el receptor de todas las llamadas ni garantiza orden/alcanzabilidad; el cuerpo muerto sigue matcheando.

**Cómo mejorar:** Ligar slot efectivo al receptor del esqueleto y pasos alcanzables. Probar hook llamado sobre objeto ajeno, un único hook válido y hook después de return.

**trait-default.** Implementación por defecto llama un hook y exige al menos dos realizaciones. Una sola implementación no invalida Template Method; la ausencia de otra es open-world, no TN universal.

**Cómo mejorar:** Separar capacidad de personalización de diversidad observada; comprobar que el cuerpo es default del trait/interfaz y probar Rust/Java con un solo impl.

**composed-skeleton.** Pipeline de exactamente tres hooks con flujo acotado entre resultados. Una composición funcional ordinaria puede cumplirlo y dos/cuatro pasos válidos quedan fuera.

**Cómo mejorar:** Definir un contrato parametrizable de secuencia/dependencia y personalización, con al menos un hook suministrado o sobrescribible. Probar logging largo, dos pasos y resultado intermedio descartado.

**Raíz / operaciones reutilizables:** dependent_steps añade orden/dependencias más específicas; debe compartir primitivas de alcanzabilidad y origen, no duplicar variantes por cantidad fija de hooks.

### visitor

TOML auditado: [visitor.toml](../../../src/ken/structural/patterns/visitor.toml).

**Algoritmo:** El elemento entrega su identidad a un visitante y éste selecciona una operación correspondiente a la variante del elemento, separando operación y estructura.

**Corpus dirigido inicial:** 4 TP, 0 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `dead-visitor` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `overloaded-dispatch` | ready | 0 | 0 |
| `named-dispatch` | ready | 3 | 0 |
| `generic-visitor` | ready | 0 | 0 |

**overloaded-dispatch.** Exige varias operaciones homónimas y paso de self, pero contar overloads no equivale a resolver la variante que recibe ese elemento. La raíz sigue matcheando con accepts muertos.

**Cómo mejorar:** Resolver firma y binding del argumento que lleva self al parámetro de tipo elemento, incluyendo overload candidato/ambigüedad. Probar overload ajeno con el mismo nombre.

**named-dispatch.** Correlaciona tipos del visitante/elemento y paso de self. Riesgo de lectura: tipo de algún parámetro y posición efectiva del self deben quedar unidos por el mismo CALL_BINDING, no por existencia independiente.

**Cómo mejorar:** Fijar BINDING_PARAMETER/BINDING_VALUE para el self pasado y TARGET del método elegido. Probar self en una posición distinta de la tipada como elemento y visitantes con dos elementos.

**generic-visitor.** Visitante genérico y callback que recibe self. Sin familia de operaciones/casos puede parecerse a un callback genérico de un solo objeto; sustitución de tipos incompleta limita Rust/TS.

**Cómo mejorar:** Relacionar parámetro de tipo por ámbito, interfaz del visitante y casos de elementos. Mantener candidato si no se observa la familia completa; probar fold de enum y callback sin estructura visitable.

### architecture.adapted-continuation-wrapper

TOML auditado: [adapted-continuation-wrapper.toml](../../../src/ken/structural/modern_patterns/adapted-continuation-wrapper.toml).

**Algoritmo:** Una fábrica devuelve la adaptación de un handler que invoca la continuación recibida.

**Corpus dirigido inicial:** 4 TP, 3 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `adapted-returns-number` (FP).

**Raíz / operaciones reutilizables:** La raíz no tiene variantes: el caso adapt(handler) con adapt definido como return 42 matchea. El flujo hasta el argumento del adaptador existe, pero no hay garantía de que el adaptador devuelva/conserve un callable. Es un FP de algoritmo respecto del alcance sintáctico declarado. Mejorar con resumen de retorno del target resuelto y modelo explícito del adaptador; si es externo, conservar candidato con esa hipótesis. Probar adaptador que envuelve, descarta, invoca inmediatamente o devuelve un escalar.

### architecture.batch-work-queue

TOML auditado: [batch-work-queue.toml](../../../src/ken/structural/modern_patterns/batch-work-queue.toml).

**Algoritmo:** Se retiene un lote de trabajos, se activa cada elemento del lote y después se vacía ese lote.

**Corpus dirigido inicial:** 4 TP, 3 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `queue-cleared-before-drain` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `stored-batch` | ready | 3 | 0 |

**stored-batch.** Tiene enlaces fuertes INSERTED_INPUT/ITERATION_SOURCE/ITERATION_INVOKES_VALUE y reset después de iteración. FP conductual confirmado si consume borra tasks antes de iterar: el reset/retención sólo son léxicos.

**Cómo mejorar:** Seguir versión de colección desde alta a drenaje, distinguir cancelación de consumo y comprobar que clear no invalide el lote previo. Probar rebind del elemento, pop/drain nativo y operaciones con argumentos.

**Raíz / operaciones reutilizables:** drain es la pieza usada también por command#queued-object: la mejora se propaga allí. AFTER_ITERATION no significa finally-safe ni exactly-once. Excepciones/async y alias de colección requieren contrato aparte.

### architecture.cache-aside

TOML auditado: [cache-aside.toml](../../../src/ken/structural/modern_patterns/cache-aside.toml).

**Algoritmo:** Buscar por clave; si hay hit retornarlo; si hay miss cargar, almacenar ese mismo resultado y retornarlo.

**Corpus dirigido inicial:** 4 TP, 3 TN, 0 FP, 1 FN.

**Desacuerdos reproducidos:** `long-noise-cache-aside` (FN).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `java-optional` | ready | 0 | 0 |
| `null-miss` | ready | 3 | 0 |

**java-optional.** Modelo específico de Optional con identificación más controlada de API y flujo de hit/fallback. No equivale a reconocer cualquier método homónimo; callbacks, entradas reasignadas o composición async requieren atención adicional.

**Cómo mejorar:** Probar Optional importado frente a tipo local homónimo, orElse eager frente a orElseGet lazy, fallback que retorna otro valor y clave transformada. Mantener las hipótesis de modelo visibles.

**null-miss.** CFG estructurado, origen de retorno, writes y bindings estables: más fuerte que la firma antigua de lookup/write. FN metamórfico confirmado al insertar veinte asignaciones independientes, por caminos CFG acotados a 16.

**Cómo mejorar:** Sustituir distancia de instrucciones por alcanzabilidad con resumen de efectos relevantes y presupuesto explícito. Probar ruido de 0/1/20/100 instrucciones y una escritura invalidante que siga rechazándose.

### architecture.continuation-wrapper

TOML auditado: [continuation-wrapper.toml](../../../src/ken/structural/modern_patterns/continuation-wrapper.toml).

**Algoritmo:** Una fábrica captura la continuación recibida y devuelve un handler que la invoca.

**Corpus dirigido inicial:** 4 TP, 3 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `continuation-rebound` (FP).

**Raíz / operaciones reutilizables:** La raíz no tiene variantes. FP conductual confirmado: next = lambda x: 0 antes de crear handler conserva un match; CALLEE_VALUE/CAPTURES identifica el binding histórico, no el valor suministrado. El claim es una forma léxica, no prueba de middleware HTTP. Añadir variante estricta con origen del callable vigente y ausencia de rebind relevante; probar captura ajena, shadowing, alias inmutable y múltiples continuaciones.

### architecture.dependency-injection

TOML auditado: [dependency-injection.toml](../../../src/ken/structural/modern_patterns/dependency-injection.toml).

**Algoritmo:** Una dependencia suministrada alcanza el campo o callable que un consumidor utiliza; retención efectiva es una garantía más fuerte que una asignación observada.

**Corpus dirigido inicial:** 4 TP, 3 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `di-overwritten-input` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `retained-object` | ready | 3 | 0 |
| `object-assignment` | ready | 3 | 1 |
| `callable-input` | ready | 0 | 0 |

**retained-object.** Variante opt-in con estrategia de retención más estricta. La raíz intencionalmente conserva object-assignment para configuración condicional; no hereda automáticamente esta garantía.

**Cómo mejorar:** Mantener visible cuál variante sustenta el resultado y permitir al usuario seleccionar retención estricta. Probar ctor/configure lineal, ramas soportadas, input rebind y overwrite final.

**object-assignment.** FP conductual confirmado si incoming se asigna y enseguida dependency=None. El hecho histórico de suministro y uso sigue existiendo; es un límite declarado del contrato raíz.

**Cómo mejorar:** Recomendar retained-object para búsquedas que exijan conservación; ampliar sus resúmenes por rama, evitando eliminar silenciosamente las configuraciones condicionales válidas.

**callable-input.** Retiene/invoca callable suministrado mediante supplied_policy. No prueba estabilidad de heap entre métodos ni semántica del callable.

**Cómo mejorar:** Correlacionar origen vigente y probar rebind antes de almacenar y reemplazo antes de uso. No distinguir Strategy y DI por el nombre de la clase: pueden ser ambos.

### architecture.dispatch-table

TOML auditado: [dispatch-table.toml](../../../src/ken/structural/modern_patterns/dispatch-table.toml).

**Algoritmo:** Una clave registra una acción y el despacho selecciona e invoca la acción conservada bajo la clave solicitada.

**Corpus dirigido inicial:** 4 TP, 3 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `dispatch-overwritten-handler` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `direct` | ready | 3 | 1 |
| `adapted` | ready | 0 | 0 |

**direct.** FP conductual confirmado con table[key]=handler seguido de table[key]=None. La query conserva la inserción histórica y la posterior forma de lookup/call, pero no prueba retención vigente.

**Cómo mejorar:** Introducir versión/contenido de entrada de mapa y enlazar selected callable al valor retenido; probar overwrite, eliminación, alias de clave y tabla ajena con mismo nombre.

**adapted.** Relaciona slots de instancia y retorno/origen de normalización del handler. Es más precisa que equiparar toda construcción a una acción, pero preservar un argumento en algún wrapper no garantiza que la tabla ejecute el recibido.

**Cómo mejorar:** Componer resumen del adaptador con escritura final/lookup de la entrada. Probar adaptador que descarta el callable y otro que lo conserva por constructor, además de handlers async.

### resilience.exception-retry

TOML auditado: [exception-retry.toml](../../../src/ken/structural/modern_patterns/exception-retry.toml).

**Algoritmo:** Ante una excepción se vuelve a intentar la operación; el éxito sale del bucle. Un bucle de fallback a otros proveedores puede tener forma parecida.

**Corpus dirigido inicial:** 4 TP, 3 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `retry-finally-break` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `explicit-continue` | ready | 3 | 1 |
| `handler-fallthrough` | ready | 0 | 0 |

**explicit-continue.** FP conductual confirmado: finally: break anula continue y no se reintenta. El caveat ya advierte expresamente que finally puede anular salidas, por lo que no contradice su claim léxico.

**Cómo mejorar:** Ofrecer una variante de control efectivo: resolver finally antes de CONTINUE_TARGET efectivo o excluir conservadoramente finally no modelado. Probar return/break/throw en finally y retry que conserva target/argumentos.

**handler-fallthrough.** HANDLER_FALLTHROUGH/LOOP_BODY_TAIL excluyen finally/resources/else y flujo no soportado: contrato más cuidadoso. La exclusión produce FN de alcance para formas equivalentes más complejas.

**Cómo mejorar:** Compartir resumen de finalización normal/abrupta con explicit-continue y ampliar sólo con evidencia. Separar retry, fallback, backoff y circuit breaker; no inferir idempotencia.

### architecture.read-through-cache

TOML auditado: [read-through-cache.toml](../../../src/ken/structural/modern_patterns/read-through-cache.toml).

**Algoritmo:** Un objeto administra un cache y ofrece una lectura que devuelve hit o carga/rellena/devuelve en miss.

**Corpus dirigido inicial:** 4 TP, 3 TN, 0 FP, 1 FN.

**Desacuerdos reproducidos:** `long-noise-read-through-cache` (FN).

**Raíz / operaciones reutilizables:** La raíz compone read_fill y exige construcción local del campo cache, lo que prueba forma de inicialización, no ownership exclusivo. FN confirmado por veinte instrucciones inocuas entre pasos: los caminos tienen cota 16. Reusar alcanzabilidad relevante y resúmenes de retorno/binding; agregar variante de cache inyectado si se quiere incluir ese alcance. read_fill debe conservar identidad de clave y resultado, diferenciando rebind de binding de mutación del mapa. Probar cache ajeno, contains/get no atómico, TTL y async como contratos independientes.

### architecture.subclass-factory

TOML auditado: [subclass-factory.toml](../../../src/ken/structural/modern_patterns/subclass-factory.toml).

**Algoritmo:** Una fábrica parametrizada por una clase devuelve una clase que extiende esa base.

**Corpus dirigido inicial:** 4 TP, 3 TN, 0 FP, 1 FN.

**Desacuerdos reproducidos:** `subclass-base-alias` (FN).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `returned-subclass` | ready | 3 | 1 |

**returned-subclass.** BASE_VALUE y retorno preservado evitan confundir clases ajenas; FN confirmado con Alias=Base y class Derived(Alias). La exclusión de aliases está declarada, pero la relación semántica es válida y frecuente.

**Cómo mejorar:** Resolver origen de la expresión base mediante reaching definitions para aliases locales sin rebind; no por igualdad de spelling. Probar alias, shadowing, factory que devuelve otra clase y composición de mixins.

### persistence.unit-of-work

TOML auditado: [unit-of-work.toml](../../../src/ken/structural/modern_patterns/unit-of-work.toml).

**Algoritmo:** Registrar acumula entidades/cambios y commit coordina su persistencia diferida; una transacción atómica es una garantía adicional.

**Corpus dirigido inicial:** 4 TP, 3 TN, 1 FP, 0 FN.

**Desacuerdos reproducidos:** `uow-erases-before-commit` (FP).

| Variante | Estado | Controles positivos con match | Casos que la seleccionan |
|---|---|---:|---:|
| `keyed-change-set` | ready | 3 | 0 |
| `transactional-change-set` | design | 0 | 0 |

**keyed-change-set.** Registro por clave y al menos dos workers que persisten elementos. FP conductual confirmado si commit reemplaza changes por dos lotes vacíos antes de llamar helpers. También falta demostrar correspondencia general entre claves de alta y claves literales consumidas.

**Cómo mejorar:** Correlacionar versión de change set, clave y entidad desde register a cada worker; no exigir que existan exactamente dos categorías para todas las UoW. Probar alta bajo clave que ningún worker lee, borrado previo y flush parcial.

**transactional-change-set.** Sigue en design y no tiene query. No es un fallo de ejecución ni un FN medido: no existe detector transaccional publicado para esta variante.

**Cómo mejorar:** Implementar begin/commit/rollback mediante identidad de transacción y resumen de salidas normales/excepcionales; persistencia debe pertenecer a esa transacción. Probar rollback en error, commit fuera de región y conexión ajena antes de marcar ready.

**Raíz / operaciones reutilizables:** keyed_flush comparte recorrido/elemento y persistencia con la raíz, pero no garantiza atomicidad ni consume todos los cambios. Etiquetar flush observado y transacción demostrada como afirmaciones diferentes.

## Rendimiento y pruebas de regresión

La ejecución registrada del corpus inicial tarda **0,943 s** dentro del runner, incluido registro/compilación (0,048 s), parsing/enlace de 252 fuentes y 1.081 evaluaciones. No incluye arranque/import de Python ni escribir results.json. Los 252 grafos son pequeños y se reconstruyen sin cache de proyecto; el registro se comparte dentro de la corrida. No es un benchmark de escala ni una comparación contra una versión anterior.

| Etapa por fuente | Total | Mediana | p95 | Máximo |
|---|---:|---:|---:|---:|
| lower_and_link | 0.645 s | 2.049 ms | 5.547 ms | 21.959 ms |
| query_projection | 0.072 s | 0.215 ms | 0.591 ms | 7.282 ms |
| queries | 0.156 s | 0.500 ms | 1.492 ms | 3.012 ms |
| total | 0.873 s | 2.821 ms | 8.180 ms | 25.933 ms |

El presupuesto por Engine es max_matches=200, max_rows=500000, max_states=100000 y timeout_ms=3000. Todos los outcomes terminaron completos. Antes de ampliar path o joins de tipos, medir en grafos de proyecto número de filas/estados, tiempo p50/p95, memoria pico y comportamiento con presupuesto agotado. Un resumen de alcanzabilidad reutilizable/indexado es preferible a enumerar caminos arbitrarios; el cache debe invalidarse por versión de IR, configuración/modelos, fuente y dependencias, sin cachear una ejecución parcial como negativa completa. **No se midió aquí el cache de 500 MB ni throughput en repos grandes.**

Los checks existentes seleccionados pasaron: **724 tests, cero failures/errors/skips**, 26,597 s de pytest (medición del XML). Incluyen GoF canónicos/negativos, revisión moderna, ABI/roundtrip de todas las queries y el corpus negativo previo. Que pasen y estos contraejemplos fallen demuestra cobertura incompleta, no una contradicción entre suites.

```sh
.venv/bin/python -m pytest \
  tests/structural/test_gof_executable.py \
  tests/structural/test_modern_catalog_review.py \
  tests/structural/test_catalog_ir_contracts.py \
  tests/structural/test_negative_corpus.py -q
```

## Orden recomendado de corrección

1. **Enlaces entre ocurrencias:** Adapter funcional, Builder inmutable, Command closure, Event Bus y Remote Proxy. Cada negativo debe rechazar aun si logging/otra iteración aportan testigos correctos ajenos. Preservar controles en todos los lenguajes de la variante.
2. **Promesas y protocolos:** module-shared written-once, once/CAS, polaridad Go y async generator sin await. Resolver el contrato antes de ajustar regexs.
3. **Origen y retención:** lazy subject, Memento serializado, DI estricta, dispatch/colas/UoW. No ampliar garantías de heap desde mera ausencia de escritura visible.
4. **Control tolerante a ruido:** Singleton y caches, guardas tempranas, finally de Retry. Ensayos de longitud creciente y una mutación relevante intercalada por cada positivo.
5. **Tipos y variaciones idiomáticas:** Bridge genérico, associated products, static policy sin campo, familias estructurales, sum types y aliases de base. Esto necesita extensiones de IR con tests de shadowing y sustitución.
6. **Contratos del catálogo:** 21/78 variantes GoF ready carecen de query_claim; completar promesa exacta, evidencia y exclusiones, sin usar “structural” para ocultar enlaces que sí se prometen. Actualizar inventarios históricos que todavía muestran 77 variantes o versiones antiguas: el snapshot real aquí es IR 1.76 y 78 GoF ready.
7. **Intención y catálogo moderno:** conservar candidatos exploratorios y búsquedas de garantía fuerte diferenciables. Añadir transacción real antes de marcar transactional-change-set ready; no afirmar que retry simple equivale a circuit breaker o que wrapper equivale a todo middleware web.

## Reproducción y artefactos

- [cases.json](cases.json): fuentes completas, target, oráculo y razón por caso; no depende de futuras ediciones de fixtures.
- [results.json](results.json): matches/bindings, complete/unknown, budgets, tiempos, hash del runner/corpus/motor y commit de base.
- [inventory.json](inventory.json): contenido y hash de los 33 TOML auditados.
- [reviews.json](reviews.json): revisión individual de las 91 variantes agrupadas en las 33 raíces.
- [runner](../../../examples/bench/audit_catalog_semantics.py): reproduce los casos sin ejecutar los programas fuente.

```sh
.venv/bin/python examples/bench/audit_catalog_semantics.py \
  --cases docs/structural-validation/catalog-adversarial-2026-09-14/cases.json \
  --output /tmp/ken-catalog-audit-results.json
```

Para comparar después de una corrección, conservar el oráculo y cambiar sólo el motor: un FP debe pasar a TN y un FN a TP. No actualizar expected con el resultado observado. No marcar un caso incompleto como TN, ni reinterpretar el silencio de una variante no implementada como detector que acertó un negativo.
