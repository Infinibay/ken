# BODY en consultas guardadas: contrato ejecutable

Estado comprobado el 15 de septiembre de 2026. Complementa
[la definición del lenguaje](language.md) y los
[contratos de los patrones](catalog-behavior-contracts.md). Describe lo que admite
el backend de consultas guardadas, no todas las capacidades previstas del lenguaje.

## Estructura y comportamiento

```kql2
pattern detect(out TypeDecl $unit) {
  type $unit {
    field $children {}
    method $operation {
      body {
        iterate $children as $child {
          body {
            call $operation { receiver: $child; dispatch: possible; };
          }
        }
      }
    }
  }
}
```

Ésta es la variante nominal de Composite: una operación recorre los hijos
almacenados e invoca esa misma operación sobre un elemento entregado por el
recorrido. El destino debe estar acreditado por la resolución de llamadas o por
el contrato nominal de los elementos. Coincidir en el nombre, sin ese contrato,
no basta. El motor no prueba que todos los elementos sean visitados, terminación,
ni el comportamiento del despacho en runtime.

`type`, `field`, `method` y `param` seleccionan declaraciones de propietarios
inmediatos. BODY selecciona una subsecuencia de operaciones de una misma ruta del
CFG. Permite logging y operaciones intermedias; no combina ramas mutuamente
excluyentes. `body adjacent` restringe la separación entre grupos de sentencias.
Las operaciones anidadas de una sentencia sólo se ordenan cuando una contiene a
la otra: una llamada produce el resultado antes del retorno que la contiene.
No se inventa un orden entre argumentos hermanos que el lenguaje fuente no garantice.

La variante contractual de Composite selecciona además un componente y un slot;
exige que el compuesto sea subtipo y que su operación sobrescriba ese slot. La
llamada del hijo se correlaciona con ese slot. Composite puede tener una operación
sin retorno: acumular resultados es un contrato adicional, no su definición general.

## Valores y bindings

```kql2
callable $produce { name: "produce"; }
callable $work {
  body {
    let $result = call $produce {};
    return $result;
  }
}
```

`let` captura un valor producido, no una variable fuente llamada `result`.
`tmp = produce(); log(); alias = tmp; return alias` satisface el contrato cuando
la procedencia está acreditada. `tmp = produce(); tmp = 0; return tmp` no.
Una asignación histórica nunca acredita por sí sola el valor de una lectura posterior.

La captura tampoco exige una asignación materializada: `return produce()` puede
contener tanto la producción como el consumo del valor. El orden de las cláusulas
de BODY describe dependencias de evaluación, no líneas separadas de código fuente.

**Caso aprobado para completar:** una llamada usada directamente en una condición
debe poder capturarse con `let` y consumirse por el `if` siguiente del patrón, sin
obligar a introducir una variable temporal. Por ejemplo, para un resultado booleano,
`if (!accept(item)) break` y `ok = accept(item); if (ok == false) break` deben
satisfacer el mismo patrón de valor/control. La condición debe consumir la misma
ocurrencia de llamada; una asignación intermedia que sustituya `ok` lo invalida.
La normalización de negación debe respetar el lenguaje: la falsedad lógica de
`null`, `None`, cero u otros valores no demuestra igualdad con el booleano `false`.
Este párrafo fija el contrato; el soporte de control y de salidas anidadas se
valida por separado y no se deduce de que la sintaxis ya se pueda parsear.

Los argumentos pueden consumir un valor capturado mediante `argument $result at 0`.
Las lecturas usan procedencia por ocurrencia (`ARGUMENT_VALUE_ORIGIN`,
`RETURN_ORIGIN` y, desde IR 1.79, `ASSIGNMENT_ORIGIN`). Las procedencias posibles
no equivalen a una identidad probada: el resultado conserva incertidumbre.
El análisis actual de orígenes no calcula puntos fijos de bucles ni efectos de heap.

