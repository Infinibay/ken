# Revisión de autoría: seis patrones de comportamiento

15 de septiembre de 2026. Subconjunto: Template Method, Strategy, Command,
Observer, Mediator y State. Este informe **no declara terminada la migración**.
Los contratos se revisaron contra `docs/design/kql2/catalog-behavior-contracts.md`;
las consultas anteriores sirvieron para encontrar variantes, no como definición.

## Cambios ejecutables

### Template Method

Todas sus consultas y su operación de refinamiento usan selectores fuente y BODY.

- `virtual-skeleton`: el método esqueleto invoca un hook del mismo tipo sobre su
  propio receptor; existe una sobrescritura del hook. No basta llamar al hook de
  otro objeto ni a una función auxiliar sin punto de extensión.
- `trait-default`: selecciona un trait y una implementación que sobrescribe el
  hook llamado por el algoritmo default sobre `self`. Exigir dos implementaciones
  presentes era un falso negativo arbitrario; basta un punto de extensión real.
- `composed-skeleton`: tres hooks distintos forman una cadena de valores en una
  misma ruta: el segundo recibe el resultado del primero, el tercero el del
  segundo. La consulta muestra por separado callables directos e interfaces
  funcionales; no confunde «llamar al callable» con «llamar un método del objeto».
- `dependent_steps`: dos operaciones distintas sobre el mismo receptor, con un
  valor producido por la primera consumido por la segunda. Permite alias local y
  logging; rechaza receptor ajeno, resultado descartado o ausencia de override.

Cambios del motor requeridos por los tests: normalización de `receiver` para
`this` implícito y `self` explícito; selector trait sobre la representación nativa
Rust (el IR general lo agrupa como interfaz); captura de destinos de llamadas.
Estas correcciones las integra el agente principal, no este lote de TOML.

Limitaciones: la variante por composición todavía no cubre mezclas de callable
puro y objeto funcional dentro del mismo esqueleto. Tampoco prueba identidad del
valor de entrada de cada parámetro tras reasignaciones ni efectos de heap. BODY
acredita una ruta del CFG, no factibilidad global de esa ruta ni despacho runtime.

### Mediator

`direct-colleagues` expresa en BODY las llamadas en ambas direcciones:
coordinador a dos campos de colegas, y operaciones de esos tipos al coordinador.
`registered-colleagues` exige además que los colegas retengan un campo tipado por
el centro y que esa sea la referencia sobre la que notifican.

Los dos colegas pueden tener el mismo tipo: dos personas no dejan de ser
participantes distintos porque implementen la misma clase. Los dos BODY de
coordinación son independientes intencionadamente; las acciones pueden ocurrir
bajo eventos o ramas diferentes. No se afirma una secuencia que la definición de
Mediator no exige. La identidad de instancia del centro entre objetos distintos
sigue siendo una limitación del análisis; las variantes de tags/payload deben
aportar sus obligaciones adicionales.

### Strategy

La variante de objeto ya usaba cuerpo fuente; se eliminó el requisito de dos
implementaciones concretas. Un consumidor tipado por contrato que usa la política
suministrada puede implementar Strategy aunque el proyecto sólo contenga una
implementación concreta. Se conservó el contrato de retención anterior para no
aceptar una asignación histórica sobrescrita después.

`consumed_policy` usa ahora `param $input { reassigned: false; }`, junto con
`let`, argumento y retorno sobre una misma ruta. El motor comprueba un inventario
cerrado de escrituras explícitas del binding: inventario incompleto queda unknown.
Así se conserva el negativo `input=0; policy(input)` sin comparar nombres ni
seguir asignaciones históricas. Se prueban las formas callable y objeto.

La restricción es conservadora: una reasignación **posterior** a la invocación
también rechaza el candidato, aunque no afecte al valor ya consumido. Esa variante
válida necesita captura del valor de entrada o intervalo preciso hasta el uso.
No acredita inmutabilidad del heap referenciado por el parámetro.

## Seguimiento por entrada aún pendiente

