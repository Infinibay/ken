# AST común, contextos y almacenamiento

Estado implementado, 14 de septiembre de 2026. El modelo fuente común está en
`src/ken/common_ast/`; su persistencia en `src/ken/structural_store/common_ast.py` y
su adaptación a KQL en `src/ken/kql2/source_ast.py`. El contrato es `common-ast/1`.
[Validación y mediciones](../../structural-validation/common-ast-2026-09-14/README.md).

## Pipeline y alcance

```text
fuente → Tree-sitter → operaciones fuente del frontend → normalize(IR) → Program
                                                                        ↓
                                           SQLite: AST, scopes, símbolos, referencias
                                                                        ↓
                                                     selectores y relaciones KQL2
```

El paso de normalización reutiliza los nodos nombrados de Tree-sitter conservados
por el frontend; no vuelve a parsear. Produce registros propios e identidades
propias. Las entidades/hechos del IR anterior siguen disponibles como puente para
los análisis semánticos y BODY existentes. No se ha sustituido todo el linker.
El catálogo TOML ya utiliza el [perfil de grafo KQL 2](graph-queries.md). `src/ken/kql2/syntax/ast.py` representa **la consulta**;
no es el AST del programa fuente.

Se integran los nueve lenguajes del frontend estructural actual: Python,
JavaScript, TypeScript, Java, C#, C++, Go, Rust y Ruby. Esto no equivale a soporte
semántico completo de cada lenguaje ni extiende el frontend a PHP, C o Kotlin.
Las formas no reconocidas se conservan como `opaque`, con `native_kind`, rango y
la bandera `normalization_unknown`. El árbol no omite esos subárboles. Los nodos
ERROR conservan categoría opaca y los diagnósticos del frontend.

## Registros e identidades

| Registro | Contenido |
|---|---|
| `Program` | Path, lenguaje, versión, nodos, scopes, símbolos, referencias, enlaces y diagnósticos |
| `Node` | ID local, kind/category, parent, ordinal, role/native_role, native_kind, source_id, inicio/fin UTF-8, línea, scope, owner heredado, propiedades y fin del subárbol |
| `Scope` | ID, padre contextual, nodo introductor, kind, nombre, namespace completo, padre de lookup, directivas global/nonlocal |
| `Symbol` | ID, nombre, scope, declaración, clase de binding, source_id, visibilidad/inicialización aproximadas, tipo nativo/familia, mutabilidad y metadatos de parámetro |
| `Reference` | Nodo de la ocurrencia, nombre, scope, modo read/write/read_write/member, símbolo opcional, estado, disponibilidad y razón |
| `Link` | Origen, relación, destino y ordinal: operandos, condición/cuerpo/alternativa/init/step y argumentos |

Los IDs enteros son locales a una unidad inmutable. Su identidad completa incluye
snapshot/revisión y unidad. No comparar IDs numéricos de dos archivos, ni asumir
que se mantienen después de editar. `source_id` enlaza con el frontend anterior;
**no define** la identidad del símbolo común: dos `let x` de Rust pueden tener
símbolos distintos aunque el IR anterior haya agrupado sus STORAGE.

Los nodos siguen preorden. Los descendientes de `n` cumplen
`n.id < child.id < n.subtree_end`; esto permite contención en O(1) y recorrido
acotado por rango. Los hijos mantienen ordinal, papel y rango dentro del padre.
No se almacenan todos los pares ancestro/descendiente. El orden es sintáctico,
no una prueba de ejecución, dominancia o flujo de valores.

`Program.validate()` valida IDs, rangos, relaciones de parentesco y referencias.
`Program.to_dict()/from_dict()` permite roundtrip JSON. El codec de SQLite es otro:
registros posicionales y strings internados, sin pickle.

## Vocabulario normalizado

La tabla auditable está en `common_ast/kinds.py`; se complementa con metadatos
extraídos por el frontend en `normalize.py`.

* Declaraciones: módulo, package/namespace, tipo, implementación Rust, callable,
  parámetros, variables, import/export y declaraciones anotadas.
* Expresiones: identificadores, llamadas, miembros/referencias cualificadas,
  indexación y slices, literales, interpolación, arrays/listas, maps, sets, tuplas,
  operadores, asignación, borrow/pointer, spread, yield y await.
* Control/regiones: if/elif/else, condición ternaria, for/while/do/loop,
  match/switch, return/break/continue/throw, try/catch/finally, recursos y locks.
* Concurrencia sintáctica: Go spawn/defer/send/select y Rust async block. Una
  llamada a una biblioteca de threads sigue siendo una llamada; su nombre por sí
  solo no acredita concurrencia ni sincronización.
* Agrupadores: bloques, parámetros, argumentos, patrones y fragmentos de literal.
  Paréntesis se conservan; no crean un scope léxico por sí solos.

