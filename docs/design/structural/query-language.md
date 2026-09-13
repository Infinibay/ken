# KenQL: lenguaje de consulta propuesto

Estado: especificación de diseño. Una parte de esta sintaxis ya está implementada;
otras extensiones siguen propuestas. Para ejemplos ejecutables y límites del
parser actual, consultar la [guía operativa](../../structural-queries.md).
Volver al [índice](README.md).

## 1. Una consulta, muchos usos

KenQL selecciona entidades y une relaciones del IR. Guardar la consulta permite
reutilizarla y adjuntar un nombre, explicación, tags o severidad. Ninguna palabra
reservada `bug`, `pattern` o `gof` cambia el evaluador.

Ejemplo inicial, adaptado al caso del usuario:

```kenql
query user_filters {
  variable(name: /^user.*/i, declared: true) as $user;
  any {
    variable(type_family: string) as $user;
  } or {
    variable(type_state: unknown) as $user;
  }
  method(return_family: [string, boolean]) as $method {
    has_parameter(position: 0, type_family: integer) as $position;
    has_parameter(name: /^filter.*$/i, type_family: string) as $filter;
  }
  require $method READS $user;
  emit $method, $position, $filter, $user;
}
```

`READS` en este ejemplo es una vista de los accesos cuyo owner es el método, sin
incluir cuerpos de funciones anidadas. Encontrar dos declaraciones en el mismo
archivo no crea esa relación. Si el tipo de retorno también puede ser desconocido,
se agrega una alternativa sobre `return_type_state`, explícitamente.

## 2. Forma, tokens y valores

Una consulta tiene `query ID { ... }`, cláusulas terminadas en `;`, comentarios
`# hasta fin de línea` y al menos un selector o relación positiva. UTF-8 para texto;
IDs de variables `$nombre`; nombres de relaciones registrados en mayúsculas;
nombres de atributos y selectores en minúsculas. Alias obligatorios para todo rol
que se quiera reusar o emitir. Sin alias se genera un rol existencial no emitible.

Los valores admitidos son strings JSON con comillas dobles, enteros decimales,
booleanos, `null`, enums registrados, listas de alternativas y regex. `*` en un
predicado no impone filtro. Una lista significa OR entre sus elementos; no es el
constructor de una unión de tipos del IR. Las listas vacías son error.

`unknown` solo es un enum válido de propiedades de conocimiento. No es un valor
universal que coincide con información ausente. Un atributo ausente no coincide
con `null`, `false` ni `0` y su comparación produce desconocimiento. Si un atributo
no existe en el schema del selector, la consulta es inválida.

Regex `/expresión/ims` usa búsqueda sobre el string; `^...$` exige toda la cadena.
El contrato portable propuesto es un subconjunto regular: sin backreferences,
lookaround ni ejecución; tamaño máximo 512 caracteres. Una implementación con
motor más permisivo debe rechazar lo que queda fuera del contrato. `glob` se
reserva para rutas mediante `path_glob: "src/**/*.py"`, con semántica documentada:
`*` dentro de un segmento, `**` entre segmentos, rutas normalizadas con `/`.
Los límites exactos de costo se validan con benchmarks antes de congelar la API.

## 3. Selectores

| Selector | Selecciona | Filtros ilustrativos |
|---|---|---|
| `module` | unidad lógica | name, language, path_glob |
| `type_decl` | declaración de tipo | name, native_kind, visibility |
| `class`, `interface` | azúcar para formas nativas registradas | name, language |
| `callable` | cualquier función ejecutable | name, async, generator, visibility |
| `method` | callable con owner de tipo | name, static, return_family |
| `function` | callable libre | name, return_type_state |
| `closure` | callable anónima con captura | language, capture_mode |
| `parameter` | slot de firma | position, name, kind, receiver, type_family |
| `variable` | storage declarado o referenciado | name, declared, storage_kind, type_state |
| `value` | valor abstracto | kind, mutable, allocation_kind |
| `call` | operación de llamada | name, dispatch, resolution |
| `operation` | operación normalizada | kind, native_kind, language |
| `resource`, `context` | recursos y ejecución | resource_kind, context_kind |
| `entity` | cualquier entidad | kind, name |

`class` no incluye automáticamente structs o traits; una regla portable usa
`type_decl` o roles por relaciones. Un `function` y un `method` no son sinónimos.
`call(name: "join")` inspecciona texto del sitio: no prueba que sea un thread join.
Para eso se consulta `JOINS`, derivado de un modelo de API resuelto.

