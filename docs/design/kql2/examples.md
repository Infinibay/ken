# Bibliotecas y ejemplos de KQL 2

Definición de referencia con implementación parcial. El ejemplo 1 se ejecuta
literalmente en Java/C# mediante los tests del motor guardado y la búsqueda pública;
los demás ejemplos siguen sujetos a las capacidades del
[contrato ejecutable](saved-body-execution.md). [Índice](README.md). Los imports `ken.*`
describen bibliotecas objetivo, no paquetes instalables existentes. Los predicados
auxiliares deben implementarse con sus contratos, no por nombre de función fuente.

## 1. Estructura como la propuesta original

```kql2
language "kql/2";
module examples.workers;
import ken.core;

pattern Worker(out TypeDecl $worker, out TypeDecl $jobType, out Callable $work) {
    class $jobType { name: /^Job$/; }
    class $worker {
        fields {
            field $name { type: string; name: /name/i; visibility: public; }
            field $age { type: integer; visibility: public; }
            field $job { type: nominal($jobType); visibility: private; }
        }
        method $work {
            name: /^work$/;
            parameters {
                param $task { position: 0; accepts_position: true; }
            }
        }
        constructor $init { }
    }
    where $worker != $jobType;
    where $name != $age and $name != $job and $age != $job;
}

query workers {
    use Worker(worker: $worker, jobType: $jobType, work: $work);
    select $worker, $jobType, $work;
}
```

Campos y parámetros adicionales se admiten. Constructor implícito no se inventa:
su captura necesita evidencia del modelo nativo. Para Rust/Go se usa `type` y
variantes de inicialización, no una clase o constructor ficticio.

## 2. El ejemplo de restricción temporal

```kql2
pattern ProtectedArgument(out Callable $owner, out Binding $variable) {
    callable $owner {
        body {
            var $variable { type: integer; } as $declaration;
            let $result = call $method {
                argument $variable at any;
            } as $invoke;
            gap until next {
                forbid write(binding($variable));
                forbid call($method, through: transitive);
            }
            $variable = $variable * 2 as $update;
        }
    }
}
```

`$method` es Callable ligado por el target exacto de la llamada. Su cuerpo puede
recursar durante `$invoke`: la prohibición empieza después de esa invocación.
Para prohibir también la recursión iniciada por ella, el intervalo debe incluirla
y el contrato debe distinguir la primera llamada permitida de sus descendientes.
No se exceptúa automáticamente el método inicial en una prohibición inclusiva.

Snippets fuente propios, sin ejecutar:

```python
# Conserva el contrato de intervalo si consume está resuelto y audit es compatible.
x = 3
result = consume(x)
audit("processed")
x = x * 2
```

```python
# Rompe la prohibición de escritura aunque se restaure después.
x = 3
result = consume(x)
x = 4
x = 3
x = x * 2
```

La query reconoce alguna subsecuencia; para señalar un punto concreto debe
anclarse por caller/ubicación/rol esperado. Los fixtures verificarán IDs de matches,
no sólo un booleano que podría satisfacerse con otra multiplicación del archivo.

## 3. Operación reutilizable y fragmento

Esta variante reconoce un lookup indexado; una biblioteca de Lookup puede añadir
variantes de APIs resueltas sin cambiar su interfaz pública.

```kql2
pattern IndexedLookup(
    in Binding $container,
    in Binding $key,
    out Value $result,
    out Fragment $step
) {
    from Callable $owner;
    callable $owner {
        body {
            fragment $step {
                let $result = read($container)[read($key)] as $access;
            }
        }
    }
    exposes $step;
}

pattern ReturnLookup(out Callable $owner) {
    callable $owner {
        param $container { position: 0; }
        param $key { position: 1; }
        body {
            use IndexedLookup(container: $container, key: $key,
                              result: $result, step: $lookup);
            gap until next {
                preserve state($result, depth: shallow);
            }
            return $result as $return;
        }
    }
}
```

La preservación de estado exige un resultado objeto; si la instancia del patrón
produce un escalar, no satisface ese contrato. Una biblioteca genérica puede tener
otra variante para escalares, donde basta identidad/procedencia del Value.
La llamada devuelve exactamente la prueba y valores de ese lookup. No se puede
reutilizar la clave de una coincidencia y el resultado de otra.

No es preciso detectar previamente una clase GoF Iterator para reconocer su uso.
Igualmente, una colección incorporada puede ofrecer Lookup mediante un modelo.
Los patrones exponen operaciones; no convierten por arte de sintaxis un campo
desconocido en una colección ni una función homónima en una API estándar.

## 4. Recursión y análisis parametrizado

Biblioteca genérica sobre relaciones finitas de Value:

```kql2
signature FlowModel {
    predicate source(Value $value);
    predicate sink(Value $value);
    predicate step(Value $from, Value $to);
    predicate barrier(Value $value);
}

pattern Reach<M: FlowModel>(in Value $source, out Value $target) {
    where not M.barrier($source);
    either {
        bind $target = $source;
    } or {
        from Value $next;
        where M.step($source, $next);
        use Reach<M>(source: $next, target: $target);
    }
}
```

La negación de `barrier` depende de un modelo ya cerrado, no de la propia
recursión. La SCC de Reach es positiva. Su base permite longitud cero; si una
query requiere movimiento debe añadir un primer `step` o distinguir identidades.

Ejemplo de modelo que importa predicados de APIs auditados; estas firmas
pertenecen a `examples.api_model`, biblioteca hipotética que debe tener fixtures:
`input_result(Value)`, `command_input(Value)`, `sanitized(Value)`.

```kql2
model Requests implements FlowModel {
    predicate source(Value $v) { input_result($v) }
    predicate sink(Value $v) { command_input($v) }
    predicate step(Value $a, Value $b) {
        value_flow($a, $b) or taint_step($a, $b)
    }
    predicate barrier(Value $v) { sanitized($v) }
}

query influenced_commands {
    from Value $source, Value $sink;
    where Requests.source($source) and Requests.sink($sink);
    use Reach<Requests>(source: $source, target: $sink);
    select $source, $sink;
}
```

Es un ejemplo de influencia parametrizada. El predicado `step` debe proporcionar
pasos/resúmenes de flujo con contexto; recorrer aristas que mezclen llamadas no
acredita flujo interprocedural válido. Una barrera requiere contrato de sanitización
para el sink: validar HTML no sanitiza SQL. No inferirla de un nombre `sanitize`.

## 5. Estados definidos por la consulta

Fragmento de modelo; `is_acquire`/`is_release` son relaciones semánticas importadas
con un Lock correlacionado, omitido aquí para mostrar sólo la tabla de estados.

```kql2
enum LockState { unlocked, locked }

predicate Transition(Operation $op, LockState $before, LockState $after) {
    (is_acquire($op) and $before == unlocked and $after == locked)
    or
    (is_release($op) and $before == locked and $after == unlocked)
}
```

Para una consulta completa, la firma de estado incluye `(Object/Lock, Point,
State)`; las transiciones se aplican sobre el mismo recurso y contexto. Una
operación compatible sin efecto conserva estado mediante transición de identidad.
Una operación desconocida no conserva estado por default. Un bug se formula como
alcanzar una operación inválida en cierto estado; la ausencia de bug exige cierre.

Otros dominios finitos: `Builder { empty, configured, consumed }`,
`Snapshot { independent, may_alias }`, `Input { raw, path_checked, html_escaped }`.
Esos nombres son etiquetas de modelos, no semánticas incorporadas al motor.
Estados de flujo pueden formar productos finitos; presupuesto agotado es incomplete.

## 6. Implementaciones distintas del mismo recorrido

| Lenguaje / mecanismo | Qué debe demostrar la variante |
|---|---|
| Python for/comprehension | Fuente y binding del elemento; expresión de salida y condición si existen |
| Python generator / async generator | Yield y contexto; consumidor adicional si se pide consumed |
| Java Stream.map/filter | API resuelta, callback correcto, pipeline y terminal según contrato |
| JS Array.map/filter | Modelo de Array, callback/item/output; un objeto con método map no basta |
| C# LINQ Select/Where | Select transforma, Where filtra; no normalizar Select a filter |
| Rust iter/map/filter | Borrow/move, lazy adaptor y consumo; no asumir copia del item |
| Go range/callback iterator | Fuente, yielded values y detención cuando callback retorna false |
| C++ ranges/iteradores | begin/end, avance, dereference y salida; modelos de overload/algoritmos |
| PHP foreach/array_map/array_filter | Paso por referencia explícito, preservación de claves según operación |
| Ruby each/map/select | Bloque, fuente, item y significado de select; soporte futuro sujeto a frontend |

Probar estas variantes contra la misma obligación, con metadatos diferentes de
orden, cardinalidad, efectos y suspensión. No anunciar soporte de un lenguaje
porque la gramática KQL pueda escribir la consulta correspondiente.

## 7. Algoritmos expresados como obligaciones

Estos son contratos de biblioteca, no detectores completos ya implementados:

| Caso | Obligaciones y contraejemplo mínimo |
|---|---|
| Builder mutable | Capturar producto, escribir parámetro en su campo y retornar ese producto; retornar otro producto refuta |
| Builder inmutable | Cada paso retorna sucesor derivado del anterior; retorno de self puede violar esa variante |
| Flyweight | Lookup por clave, creación en ausencia, publicación misma clave/objeto y retorno correlacionado; overwrite incondicional refuta |
| Observer con snapshot | Copiar colección de listeners, recorrer copia e invocar esos listeners; alias de lista viva rompe aislamiento |
| Memento | Snapshot conserva estado seleccionado independiente cuando éste cambia; copiar referencia mutable no basta |
| Proxy remoto | Serialización → transporte → decodificación → retorno, sobre valores correlacionados; decoder constante refuta |
| Cache-Aside | Hit retorna entrada; miss carga/publica/retorna; invalidación/reasignación intermedia puede romper el contrato |
| Middleware | Entrada llega a continuación, respuesta procede de ésta; pedir exactly-once requiere control adicional |
| Retry | Fallo conduce a intento posterior y finally no anula ese flujo; no implica idempotencia |
| Transacción | Begin/commit/rollback del mismo recurso, escrituras dentro y salidas cubiertas; una lista de cambios no basta |