Los selectores `node`, `expression`, `statement` usan una categoría principal.
Por ejemplo `assignment` es una expresión y puede estar dentro de un
`expression_statement`; no buscar todas las asignaciones con `statement`.
`node {kind:"assignment";}` es la vista independiente de esa categoría.
El modelo conceptual de vistas múltiples del documento `code-model.md` es más
amplio que esta clasificación inicial.

Un `for` C conserva init/condition/step/body y continue. No se reescribe a un while
que pueda saltarse el step. Yield/delegación/await se distinguen: la normalización
no identifica un generator con un Iterator manual. Las diferencias pertenecen a
variantes de una consulta/patrón. Los tokens `&&`, `||`, `!`, `:=` se normalizan a
`and`, `or`, `not`, `=` conservando la forma nativa del nodo.

`type_kind` es una familia sintáctica, no un tipo inferido completo. Los símbolos
conservan `native_type`; se usa el parser de TypeRef existente. Distingue int,
float, bool, char, str, list/array, map, set, tuple, any, unknown, tipos nominales,
referencias y otros constructores. `list` y `array` son categorías diferentes del
TypeRef existente. No demuestra subtipado, trait implementation, API identity ni
que una operación sobre un objeto sea válida. Sin anotación puede ser unknown.
Los literales guardan texto exacto, incluso strings con fragmentos nombrados.
Un string interpolado no se acredita como constante.

## Parámetros y argumentos

Cada parámetro es un símbolo con `parameter_kind`: positional_only, positional,
keyword_only, variadic_positional o variadic_keyword cuando el frontend lo conoce.
`position` enumera parámetros ordinarios sin receptores ni separadores gramaticales;
`native_position` conserva la posición nativa. Las banderas identifican receptores.

La ocurrencia que representa un argumento lleva `argument_kind`, `argument_name`,
`source_position` y `argument_position`. `source_position` es el ordinal escrito;
`argument_position` es una posición efectiva acreditada, o None si depende de un
pack. No expandir `*args`, `**kwargs` o `...xs` por su nombre.

```python
consume(x, *xs, flag=value, **kw)
# positional(0), spread_positional(?), named(flag), spread_named(?)
```

Un `y` después de `...xs` no tiene una posición efectiva conocida. Una consulta que
exija `argument_position: 1` produce un candidato unknown, no un negativo seguro.
La etiqueta `flag` de un keyword argument no es una lectura de una variable local.
Los argumentos se enlazan además desde la llamada con la relación `argument`.

## Contextos, namespaces y lookup

La representación distingue padre sintáctico, padre contextual y `lookup_parent`.
Los scopes contienen un namespace cualificado internado; los nodos sólo guardan
el ID del scope. Los ámbitos anónimos comparten texto de namespace, conservando su
propio ID. Java/Go incorporan el package; namespaces/clases/métodos extienden el
nombre. Los nombres no equivalen a resolución nominal de tipos entre archivos.

Perfiles verificados:

* Python: ámbito local de función, global/nonlocal persistidos, lookup de métodos
  que salta el namespace de clase, defaults evaluados en el scope de definición,
  comprensión aislada y primer iterable evaluado fuera de ella; alias de recursos.
* JS/TS: var en el callable y let/const de bloque, hoisting y TDZ, shadowing.
* Rust: cada let tiene identidad, el inicializador puede leer el binding anterior;
  closures y async blocks tienen contexto de ejecución propio.
* Ruby: métodos nombrados no heredan variables locales exteriores; parámetros de
  bloques capturantes tienen su propio scope. Resolución completa de constantes,
  redefiniciones dinámicas y todas las reglas de asignación en bloques no se acredita.
* Los lenguajes de bloque crean scopes para los bloques/for/catch modelados.

Los imports son bindings léxicos externos, sin fingir que se resolvió su destino.
Hay aliases Python/JS/TS, imports Java simples, aliases C#, imports Rust agrupados
con aliases e imports Go explícitamente renombrados. `using Namespace` de C# no
introduce una variable local llamada Namespace. Go sin alias requiere conocer el
package del módulo importado: **no se adivina por el último componente del path**.
Imports wildcard, macros, dispatch, atributos, overloads y targets entre módulos
requieren análisis adicional y pueden quedar unknown.

`Environment.resolve(name, scope, byte_offset)` separa dos resultados:

* `status=known`: identidad léxica resuelta; no es garantía de inicialización.
* `availability=available/unavailable/unknown`: evidencia sintáctica conservadora.

Una lectura JS let antes de su inicializador puede resolver el símbolo correcto y
estar unavailable. Entre distintos contextos de ejecución, bajo inicialización
condicional, del/exec/eval u otras incertidumbres modeladas se conserva unknown.
La búsqueda no atribuye automáticamente disponibilidad a todo nombre del padre.
No es un verificador completo de definite assignment: borrow/move, escapes,
excepciones, alias/heap, deletes transitivos y lifetime necesitan sus propios
análisis. Una referencia externa sin resolver no prueba inexistencia.

## Consultas ejecutables

```kql2
language "kql/2";
module examples.ast;
query returns {
    node $return { kind: "return"; }
    select $return.path, $return.line, $return.namespace;
}
```