Los filtros exactos usan `name: "load"`; regex son opt-in. Filtros combinados dentro
de `(...)` se conjugan. Para comparar magnitudes o bindings se usa `where`.

## 4. Relaciones, nesting e identidad

```kenql
query product_flow {
  callable() as $factory;
  require $factory RETURNS_NEW $product;
  call() as $creation;
  require $creation TARGET $factory;
  require $creation RESULT $result;
  path $result VALUE_FLOW{1,6} $consumed as $flow;
  call() as $consumer;
  require $consumer ARGUMENT $argument;
  require $argument VALUE $consumed;
  emit $factory, $creation, $consumer, $flow;
}
```

`RETURNS_NEW` y `RESULT` son vistas públicas con expansión explicable. Las vistas
pueden tener firmas diferentes: `RETURNS_NEW` relaciona callable con tipo del
producto, mientras que `RETURNS_VALUE` la relaciona con valor abstracto.

Una variable repetida exige la misma identidad, no el mismo nombre. Dos variables
pueden coincidir salvo `different $a $b;`. `_` es un existencial fresco por aparición;
no enlaza cláusulas. Una variable solo introducida en una negación no escapa de ella.

```kenql
query signature {
  method(name: "find") as $m {
    has_parameter(kind: keyword_only) as $p;
  }
  emit $m, $p;
}
```

Equivale a un selector de método, `require $m HAS_PARAMETER $p;` y un selector de
parámetro. Nesting es azúcar de relación, no contención arbitraria de texto.
`has_argument` selecciona ocurrencias de argumento; se accede al valor con `VALUE`.
`used_by` debe expandir la relación inversa declarada por el selector, nunca adivinar
si el usuario quiso un read, un call o una importación. Se prefieren formas explícitas
`called_by`, `read_by`, `imported_by` para evitar esa ambigüedad.

Las aristas se filtran con atributos entre corchetes:

```kenql
query possible_dispatch {
  call() as $c;
  require $c TARGET $target [modality: may];
  emit $c, $target;
}
```

Consultar explícitamente una arista `may` confirma que existe ese candidato, no que
se ejecuta en runtime. En modo estricto, solo la pertenencia al conjunto de candidatos
queda demostrada; el resultado incluye esa distinción en la evidencia.

## 5. Restricciones, alternativas y evidencia opcional

```kenql
query construction {
  type_decl() as $builder;
  any {
    require $builder HAS_METHOD $finish;
    require $finish RETURNS_NEW $product;
  } or {
    require $builder HAS_METHOD $finish;
    require $finish RETURNS_STORED_PRODUCT $product;
  }
  optional {
    require $director CALLS $finish;
  }
  emit $builder, $finish, $product;
}
```

`any ... or ...` es unión de soluciones. Todas las ramas deben enlazar los roles
usados después, con tipos compatibles. Roles exclusivos de una rama son locales.
Cada rama puede tener `variant: "immutable"` en metadatos de regla o nombre en la
representación compilada; no puede alterar el significado de primitivas.

`optional` agrega evidencia a un resultado ya válido. No inventa resultados cuando
fallan restricciones obligatorias. Sus roles son opcionales y no se pueden usar en
una obligación posterior. Las evidencias opcionales se agrupan por binding
principal; no multiplican resultados como un producto cartesiano accidental.

`where $a.name == $b.name;`, `where $p.position >= 1;` y `different $a $b;` son
comparaciones sobre valores o identidad. No permiten funciones Python, acceso al
filesystem ni código arbitrario. Los operandos deben estar ligados positivamente.
No hay conversión implícita de string `"1"` a entero `1`.

## 6. Negación y lógica de conocimiento

```kenql
query missing_local_release {
  operation(kind: lock_acquire) as $acquire;
  require $acquire ACQUIRES $lock;
  require $acquire OWNER $owner;
  not exists {
    operation(kind: lock_release) as $release;
    require $release OWNER $owner;
    require $release RELEASES $lock;
  } within callable($owner);
  emit $acquire, $lock;
}
```

Esta consulta pide ausencia de un release **en el cuerpo**. No demuestra que el lock
quede bloqueado: un RAII guard, un helper, una transferencia de ownership o el
llamador pueden liberarlo. Una regla de fuga debe agregar el análisis de salidas,
escapes y modelos de recursos descrito en los casos de uso.

