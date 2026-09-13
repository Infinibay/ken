# Consultas estructurales de Ken

Esta guía describe KenQL `kenql/1` sobre IR **1.47.0**. La [especificación de diseño](design/structural/README.md)
contiene además capacidades futuras; no todas sus variantes están implementadas.

Para diseñar una búsqueda, empezar por [las construcciones disponibles](#lenguaje-disponible)
y [la composición mediante operaciones públicas](#operaciones-públicas-reutilizables).
La [referencia del grafo](structural-ir.md#representation-contract) distingue
operandos fuente y valores de consulta; [IR y precisión](#ir-y-precisión) explica
los estados y límites que hay que consultar antes de interpretar un resultado vacío.

## Consultas nombradas

Los extremos de `require` y `path` aceptan cadenas JSON entre comillas dobles.
Se comparan de forma exacta: `"$handler"`, `"_"` y `"A|B"` son valores literales,
no variables, comodines ni alternativas. Sin comillas, `$handler` vincula un rol
y `_` acepta cualquier extremo. Las cadenas admiten escapes JSON y Unicode;
los escapes inválidos se rechazan al parsear la consulta. Esto también se conserva
al componer consultas mediante `match`.

```kenql
query derives_clone {
  type_decl(language: rust) as $type;
  require $type DERIVE_NAME "Clone";
  emit $type;
}
```

Esta consulta identifica el atributo sintáctico; no demuestra cómo expande una
macro ni que la copia sea profunda.

```kenql
query product_flow {
  match "gof.factory-method"(
    factory: $factory,
    product: $product
  ) as $factory_match;
  call() as $creation;
  require $creation TARGET $factory;
  require $creation RESULT $result;
  call() as $consumer;
  require $consumer ARGUMENT $argument;
  require $argument VALUE $result;
  emit $factory, $creation, $consumer;
}
```

Guardar el texto en `product-flow.kenq` y ejecutar:

```sh
ken structural search --query-file product-flow.kenq
ken structural search --rule gof.iterator
ken structural search --rule 'gof.iterator#generator'
ken structural search --rule 'gof.builder#mutable-product'
ken structural rules --collection gof
ken structural ir --scope src/example.py --view query
```

El resultado incluye bindings, evidencia de las consultas usadas, localizaciones,
razones de incertidumbre, dependencias y estadísticas. Los roles de un `match`
siempre corresponden a una misma coincidencia; omitir un rol lo vuelve existencial.
Aliases internos de otras consultas no capturan variables del llamador.

Cuando varias derivaciones producen los mismos bindings públicos, Ken devuelve
una coincidencia y conserva pruebas alternativas en `evidence`. Cada grupo tiene
esta forma (los objetos de evidencia se abrevian aquí):

```json
{"alternatives": [
  {"evidence": [{"query": "pattern#variant-a"}], "unknown": []},
  {"evidence": [{"query": "pattern#variant-b"}], "unknown": ["possible:TARGET"]}
], "truncated": false}
```

Las alternativas son disyuntivas: sus testigos no se pueden combinar entre sí.
Los elementos consecutivos de una lista de evidencia pertenecen a la misma
derivación. Esto también vale para hechos posteriores a un `match` que proyecta
solo algunos roles. Una prueba cierta basta para que la coincidencia sea
`structural_match`; la incertidumbre de otra alternativa queda asociada a esa
prueba. Esto certifica la forma estructural, no la intención del patrón.

Se conservan hasta 16 alternativas por grupo, priorizando pruebas sin razones de
incertidumbre. `truncated: true` indica que se omitieron pruebas adicionales; no
significa que falten coincidencias ni cambia `complete`. El límite es por grupo,
no un límite global de bytes de evidencia. Los consumidores deben recorrer los
grupos anidados para mostrar las variantes y consultar `complete` por separado
para saber si la enumeración agotó su presupuesto.

`gof.iterator` une las variantes habilitadas con el rol público `iterator`:
generación, delegación de generador, cursores Python y el protocolo Java pareado. `gof.builder` une construcción
mutable, director y producto almacenado con los roles `builder`, `finish`, `product`. Un director debe
invocar la finalización además de los pasos; la variante mutable conecta el campo
con un argumento del objeto realmente devuelto.

### Operaciones públicas reutilizables

Un patrón puede exponer consultas de uso en `[[operations]]` de su TOML.
Se invocan con el mismo `match` y sus roles públicos, sin copiar la implementación
ni exigir automáticamente una coincidencia del patrón completo. El catálogo
actual expone estas quince operaciones con estado `ready`:

| ID | Evidencia que permite reutilizar |
|---|---|
| `singleton.lazy_instance` | Guardia de nulidad, única escritura explícita y retornos directos del slot por hit/miss; no garantiza sincronización ni unicidad. |
| `singleton.shared_instance` | Campo estático inicializado con su propia clase y accessor estático que devuelve directamente ese slot; no prueba unicidad global. |
| `strategy.supplied_policy` | Última escritura fuente del parámetro configurador a una política, o inicialización de constructor soportada; no exige despacho ni intención de algoritmo. |
| `command.retained_dispatch` | Parámetro con contrato retenido en un campo y llamada a su slot desde otro método del invocador. |
| `iterator.iterate_over` | Fuente, binding del elemento, cuerpo e iteración foreach soportada. |
| `prototype.derived_copy` | Uso modelado de una copia Rust asociada a `derive(Clone)`. |
| `architecture.batch-work-queue.drain` | Registro, iteración, activación y vaciado posterior de trabajo. |
| `architecture.read-through-cache.read_fill` | Consulta con hit/retorno y miss/carga/escritura/retorno. |
| `persistence.unit-of-work.keyed_flush` | Uso modelado de un flush de registros por clave. |
| `factory-method.client_flow` | Resultado de una llamada al slot de creación pasado directamente a un consumidor. |
| `builder.directed_state` | Director y builder mutable correlacionados por builder, finalización y producto. |
| `bridge.returned_primitive` | Origen del retorno de una abstracción refinada vinculado a la llamada a su implementación. |
| `strategy.consumed_policy` | Parámetro pasado a la política suministrada y resultado de esa invocación retornado. |
| `template-method.dependent_steps` | Dos hooks sobre la misma instancia modelada; el primero produce el argumento del segundo. |
| `singleton.observed_lazy_use` | Llamada resuelta al accessor de la instancia lazy seleccionada. |

Las garantías y exclusiones de cada operación siguen siendo las de su consulta.
Las seis operaciones del ejercicio GoF se describen en la
[revisión por algoritmo](design/structural/algorithms/README.md); los TOML conservan
sus límites. Una identidad de storage no prueba estabilidad del valor después de
una reasignación, y las operaciones de uso no sustituyen las variantes canónicas.
`iterator.iterate_over` no es un intérprete que ejecute el cuerpo del programa:
devuelve sus roles en el grafo. Ver el [ejemplo ejecutable y sus límites](structural-ir.md#queryable-types-operators-and-control).
La sintaxis `%iterate_over(...) do … %end`, `%map` y `%filter`/`%select`
sigue siendo una propuesta, no sintaxis aceptada por el parser actual.

## Escrituras y retornos por ocurrencia

Para inspeccionar asignaciones concretas, sin mezclar valores de escrituras
diferentes, se pueden consultar sus operandos:

```kenql
query writes {
  require $write ASSIGNMENT_TARGET $storage;
  require $write ASSIGNMENT_VALUE $operand;
  emit $write, $storage, $operand;
}
```

`$write` es una operación con posición y owner. `RETURN_OPERAND` permite
inspeccionar el operando de un retorno explícito. Estas relaciones son sintácticas:
compartir `$storage` no prueba que esa escritura alcance ese retorno. Los bloques
secuenciales soportados desde IR 1.19.0, y las ramas `if/else/elif` desde 1.20.0,
ofrecen además:

```kenql
query returned_local {
  require $return RETURN_REACHES $write;
  require $write ASSIGNMENT_TARGET $storage;
  require $return RETURN_ORIGIN $origin;
  emit $return, $write, $storage, $origin;
}
```

`RETURN_FLOW_STATUS` documenta por callable si ese pase pudo analizar el cuerpo
con `analysis=structured-locals/3` y estado `supported` o `unsupported`.
Una ausencia de `RETURN_ORIGIN` en un ámbito `unsupported` no prueba ausencia de
flujo. Las ramas unen orígenes posibles; desde IR 1.26.0 las escrituras simples
a miembros de locales conservan estados separados por rama. Los bucles,
escrituras indirectas fuera de ese modelo y ternarios fuera del RHS de un campo
siguen excluidos. `RETURN_REACHES` y
`RETURN_ORIGIN` son proyecciones separadas: en una rama con alternativas, el join
del ejemplo no demuestra que cada combinación de escritura y origen sea un par
factible. `RETURN_FIELD_STATE`, `FIELD_STATE_ORIGIN` y `FIELD_STATE_WRITE`
conservan la correlación entre retorno, asignación nueva y escritura de campo.
Su modalidad `may` requiere `--evidence-mode possible`. Los límites y un ejemplo
ejecutable se detallan en la [guía IR](structural-ir.md).

## Un archivo por patrón y por consulta propia

Las 23 definiciones GoF están en `src/ken/structural/patterns/<id>.toml` y se incluyen
en wheel y sdist. Contienen la firma de compatibilidad, las variantes, sus queries,
estado y requisitos documentados. No están embebidas en una lista Python. El listado
`ken structural rules` expone la ruta de origen y las variantes para inspeccionarlas.

Las consultas propias se descubren en `.ken/rules/*.toml`:

```toml
id = "team.public-functions"
name = "Funciones públicas por convención"
tags = ["architecture"]
collections = ["team"]
query = '''
query public_functions {
  function(name: /^public_/) as $function;
  emit callable = $function;
}
'''
```

```kenql
query callers {
  match "team.public-functions"(callable: $target);
  call() as $call;
  require $call TARGET $target;
  emit $call, $target;
}
```

También se pueden crear con `ken structural save-rule team.rule --query-file rule.kenq`.
`--overwrite` reemplaza una consulta propia. Cada archivo se escribe atómicamente,
con lock para serializar guardados concurrentes. Los IDs reservados no se pueden
ocultar con una definición local. `.ken/rules.json` continúa aceptándose como formato
de compatibilidad; una definición duplicada entre bibliotecas produce error.

`--rules-file biblioteca.toml` carga una consulta o una biblioteca JSON versionada
adicional dentro del proyecto; se puede combinar con `--query-file` para resolver
sus dependencias. Cargar una biblioteca por sí solo no ejecuta todas sus reglas.

## Lenguaje disponible

| Construcción | Ejemplo / comportamiento |
|---|---|
| Selectores | `callable`, `method`, `function`, `type_decl`, `parameter`, `variable`, `call`, `value`, `operation` |
| Predicados | `name: "load"`, `name: /^load/i`, `type_family: [string, integer]` |
| Firmas | `method() as $m { has_parameter(position: 0) as $p; }` |
| Relaciones | `require $call TARGET $function;` |
| Composición | `match "team.query"(role: $local) as $proof;` |
| Alternativas | `any { ... } or { ... }` |
| Evidencia adicional | `optional { ... }`, sin multiplicar filas |
| Conteos | `count distinct $m >= 2 { ... };`, correlacionados por roles externos |
| Negación | `not exists { ... } within callable($owner);` |
| Desigualdad | `different $a $b;` |
| Comparaciones | `where $a.name == $b.name;` |
| Caminos | `path $a VALUE_FLOW{0,6} $b as $flow;` |
| Proyección | `emit creator = $internal, $product;` |

Las dependencias de consultas son acíclicas. Se validan IDs, roles públicos y tipos
inferibles antes de escanear archivos. Comparaciones y selecciones de tipos no
permiten ejecución de Python. Regex no acepta backreferences/lookaround y mantiene
un límite de longitud y tiempo. Caminos requieren límites explícitos de 0 a 32;
cero permite identidad. El presupuesto se comparte con las dependencias.
Se conserva el primer testigo por extremo y modalidad de incertidumbre. Los
recorridos que convergen en el mismo nodo a la misma profundidad comparten su
exploración posterior; las profundidades distintas se mantienen para respetar
el mínimo incluso con ciclos. No se enumeran todos los caminos posibles.

`strict` es el modo predeterminado de KenQL: no entrega como coincidencia confirmada
una obligación desconocida. `--evidence-mode possible` incluye candidatos marcados
`unknown`. La negación y los límites superiores/exactos de conteo requieren cobertura
por sujeto y relación. `complete` expresa enumeración del grafo dentro del presupuesto,
no conocimiento exhaustivo del programa.

## IR y precisión

IR 1.47.0 conserva el rol sintáctico de una operación con
`operation(role: [consequence, alternative])`. Proxy y Chain lo usan para ubicar
la llamada concreta en un brazo de una rama, evitando mezclarla con una condición
o con otra llamada. Ese rol nativo no prueba dominancia ni protección de todos
los caminos. El núcleo de instrucciones añade regiones de selección, cortocircuito
e iteración y conserva formas incompletas como `native/partial`.

IR 1.46.0 añade NORMAL_COMPLETION, LOOP_BODY_TAIL y HANDLER_FALLTHROUGH para
describir terminación normal de regiones y Retry sin continue explícito.
El [núcleo de instrucciones](structural-ir.md#instruction-core-and-algorithm-contracts)
se inspecciona mediante `--view instructions`; todavía no sustituye el grafo
que consulta KenQL. La gramática de cuerpos y preserve sigue siendo un contrato
de diseño, derivado de [algoritmos escritos en palabras](design/structural/algorithms-to-ir.md).

IR 1.45.0 publica FIELD_DECLARATION, FIELD_INITIAL_STATUS y FIELD_INITIAL_VALUE,
separando inicializadores explícitos, defaults de lenguaje y ausencia de asignación.
La operación lazy puede reutilizar null implícito de campos Java/C#; no confunde
ese default con undefined de JS ni con anotaciones Python. Los hechos describen
la fase de declaración, sin probar el estado posterior a constructores o métodos.
Ver [relaciones, atributos y ejemplos por lenguaje](structural-ir.md#relation-contract).

IR 1.44.0 expone `singleton.lazy_instance` para componer búsqueda de inicialización
lazy con sus usos; la variante canónica reutiliza esa consulta. NULL_TEST conserva
la polaridad bajo negaciones lógicas explícitas, sin descomponer AND/OR. Ver
[ejemplos y límites](structural-ir.md#lazy-initialization-and-negated-null-tests).

IR 1.43.0 añade atributos de acceso a constructores e inventarios consultables de
declaraciones y sitios de construcción resueltos. La variante eager de Singleton
exige construcción privada declarada y un solo sitio resuelto; la operación
`singleton.shared_instance` conserva su alcance amplio. Ver
[contratos y ejemplos](structural-ir.md#construction-access-and-resolved-allocation-sites).

La vista `query` distingue llamadas, resultados, argumentos y valores leídos de
storage. `ARGUMENT` lleva a una ocurrencia; `VALUE` al valor. `RESULT` lleva de la
operación al resultado. Una lectura tiene `LOADED_FROM`; los flujos de escrituras a
lecturas que no cuentan con prueba de reaching definitions se marcan `may`.

Desde IR 1.27.0, `RETURNS_VALUE` usa `RETURN_ORIGIN` en callables soportados:
un local que conserva una construcción se une directamente a su `RESULT`.
La arista retiene `basis=flow`, modalidad y `return_operation`; las alternativas
may necesitan modo possible. Fuera de ese pase se conserva la proyección previa
con `basis=syntax`. Una consulta puede exigir `[basis: flow]` para evitar mezclar
ambas garantías. Esto no hace precisas las lecturas de argumentos en general.

Desde IR 1.28.0, `CALL_BINDING` identifica cada argumento explícito por llamada;
`BINDING_PARAMETER`, `BINDING_VALUE` y `BINDING_TARGET` preservan su correlación.
`BINDING_VALUE` apunta al operando fuente, no al valor normalizado de `ARGUMENT`.
Los modelos de constructor único y transferencias lineales de campos permiten
Memento con getters y contratos en cinco lenguajes. Ver los
[contratos, estados y límites](design/structural/call-bindings.md); no equivalen
a resolver sobrecargas, argumentos expandidos ni efectos ocultos.

Desde IR 1.29.0, `DECLARED_TARGET` permite consultar el slot nominal de una llamada
sin eliminar sus destinos concretos ambiguos. `CONSTRUCTOR_FIELD_INPUT` vincula
campos con parámetros retenidos por constructores lineales; incluye parámetros-
propiedad TypeScript. State utiliza estas relaciones en `context-transition`.
Ver [semántica, ejemplos y límites](design/structural/state-context-transitions.md).

Desde IR 1.30.0, `call(explicit_arguments: 0)` selecciona llamadas sin argumentos
escritos. `architecture.batch-work-queue.drain` expone un uso de registro, iteración,
activación y vaciado posterior; lo reutilizan Command y la regla moderna de lotes
de trabajo. [Contrato y ejemplos](design/structural/queued-command.md).

Desde IR 1.31.0, `builder#stored-product` enlaza producto interno, configuración
por parámetro y finalización; `prototype.derived_copy` expone roles `unit`,
`receiver` y `copy` para reutilizar usos Rust de derive(Clone). `TYPE_HEAD` separa
la raíz nominal de la anotación escrita. `FINAL_MEMBER_INPUT` y
`MEMBER_FLOW_STATUS` exponen el pase de última escritura lineal en seis lenguajes.
Ver [contratos, consultas y ejemplos](design/structural/stored-product-builder.md).

Desde IR 1.32.0, `builder#mutable-product` exige una escritura final directa del
parámetro mediante `FINAL_MEMBER_INPUT`; ya no basta una ASSIGNED_FROM histórica.
El pase incluye campos directos y gramáticas C++/Go, con estados explícitos para
cuerpos no soportados. Ver [ejemplos, contratos y límites](design/structural/builder-input-writes.md).

Desde IR 1.33.0, `architecture.read-through-cache.read_fill` es una operación
pública que conecta hit/retorno y miss/carga/escritura/retorno. TRUTH_TEST conserva
polaridad simple y UNREASSIGNED_BINDING/UNIQUE_BINDING_WRITE exponen evidencia
positiva del inventario de escrituras. Ver [contratos y ejemplos](design/structural/read-through-cache.md).

Desde IR 1.34.0, `BINDING_WRITE_COUNT` admite filtros como `[count:2]` sobre
asignaciones explícitas por callable. Cache-Aside null-miss lo combina con CFG
y orígenes posibles de retorno para rechazar escrituras adelantadas y rebindings.
Ver [contratos y ejemplos](design/structural/cache-aside-flow.md); el conteo no es
un número de ejecuciones y no extiende las garantías de la variante Java Optional.

Desde IR 1.35.0, `bridge#refined-composition` expone las dos familias, campo y
operación delegada. `NOMINAL_ROOT`/`NOMINAL_ROOT_STATUS` permiten consultar raíces
de bases explícitas resueltas sin convertir información ausente en independencia.
C# corrige el filtro `static` de campos. Ver [contratos y límites](design/structural/patterns/bridge.md).

Desde IR 1.36.0, las consultas sobre campos C++ comparten el slot declarado con
sus usos. `TYPE_QUALIFIER`, `TYPE_HEAD_STATUS` y `CPP_FIELD_DECL_STATUS` exponen
cualificación, disponibilidad del head y normalización del declarador. Ver
[ejemplos y límites](design/structural/cpp-field-declarators.md).

Desde IR 1.37.0, los prototipos de métodos C++ son callables consultables.
`METHOD_SIGNATURE_STATUS` y `VIRTUAL_METHOD` exponen disponibilidad de firmas
y slots virtuales; `OVERRIDES` exige correspondencia de parámetros y cv/ref en
C++. Esto permite detectar formas adicionales de Abstract Factory, Adapter,
Factory Method, Interpreter, Template Method y Visitor con despacho por nombre.
No selecciona sobrecargas de
llamadas ni resuelve firmas externas o templates. Ver [contratos y ejemplos](structural-ir.md#c-method-declarations-and-virtual-signatures).

Desde IR 1.42.0, `architecture.subclass-factory` expone factories que devuelven
clases derivadas de su base suministrada. CLASS_EXPRESSION, BASE_VALUE y
TYPE_ASSERTION_VALUE distinguen ámbito, referencia léxica y aserciones borradas
de TypeScript. Ver [consultas ejecutables](structural-ir.md#class-expressions-base-values-and-erased-assertions).

Desde IR 1.41.0, `singleton.shared_instance` expone inicialización de clase y
accessor directo, y puede componerse con llamadas a ese accessor. TARGET/CALLS
con `basis=direct-class-static` identifica métodos static propios de receptores
de clase ya resueltos; no prueba ejecución ni accesibilidad y excluye propiedades
JS/TS. Ver [ejemplos y límites](structural-ir.md#shared-class-storage-and-static-calls).

Desde IR 1.40.0, `CALLEE_VALUE` preserva identificadores, miembros e indexaciones
llamados entre paréntesis, sin borrar casts ni otras expresiones. La variante
`architecture.dependency-injection#callable-input` reutiliza `strategy.supplied_policy`
y conserva los roles de la variante por objeto. Ambas se ejecutan mediante la
consulta canónica. Ver [ejemplos y límites](structural-ir.md#parenthesized-callee-bindings-and-callable-dependencies).

Desde IR 1.39.0, `FINAL_BINDING_INPUT` y `BINDING_FLOW_STATUS` describen la última
escritura explícita del parámetro a un binding en ocho gramáticas. Strategy usa
`strategy.supplied_policy` para correlacionar esa entrada con el campo y su
configurador; el despacho por objeto exige un slot declarado del contrato.
Los descriptores Python conservan una evidencia de escritura fuente, sin garantía
sobre el valor almacenado. Ver [contrato y consultas](structural-ir.md#last-binding-inputs-and-supplied-policies).

Desde IR 1.38.0, HAS_INITIALIZER/INITIALIZES_FIELD e INITIALIZER_ARGUMENT
representan listas explícitas de constructores C++. CONSTRUCTOR_INITIALIZER_INPUT
es un input sintáctico; CONSTRUCTOR_FIELD_INPUT exige retención después del cuerpo
en el pase soportado. `command.retained_dispatch` reutiliza retención final y
despacho por contrato; la nueva variante `command#retained-contract` agrega la
acción concreta. Ver [relaciones, consultas y límites](structural-ir.md#c-constructor-initializers-and-retained-command-dispatch).

Los tipos nativos y la disponibilidad de información se conservan separados:
`parameter(native_type: "unknown", type_state: known)` encuentra anotaciones
TypeScript explícitas, sin confundirlas con un parámetro sin tipo inferible.
Métodos y funciones libres son selectores distintos. Se preservan operaciones
nativas y spans de bytes. `--view source` permite inspeccionar los hechos anteriores
usados por las consultas de compatibilidad.

Python API:

```python
from ken.structural import evaluate_query, link_project, lower_source

ir = link_project([lower_source("def items():\n yield 1\n", "python", "items.py")])
result = evaluate_query(ir, '''query q {
  match "gof.iterator"(iterator: $i);
  emit $i;
}''')
```

El MCP equivalente es `ken_find(query=..., scope="structure")`, o seleccionar
`rules=["gof.iterator"]` sin query. `evidence_mode="possible"` habilita candidatos.
Las búsquedas semánticas/textuales existentes conservan sus interfaces; también
se conserva `ken tools find "texto" --scope text`.

## Cobertura y pendientes explícitos

Los 23 GoF tienen ahora una consulta canónica ejecutable y tests de fuente en
**Python, Java y TypeScript**: positivos, renombrado de clases, negativos por nombre
y negativos que eliminan una conducta esencial. La [matriz de cobertura](gof-coverage.md)
explica la evidencia exigida y las variantes adicionales por lenguaje.

`patterns`, los IDs cortos y `gof.<id>` ejecutan las consultas nuevas. Las firmas
anteriores requieren el namespace explícito `legacy.gof.<id>`; pueden producir
muchos candidatos débiles. Los archivos conservan esas firmas como `legacy_query`.
El catálogo distingue `executable_variants` y `planned_variants`.

Hay **44 variantes GoF ejecutables** y **33 propuestas de diseño pendientes**,
además de **diez reglas modernas/web**. Tener una
consulta para los 23 conceptos no significa cubrir todas las formas posibles de
implementarlos. Siguen pendientes, entre otras, variantes con typestate, macros,
interfaces estructurales Go, eventos C#, aliasing general y buses de frameworks.
Los frontends aceptan también JS, C#, C++, Go y Rust; la cobertura semántica depende
de la propiedad y no implica que los 23 GoF estén validados en esos cinco lenguajes.
Por ejemplo, una firma C++ con tipos externos no resueltos puede conservar su
callable pero carecer de enlaces OVERRIDES. La ausencia de un match que los necesita
no demuestra ausencia del patrón, incluso si el parser no informa errores.

Los generadores decorados mediante imports de `contextlib.contextmanager` o
`asynccontextmanager` se excluyen de Iterator. Se admite el protocolo Python
con estado local o delegación a `next()`, además del par Java `next`/`hasNext`.
El modelo de decoradores es local y conservador, no ejecución de Python.

Las listas `requires` de los borradores son requisitos de diseño para su desarrollo;
no equivalen a capacidades completas ya certificadas. La certeza efectiva viene
de los hechos y su modalidad, y de la cobertura local que conoce el evaluador.

## Caché y distribución

La caché de IR conserva su límite configurable predeterminado de **500 MB decimales**.
`--cache-mb 0` la desactiva. Los archivos de consultas se releen: editar una dependencia
no reutiliza una evaluación anterior. Durante cada consulta se comparten los
resultados de dependencias con iguales restricciones y scope. En lotes se reutiliza
el índice de la vista de consulta.

El backend actual es Python más las gramáticas tree-sitter. No se incorporó Rust:
el wheel mantiene la instalación habitual con `uv tool install`. La frontera entre
parser, grafo y evaluador permite evaluar un backend nativo después de medirlo.

Verificación: `uv run pytest tests/structural`, `uv run mypy` y
`uv run python examples/bench/structural.py --files 300`. El smoke de wheel comprueba
el catálogo distribuido y una consulta nombrada de generadores desde una instalación
limpia, sin depender del checkout.

## Verificación de los ejemplos

Los bloques KenQL de ambas guías se ejecutan contra fuentes de prueba. Los de
esta guía cargan además su ejemplo TOML como dependencia y tienen controles
negativos que retiran la evidencia necesaria. Para comprobarlos:

```sh
uv run pytest tests/structural/test_documented_ir_queries.py tests/structural/test_documented_kenql_queries.py
```

La [revisión de documentación de IR 1.45.0](structural-validation/ir145-documentation-review.md)
registra ejemplos, contratos, enlaces y verificaciones de esta actualización.