| Patrón | Entrada | Obligación pendiente de expresar/ejecutar |
| --- | --- | --- |
| Strategy | supplied_policy | Transferencia del valor suministrado al campo y ausencia de sobrescritura hasta todas las salidas relevantes; inicializadores de constructor equivalentes. |
| Strategy | static-policy | Parámetro de tipo propietario y selección de operación por ese parámetro, sin inventar un objeto en runtime. |
| Strategy | consumed_policy (precisión adicional) | La consulta fuente está implementada con binding no reasignado. Capturar el valor al entrar permitirá reasignaciones inocuas posteriores al consumo. |
| Command | retained_dispatch | Retener referencia suministrada y despachar después sobre esa referencia; distinguir binding actual de valor original. |
| Command | retained-contract | Implementación del slot de comando que retiene y usa su receptor; no exigir aridad cero o descartar siempre resultados. |
| Command | command-object | Petición como objeto transmisible/retensible cuyo cuerpo usa receptor/datos, con invocador correlacionado. |
| Command | stored-closure | Closure con capturas y transferencia al campo que después se invoca. |
| Command | retained-object | Existe ya BODY, pero falta intervalo hasta salida en setter y estabilidad de receptor; no se considera validada sólo por su sintaxis. |
| Command | command-closure | Captura de payload, inserción de esa closure en cola, extracción e invocación con contexto correspondiente. |
| Command | queued-object | Registrar los comandos que se ejecutan y correlacionar el contrato del elemento con la acción retenida. |
| Command | captured_payload | Captura de receptor y payload; la acción usa sus valores correspondientes, no sólo nombres de campos. |
| Observer | listener-registry | Registro del listener suministrado y notificación del mismo registro; distinguir suscripción de árbol de hijos. |
| Observer | map-key-registry | Listener como clave del mapa y notificación sobre esas claves, no sus valores. |
| Observer | snapshot-registry | Copia de la lista registrada y recorrido de esa instantánea; establecer política shallow/heap. |
| Observer | language-event | Suscribir, desuscribir y emitir sobre el mismo evento C#, con modelos explícitos de operaciones nativas. |
| Observer | event-bus | La clave/topic usada al registrar corresponde al bucket recorrido y el payload llega a los listeners. |
| Observer | registered-listeners | Reemplazar comprobaciones gruesas de escritura/recorrido por inserción del parámetro y consumo del elemento real. |
| Observer | event_delivery | Valor de evento propagado a la invocación del listener, no a una llamada distinta del loop. |
| Mediator | message-coordination | Ramas encaminan el mismo evento hacia destinos pertinentes, más llamadas entrantes correlacionadas. |
| Mediator | tag-dispatch | Condición sobre tag discrimina las acciones; simple presencia de dos llamadas no lo demuestra. |
| Mediator | broadcast-colleagues | Registro de participantes, consumo del elemento original y comunicación de vuelta al centro. |
| Mediator | event_delivery | Correlación por ocurrencia entre evento recibido y evento comunicado. |
| State | state-object | Ya tiene BODY; verificar que la transición persiste hasta salida y que la selección no se reemplaza antes del despacho. |
| State | state-enum | Condición sobre estado actual y escritura del siguiente estado en esa rama. |
| State | context-transition | El estado instalado llama al setter de su contexto con un nuevo estado compatible; correlación de contexto retenido. |
| State | event_transition | Lo anterior más procedencia del evento que gobierna la transición. |

Las consultas antiguas de estas entradas siguen activas durante el trabajo. No
se borraron variantes ni se transformaron en `design` para obtener artificialmente
un catálogo sin operadores internos. Esto es trabajo pendiente de implementación,
no el resultado final solicitado por el usuario.

## Primitivas necesarias: propuestas concretas

Las siguientes son **propuestas para integrar en el lenguaje**, no sintaxis que
este informe afirme disponible. Son operaciones comunes reutilizables por varios
patrones, no funciones que oculten un detector entero.

### Retención hasta salida

```kql2
class $context {
  field $policy {}
  method $configure {
    param $supplied {}
    body {
      $policy = $supplied;
      gap until end { forbid write(binding($policy)); }
    }
  }
}
```

`end` debe cubrir las salidas relevantes desde la asignación y no permitir una
rama de sobrescritura sólo porque exista otra limpia. Debe preservar `unknown`
cuando efectos indirectos invaliden el inventario. Retener el valor de entrada de
`supplied` requiere además la siguiente captura, no usar meramente su lectura.

### Captura de valor al entrar

```kql2
method $algorithm {
  param $input {}
  body {
    at entry { let $original = read($input); }
    let $result = call $policy { argument $original at 0; };
    return $result;
  }
}
```

Un alias del valor debe ser válido; reasignar `input` antes del consumo debe
rechazarse. `let $original = read($input)` sin ancla de entrada puede seleccionar
una lectura posterior a una sobrescritura y no cubre el contrato.

### Colecciones, callbacks y eventos

```kql2
method $subscribe {
  param $listener {}
  body { insert $listener into $registry; }
}
method $notify {
  param $event {}
  body {
    iterate $registry as $listener {
      body { call $listener { argument $event at 0; }; }
    }
  }
}
```

