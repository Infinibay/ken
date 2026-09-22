# BODY, intervalos y efectos

Propuesta 0.1; no implementada. [Índice](README.md).

## 1. Un cuerpo es un patrón de ejecución

`body { ... }` dentro de un callable reconoce una secuencia ordenada de operaciones
de ese callable. No ejecuta instrucciones KQL. Todas las capturas pertenecen al
mismo testigo de control; no se combinan operaciones de ramas incompatibles.

Por defecto es una **subsecuencia ordenada**, admite cero o más instrucciones
intermedias. La búsqueda puede encontrar varias subsecuencias. No elige la primera
coincidencia de forma greedy ni establece adyacencia textual implícita.
`body adjacent` exige adyacencia de grupos de instrucciones fuente normalizados.
Lecturas/operandos internos de la misma sentencia no son ruido adicional;
una llamada independiente, incluso a un logger, sí lo es.

Para exigirlo sólo entre dos pasos, se usa `adjacent;`:

```kql2
body {
    var $variable { } as $declaration;
    adjacent;
    $variable = 1 as $assignment;
}
```

No hay instrucción fuente intermedia entre declaración y asignación. Comentarios,
espacios, llaves de agrupación y nodos sintéticos del CFG no cuentan; una sentencia
vacía o `pass` explícito sí cuenta como grupo fuente. La actualización/condición
de un loop o una llamada oculta modelada como operación intermedia impide adyacencia.
La inicialización incluida en la declaración pertenece al ancla anterior.
No se acepta usar la misma operación como ambas anclas para aparentar distancia cero.

`adjacent;` usa la regla léxica de anclas de `gap until next`, con paths: all y
cero grupos fuente en el intervalo. En un BODY completo `adjacent` es equivalente
a exigir esa condición entre cada pareja de instrucciones anclables consecutivas.
No demuestra que se alcance la segunda; exige además camino conector en términos
de puntos. No se llama `NOOP`: no está buscando una instrucción nop.

Las declaraciones `var`, llamadas, asignaciones, retornos, ramas, loops,
suspensiones y fragmentos expuestos son anclables. `where`, `bind`, restricciones
y evidencia opcional no consumen una operación ni desplazan `next`.
El orden es CFG/semántico, no orden por línea o byte. Para sintaxis muerta se usa
`syntax { ... }`, que busca dentro del AST y no admite garantías de ejecución,
intervalos ni `preserve`. No convertir silenciosamente un BODY a búsqueda AST.

## 2. Variables, llamadas y valores

Fragmento de un método, con `$method` ligado a un Callable:

```kql2
body {
    var $value { type: integer; } as $declaration;

    let $result = call $method {
        argument $value at any;
    } as $invocation;

    gap until next {
        forbid write(binding($value));
        forbid call($method, through: direct);
    }

    $value = $value * 2 as $update;
    return $result as $returned;
}
```

`var $value` captura un **Binding** y su declaración; no exige que la palabra
fuente sea `var` ni que sea mutable, salvo filtro `mutable: true`. En BODY consume
el punto de declaración; fuera de BODY sólo selecciona la declaración.
`let $result = call ...` captura el **Value resultado de esa llamada**; no exige
asignación a una variable fuente. `let` aquí no describe constancia del binding
fuente y no es la palabra fuente `let`. Para exigir almacenamiento posterior:
`$slot = $result as $store;`, con `$slot` ligado como Binding.

`$value = $value * 2` describe una asignación a ese binding. En un operando BODY,
un rol Binding/Parameter abrevia la lectura de ese binding **en esa ocurrencia**;
un rol Value requiere ese valor, con identidad/procedencia acreditada. La lectura
antes de una llamada y la lectura posterior no son iguales automáticamente.
`read($binding)` es la forma explícita equivalente en operandos BODY.
Fuera de BODY no hay conversión Binding → Value: se exige `value_at(binding,point)`.

`let $v = expression as $op;` captura un valor producido y una operación fuente
existente, no construye valores simbólicos sin testigo. `bind` calcula en la query;
`let` reconoce en el programa. Los nombres introducidos por `let` son inmutables
en la consulta y no pueden ser LHS de asignación fuente.

`call $target` une una operación con su destino. Sin filtro de dispatch exige
destino exacto acreditado. `dispatch: possible` solicita pertenencia al conjunto
de posibles destinos y se etiqueta así en la evidencia. No implica ejecución.
`receiver: $object;` correlaciona la misma instancia, no solamente su tipo.

Argumentos son ocurrencias diferentes de los parámetros de firma:

```kql2
call $target {
    argument $input at 0 as $first;
    argument $filter at any as $arg;
    where passing($arg) == reference;
};
```