La combinación de `use`, fragmentos, ramas, estados y restricciones expresa esas
obligaciones. Qué datos faltan para probarlas pertenece a capacidades del IR,
no a palabras nuevas específicas para cada GoF.

### Effective inherited fields

```graphql
type $subject {
  field $access {
    effective: true;
    declaration: $declaration;
    type: nominal($backend);
    static: false;
  }
  method $operation {
    call $invocation {}
    body { call $invocation { receiver: $access; }; }
  }
}
```

`effective: true` resolves a field through verified lexical ancestry. `$access`
keeps the storage identity used in the subject's body; optional `$declaration`
captures the nearest actual field declaration, whose type and visibility are
checked. A local declaration or property shadows an ancestor. Matching names in
unrelated classes do not establish identity. The default (`effective: false`)
continues to select immediate fields. `declaration` requires `effective: true`.

The current resolver supports a finite, resolved single class-inheritance chain;
Java/C# interface bases do not count as additional instance-field bases. Missing
bases, cycles and multiple class inheritance produce uncertainty rather than a
guessed field. Inherited private fields are not guessed. This selector proves
field identity and metadata, not its runtime value or absence of heap mutation.

### Closures and macro occurrences

```graphql
callable $factory { param $inner {} }
callable $wrapper { captures: $inner; }
callable $factory { body { return $wrapper; } }
callable $wrapper {
  macro $log { name: /^(println|eprintln)$/; }
  body { macro $log; }
}
```

`captures` requires lexical binding identity; a same-named variable in another
scope is insufficient. `macro` selects a macro invocation owned by the callable;
its `name` uses ordinary literal/list/regex matching. BODY `macro $log;` anchors
that exact occurrence in the execution subsequence. It identifies syntax and
control-flow presence, not macro expansion or observable effects. Currently the
macro selector supports Rust invocations and only the `name` property.

`callable $slot { functional: true; }` identifies an accredited functional
interface operation. Current models cover the audited Java IntSupplier and
IntUnaryOperator API and direct source Java interfaces with one abstract method.
Static/default/private methods do not contribute abstract slots; inherited
interfaces are conservatively unmodeled. Missing evidence is not proof that an
arbitrary object method represents a callable protocol.

### Generator suspension

```graphql
callable $producer {
  generator: true;
  context_manager: false;
  parameters { param $items {} }
  body { yield $items as $suspension; }
}
```

`yield _;` matches production of any value; Python's bare `yield` produces `null`.
`yield from $items;` matches delegation (Python `yield from`, JS/TS `yield*`),
which ordinary `yield` deliberately does not match. An optional `as` captures the
suspension Operation. C# `yield break` is termination, not element production.

Execution currently admits a **single yield instruction** when CFG coverage is
partial only for modeled yield/await suspension forms. It proves that source
control can reach that suspension, not resumption, completion of awaited work,
progress, exhaustion or a runtime-feasible path. A yield after return/yield-break or
in a constant-false branch does not qualify. Parenthesized literal conditions have
the same effect. Nested callable yields belong to their own callable.

Other incomplete CFG reasons (such as unsupported try/finally), and BODY sequences
that cross suspensions using several instructions, retain uncertainty. This is not
a claim that arbitrary continuation across yield has been implemented. Generator
and delegated-generator catalog variants use this precise single-instruction
contract; the `context_manager: false` property excludes Python context managers.

### Async iteration of a selected invocation

```graphql
callable $producer { async: true; body { yield _; } }
callable $consumer {
  async: true;
  call $source { target: $producer; }
  body {
    iterate $source as $item as $loop {
      async: true;
      body {}
    }
  }
}
```

An iteration source may be a selected Call occurrence or a Value captured from
that call, in addition to a storage/parameter. This compares the actual source
identity, not a name or another call to the same function. Captured call values
currently support direct source occurrences; arbitrary stored iterable aliases
need additional provenance support. `async: false` explicitly selects synchronous
loops; omitting the property permits either form. Empty nested BODY imposes no
constraint on the loop's instructions, while still requiring an iteration body.

A single async iteration with empty nested BODY can match CFG coverage partial
only because of await expressions. This establishes the suspending loop's source
shape; it does not claim that awaited work completes or that its body is executed.
Other partial reasons and constrained nested BODY retain their usual uncertainty.