`iterate $collection as $element` introduce un valor de elemento local al BODY
anidado. La variable fuente que lo recibe puede reasignarse, pero una llamada
posterior usando la nueva asignación no usa el elemento original. El motor
consulta un índice ordenado de escrituras explícitas del propietario, incluyendo
las anteriores a una región anidada. Las escrituras posteriores al uso no lo
invalidan. Aliases de elementos, callbacks `map/filter`, y salidas `into` requieren
más modelado; no se declaran soportados por este recorrido explícito.

## Ejecución, coste y persistencia

Las consultas guardadas compilan a operadores relacionales. Los selectores se
bajan a joins indexados internos; BODY consume participantes ya ligados: el optimizador respeta esa dependencia
y no adelanta restricciones que lean sus capturas. Puede adelantar filtros puros
sobre declaraciones independientes para reducir candidatos. BODY reutiliza el grafo y los índices de la ejecución: no vuelve a
parsear fuentes ni crea una base SQLite auxiliar.

La vista de cada callable contiene sus entidades y operaciones. Los hechos
semánticos se consultan en el índice compartido; no se copian todos los hechos
del proyecto en cada vista. Las búsquedas del BODY y del índice de escrituras
consumen el mismo presupuesto que la consulta. Agotar el presupuesto produce
`complete: false`; no significa «no existe el patrón».

Los aliases de consulta se normalizan también dentro de BODY. Las alternativas
de `either` tienen ámbitos de tipos separados; al salir sólo conservan roles
ligados en todas las ramas. Un `tally` no filtra los roles locales hacia afuera.

El grafo persistido usa IR 1.82.0 para invalidar snapshots anteriores sin las
referencias de bindings, los retornos implícitos normalizados y los modelos de esta revisión. Esto no prueba que todas las consultas sean más rápidas:
los selectores pueden aumentar candidatos y el coste de BODY depende de ellos.
La migración necesita mediciones sobre repositorios, además de tests unitarios.

## Límites y seguimiento

Siguen pendientes en este backend partes del lenguaje previsto: control distinto
de if/else y recorrido explícito, formas funcionales de iteración, efectos generales
de heap y restricciones avanzadas de tipos. No es correcto ocultar esas carencias tras
predicados que sólo renombren una relación interna o aprobar un patrón más débil.

El [inventario de autoría](../../structural-validation/kql2-catalog-rewrite-2026-09-15/authoring-inventory.json)
distingue entradas con operadores internos, consultas de composición, consultas
con sintaxis fuente pendientes de revisión, y las revisadas conductualmente.
Contar TOMLs sin `edge` no mide exactitud ni finalización del catálogo.

## Ampliaciones verificadas en esta continuación

La ampliación **IR 1.81.0** añadió referencias de bindings por
ocurrencia (`BINDING_REFERENCE`), visibilidad declarada de campos en Java/C#/TS y
la capacidad de los parámetros de admitir argumentos posicionales. Son datos
internos: el autor consulta propiedades y código, no esas relaciones.

El primer ejemplo de [examples.md](examples.md) se ejecuta literalmente en tests
de Java y C#, tanto en consultas guardadas como por la búsqueda pública, también
al reutilizar los artefactos en disco. Tipos primitivos y contenedores usan el
mismo descriptor de tipos común que el otro backend. `any` no equivale a una
anotación ausente; ésta mantiene incertidumbre. `visibility: public` es sintaxis
admitida. El soporte de visibilidad no se infiere para otros lenguajes.

`receiver $self {}` captura la instancia de un método, incluido el receptor
implícito. No captura un parámetro ordinario del mismo tipo. Actualmente esta
vista no acepta filtros de propiedades. `trait` identifica traits de Rust aunque
el grafo normalice el contrato como interfaz; no coincide con cualquier interfaz.

`call $method { ... }` puede introducir un destino fresco, sin escanear previamente
todas las funciones. Sólo lo liga cuando hay un destino exacto acreditado y único.
La ausencia o ambigüedad del destino sigue siendo desconocida.

```kql2
constructor $initialize {
    parameters { param $input {} }
    body { $state = $input; }
}
method $copy {
    body {
        let $replica = call $initialize {
            argument $state for $input;
        };
        return $replica;
    }
}
```

