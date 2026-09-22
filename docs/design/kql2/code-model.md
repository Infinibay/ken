# Modelo consultable del programa

Contrato de diseño 0.1. [Índice](README.md). La base ejecutable y sus límites
están descritos en [AST común](common-ast.md). Este capítulo incluye capacidades
adicionales aún pendientes: su presencia aquí no significa que el runtime las
implemente.

## 1. Jerarquía conceptual

```text
CodeNode
├── Declaration: ModuleDecl, TypeDecl, CallableDecl, BindingDecl, Import, Export
├── Expression: literal, read, call, arithmetic, conditional, block-value, ...
├── Statement: assign, return, break, throw, declaration-statement, ...
└── Region: module body, callable body, branch, loop, handler, ...

Expression --produces--> Value
BindingDecl --declares--> Binding
CallableDecl --has_parameter--> Parameter (subtipo de Binding)
Call --has_argument--> Argument --value--> Value
Region --contains_direct--> CodeNode
```

Es una jerarquía conceptual de vistas, no una exigencia de clases Python. Una
declaración puede aparecer como statement en un lenguaje y producir valor en
otro; conserva ambas relaciones, sin duplicar su identidad fuente.
No todo CodeNode produce un Value. Un body es Region, que puede producir valor
si el lenguaje lo permite. Un módulo no se convierte en Expression para permitir
buscar imports o declaraciones: todos comparten la vista CodeNode/Region.

Selectores adicionales al núcleo de [lenguaje](language.md): `node`, `expression`,
`statement`, `constant`. `constant` requiere contrato de constante declarado o
evaluado; no es simplemente un binding con cero escrituras observadas.

`contains_direct(region,node)` sólo hijos inmediatos. `contains(region,node)` es
cierre de regiones sintácticas, incluyendo declaraciones anidadas; `executes_in`
es pertenencia al contexto ejecutable, excluye cuerpo de una closure no invocada.
El usuario elige la relación. Encontrar una definición dentro de una expresión
no prueba que su cuerpo se ejecute al evaluar esa expresión.

## 2. Variables: declaración, tipo, capacidad y estado

| Propiedad | Dominio | Ejemplo y límite |
|---|---|---|
| `name` | BindingDecl | Regex textual; no resuelve identidad |
| `type` / `native_type` | TypeRef + grafía | `integer`, `reference<T>` y `i32` son vistas diferentes |
| `type_status` | Estado de conocimiento | Anotación ausente no es tipo explícito unknown |
| `storage` | local, parameter, field, module, captured | Field requiere instancia para obtener lugar concreto |
| `scope` | Scope ID | Bloque, callable, módulo, namespace; distinto de visibilidad |
| `visibility` | Acceso declarado/conventional | No sustituye scope ni control runtime |
| `mutable` | Declaración del binding | No acredita mutabilidad de sus objetos hijos |
| `lifetime` / `ownership` | Modelo nativo | Owned, borrowed, shared, moved son estados/relaciones con contexto |
| `readable_at` / `writable_at` | Binding/Location × Point | Inicialización, borrow activo, move, permisos y ámbito |
| `addressable_at` | Location × Point | Poder obtener dirección/referencia no es igual a poder escribir |

Extensión de schema: `scope_kind` filtra `block|callable|module|namespace|type`;
`scope` es un ID consultado relacionalmente, no string del nombre del padre.
`lifetime` y `ownership` no se aceptan como escalares estáticos de cualquier var:
se consultan con predicados que incluyen Point y perfil nativo.

Ejemplo estructural y de capacidad, fragmento dentro de un patrón:

```kql2
var $items {
    name: /^items$/;
    storage: local;
    scope_kind: callable;
}
where has_family($items, iterable);
where writable_at($items, $point);
```

`$point` debe estar ligado a un Point. `has_family` selecciona una capacidad
normalizada soportada por el modelo; no obliga a que el tipo sea exactamente
`array`. Ausencia de información sobre inicialización/moves produce unknown.

Ejemplos de diferencias que deben conservarse:

* Rust: binding mutable, referencia compartida activa, moves y mutabilidad
  interior son cuestiones distintas. `&T` no autoriza escritura ordinaria en T;
  APIs de mutabilidad interior requieren modelo propio.
* Python: no reasignar un nombre no vuelve inmutable la lista que referencia.
* JavaScript: `const` fija el binding, no congela recursivamente el objeto.
* C++: const del puntero, del objeto apuntado y referencias son propiedades
  diferentes; overloads, casts y lifetime impiden simplificaciones universales.
