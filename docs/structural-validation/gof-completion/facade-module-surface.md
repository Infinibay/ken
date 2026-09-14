# `facade#module-surface` — vertical end-to-end (IR 1.50)

Estado: **cerrada**. La variante es `ready` en sus cinco lenguajes declarados.
Fecha: 2026-09-13. Base: `d633943` (antes de la promoción).

## Qué se intentó

En lugar de seguir acumulando capacidades de IR, se tomó **una** variante del
inventario y se llevó hasta el final: fixtures, query y tests. El objetivo era un
binario claro —la variante pasa a `ready`, o queda bloqueada con un motivo
concreto y reproducible—. Se recorrieron los dos lados: primero se midió el
bloqueo, y al resolverse se promovió la fila.

## Lo que el IR ya daba (y no hizo falta tocar)

El traspaso productor→consumidor **ya funcionaba** gracias a IR 1.48/1.49:

```python
def run(key):
    carried = fetch(key)
    metric = 1 + 2
    print(metric)
    return store(carried)
```

```text
ARGUMENT_ORIGIN  CALL:170 operand=STORAGE:carried
                 modality=must origins=[CALL:107]      # CALL:107 = fetch(key)
VALUE_FLOW (vista de query)  result -> loaded-value  modality=must
```

El logging independiente (`metric = 1 + 2`, `print(metric)`) no rompe nada. El
trabajo de P1 habilitó algo real, y este vertical lo confirmó.

## Huecos encontrados y cerrados

### 1. `EXPORT` no se emitía nunca

`EXPORT_SYNTAX` existía solo como texto crudo de `export_statement` (JS/TS). La
relación `EXPORT` **no la producía nadie**, y Python, Go y Rust no tenían
ninguna evidencia de visibilidad; el requisito `exports` de la fila estaba
insatisfecho. `mark_export` emite ahora `module EXPORT <símbolo>` con la regla
**propia de cada lenguaje** (nunca una convención de proyecto):

| Lenguaje | Regla | `basis` |
|---|---|---|
| javascript / typescript | `export function` / `export class` envolvente | `explicit-export` |
| javascript / typescript | `export { a, b }`, `export default a` | `export-clause` |
| rust | modificador `pub` | `visibility-modifier` |
| go | inicial mayúscula | `public-name` |
| python | nombre de nivel de módulo sin `_` inicial | `public-name` |

`__all__` **no** se interpreta: un nombre público de módulo sigue siendo
importable aunque no se re-liste ahí.

### 2. La entidad módulo no emitía su hecho `IS`

`require $module IS MODULE` no daba ningún match: el módulo se construye a mano
en `Lowerer.__init__` y no pasa por `entity()`, así que era la única entidad sin
hecho de tipo. Sin ese arreglo la query era inescribible con sujeto tipado.

### 3. Go y Rust fuera del pase (P1.6)

`structured-locals/3` solo admitía cinco lenguajes. Habilitarlos no alcanzaba:
en Go, `statement_list` (contenedor de sentencias del cuerpo) y `expression_list`
(envoltura de los operandos de `a := f(x)`) no estaban admitidos, así que
`region_for` y `call_region` devolvían `None` y todo se rechazaba.

Antes de habilitar cada lenguaje se midieron sus contratos de ownership para
comprobar que lo no modelado **se rechaza** en vez de adivinarse:

| Constructo | Resultado |
|---|---|
| Go `a, b := f()` / `a, b := 1, 2` / `a, b = b, a` | `unsupported` |
| Go `value, err := f()` + `if err != nil` | `unsupported` |
| Rust `let (a, b) = f()` | `unsupported` |
| Rust `let carried = *boxed; *boxed = 5` | `unsupported` |
| Rust `if let Some(v) = opt` | `unsupported` |
| Rust `let b = a` (move) | `supported`: `b` conserva el origen — un move preserva el valor |

El único caso de move donde el pase **afirma** algo lo afirma con razón: `b`
recibe el valor que tenía `a`. No se afirma nada sobre la usabilidad posterior de
`a`, que es lo que gobierna el borrow checker. Detalles en
[P1.6 — Go y Rust](go-rust-p16.md).

## Contrato publicado

```kenql
query facade {
 require $module IS MODULE;
 require $module EXPORT $unit;
 require $unit IS CALLABLE;
 require $unit HAS_CALL $producer;
 require $producer RESULT $produced;
 require $unit HAS_CALL $consumer;
 require $consumer ARGUMENT $argument;
 require $argument VALUE $input;
 path $produced VALUE_FLOW{0,3} $input as $flow;
 different $producer $consumer;
 emit $unit, $module, $producer, $consumer;
}
```

**Contrato del rol compartido `unit`** (revisado, no mapeado a ciegas): en
`object-surface` es una **clase**; en `module-surface` es un **callable** de
módulo. La raíz `facade` une ambas variantes y emite `$unit`, así que `unit`
significa «la unidad con fachada», con `IS CLASS` o `IS CALLABLE` según la
variante. Los roles detallados (`module`, `producer`, `consumer`) solo están
disponibles en la variante.

## Resultado por lenguaje

| Lenguaje | Evidencia de export | Procedencia del traspaso | Detecta |
|---|---|---|---|
| python | 3 `EXPORT` | `must` | ✅ |
| javascript | 3 `EXPORT` | `must` | ✅ |
| typescript | 3 `EXPORT` | `must` | ✅ |
| go | 3 `EXPORT` | `must` | ✅ |
| rust | 3 `EXPORT` | `must` | ✅ |

Negativos verificados en los cinco lenguajes (todos sin match): entrada no
pública, entrada pública sin coordinación, resultado sobrescrito antes de
consumir, consumo antes de la producción, y consumidor que recibe una constante.
Más un positivo con identificadores renombrados (`Alpha`/`Beta`/`Gamma`).

## Archivos

- `src/ken/structural/frontend.py`: `mark_export`, `export_basis`,
  `export_clause_names`, `exported_names`, `module IS MODULE`.
- `src/ken/structural/return_flow.py`: `statement_list`, `expression_list`, Go y
  Rust en la lista blanca.
- `src/ken/structural/model.py`: `IR_VERSION` 1.49.0 → 1.50.0.
- `src/ken/structural/patterns/facade.toml`: variante `ready` con query, raíz con
  unión.
- `tests/structural/test_facade_module_surface.py`: 36 tests por el nombre
  registrado `facade#module-surface`.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_facade_module_surface.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
.venv/bin/python -m pytest -o addopts='' -q --junitxml=/tmp/ken-p16-junit.xml tests/structural/
.venv/bin/python -m mypy src/ken
```

- Matriz nueva: **36 passed**.
- Suite estructural completa: **6.644 passed, 146 xfailed**, sin fallos.
- `mypy src/ken`: 107 archivos, sin errores.

## Inventario

**45 ready / 32 design** (antes 44 / 33). Es la primera variante del inventario
promovida en este trabajo.