```kql2
language "kql/2";
module examples.bindings;
query local_uses {
    node $declaration { kind: "binding_declaration"; name: /^user/i; }
    node $use { kind: "identifier"; }
    where same_symbol($declaration, $use);
    select $declaration.path, $declaration.line, $use.line;
}
```

Si hay nodos opacos, los dominios clasificados no acreditan ausencia: una
negación/cuántificación puede producir unknown. Un selector positivo sigue
encontrando los nodos reconocidos.

Los dominios `CodeNode`, `Expression`, `Statement` sirven para `from`, cuantificadores,
composición y anti-joins. Se admiten selectores AST anidados; significan hijos
sintácticos inmediatos. No se anidan bajo un selector legacy `class`/`callable`:
para eso seleccionar el nodo común de declaración y usar su contención.
El compilador rechaza esa mezcla antes de escanear el proyecto.

Relaciones:

| Relación | Semántica actual |
|---|---|
| `contains(a,b)` | Descendiente sintáctico estricto, incluye código inalcanzable y cuerpos anidados |
| `contains_direct(a,b)` | Padre sintáctico inmediato |
| `same_symbol(a,b)` | Las ocurrencias/declaraciones tienen el mismo símbolo resuelto |
| `visible_at(a,b)` | El símbolo de a es el binding léxico seleccionado en el contexto/punto de b |
| `initialized_at(a,b)` | Lo anterior y evidencia sintáctica de inicialización; puede producir unknown |

Propiedades adicionales: kind, category, role, operator, text, type_kind,
namespace, scope_kind, normalized, start_byte, end_byte, line y los cuatro campos
argument_* / source_position. Más las comunes name/path/language/native_kind.
`normalized` sólo indica que el nodo tiene clasificación; **no certifica** sus
hijos ni una operación semántica. `stable_id()` expone un identificador local legible (path + ID de nodo);
para usarlo fuera de la consulta hay que acompañarlo de su snapshot/revisión.

API de normalización:

```python
from ken.common_ast import parse
from ken.common_ast.environment import Environment
p = parse('def f(x):\n return x\n', 'python', 'example.py')
env = Environment(p.scopes, p.symbols, language=p.language)
for ref in p.references:
    print(ref.name, env.resolve(ref.name, ref.scope, p.nodes[ref.node].start))
```

## Persistencia, índices, cache y migración

Schema **6** agrega `k2_ast_units`, `k2_ast_strings`, `k2_ast_nodes`, `k2_ast_scopes`,
`k2_ast_symbols`, `k2_ast_references` y `k2_ast_links`. IDs enteros y strings
internados por unidad; registros compuestos `WITHOUT ROWID`. No se copia el mapa
completo de nombres disponibles en cada if/while/paréntesis.

Índices: nodos por kind/name, padre+ordinal y scope; scopes por namespace; símbolos
por scope+name+visible_from; referencias por símbolo y enlaces por destino.
`View.nodes()` permite filtro por tipo/nombre/padre/scope/subárbol;
`View.declarations()` lookup local indexado y `references_to()` referencias inversas.

Las unidades nuevas se normalizan y persisten en la transacción de `put_unit`.
Migración 5→6 agrega las tablas; unidades previas se normalizan desde su IR guardado
al primer acceso. No requiere volver a parsear. Downgrade 6→5 elimina sólo la
proyección común; preserva las unidades y los datos de otras bases. Se prueba
rollback/fallback de retención y borrado por cascada. No hay DROP global.

KQL reutiliza el AST guardado sin descomprimir el IR legacy ni invocar el linker
global. Carga strings/scopes por unidad y las filas seleccionadas por índices.
La vista de consulta mantiene LRU de dos unidades; símbolos/referencias y mapas de
lookup se preparan bajo demanda y se reutilizan. Esto limita el número de unidades
retenidas, no es una cuota total de RSS. Una consulta que hace un producto grande
de roles todavía puede ser costosa; contención O(1) no optimiza todos los joins.

El fingerprint de frontend incluye el código del normalizador. Un cambio de fuente,
normalizador o gramática genera otra unidad y snapshot; resultados y planes usan
sus claves de contenido/revisión. El AST se guarda en la misma cache en disco
`.ken/structural/v2/store.sqlite`, con configuración default 500 MB y cache 0
soportado. El límite es de retención: ver las restricciones de RAM/WAL/temporales
que siguen vigentes en [estado de implementación](implementation-status.md).

## Lo que esta entrega no completa

El AST común consultable y persistido está implementado para el frontend actual.
No equivale a terminar todos los motores semánticos: faltan las partes documentadas
de BODY/control explícito, produced values, alias/heap/preserve, efectos transitivos,
protocolos/iteración/concurrencia, disponibilidad runtime completa. La migración TOML usa los hechos semánticos existentes.
Un código conservado como árbol puede consultarse sintácticamente aunque todavía
no exista un análisis que pruebe su algoritmo o sus efectos.
