# `adapter#functional-adapter` (8 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados.
Fecha: 2026-09-13. Base: `7e98fda`.

## Quinta variante que no necesitó capacidad nueva

El IR ya registraba todo lo que la adaptación funcional pide:

| Necesidad | Evidencia ya existente |
|---|---|
| La fábrica recibe un callable | `HAS_PARAMETER` |
| Devuelve un wrapper que lo captura | `RETURNS` + `CAPTURES` |
| Invoca el capturado | `CALLEE_VALUE` (o `RECEIVER` en Java) |
| **Adapta la entrada**: dos argumentos distintos | dos `ARGUMENT` con posiciones distintas |
| Cada argumento viene de indexar el parámetro | `ARGUMENT` → `VALUE` → `INDEX` |

Fixture mínimo (Python):

```python
def adapt(inner):
    def wrapped(pair):
        return inner(pair[0], pair[1])
    return wrapped
```

## Cómo se distingue de `decorator#callable-wrapper`

Las dos variantes tienen la misma estructura básica —fábrica, cierre, captura,
invocación—, así que la obligación que las separa es **la adaptación**:

| Variante | Qué exige |
|---|---|
| `decorator#callable-wrapper` | el wrapper invoca el capturado **reenviando su propio argumento** |
| `adapter#functional-adapter` | el wrapper invoca el capturado con **dos argumentos distintos**, cada uno indexado del único parámetro |

El negativo de passthrough lo verifica explícitamente: `inner(value)` con un solo
argumento **no** matchea esta variante. Y el negativo de argumentos constantes
(`inner(1, 2)`) verifica que la adaptación venga de la entrada indexada y no de
valores fijos.

Es exactamente el solapamiento con Adapter que la ficha de `callable-wrapper`
pedía documentar.

## Contrato publicado

```kenql
query adapter {
 require $factory HAS_PARAMETER $inner;
 parameter(receiver: false) as $inner;
 require $factory RETURNS $wrapped;
 different $factory $wrapped;
 callable(constructor: false) as $wrapped;
 require $wrapped CAPTURES $inner;
 require $wrapped HAS_PARAMETER $request;
 parameter(receiver: false) as $request;
 require $wrapped HAS_CALL $delegation;
 any { require $delegation CALLEE_VALUE $inner; } or { require $delegation RECEIVER $inner; }
 count distinct $argument >= 2 {
  require $delegation ARGUMENT $argument;
 };
 require $delegation ARGUMENT $first_argument;
 require $delegation ARGUMENT $second_argument;
 different $first_argument $second_argument;
 require $first_argument VALUE $first_value;
 require $first_value INDEX $first_index;
 require $second_argument VALUE $second_value;
 require $second_value INDEX $second_index;
 emit unit=$wrapped, $factory, $inner, $wrapped, $request;
}
```

El rol compartido `unit` es el **wrapper devuelto**: en las otras dos variantes de
Adapter es la clase adaptadora, y aquí el callable adaptado.

**Lo que no prueba** (declarado en `query_claim`): el contrato de tipos de la
adaptación, la variante de **transformación de salida**, y que el callable
adaptado sea el efectivamente invocado en ejecución.

## Positivo y negativos

Positivo: **1 match** por lenguaje.

| Negativo | Por qué no hay match |
|---|---|
| Passthrough de un argumento | es `decorator#callable-wrapper`, no adaptación |
| Dos argumentos constantes (`inner(1, 2)`) | no vienen de indexar la entrada |
| Adapta un callable que **no** capturó | falta `CAPTURES` hacia el invocado |
| Llamada inmediata sin wrapper | falta el cierre devuelto |
| El wrapper no se devuelve | falta `RETURNS` |

## Archivos

- `src/ken/structural/patterns/adapter.toml`: variante `ready` con query; raíz con
  unión de tres variantes.
- `tests/structural/test_adapter_functional_adapter.py`: 14 tests.

Sin cambios en `src/ken/structural/*.py` y sin subir `IR_VERSION`.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_adapter_functional_adapter.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/
```

- Matriz nueva + catálogo: **287 passed**.
- Suite estructural completa: **6.784 passed, 140 xfailed**, sin fallos.
- `mypy src/ken`: 109 archivos, sin errores.

## Inventario

**55 ready / 22 design** (antes 54 / 23).

## Balance del método

**Cinco de las once variantes cerradas no necesitaron capacidad nueva.** En este
caso el IR tenía incluso la pieza que parecía específica —`INDEX` sobre el
argumento del parámetro—, así que el trabajo pendiente era de expresión del
contrato y de distinguirlo de la variante vecina.

## Siguiente paso

Queda del cluster de cierres `chain#middleware-closures` (ocho lenguajes), que
además necesita alcanzabilidad (P2.1) para la salida temprana. Sigue pendiente
`abstract-factory#structural-families`, el único caso medido donde la query directa
revienta el presupuesto. Y los bloques grandes sin empezar: modelos de bus/topic
(P6), tipos suma (P5), protocolos async y copia por lenguaje.