Posiciones desde cero, sin receptor implícito. `at any` genera cada posición
resuelta compatible; una coincidencia conserva la ocurrencia `$arg`. Para keywords
se permite `at name("filter")`. Packs `*args`, `**kwargs`, spread JS, variádicos
C/C++/Go y forwarded packs conservan un `ArgumentPack`: sus posiciones efectivas
no se adivinan. `argument_pack $pack { kind: positional; }` los captura. Si no se
resuelve la expansión, un argumento efectivo individual puede quedar desconocido.

## 3. Expresiones y operaciones fuente

BODY reconoce literales, lectura de binding, miembro/indexado, construcción,
operaciones aritméticas, comparaciones, lógica, conversiones y llamadas.
`$x.field` no interpreta `field` como rol: es nombre literal; miembros capturados
usan `member($object,$field)`. Indexado `$map[$key]` mantiene clave y contenedor.

`$place.name` es un **lugar miembro** y sirve de destino y de valor leído:

```kql2
body {
    $context.state = $context.other as $write;
}
```

El objeto debe ser un lugar ligado (campo, binding, parámetro o receptor) y el miembro
debe **pertenecer a ese lugar** y estar **declarado por un campo que el patrón ligó con
ese nombre**. No es una comparación de texto: el testigo es el miembro del objeto
ligado, así que nombrar un miembro que el patrón no declaró no acredita el lugar, un
miembro de otra instancia no lo satisface, y leer un miembro distinto del escrito no es
la cláusula descrita. Un valor producido por una llamada (`let`) o una construcción
sigue usándose por su rol.
Las operaciones `+ - * / % **`, comparaciones `== != < <= > >=`, `and or not`,
bitwise `& | ^ ~ << >>`, `+= -= *= /= %=`, prefijo/postfijo `++ --` tienen códigos
IR distintos cuando sus efectos difieren. Precedencia de fuente normalizada:
postfix > potencia (derecha) > unary > producto > suma > shifts > bitwise
> comparaciones > and > or. No se reordena aritmética ni se asume conmutatividad.

Dentro de bitwise, `&` precede a `^`, que precede a `|`. Esta precedencia es la de
la notación KQL; el frontend preserva el árbol real del lenguaje fuente antes de
compararlo. No vuelve a parsear texto C/Python con reglas de KQL.

`new $type(...)` reconoce construcción resuelta, incluyendo inicialización nativa
modelada; no exige token `new`. Campos inicializados por nombre conservan nombres.
Asignar puede invocar setters/overloads; el efecto semántico no se reduce a un
store ordinario cuando el lenguaje no lo garantiza. `x++` no se vuelve `x+1` sin
guardar el valor previo/posterior y sus posibles efectos.

Operaciones de control: `if (expr) { ... } else { ... }`, `while (expr) { ... }`,
`for { init { ... } condition expr; step { ... } body { ... } }`, `break;`,
`continue;`, `return [expr];`, `throw expr;`, `yield expr;`, `yield from expr;`,
`await expr;`, `try { ... } catch $error when (expr) { ... } else { ... } finally { ... }`.
`else if` es anidamiento normal; `switch/match` se reconoce con un selector
`operation { kind: match; }` y predicados de brazos/patrones, sin normalizar
exhaustividad, guards o fallthrough a un if arbitrario.

Estos bloques son **forma de control**: exigen región de ese tipo. Una búsqueda
que quiera aceptar guard clauses, ternarios y if/else debe usar una biblioteca de
ramificación por condiciones y sus variantes, no exigir un `if` sintáctico.
`else` omitido no impone su ausencia. `catch` captura la excepción ligada, no
demuestra exhaustividad. `finally` y salidas excepcionales participan del CFG.
Filtros, else y normalización segura de for están definidos en el
[modelo del programa](code-model.md).

`if` inspecciona brazos distintos sin afirmar que ambos se ejecutan. Capturas de
cada brazo son locales. Un valor común posterior exige una relación explícita
`merged_value`/procedencia sobre los brazos; no se exporta un Value arbitrario.

`insert $valor into $coleccion [at $clave];` reconoce una **inserción en colección**
como efecto anclable. El valor y la clave son operandos fuente (lugar ligado, valor
capturado, miembro o literal) y la colección un lugar ligado. Cubre las dos formas
reales: la llamada a la API de colección (`add`/`append`/`push`, que publica el valor
insertado) y la escritura indexada (`$map[$k] = $v`, que publica el valor almacenado y
la escritura de elemento). Nombrar el miembro insertado no basta: el valor tiene que
ser el de esa ocurrencia, y la clave, si se pide, la de esa inserción.

```kql2
body {
    insert $listener into $listeners;
    insert $handler into $registry[$topic];   // el bucket que esa clave selecciona
}
```