La inserción necesita modelos de APIs y de modificaciones nativas, sin buscar
nombres como `append` en cualquier receptor. El elemento iterado es un Value:
invocar ese callable debe conservar su identidad aunque la variable fuente se
reasigne. Para eventos por objetos, el cuerpo usa `call $update { receiver:
$listener; argument $event at 0; }`. Un registro borrado antes del recorrido es un
negativo; una colección de hijos visitados sin evidencia de evento no debe
presentarse como Observer confirmado.

### Estados y selección por evento

```kql2
method $transition {
  body {
    if read($state) == $current {
      $state = $next;
      gap until end { forbid write(binding($state)); }
    }
  }
}
```

La rama debe depender de la lectura correcta del estado; `$current` y `$next`
son valores constantes o variantes del dominio, no roles ligados por posiciones
de texto. Ramas de un mismo switch/match requieren normalización equivalente.

## Validación de este lote

Tests independientes de autoría en tres ficheros `test_authored_behavioral_*`:
31 Template Method, 24 Mediator y 31 Strategy (86 casos). Positivos y negativos en Python,
Java y TypeScript; composición también Go y trait default Rust. Se conserva
ruido entre pasos y se introducen contraejemplos que rompen colaboración,
procedencia o sobrescritura.

Esta selección no es una medición de precisión/recall del catálogo entero ni un
benchmark de repositorios. Las entradas pendientes necesitan tests adicionales
al habilitar sus primitivas y después una nueva ejecución del corpus externo.

Revisión ampliada focalizada: **229 pasan y 3 fallan** al incluir los tests previos
`test_algorithm_template_method.py` y `test_strategy_binding_inputs.py` junto con
los 61 nuevos. Los tres fallos son el mismo contraste en Python/Java/TypeScript:
el test anterior exige que el detector raíz acepte `other.first(...)`, aunque el
hook se ejecute sobre otro objeto. La reescritura del esqueleto sobre su propio
receptor lo rechaza. El negativo del refinamiento sigue siendo negativo. Esas
expectativas históricas requieren revisión semántica explícita; no se cambiaron
para lograr verde ni se debilitó la consulta. Log: `/tmp/behavioral-focused.log`.


Validación posterior de `consumed_policy`: 25 nuevos contrastes (5 formas entre
Python/Java/TypeScript × positivo, argumento ajeno, resultado descartado, resultado
sobrescrito y parámetro sobrescrito) pasan. El lote Strategy completo pasa 31/31.
La prueba ampliada histórica de 229/3 corresponde al paso anterior a estos casos.

## Segunda pasada: regresiones de la suite global

- **Receptor implícito**: en Java, C# y C++ una llamada no calificada a un miembro
  resuelto no estático usa `this`. El enlazador ahora publica ese receptor tras
  resolver el destino lexicalmente. No lo inventa para funciones libres,
  parámetros callables, métodos estáticos o cuerpos estáticos. Los tests de Java
  entre paquetes y C++ vuelven a pasar: lote de 205 tests, incluidos 13 contrastes
  nuevos de receptor implícito.
