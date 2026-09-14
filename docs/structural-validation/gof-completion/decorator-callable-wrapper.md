# `decorator#callable-wrapper` (8 lenguajes) — cerrada (IR 1.54)

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados.
Fecha: 2026-09-13. Base: `9154511`.

## Qué pide la ficha

> Relacionar callable capturado, invocación con argumentos compatibles y
> comportamiento añadido alcanzable. Permitir modificación aritmética del
> resultado sin exigir una segunda llamada. Positivo: wrapper que mide/loguea o
> transforma el valor y conserva el contrato de llamada pertinente.

Contraejemplos: comportamiento adicional muerto, destino diferente y
argumentos/resultados perdidos bajo contrato transparente.

## La capacidad que faltaba: el cierre de Rust

Siete de los ocho lenguajes ya tenían todo: fábrica con parámetro callable,
cierre anidado como `CALLABLE` propio, `CAPTURES` hacia ese parámetro,
`RETURNS` de la fábrica al cierre, e invocación del capturado.

Rust era la excepción y la causa era chica: su cierre es un nodo
**`closure_expression`**, que **no estaba en `FUNCTIONS`** (sí estaban
`lambda`, `arrow_function`, `function_expression` y `func_literal` de los otros
lenguajes). Sin él, el cuerpo del cierre se aplanaba dentro de la función
envolvente: no había `CALLABLE` anidado, no había `CAPTURES`, y el «wrapper»
perdía identidad.

```rust
pub fn traced<F: Fn(i32) -> i32>(inner: F) -> impl Fn(i32) -> i32 {
    move |value: i32| { let result = inner(value); result }
}
```

Antes: `traced RETURNS VALUE`. Después: `traced RETURNS CALLABLE:anonymous` con
`CAPTURES -> inner` y `anonymous CALLEE_VALUE -> inner`, igual que Python, JS, Go,
Java, C# y C++.

## La segunda forma de invocar: interfaz funcional

Java invoca el callable capturado como **método** sobre él
(`inner.applyAsInt(value)`), no como llamada directa. El grafo lo registra como
`RECEIVER -> PARAMETER:inner`, mientras que los demás lenguajes emiten
`CALLEE_VALUE -> PARAMETER:inner`. Las dos formas significan «invocar el
callable», así que la query las acepta explícitamente:

```kenql
any {
 require $delegation CALLEE_VALUE $inner;
} or {
 require $delegation RECEIVER $inner;
}
```

No es un sinónimo: es la diferencia real entre invocar un valor callable y
invocar el método de una interfaz funcional, y se declara en `query_claim`.

## Contrato publicado

```kenql
query decorator {
 require $factory HAS_PARAMETER $inner;
 parameter(receiver: false) as $inner;
 require $factory RETURNS $wrapper;
 different $factory $wrapper;
 callable(constructor: false) as $wrapper;
 require $wrapper CAPTURES $inner;
 require $wrapper HAS_PARAMETER $value;
 parameter(receiver: false) as $value;
 require $wrapper HAS_CALL $delegation;
 any { ... CALLEE_VALUE ... } or { ... RECEIVER ... }
 require $delegation ARGUMENT $argument;
 require $argument VALUE $input;
 require $input LOADED_FROM $value;
 emit unit=$wrapper, $factory, $inner, $wrapper;
}
```

**Lo que no prueba** (declarado en `query_claim`): que el comportamiento añadido
sea alcanzable en ejecución, la modificación aritmética del resultado sin segunda
llamada, y la transparencia del contrato de llamada. Los tres son refinamientos
más fuertes que requieren alcanzabilidad (P2.1) y contratos de aridad.

## Positivo y negativos

Positivo: **1 match** por lenguaje, con `$factory ≠ $wrapper` y `$inner` un
parámetro de la fábrica.

| Negativo | Por qué no hay match |
|---|---|
| La fábrica devuelve el callable sin envolverlo | falta `$wrapper` distinto de `$factory` |
| El cierre captura pero **nunca** invoca el capturado | falta la llamada de delegación |
| El cierre invoca **otro** callable | el `CALLEE_VALUE` no es `$inner` |
| El cierre no reenvía su propio argumento (`inner(0)`) | `LOADED_FROM $value` falla |
| No hay parámetro callable que capturar | falta la captura |

Más un positivo con nombres renombrados (`wrap`/`operation`/`wrapped`).

## Una restricción del catálogo que valió la pena

`rules.py` valida que **todas las variantes `ready` de una regla exporten al menos
un rol común**, porque la unión canónica `gof.<id>` se construye con la
intersección de sus exports. El primer intento de `callable-wrapper` exportaba
`factory`, `inner`, `wrapper` y el hermano `object-wrapper` exporta `unit`: la
intersección era vacía y la colección del catálogo **falló en import**.

Se corrigió añadiendo `unit=$wrapper` —el cierre es la «unidad» decorada, análogo
al objeto envuelto—, no relajando la validación. Es exactamente lo que el plan
pide en §8: «Mantener los nombres de roles públicos y el dominio de las
variables».

## Archivos

- `src/ken/structural/frontend.py`: `closure_expression` en `FUNCTIONS`.
- `src/ken/structural/model.py`: `IR_VERSION` 1.53.0 → 1.54.0.
- `src/ken/structural/patterns/decorator.toml`: variante `ready` con query; raíz
  con unión.
- `tests/structural/test_decorator_callable_wrapper.py`: 13 tests.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_decorator_callable_wrapper.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/
.venv/bin/python -m mypy src/ken
```

- Matriz nueva + catálogo: **285 passed**.
- Suite estructural completa: **6.738 passed, 140 xfailed**, sin fallos
  (baseline previo: 6.719 / 143). Los 3 xfail que menos son los de esta variante,
  convertidos en regresión normal.
- `mypy src/ken`: 109 archivos, sin errores.

Hashes de esta entrega:

| Archivo | sha256 |
|---|---|
| `src/ken/structural/frontend.py` | `971b80b78e8b62bb1c631deaf7f5bfc073826920566833100bb84b154a508f9e` |
| `src/ken/structural/model.py` | `7a6b2e43becee8108ff227042fba1d76a032988218aa5a31c337c3f5b0e07a1c` |
| `src/ken/structural/patterns/decorator.toml` | `8f8006f2f992ff82c71fe1cc66ed49e39745d741b76e308102af03d1451c56be` |
| `tests/structural/test_decorator_callable_wrapper.py` | `08e09a49c9a51baeed71e1c40f43756fc1bfaade989a2ec0c30aacf7106aeb47` |

## Inventario

**52 ready / 25 design** (antes 51 / 26).

## Siguiente paso

`closure_expression` y `CAPTURES` ya funcionan en los ocho lenguajes, así que el
mismo recorrido sirve a las otras variantes de cierre: `command#command-closure`,
`chain#middleware-closures`, `adapter#functional-adapter`,
`template-method#composed-skeleton` y `composite#higher-order-traversal`. La
diferencia de cada una es qué se hace con el callable (almacenarlo, encadenarlo,
transformar argumentos), no la captura.