* Java/C#: un campo readonly/final no acredita inmutabilidad profunda.

Las propiedades anteriores describen lo que puede acreditarse estáticamente
bajo un perfil. No se presenta un modelo aproximado como reemplazo del borrow
checker o del typechecker del lenguaje fuente.

## 3. Familia, subtipos, traits y comportamiento

Separar cuatro preguntas:

| Pregunta | Predicado objetivo |
|---|---|
| ¿Pertenece a una familia normalizada? | `has_family(Entity,Family)` |
| ¿Es subtipo nominal/estructural según ese lenguaje? | `subtype(TypeRef,TypeRef)` |
| ¿Implementa un contrato declarado? | `implements(TypeRef,TypeDecl)` |
| ¿Su código satisface un comportamiento? | `matches(Pattern, roles...)` |

Familias mínimas: `numeric`, `integral`, `floating`, `textual`, `sequence`,
`mapping`, `setlike`, `iterable`, `iterator`, `async_iterable`, `callable`,
`awaitable`. Son propiedades acumulables: un array puede ser sequence e iterable.
No son una jerarquía universal de herencia. `iterable` no significa reiterable,
finito, ordenado, sin efectos o eager.

Un trait Rust nominal resuelto puede acreditar `implements`; un protocolo Python
puede requerir métodos/semánticas distintas. Tener un método llamado `next` no
demuestra el patrón Iterator ni progreso. Un protocolo estructural debe declarar
firmas, efectos y grado de conocimiento exigido.

`supports_operator(TypeRef,Operator,TypeRef,TypeRef)` relaciona tipo izquierdo,
operador, derecho y resultado. Versiones unarias tienen firma separada. Distinguir
`operator_defined` (hay resolución estática), `operator_total` (siempre definido
para los valores del dominio) y `operator_pure` (sin efectos según modelo).
División soportada no prueba divisor no cero; `+` puede invocar una sobrecarga.
La disponibilidad de operadores nunca prueba conmutatividad ni ausencia de throw.

## 4. Expresiones, definiciones e imports/exports

Propiedades de Expression: `kind`, `type`, `type_status`, `native_kind`, región
propietaria, operandos, Value producido, efectos, posibles salidas y carácter
constant-evaluable. Un callable, clase o módulo puede ser un valor de una expresión
según el lenguaje, pero su Declaration y su Value son entidades diferentes.

```kql2
from Region $body, Expression $expr, Binding $slot, Operation $write, Value $rhs;
where contains($body, $expr);
where produces_value($expr, $rhs) and assignment($write, $slot, $rhs);
```

Fragmento relacional: `assignment` exige misma operación y origen del RHS.
`result_of` es accessor parcial: si la expresión no produce valor o lo desconoce,
no inventa uno. Para múltiples resultados se usa relación `produces_value`.

Una expresión puede contener definiciones de closures/clases locales mediante
`contains`; una búsqueda de sus efectos usa la región de evaluación apropiada.
La unión de kinds se expresa `kind: oneof(variable_read, module_value, type_value,
callable_value, constant)` en un selector `value`, con enums registrados. No
interpretar `VARIABLE | MODULO | CLASE` como equivalencia entre declaraciones.

Import y export conservan: declaración, módulo origen/destino, símbolo/alias,
namespace, default/named/wildcard, type-only, estático/dinámico, resolución y efectos
de evaluación cuando apliquen. Import Python dentro de función pertenece a esa
región; un import estático JS pertenece al módulo. CommonJS y imports dinámicos
requieren modelos explícitos. Export por asignación dinámica no se deduce de un
identificador público. Exportar un símbolo tampoco demuestra que un cliente lo use.

`import_decl` y `export_decl` seleccionan estas declaraciones. `import` al inicio
de un archivo KQL carga una biblioteca KQL: son espacios semánticos separados.

## 5. Control y normalización segura de loops

Un `if` conserva expresión de condición, brazo true/false y posibles efectos de
evaluarla. `elif`/`else if` es encadenamiento de regiones, manteniendo ubicaciones
fuente. Una expresión booleana puede suspender, lanzar o mutar; no se la marca pura
por ser una condición.

Se conserva forma nativa y una vista normalizada. Un `for` C puede compartir
un modelo de loop con while, **pero no** mediante esta sustitución textual:

```c
// Original: continue ejecuta i++ antes de comprobar otra vez i < n.
for (int i = 0; i < n; i++) {
    if (skip(i)) continue;
    work(i);
}
```