`argument ... for $parameter` correlaciona la ocurrencia con un parámetro ya
seleccionado, mediante el enlace de argumentos del lenguaje fuente. No exige
posición cero ni que el argumento tenga el mismo nombre. Spreads, overloads o
firmas no resueltas no se convierten en correspondencias inventadas. El fragmento
no demuestra retención final del estado: un patrón de copia debe añadir esa
obligación y sus negativos.

```kql2
callable $factory {
    parameters { param $continuation { reassigned: false; } }
    callable $handler {
        body { call $continuation {}; }
    }
    body { return $handler; }
}
```

`reassigned: false` en Parameter exige un inventario cerrado con cero escrituras
explícitas a ese binding; `true` exige al menos una. No describe la mutabilidad
del objeto referido ni prueba ausencia de efectos ocultos. Rechaza también una
reasignación después de un consumo, por lo que puede ser demasiado fuerte para
un contrato limitado a un intervalo. No se aplica a Field o variables locales:
una inicialización de esos lugares no es una reasignación de un parámetro.

Se admite Callable como valor de retorno o argumento, y callable anidado con
propietario inmediato. Una flecha cuyo cuerpo es otra función retorna esa función
implícitamente. El retorno por alias local sólo se acredita en el caso lineal de
una única asignación explícita anterior, en el mismo bloque. Un único `call` en
un BODY admite suspensión `await` en el CFG porque sólo busca la invocación;
esto no habilita secuencias ni garantías de finalización a través de la suspensión.

```kql2
body {
    if ($flag) {
        call $enabled {};
    } else {
        call $disabled {};
    }
    return $result;
}
```

`if/else` ya inspecciona brazos correlacionados. Las capturas de cada brazo son
locales, y no se afirma que ambos brazos se ejecuten. El paso posterior está
fuera del bloque completo; la misma regla se aplica después de `iterate`. El
motor conserva la polaridad y los bindings de las condiciones, incluidos campos:
`self.state` no se confunde con `other.state`. Aún faltan el resto de formas de control,
efectos de heap, contratos sobre todos los caminos y valores fusionados de ramas.


## Retornos implícitos y llamadas externas

El retorno de una expresión final simple de Rust se normaliza como una operación
RETURN sintética que contiene la expresión original. Conserva sus spans, identidad
y procedencia: `let $result = construct $product {}; return $result;` reconoce
literales de struct y aliases vigentes. Un punto y coma elimina el retorno implícito;
una asignación posterior al alias puede invalidar su procedencia. Las expresiones
finales de control (`match`, `if`, bucles) necesitan modelado adicional.

Un selector `call` selecciona una ocurrencia; un selector `callable` selecciona una
declaración. Ambos pueden usarse en BODY, con obligaciones distintas:

```kql2
callable $work {
    param $service { name: "service"; }
    call $fetch { name: "fetch"; }
    body {
        let $result = call $fetch { receiver: $service; };
        return $result;
    }
}
```

Esto identifica la llamada sobre ese parámetro y su resultado aunque el proveedor
sea externo. No acredita la identidad de una declaración destino. En cambio,
`call $method` con `$method` seleccionado como Callable exige resolución de destino.
Un valor capturado fuera de un `if` puede consumirse dentro; la prueba usa el origen
evaluado de esa ocurrencia y conserva los efectos de reasignaciones intermedias.

## Transferencia de colecciones a una construcción

```kql2
let $product = construct $productType {
    initializer $items { transfer: [identity, shallow_copy]; };
};
return $product;
```

Sin propiedad, `initializer` sólo permite identidad del operando. `shallow_copy`
admite los modelos de `list(items)` de Python sin binding local que oculte `list`,
y `[...items]` de JavaScript/TypeScript con un único spread. La propiedad puede
exigir sólo copia. No acepta otra colección, una llamada arbitraria que reciba
`items`, ni elementos adicionales en el literal. Es un modelo de copia superficial
sintáctica, no prueba de copia profunda, pureza del iterador ni ausencia de parches
dinámicos a builtins. Sólo cuenta una copia realmente usada como inicializador.

## Escape del receptor

```kql2
constructor $initialize {
    receiver $self { escapes: false; }
    parameters { param $input {} }
    body { $state = $input; }
}
```