Semántica de una proposición sobre el scope elegido:

| Evidencia | Resultado |
|---|---|
| Hecho que satisface la proposición | true |
| No hay hecho y la relación pertinente está completa | false |
| No hay hecho y la relación no está completa | unknown |
| Hecho solo posible para una proposición de target exacto | unknown |

`not true = false`, `not false = true`, `not unknown = unknown`. En conjunción,
false domina y unknown se conserva si nada es false. En disyunción, true domina y
unknown se conserva si nada es true. El planificador debe preservar esta semántica
al reordenar cláusulas. Una consulta sin bindings candidatos no puede enumerar todo
lo desconocido del universo; reporta además brechas de cobertura a nivel de análisis.

Un error de parsing de consulta es error, no `unknown`. Agotar el presupuesto deja
la ejecución parcial, no convierte las filas pendientes en resultados negativos.

## 7. Cardinalidad y cuantificadores

```kenql
query several_products {
  type_decl() as $factory;
  count distinct $method >= 2 {
    require $factory HAS_METHOD $method;
    require $method RETURNS_NEW $product;
  };
  emit $factory;
}
```

El grupo está correlacionado por `$factory`; `$method` y `$product` son locales al
conteo. Distinct exige identidad: dos evidencias de la misma arista no son dos
métodos. Para contar tipos de producto distintos se cuenta `$product`.

El motor representa un intervalo `[observados, máximo]`, donde máximo puede ser
infinito si la cobertura está abierta. `>= 2` se confirma al observar dos; `= 0`,
`<= 2` o `= 2` requieren cerrar el conjunto pertinente. Si hay truncamiento del
solver no se afirma completitud aunque la relación fuente fuera completa.

La cuantificación universal se expresa como ausencia de contraejemplos dentro de
un scope cerrado. No introducir `all` como un atajo que ignora archivos no parseados.

## 8. Caminos y contexto

`path $a REL{min,max} $b as $witness;` requiere bounds explícitos, inicialmente
`0 <= min <= max <= 32`. `{0,4}` permite identidad; `{1,4}` exige al menos una
arista. Se rechazan `REL+` y `REL*` sin límite: ningún corte oculto de 16 saltos.
La elección de 32 es un límite inicial del producto, no una propiedad del código.

Los resultados se deduplican por extremos y bindings emitidos; el witness es un
camino canónico más corto, con desempate estable. Los ciclos no producen infinitas
filas. Si se quieren todos los caminos, será otra capacidad con presupuesto
explícito; no está en el núcleo inicial.

`VALUE_FLOW` no significa contaminación. Una suma depende de sus operandos pero no
conserva su identidad. Una búsqueda de taint usa un modelo de transferencias y
sanitización, con el contexto de sink correspondiente. Caminos interprocedurales
requieren retornos compatibles con sus sitios de llamada; concatenar aristas sin
contexto puede combinar dos invocaciones incompatibles.

## 9. Exactitud y flexibilidad

Parámetro de ejecución `evidence_mode`:

| Modo | Resultado admitido |
|---|---|
| `strict` (defecto) | Todas las obligaciones demostradas dentro del modelo declarado |
| `possible` | También bindings con obligaciones pendientes, marcados candidate |

`strict` no significa «intención GoF probada». Una regla que solo pide forma sigue
confirmando forma. No habrá un slider ambiguo que cambie el significado de los
predicados. La flexibilidad se expresa con alternativas, tipo por familia,
compatibilidad explícita, regex, relaciones may y cláusulas opcionales.

Una regla puede ofrecer variantes `shape`, `usage` o `protocol` como metadatos,
mostrando cuáles se cumplieron. La puntuación ordena evidencia opcional; no se
presenta como probabilidad de que el software contenga un bug.

## 10. Proyección, resultados y explicación

`emit` define los bindings que identifican una coincidencia. Los roles internos se
conservan en explicación sin generar duplicados visibles. Orden por regla, ruta,
span y bindings estables; un límite parcial no promete los mejores resultados
globales si faltó explorar candidatos.

Respuesta conceptual:

```json
{
  "query_version": "draft-2",
  "execution": {"complete": false, "reason": "max_states", "visited_states": 50000},
  "analysis": {"coverage_complete": false, "unresolved_calls": 3},
  "matches": [{
    "rule_id": "team.construction",
    "status": "confirmed",
    "claim": "structural-signature",
    "bindings": {"builder": "entity:17", "product": "entity:82"},
    "evidence": ["edge:201", "edge:309"],
    "assumptions": [],
    "missing_capabilities": [],
    "locations": [{"path": "src/build.py", "line": 9}]
  }]
}
```

`explain` muestra selector inicial, índices usados, joins, estimaciones vs conteos,
razón de unknown, expansión de vistas y evidencia fuente. En una respuesta parcial
cada match ya confirmado sigue siendo válido; lo incompleto es la enumeración.

## 11. Reglas guardadas y colecciones

Formato propuesto, usando archivo de consulta para facilitar revisión:

```json
{
  "version": 2,
  "rules": [{
    "id": "team.constructor",
    "name": "Construcción de productos",
    "query_file": "queries/construction.kenq",
    "description": "Relaciona construcción con producto devuelto.",
    "tags": ["architecture", "construction"],
    "collections": ["team"],
    "severity": null,
    "recommendation": "Revisar si esta responsabilidad está agrupada.",
    "claim": "structural-signature"
  }]
}
```

`query` inline y `query_file` son excluyentes. Las rutas son relativas a la biblioteca
que las declara, deben permanecer dentro de la raíz permitida y nunca ejecutan
código. IDs duplicados son error; override exige una operación explícita y auditable.
Bibliotecas se versionan y declaran schema/semantics requeridos. Cambiar tags no
cambia resultados de ejecutar la consulta.

Interfaz prevista, pendiente de implementación:

```sh
ken structural search --query-file queries/construction.kenq
ken structural search --rule team.constructor
ken structural search --collection gof
ken structural search --tag concurrency --evidence-mode possible
ken structural rules --collection gof
```

Varios valores del mismo selector se unen; dimensiones diferentes se intersectan.
Query inline y selección de reglas no se mezclan en una misma invocación. Cargar
una biblioteca no ejecuta todas sus reglas implícitamente: sin consulta o selección
explícita se informa error. Los comandos antiguos pueden conservarse como aliases.

## 12. Gramática de referencia y validación

EBNF abreviada; `predicate` y `comparison` usan los valores tipados definidos arriba:

```ebnf
query       = "query", identifier, "{", clause+, "emit", projections, ";", "}" ;
clause      = selector | relation | path | comparison | different
            | alternative | optional | negative | cardinality | named_match ;
selector    = selector_name, "(", predicates?, ")", ("as", variable)?,
              (";" | "{", nested_selector*, "}") ;
relation    = "require", term, relation_name, term, edge_filters?, ";" ;
path        = "path", term, relation_name, "{", integer, ",", integer, "}",
              term, "as", variable, ";" ;
comparison  = "where", operand, comparator, operand, ";" ;
different   = "different", variable, variable, ";" ;
alternative = "any", block, ("or", block)+ ;
optional    = "optional", block ;
negative    = "not", "exists", block, "within", scope, ";" ;
cardinality = "count", "distinct", variable, comparator, integer, block, ";" ;
block       = "{", clause+, "}" ;
named_match = "match", string, "(", role_bindings?, ")",
              ("as", variable)?, ";" ;
term        = variable | "_" ;
```

La gramática completa será un artefacto de la siguiente fase, antes del parser.
Validaciones estáticas: relaciones y atributos registrados, tipos de extremos,
roles ligados, ramas compatibles, negación acotada, bounds y costos, dependencias
nombradas acíclicas y vistas sin ciclos. Diagnósticos con archivo, línea, columna y sugerencia.

No se incorporan inicialmente joins arbitrarios sobre texto fuente, funciones de
usuario ejecutables, SQL libre, recursión no acotada ni auto-fixes. La composición
por vistas públicas debe bastar para el catálogo; si no basta, se revisa el núcleo.

## 13. Consultas nombradas como relaciones

`match "gof.factory-method"(factory: $factory, product: $product) as $proof;`
reutiliza una consulta por sus roles públicos. `emit factory = $internal;` define
esos nombres; `emit $factory;` conserva la forma abreviada. El handle `$proof`
representa evidencia, no una entidad del IR. Véase la [especificación de
composición](composition.md) para identidad, tipos, variantes, negación, dependencias
y caché transitiva. Los patterns son consultas nombradas con metadata, sin otro
evaluador.