- **Java externo**: se modelaron exclusivamente los slots funcionales acreditados
  `java.util.function.IntSupplier.getAsInt()` e
  `java.util.function.IntUnaryOperator.applyAsInt(int)`, con identidad nominal,
  firma y destino declarado externo. Se exige nombre calificado o import explícito
  único y ausencia de shadow por tipo declarado o parámetro genérico. No se
  publica un destino runtime ni cuerpo inventado. Las firmas están documentadas
  en [IntSupplier](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/function/IntSupplier.html)
  y [IntUnaryOperator](https://docs.oracle.com/en/java/javase/25/docs/api/java.base/java/util/function/IntUnaryOperator.html).
  Doce contrastes nuevos comprueban imports, homónimos, shadow, método y aridad.
- **Mediator registrado**: los fixtures legítimos reciben el centro como parámetro.
  Se añadió esa alternativa al campo retenido, manteniendo receptor nominal y
  llamada al coordinador. Imponer retención en los colegas no era requisito de
  Mediator. Lote de 39 tests de la variante y autoría pasan.
- **Oráculos históricos revisados**: se retiró la exigencia arbitraria de dos
  implementaciones de Strategy y del hook Rust; se reemplazaron comprobaciones
  textuales que exigían operadores internos por comprobaciones de autoría fuente.
  Se retiró de la deuda de documentación una variante que ya tiene claim explícito.
- **Ambigüedad pendiente de clasificación**: quitar el conteo de implementaciones
  expone dos candidatos Strategy en `negative_corpus/service.py` y `wrapper.py`.
  Son dependencia delegada y wrapper con contrato nominal, respectivamente. Se
  registraron por separado en `AMBIGUOUS_HITS`, con razones por fichero, y se
  mantuvieron las tres etiquetas anteriores en `KNOWN_HITS`. No se califican
  automáticamente como aciertos ni como errores: la estructura compartida no
  acredita por sí sola intención de algoritmo intercambiable. El test exige
  exactamente la unión de ambas listas y que sean disjuntas; cualquier nuevo hit
  sigue requiriendo revisión explícita.

Validación de integración acotada tras estas correcciones: **680 pasan** entre
casos Java, paquetes, modelos funcionales y variantes virtuales del catálogo
adversarial; no sustituye una ejecución de la suite global completa.


Cierre de revisión de oráculos: `OrderService` consume repositorio y mailer
inyectados; el papel de dependencia no prueba ni excluye una política Strategy.
`AuthenticatedClient` añade responsabilidad alrededor de `Client.request` y
permite sustituir el cliente; el mismo código puede servir como wrapper/Decorator
y como consumidor de política. No hay fundamento para restaurar el umbral de dos
clases concretas ni para computar ambos como TP/FP sin etiquetado de intención.
Se conserva su clasificación **ambigua** separada en el test y en este reporte.

Lote estable posterior: **87 tests pasan**, incluidos corpus negativo con
clasificaciones separadas, oráculos de Template Method, C++ Strategy y nuevos
modelos de receptor/API. La versión global IR 1.81 invalida caché anterior a los
nuevos hechos semánticos.

## Bridge and Decorator: inherited places and returned transformations

The refined Bridge query now describes two nominal dimensions, an overridden
abstraction operation, its effective implementation field, and an invocation on
that field inside BODY. `field effective:true; declaration:$field` preserves the
access place used by BODY while resolving metadata from its nearest declaration.
This replaces the authored INSTANCE_SLOT walk; unrelated identically named fields
cannot supply the implementation type. Missing/multiple class ancestry remains
unknown, and property/local shadows suppress inherited candidates. The operation
still does not establish constructor injection or preserve the runtime field value.
The returned-primitive refinement separately tracks the actual returned call value.

Decorator object-wrapper now composes the authored typed-delegator responsibility
contract or matches a returned binary expression using the delegated result as an
operand. Both operand positions are supported. An unrelated arithmetic return or
reassignment of the delegated result is rejected. Arithmetic identities such as
adding zero are intentionally not simplified: this is an expression transformation,
not proof of an observable responsibility. The additional-call alternative also
cannot prove that a pure helper has an observable effect; Proxy remains ambiguous.

Validation: 163 tests passed across `test_authored_effective_fields.py`,
`test_authored_structural_wrappers.py`, and `test_refined_bridge.py`. This includes
Python/Java/TypeScript positive/negative transformations, wrong receivers,
overwritten or discarded results, inherited field types, unrelated declarations,
local/property shadows and conservative unresolved/diamond inheritance handling.
Effective-field execution is an explicit internal operator behind the field selector;
its optimizer boundary is conservative and it participates in the implementation
fingerprint through the KQL2 module tree. It does not add a public graph relation.

Remaining authored graph queries have not been removed merely to improve counts:
Bridge generic-composition needs source generic-parameter identity; its injected
refinement needs constructor retention semantics. Decorator callable-wrapper still
needs complete callable capture and invocation semantics, while untyped/subclass
variants need precise inherited input retention/forwarding behavior. These are
pending migrations, not claims that the complete catalog is now source-authored.

### Strategy budget regression: named-query outputs

The 120-context fixture (eight fields and eight configuration parameters per type)
needed 10,331 states after source migration and exceeded its unchanged 10,000-state
budget. This was not a field/parameter Cartesian product: the source planner failed
to record outputs of a completed named query. Consequently `$configure !=
$algorithm` could not move before BODY, which redundantly searched configure too.
Recording exported arguments as available after the named-query barrier reduced
the same 120 matches to 7,091 states (1,680 to 1,560 relational rows examined).
An illustrative local query time fell from 113ms to 71ms; states are the reproducible
metric, these single-run wall times are not a benchmark claim. Named-query scope
remains a motion barrier. Tests compare results and evidence with reference execution
and separately pin the plan boundary. The original 10,000-state budget is unchanged.

## Decorator final source-authoring pass (IR 1.83.0)

Every executable Decorator query now uses source selectors, BODY, composable named
patterns and type/override predicates. No authored edge/walk, delegates_to,
forwards_slot or final_member_input remains. The callable variant preserves all
eight language witnesses and Rust output macros. New generic `captures` and macro
selectors expose lexical binding and invocation identity; Java `functional:true`
is accredited from audited API slots or a direct single-abstract-method interface.
Default/static/private methods do not count; inherited Java SAM interfaces remain
an explicit limitation. Helpers and arithmetic identities do not prove observable
responsibility. Extra calls/macros must coexist with delegation on the same path.

Closing the other two variants revealed real model defects, not query spelling:
Rust's synthetic return of a tail closure belonged to the closure instead of its
factory. Its owner now follows the containing source scope; the nested function
retains ownership of its own body. Ruby's body_statement was a single CFG point,
preventing sequential calls from matching; it is now a block, while rescue/ensure
remain explicitly unsupported control. Java/TS/C# super calls previously resolved
back to the overriding method itself. Language-accredited base syntax now resolves
along one verified class chain; Python zero-argument super excludes lexical
shadowing. Multiple inheritance and ambiguous overloads are not guessed.

The subclass variant now requires the actual inherited invocation when delegation
lives in the base. Previously the query accepted a subclass with any extra call,
even when it never invoked the base behavior. Negative tests explicitly remove or
rename that invocation. Untyped retention uses a linear assignment and terminal gap;
its input is not explicitly reassigned, and the field has no later explicit write.
These source restrictions do not establish descriptor effects or runtime heap
stability. IR version 1.83.0 invalidates cached graphs for the new functional/base
metadata and corrected closure ownership/Ruby control flow.

Validation for this final pass: 264 Decorator/wrapper/adversarial tests passed;
70 additional functional-interface, implicit-receiver, effective-field and optimizer
regressions passed. A final 48-test protocol/closure rerun also passed after restricting
base dispatch to immediate nonstatic method contexts. No global-suite conclusion is
implied; other agents continue integration changes.

## Iterator generator pass (IR 1.84.0)

The generator and delegated-generator variants now use `body { yield _; }` and
`body { yield from _; }`. The generic BODY instruction supports a selected binding,
literal or wildcard operand and captures an Operation alias. Delegation is distinct
from ordinary production. Python bare yield emits null; C# yield break terminates
control and is excluded from production. This CFG correction increments IR to1.84.0.

A single-yield BODY may consume a partial CFG only when all missing reasons are
supported yield/await syntax. This establishes reachable source suspension shape,
not completion/resumption or finite traversal. Multi-instruction BODY across such
suspensions and other partial reasons remain unknown. Nested callable ownership,
post-return/post-yield-break code and literal-false branches have negative tests.
The branch test exposed parenthesized JS/TS constants; successors now unwrap only
transparent parentheses before its existing true/false filtering.

Other Iterator variants and operations remain outside this bounded migration pass;
the previously written Iterator plan records the primitives still needed.

### Async Iterator continuation of the bounded pass

`async-iterator` now selects its async producer and yielding BODY, the consumer's
specific invocation of that producer, and an async `iterate` BODY over that exact
invocation. Original exported loop/source/suspension identities remain available.
Generic iteration now accepts selected Calls/captured call Values and an async
boolean property. An empty iteration body is an unconstrained body region rather
than a missing-anchor compile error. For the single async-loop shape only, an
await-only partial CFG is sufficient; no awaited completion or body effects are
asserted. Callback Iterator remains pending because properly exporting its nested
binding/call/branch/exit evidence and validating scoped breaks needs a separate
engine/test pass; no relation wrapper or weakened replacement was introduced.

### Approved callback BODY execution, 2026-09-15

Implemented the approved nested `iterate … as $loop`, evaluated `let`, and
`break $loop as $exit` form. A call directly inside a condition and a saved
unmodified temporary share evaluated-value identity; a reassignment does not.
Formal nested outputs retain their Value/Operation domains across catalog and
persisted search backends. Branch witnesses preserve their bindings rather than
returning only a boolean success flag.

Tests cover Go, JavaScript, TypeScript, Python and Ruby, including Ruby postfix
`break if …`, wrong callback arguments, another invocation, reassignment, and a
break belonging to an inner loop. Ruby uses the existing explicit call-occurrence
selector with `receiver: $callback`; an arbitrary `.call` method is not silently
classified as a language-level function invocation. Primitive-boolean
accreditation permits Go/TypeScript negation syntax to match equality to false;
untyped dynamic callback negation remains unknown.

The callback catalog variant is deliberately unchanged: its existing public
`$branch` output has no alias in the approved conditional syntax. Replacing or
removing that output without approval would change the catalog contract. The
new engine behavior is tested independently; migrating this particular variant
still needs a decision about preserving its branch evidence output.