El filtro se limita al callable seleccionado. `escapes: false` exige que todos
los usos inventariados del receptor estén soportados y no lo publiquen; `true`
requiere publicación explícita acreditada como argumento. Logging que no recibe
el receptor y escrituras directas a sus campos son compatibles con `false`.

Aliases, capturas, contenedores, retornos del receptor, llamadas opacas sobre él,
reflexión reconocida e inicialización de una base no modelada conservan
`unknown`. Un `unknown` no satisface una afirmación estricta de no escape. No es
un análisis general de heap ni prueba de ausencia de reflexión arbitraria. Una
delegación Java `this()` sólo se acredita mediante un constructor único compatible
cuyo resumen también pruebe no escape; ciclos conservan incertidumbre. El resumen
se memoiza por callable/receptor en la ejecución y consume su presupuesto.


## Memoización durante una consulta

El predicado BODY se memoiza por patrón y por las identidades de los roles que
consulta. Los roles externos irrelevantes no fuerzan otra ejecución; los receptores,
argumentos y outputs proporcionados por una consulta padre sí forman parte de la
clave. Cada fila conserva su propia evidencia y sus razones de incertidumbre.
Es una optimización local al executor: no mezcla snapshots ni consultas distintas.
El LRU contiene como máximo 1.024 claves y sólo retiene entradas de hasta 16
resultados; los resultados mayores se recorren sin retenerlos. Incluso un acierto
de caché negativo consume presupuesto de ejecución.

## Condiciones sobre resultados capturados (IR 1.82)

```kql2
callable $work {
    call $lookup { name: "get"; }
    body {
        let $cached = call $lookup {};
        if ($cached == null) { return 1; } else { return 2; }
    }
}
```

La condición consulta el origen evaluado en esa ocurrencia. Una copia local del
binding conserva el origen; sobrescribirlo antes del test lo cambia. Una unión de
ramas que permite ambos valores produce incertidumbre y no satisface un match
estricto. El análisis es local y estructurado: no acredita alias de heap ni
escrituras indirectas. El contrato se prueba en Python, Java, JavaScript,
TypeScript, C#, C++ y Go. Rust conserva las limitaciones de regiones de control
indicadas anteriormente.

Para un literal `null`, se admiten las grafías `is None` de Python y `=== null`
de JS/TS. Esa normalización no se aplica a comparaciones arbitrarias; tampoco
prueba ausencia de sobrecargas ni contratos de una API de caché.

## Transformación de un resultado

```kql2
body {
    let $result = call $wrapped { receiver: $component; };
    return binary(left: $result, operator: ["+", "*"], right: _);
}
```

`return $result + _;` describe suma con el resultado como operando izquierdo.
`binary(left: ..., operator: ..., right: ...)` permite restringir el operador con
un string, una lista no vacía o `_`. Los operandos conservan orden e identidad;
la búsqueda no presume conmutatividad. El resultado debe llegar a ese operando
según el análisis local de la ocurrencia. Una sobrescritura previa no cumple;
una copia local sí. Un operador sobrecargado puede tener efectos no modelados:
este selector verifica la forma y la procedencia, no su pureza matemática.

Los selectores de llamada admiten `target: $method` para una declaración resuelta
(o un slot nominal acreditado), sin aceptar destinos meramente posibles. Un
callable admite `exported: true`; anidado en `module_decl`, la exportación debe
pertenecer a ese módulo. No se admite `exported: false` hasta contar con un
inventario cerrado que justifique esa ausencia.

## Wrappers adaptados y argumentos callable

Un argumento de BODY puede ser el callable seleccionado: `argument $handler at
any;`. Se admite una cadena local de alias cuando cada lectura tiene una última
escritura anterior acreditada en el mismo bloque. Las escrituras posteriores no
cambian el valor ya pasado. Una escritura condicional, una captura que escribe el
binding o un inventario incompleto no acreditan esa transferencia.