CFG normalizado requerido:

```text
init → condition ─false→ exit
          │true
          v
         body ─normal/continue→ update → condition
          └─break→ exit
```

Poner `i++` al final de un while sin redirigir continue sería incorrecto. También
se conservan scope de `i`, orden de update, salidas excepcionales y resolución de
labels/niveles de break/continue. Bucles sin condition tienen condición verdadera
con origen explícito, no inventan una prueba de terminación.

`for $item in $collection { ... }` se admite como azúcar de un loop foreach nativo
con item/fuente correlacionados. **No** es azúcar de `iterate` con todas las formas:
para aceptar map/filter/protocolos usar `iterate`. El `for` clásico usa init,
condition, step y body de [comportamiento](behavior.md). Un while puede satisfacer
una query de Iteration sólo si el análisis/modelo prueba fuente, avance e item.

## 6. Excepciones con filtros y else

Extensión canónica de BODY:

```kql2
try {
    call $work { };
} catch $error when ($condition) {
    call $recover { argument $error at 0; };
} catch $other {
    throw $other;
} else {
    call $success { };
} finally {
    call $cleanup { };
}
```

Es fragmento de patrón con callables ligados; `$condition` captura un Value de
condición del filtro. Tipos de excepción se restringen con predicados sobre el
binding de catch. `when` captura filtro nativo donde existe (como C#), no confunde
un `if` dentro del handler con la selección de handler.

Catch conserva orden de evaluación, clases capturadas, filtro y binding local.
Filtros desconocidos pueden cambiar el handler elegido. No generalizar el efecto
de una excepción lanzada durante un filtro: el modelo nativo debe especificarlo.

`else` de try es una región propia, disponible cuando el lenguaje tiene esa
semántica: corre después de terminación normal del try, no después de un catch
que recuperó. Return/break/continue del try tampoco activan el else de Python.
Una excepción en else no vuelve a entrar en los catches hermanos del mismo try.
Finally sigue participando al salir, y puede sustituir una salida pendiente.

Pedir `else` en un lenguaje sin esa construcción no inventa el nodo. Una biblioteca
de «acción tras éxito» puede aceptar otras implementaciones con contratos de CFG.
Omitir catch/else/finally en la query no exige su ausencia en el programa.

## 7. Métodos, parámetros y argumentos

Callable ofrece nombre, owner, visibilidad, static/virtual/abstract, generics,
parámetros, receptor, tipo de retorno, posibles valores retornados, body,
throws/async/generator y atributos/anotaciones. Prototipo sin body sigue siendo
Callable; exigir BODY requiere definición disponible y enlazada.

Parameter es un Binding formal con nombre, tipo, familia/capacidades y scope, más:
posición semántica, posición fuente, nombre externo si difiere, default y passing.
`kind` usa `positional_only`, `positional_or_keyword`, `keyword_only`,
`variadic_positional`, `variadic_keyword`. `accepts_position` y `accepts_name`
permiten pedir capacidades sin exigir un kind exacto. Packs conservan slots,
no cantidades ficticias de argumentos expandidos.
Receptor implícito o explícito se modela como Receiver, subtipo de Binding,
separado de Parameter; el explícito conserva su declaración fuente. Ambos se
excluyen de posiciones ordinarias y del grupo `parameters`. `receiver $self { }`
captura esa vista. Posiciones nativas conservan offsets de firma cuando difieren.

Argument es la ocurrencia real en un call. Puede ser un literal, una expresión,
un read o un pack; **no hereda Binding**. Ofrece Value, tipo/familia de ese Value,
posición sintáctica/efectiva, keyword, spread/pack, binding de origen si existe y
mapeo al Parameter. No atribuirle nombre/scope de variable a `send(1 + f())`.

Paso semántico: `value`, `reference`, `borrow_shared`, `borrow_mut`, `move`,
`out`, `inout`, `unknown`. Java pasa valores de referencia a objetos por valor;
Python comparte objetos sin ser paso por referencia del binding del llamador.
C++/Rust preservan resolución y ownership. La mutabilidad del objeto no identifica
el modo de paso. El mapper debe separar receptor y argumentos ordinarios.

El body hereda navegación CodeNode/Region y puede incluir imports, clases locales,
variables y expresiones. Tipo de retorno declarado, Value retornado y efectos de
retorno son propiedades diferentes. Retornar un generator/task no demuestra
ejecución de su cuerpo, ni que su resultado interno tenga el mismo tipo.
