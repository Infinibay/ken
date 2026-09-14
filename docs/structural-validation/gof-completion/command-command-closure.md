# `command#command-closure` (8 lenguajes) — cerrada (IR 1.55)

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados.
Fecha: 2026-09-13. Base: `f3a1f4c`.

> Revisión posterior, sin cambio de IR ni de semántica: el `sha256` de
> `src/ken/structural/patterns/command.toml` que aparece al final ya no aplica.
> `callable(constructor: false) as $action` se movió del preámbulo al interior de
> cada rama del `any`, donde la rama liga `$action` (`$insertion INSERTED_VALUE
> $action`) antes de comprobarlo. Antes el planificador generaba los ~266
> callables por fila y la rama descartaba todos: 20 s y 11 M estados sobre
> `src/ken/structural`, ahora 2.9 s y 3.1 M, con la misma conjunción por rama y
> los mismos matches. La equivalencia se comprobó con los conjuntos de findings
> de ocho corpus RefactoringGuru/faif, idénticos antes y después.

## Qué pide la ficha

> Relacionar captura de acción/datos, transferencia o almacenamiento de la función
> y posterior invocación diferida. Comprobar que los datos capturados llegan a la
> acción. Positivo: cola de closures con payload y un contexto de ejecución
> adicional; FnOnce/move sólo donde se resuelva.

Contraejemplos: closure creada y descartada, llamada inmediata sin representación
diferida, slot sobrescrito o payload equivocado. Y una instrucción explícita:
**no imponer aridad cero**, porque un comando puede recibir contexto al ejecutarse.

## Qué la distingue de las vecinas ya `ready`

`stored-closure` cubre un cierre guardado en un **campo** e invocado por otro
método, sin exigir contexto. `queued-object` cubre objetos comando con operación
**de aridad cero** en una cola. `command-closure` es lo que queda: el cierre va a
una **colección** y se invoca con un **contexto de ejecución** que el invocador
recibe por parámetro.

## Tres capacidades, una por lenguaje

La captura y la invocación diferida ya existían en Python. Los otros siete
fallaban, y por tres razones distintas y generales:

### 1. Alias local del cierre (JS, TS, Java, C#, C++)

En esos lenguajes el cierre no se encola directamente: se asigna a una variable y
es la variable la que se encola.

```js
const action = (context) => payload + context;
this.pending.push(action);        // INSERTED_VALUE -> STORAGE:action
```

La query sigue la identidad con `path $action FLOWS_TO{0,2} $inserted` sobre la
relación que ya emitía la asignación. Python encola el `CALLABLE` directo.

### 2. `append` de Go (capacidad general nueva)

`d.pending = append(d.pending, action)` no producía `INSERTS_INTO`: la emisión
existente exigía un **receptor** (`lista.append(x)`, `vec.push(x)`), y `append` es
una función libre de Go. Se agregó el caso libre con dos argumentos, que es la
forma canónica de añadir a un slice.

### 3. `for-range` de C++ (capacidad general nueva)

`for (auto &action : pending) { action(context); }` no producía `ITERATES_CALLS`.
La emisión buscaba el binding del bucle en los campos `left`/`name`/`pattern`, y
C++ usa **`declarator`** envolviendo el nombre en un `reference_declarator`. Se
agregó un helper `loop_binding` que prueba también `declarator` y desenvuelve los
declaradores de referencia y puntero.

### 4. Envoltorio `Box::new` de Rust

`self.pending.push(Box::new(action))` encola el **resultado** de la llamada, no el
cierre. La tercera rama de la query sigue `INSERTED_VALUE` → `ARGUMENT` → `VALUE` →
`LOADED_FROM` hasta el alias, que es la forma de un envoltorio de un solo
argumento.

## Contrato publicado

```kenql
query command {
 require $unit HAS_FIELD $queue;
 require $unit HAS_METHOD $submit;
 callable(constructor: false) as $submit;
 callable(constructor: false) as $run;
 different $run $submit;
 require $unit HAS_METHOD $run;
 callable(constructor: false) as $action;
 require $submit HAS_CALL $insertion;
 require $insertion INSERTS_INTO $queue;
 any { ... el cierre directo ... }
 or { ... alias local ... }
 or { ... envoltorio de un argumento ... }
 require $action CAPTURES $payload;
 require $action READS $payload;          # los datos llegan a la acción
 require $action HAS_PARAMETER $context;  # NO se impone aridad cero
 parameter(receiver: false) as $context;
 require $run ITERATES_CALLS $queue;      # la MISMA cola
 require $run HAS_PARAMETER $execution;
 parameter(receiver: false) as $execution;
 require $run HAS_CALL $dispatch;
 require $dispatch ARGUMENT $argument;
 require $argument VALUE $input;
 require $input LOADED_FROM $execution;   # contexto de ejecución
 emit $unit, $queue, $submit, $run, $action;
}
```

**Lo que no prueba** (declarado en `query_claim`): orden temporal, ejecución
exactamente una vez, ni `FnOnce`/`move`.

## Positivo y negativos

Positivo: **1 match** por lenguaje.

| Negativo | Por qué no hay match |
|---|---|
| Cierre llamado **inmediatamente** y nunca encolado | falta la inserción (contraejemplo de la ficha) |
| El cierre no lee el payload capturado | `READS $payload` falla |
| Cierre de **aridad cero** | `HAS_PARAMETER $context` falla; la ficha prohíbe imponer aridad cero |
| La cola nunca se recorre | falta `ITERATES_CALLS` |
| El invocador recorre **otra** colección | la cola no coincide |
| El invocador no recibe contexto | la cadena de valor del argumento no llega |

## Archivos

- `src/ken/structural/frontend.py`: helper `loop_binding` (range-for de C++),
  `append` libre de Go como inserción.
- `src/ken/structural/model.py`: `IR_VERSION` 1.54.0 → 1.55.0.
- `src/ken/structural/patterns/command.toml`: variante `ready` con query; raíz con
  unión de seis variantes.
- `tests/structural/test_command_command_closure.py`: 14 tests.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_command_command_closure.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/
.venv/bin/python -m mypy src/ken
```

- Matriz nueva + catálogo: **287 passed**.
- Suite estructural completa: **6.769 passed, 140 xfailed**, sin fallos
  (baseline previo: 6.753 / 140).
- `mypy src/ken`: 109 archivos, sin errores.

Hashes de esta entrega:

| Archivo | sha256 |
|---|---|
| `src/ken/structural/frontend.py` | `da64568949e20fa06138705c94b7850b0ca577ebae0a57a585d07910d15bc797` |
| `src/ken/structural/model.py` | `b2c7ec52178603e2e378d6a4413e01c8271f2b2c65a765ec42b71e30d0a86c18` |
| `src/ken/structural/patterns/command.toml` | `a6e2e8dcf1d40f5d19eb3d793a706425e87a4ff9e5844f8bfe0609053dfdf4e5` |
| `tests/structural/test_command_command_closure.py` | `9373b02ea92d8df24c8aecc4f7b3561469bf27e3a6d6c2482720f629dd4d21c2` |

## Inventario

**54 ready / 23 design** (antes 53 / 24).