Un destino indexado (`$registry[$topic]`) es el **bucket** que la clave selecciona: la
inserción tiene que apuntar a un bucket cuyo contenedor sea ese lugar y cuyo índice sea
esa clave. Sin clave, basta que la inserción apunte al lugar o a un bucket suyo. La
misma forma vale para recorrer: `iterate $registry[$topic] as $handler { ... }` camina
ese bucket, y el elemento puede invocarse como callable (`call $handler { ... }`),
porque la colección es quien lo entrega.

## 4. Intervalos

Todo ancla Operation tiene `.before`, `.after_normal` y `.after_exceptional`.
`.after` abrevia `.after_normal`; no incluye una llamada que no retornó normalmente.
`return` no tiene continuación normal dentro del callable: usar `.before` como
fin de intervalo, o `exit` del callable según el contrato.

```kql2
restriction between $invocation.after and $update.before {
    paths: all;
    forbid write(binding($value));
    forbid call($method, through: transitive);
}
```

El intervalo incluye eventos ocurridos **después de completar la primera operación
y antes de iniciar la segunda**. No incluye efectos de ninguna de las dos anclas.
Para incluir los de la primera, comenzar en `.before`; para incluir los de la
segunda, terminar en `.after`. Intervalo vacío es válido si hay conectividad.
No se fabrican conclusiones sobre un intervalo sin camino conector.

`gap until next { ... }` es azúcar exclusivamente léxica: anterior instrucción
anclable `.after` → siguiente instrucción anclable `.before` del mismo bloque.
El gap no puede ser primero/último, apuntar dentro de otra rama o cruzar fuera
del bloque. Insertar `where` no cambia extremos; insertar una instrucción anclable
sí cambia la expansión. El compilador debe mostrar ambos extremos en `explain`.
Un fragmento tiene entrada/salida explícitas; no se usa todo el método que lo aloja.

`next` significa siguiente **en el patrón**, no primer uso runtime ni siguiente
ocurrencia textual del identificador. Si se requiere el siguiente uso del binding,
la biblioteca `next_use(binding,start,end)` lo exige explícitamente.

### Caminos, ciclos y totalidad

`paths: all` es el default: todos los caminos del modelo que conectan esas
ocurrencias y no atraviesan antes el punto final deben satisfacer la restricción.
`paths: witness` sólo verifica el camino seleccionado por el BODY y devuelve
`path_scope: witness`; no debe presentarse como garantía general.

El ancla se identifica por nodo, contexto de llamada y contexto de iteración
abstracto. No se empareja una lectura de iteración N con un store de N+1 para
inventar preservación. Cuando no puede separar ocurrencias requeridas, unknown.
En ciclos, las restricciones se evalúan por punto fijo/alcanzabilidad, no por
enumeración ilimitada de caminos. La precisión de contexto se declara en el perfil.

Los caminos que retornan/arrojan o no terminan antes del extremo final no son
conectores. Por eso `all` no garantiza que se alcance ese extremo. `must_reach`
es una obligación distinta, incluye salidas alternativas y no terminación; puede
quedar desconocida. Un BODY ordenado tampoco significa ejecución inevitable.

## 5. Efectos y preservación

| Restricción | Contrato |
|---|---|
| `forbid write(binding($b))` | Ninguna escritura al slot, incluso escribirle el mismo valor |
| `preserve binding($b)` | La identidad/valor ligado coincide con el inicial en todos los puntos del intervalo; puede haber escritura del mismo valor acreditado |
| `preserve value($v)` | Valor semántico del objeto/estructura seleccionado según igualdad de su tipo; no usar en un Value SSA inmutable como prueba del heap |
| `forbid mutate(object($o))` | Ninguna escritura al estado directo del objeto, incluidos aliases |
| `preserve state($o, depth: shallow)` | Estado directo constante; referencias a hijos conservadas, no estados de hijos |
| `preserve state($o, depth: reachable)` | Estado de objetos alcanzables del objeto inicial constante; footprint y escapes deben resolverse |
| `forbid insert(elements($c))` | Ninguna inserción en la colección |
| `forbid remove(elements($c))` | Ninguna eliminación en la colección |
| `forbid replace(elements($c))` | Ninguna sustitución de elementos existentes |
| `preserve elements($c, order: true)` | Misma secuencia de identidades/valores durante el intervalo |
| `forbid call($f, through: direct)` | Ningún sitio directo del intervalo puede invocar ese destino |
| `forbid call($f, through: transitive)` | Incluye llamadas descendientes de cada llamada del intervalo |
| `forbid escape($o)` | No entregar referencia a almacenamiento/contexto fuera del ámbito especificado |
| `forbid suspend()` | No await/yield/bloqueo clasificado como suspensión por el modelo |

`preserve` vale en cada punto, no sólo en los extremos. Modificar y restaurar no
lo cumple. `same_state_at($o,$a,$b)` compara extremos como propiedad separada.
`preserve value` requiere definir igualdad estructural o de valor para el tipo;
no llama al `equals` del programa. Sin esa definición, unknown.

