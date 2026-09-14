# `template-method#composed-skeleton` (8 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados.
Fecha: 2026-09-13. Base: `0865f16`.

## Cuarta variante que no necesitó capacidad nueva

El IR ya registraba todo lo que el contrato de composición pide:

| Necesidad | Evidencia ya existente |
|---|---|
| El esqueleto recibe hooks como funciones | `HAS_PARAMETER` de los tres callables |
| Invoca cada hook | `HAS_CALL` + `CALLEE_VALUE` (o `RECEIVER` en Java) |
| El resultado de un paso llega al argumento del siguiente | `ARGUMENT` + `VALUE` + `path … VALUE_FLOW` |
| El orden es el del encadenamiento | la cadena de valores, no la posición textual |

Fixture mínimo (Python):

```python
def run(prepare, transform, finish):
    value = prepare()
    result = transform(value)
    return finish(result)
```

## Contrato publicado

```kenql
query template_method {
 require $unit HAS_PARAMETER $prepare;
 parameter(receiver: false) as $prepare;
 ... (idéntico para transform y finish) ...
 different $prepare $transform;
 different $transform $finish;
 different $prepare $finish;
 require $unit HAS_CALL $prepare_call;
 any { require $prepare_call CALLEE_VALUE $prepare; } or { require $prepare_call RECEIVER $prepare; }
 ... (idéntico para los otros dos hooks) ...
 require $prepare_call RESULT $prepared;
 require $transform_call ARGUMENT $transform_argument;
 require $transform_argument VALUE $transform_input;
 path $prepared VALUE_FLOW{0,3} $transform_input as $handoff;
 require $transform_call RESULT $transformed;
 require $finish_call ARGUMENT $finish_argument;
 require $finish_argument VALUE $finish_input;
 path $transformed VALUE_FLOW{0,3} $finish_input as $handoff2;
 emit $unit, $prepare, $transform, $finish;
}
```

Los tres `different` son lo que exige **tres hooks distintos**: reutilizar uno para
dos pasos no es un esqueleto de tres pasos. Las dos cadenas `VALUE_FLOW` son lo que
exige que los pasos estén **encadenados por valor**, que es la diferencia entre un
esqueleto y tres callbacks sueltos.

El `any {} or {}` repite el patrón de `decorator#callable-wrapper`: en Java un hook
se invoca como método sobre la interfaz funcional (`prepare.getAsInt()`), en los
demás como llamada directa.

**Lo que no prueba** (declarado en `query_claim`): el orden real de ejecución más
allá de la cadena de valores, pasos en ramas excluyentes, ni que el esqueleto sea
reutilizado por varios clientes.

## Positivo y negativos

Positivo: **1 match** por lenguaje, con tres hooks distintos.

| Negativo | Por qué no hay match |
|---|---|
| Los hooks no se pasan el valor (`transform(0)`, `finish(0)`) | falta la cadena `VALUE_FLOW` |
| Solo dos hooks | falta el tercer parámetro |
| Un hook reutilizado para dos pasos | `different` falla |
| Los pasos no están encadenados (el segundo usa una constante) | falta la cadena de valor |

Más un positivo con hooks renombrados (`pipeline`/`first`/`second`/`third`).

## Archivos

- `src/ken/structural/patterns/template-method.toml`: variante `ready` con query;
  raíz con unión de tres variantes.
- `tests/structural/test_template_method_composed_skeleton.py`: 14 tests.

Sin cambios en `src/ken/structural/*.py` y sin subir `IR_VERSION`.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_template_method_composed_skeleton.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/
```

- Matriz nueva + catálogo: **285 passed**.
- Suite estructural completa: **6.753 passed, 140 xfailed**, sin fallos.
- `mypy src/ken`: 109 archivos, sin errores.

## Inventario

**53 ready / 24 design** (antes 52 / 25).

## Siguiente paso

El cluster de cierres/callables ya tiene su recorrido probado en ocho lenguajes.
Quedan con la misma forma: `command#command-closure` (almacenar el callable y
invocarlo diferido), `chain#middleware-closures` (encadenar `next` con salida
temprana, que sí requiere alcanzabilidad P2.1) y `adapter#functional-adapter`
(transformar argumentos antes de delegar).