`call $adapter { result_family: unknown; }` consulta la clasificación disponible
del resultado. Actualmente sólo se modelan `scalar` y `unknown`: un adapter local
resuelto que devuelve escalares puede descartarse; `unknown` **no prueba** que
el resultado sea callable. El catálogo de continuación adaptada declara por ello
un candidato estructural, no un middleware registrado o funcionalmente correcto.
La query muestra por separado el handler, su uso de la continuación recibida,
el paso del handler al adapter y el retorno del resultado del adapter.

## Retención hasta la salida e inicialización del constructor

```kql2
pattern Supplied(out TypeDecl $context, out Field $policy, out Parameter $input) {
  type $context {
    field $policy {}
    method $configure {
      parameters { param $input { reassigned: false; } }
      body linear {
        $policy = $input;
        gap until exit { forbid assign(binding($policy)); }
      }
    }
  }
}
```

`gap until exit` ocupa el último lugar del BODY y requiere un ancla anterior.
Revisa los sucesores alcanzables de esa ancla hasta las salidas de la región
actual. Una escritura posterior a `return` no invalida la retención. Una
escritura anterior al ancla tampoco: puede reemplazarse un valor por otro
parámetro suministrado. Una segunda escritura en la misma sentencia no se
considera ordenada con seguridad y rechaza la coincidencia. El análisis no
inventa el orden de evaluación entre subexpresiones hermanas.

`forbid assign(binding($policy))` prohíbe asignaciones explícitas a ese binding;
no afirma que el objeto almacenado sea inmutable ni que un descriptor Python
almacene realmente el valor. El inventario cerrado de escrituras debe estar
soportado. Operadores de actualización sin destino acreditado, asignaciones no
modeladas y reflexión dinámica conservan `unknown`. `body linear` impide
atravesar decisiones no descritas, incluso después de la asignación. BODY sin
`linear` mantiene la semántica de subsecuencia; la restricción terminal revisa
todas las continuaciones representadas desde el ancla elegida.

La fase declarativa de un constructor puede describirse antes de sus sentencias:

```kql2
constructor $configure {
  receiver $self { escapes: false; }
  parameters { param $input { reassigned: false; } }
  body linear {
    initializer { $policy = $input; }
    gap until exit { forbid assign(binding($policy)); }
  }
}
```

Este bloque `initializer` sólo puede ser el primer paso y admite asignaciones
de parámetros ligados a campos ligados. Representa propiedades de parámetros
TypeScript y listas de inicialización de miembros C++. El bloque acredita la
entrada del valor, no el estado final: la restricción terminal verifica por
separado que el cuerpo no lo sobrescriba. Inicializadores no modelados impiden
concluir esa transferencia. `escapes: false` es otra obligación independiente:
no se deduce automáticamente de una asignación. Las asignaciones ordinarias de
constructores se escriben como asignaciones BODY ordinarias.

Una única llamada BODY puede encontrarse antes de una suspensión `await`
representada por el CFG parcial de Python/JavaScript/TypeScript. Esta excepción
sólo acredita la ocurrencia de la llamada; no habilita secuencias que crucen la
suspensión ni pruebas de estabilidad alrededor de ella.

## Expresión inicial de una declaración

```kql2
type $unit {
  field $shared {
    static: true;
    initializer { construct $unit {} as $creation; }
  }
  method $accessor {
    static: true;
    arity: 0;
    writes: exactly($shared, 0);
    body { return $shared; }
  }
}
```

En un selector `field` o `var`, `initializer { ... }` contiene una expresión,
no una secuencia BODY. `construct $unit {} as $creation` exige que la raíz del
inicializador sea una construcción del tipo seleccionado. El alias es un
`Call`. Los paréntesis transparentes conservan la coincidencia; `wrap(new Unit())`
no la satisface, porque construir una instancia como argumento no determina el
valor almacenado. Tampoco se acepta una construcción realizada por una
asignación posterior en un método. La ubicación de la declaración y el destino
de la asignación deben corresponder al mismo binding.

`initializer { call $site {}; }` exige como raíz una ocurrencia `Call` ya
seleccionada. Actualmente ambos matchers requieren restricciones internas
vacías; no se aceptan restricciones que el motor vaya a ignorar. Esta sintaxis
es distinta tanto del prefijo BODY `initializer { $field = $param; }` como del
matcher `initializer $state;` dentro de una construcción.