No hay whitelist que anule una prohibición: una operación conocida sólo se
acepta si sus efectos son compatibles. Logging no es puro por su nombre. Un
logger sin acceso al objeto protegido puede ser compatible con preservación,
aunque haga I/O; sus excepciones siguen afectando a terminación.

Un efecto posible que podría vulnerar la restricción impide confirmarla. Un
contraejemplo acreditado la refuta; un alias/dispatch no resuelto produce unknown.
La ausencia de una arista WRITES en un IR parcial nunca acredita preservación.

## 6. Fragmentos y uso de algoritmos nombrados

`fragment $piece { ... }` dentro de BODY captura una subsecuencia con sus anclas
y prueba correlacionada. Debe tener al menos una operación y extremos inequívocos
por testigo. Esas capturas pueden exponerse como `out Fragment` de un patrón.

Un `use Lookup(..., step: $lookup);` dentro de BODY sólo es anclable si la firma
declara un fragmento de comportamiento principal. Se declara con `exposes $step;`
en el patrón. Sus operaciones se vinculan dentro de la región actual. Si no hay
fragmento expuesto, `use` es una restricción relacional y no mueve `next`.
Dos fragmentos consecutivos deben respetar orden; no solaparse salvo relación
explícita de biblioteca. No se acepta solapamiento implícito para abaratar un match.

## 7. Iteración

```kql2
iterate $source as $item into $output as $iteration {
    forms: [loop, iterator, map, filter];
    execution: consumed;
    body {
        let $mapped = call $transform { argument $item at 0; } as $apply;
    }
    where produces($iteration, $item, $mapped);
    where output_of($iteration, $output);
}
```

`$source` y `$output` son Values de colecciones/pipelines; `$item` es el Value
abstracto ligado por esa iteración, no cualquier variable homónima. Se evalúa el
body/callback con ese elemento. `$mapped` no escapa del cuerpo salvo los predicados
del mismo bloque de iteración que verifican producción; no escapa al método.
`$iteration` es Iteration y ancla la operación de recorrido o consumo modelado.
`into` es opcional; si aparece, exige salida correlacionada, no mera asignación.

`forms` restringe realizaciones permitidas, no elimina obligaciones del cuerpo.
`loop` incluye foreach/comprehension normalizados; `iterator` protocolo explícito;
`map` transformación, `filter` selección. `select` no es forma portable: Ruby
select filtra, LINQ Select transforma; decide el modelo resuelto de la API.
`each` se modela como recorrido sin salida, `reduce` publica acumulador/combiner
en un patrón de biblioteca distinto. No aceptar todas esas operaciones por nombre.

`execution: defined` reconoce algoritmo/callback sin consumo probado;
`execution: consumed` exige consumidor/activación en el modelo, no que ocurra
necesariamente en runtime. Diferenciar eager/lazy, sync/async, orden, short-circuit,
cardinalidad y política de errores con propiedades independientes.
Sin filtro de execution no se impone consumo; la evidencia publica su estado.

`produces` sólo relaciona elementos efectivamente emitidos. Pedir «uno por cada
entrada», conservación de orden o agotamiento requiere `cardinality(...,one_to_one)`,
`preserves_order` y `exhausts`, respectivamente. Map con excepción/early exit no
demuestra cobertura total. Filter conserva identidad de seleccionados y predicado
aplicado; no satisface transformación arbitraria por incluirse en `forms`.

## 8. Suspensión y concurrencia

`yield`, `yield from` y `await` son operaciones diferentes. Un generador puede
ser tal sin producir elementos; un `yield` muerto sólo acredita forma léxica.
Un iterador Rust puede ser lazy; un callback Go puede detenerse con false.
Un `async` sin await es válido. Ninguna de esas variantes se fuerza a un loop eager.

Las operaciones `spawn $callable as $task;`, `join $task;`, `acquire $lock;`,
`release $lock;`, `send $value to $channel;`, `receive $channel as $value;` son
patrones de operaciones semánticas: requieren API/protocolo modelado, no nombres.
`$task` es Task, `$lock` Lock, canales Values; spawn no implica thread del SO.

El orden entre tasks se expresa con `happens_before(point,point)`; no con líneas
ni un CFG intraprocedural. `atomic`, `synchronized`, RAII, defer y cancelación
aportan eventos/regiones a bibliotecas, conservando su semántica nativa.
Preservación local usa contexto `task_local` y lo etiqueta. Pedir
`concurrency: shared` en una restricción exige incluir escritores concurrentes y
sincronización. Sin análisis suficiente, unknown, nunca «thread safe» por default.

Se puede describir uso sin lock o un protocolo acquire/release mediante estados
y efectos; la definición no promete resolver todas las carreras ni deadlocks.