La expresión se resuelve con operaciones y relaciones de la declaración. No
se crea un callable ni un CFG sintético. El matcher tiene un índice por
operación y memo por binding dentro de cada ejecución, y acredita la operación
de asignación y su expresión raíz en la evidencia.

## Requerimientos cuantificados de declaraciones

```kql2
type $type {}
require exists constructor of $type;
require every constructor of $type { visibility: private; }
```

Estas cláusulas, aprobadas e implementadas, pertenecen al nivel de restricciones,
fuera del BODY. `exists` exige al menos una declaración explícita de constructor
de instancia. `every` verifica cada una, con un inventario de declaraciones
cerrado. Son condiciones independientes: `every` sobre un dominio vacío cerrado
es verdadero; agregar `exists` evita aceptar ese caso.

El alcance inicial es `constructor`, con `visibility` como restricción de
`every`. El propietario debe ser un `TypeDecl` ya ligado. No se aceptan todavía
otros dominios, bloques BODY ni propiedades no implementadas; el compilador los
rechaza antes de ejecutar. Los inicializadores estáticos no son constructores de
instancia. La visibilidad es evidencia del lenguaje, no una garantía de acceso
en runtime.

Un testigo conocido puede acreditar `exists` aunque falten otras declaraciones;
un constructor público conocido refuta `every { visibility: private; }` aunque
el inventario esté abierto. Si no hay evidencia decisiva, inventarios faltantes,
C# `partial`, miembros ausentes y visibilidad desconocida conservan `unknown`.
La evidencia incluye propietario, miembros revisados, restricción y estado de
cierre. La ejecución usa el mismo grafo y memoiza la enumeración por propietario.

## Acreditación de resultados booleanos para normalizaciones

`BooleanResults` es un servicio interno genérico para decidir si el modelo
estático acredita que una llamada produce un booleano primitivo. No decide si el
valor es verdadero. Su resultado negativo significa «no acreditado».

Acepta retornos primitivos anotados de un destino único resuelto, excluyendo
llamadas ambiguas, resultados de funciones async/generadores y tipos boxed,
nullable, unión o contenedor. Las anotaciones son evidencia estática; no se
presentan como validación de tipos efectuada en runtime. Los nombres de tipo
`Boolean` y `Promise<boolean>` no acreditan un booleano primitivo.

Para callbacks Go/TypeScript lee el árbol de su anotación `function_type`, el
resultado inmediato `bool`/`boolean` y un inventario cerrado sin reasignaciones
del parámetro. No busca un sufijo mediante regex: `func(int) (bool,error)` y
`(x:number)=>boolean|undefined` se distinguen estructuralmente de retornos
booleanos simples. Un tipo `bool` sombreado, un callback reasignado o un inventario
incompleto no habilita la normalización. No se infiere tipo booleano de un nombre
como `yield` ni del uso de negación/truthiness en JavaScript sin tipos.

### Nested evaluated values and a scoped break

A `let` instruction captures an evaluated result. It does not require a source
variable declaration or assignment. For example:

```graphql
iterate $items as $element as $loop {
    body {
        let $continue = call $callback { argument $element at 0; };
        if ($continue == false) {
            break $loop as $exit;
        }
    }
}
```

The call may occur directly inside the source condition. The break must leave
that exact loop; a break belonging to a nested loop or switch is not a match.
`$loop` and `$exit` identify operations. A nested capture declared as an `out`
parameter of the enclosing pattern is available to its caller; `$continue` has
`Value` domain. Local captures otherwise remain local to their nested BODY.
Each emitted tuple preserves a single compatible witness for nested captures.
An exported iteration element uses `Binding` domain and identifies the source
iteration binding; inside the iteration BODY it denotes the current element.

Matching `if ($continue == false)` against source `if (!callback(element))`
requires proof that the callback returns a primitive boolean. An untyped or
nullable result leaves that equivalence unknown: false, null, zero and empty
values have different equality and truthiness semantics. Exact source equality
to false does not need that rewrite. Captured temporary reads require evaluated
origin evidence; an earlier historical assignment alone is insufficient.
