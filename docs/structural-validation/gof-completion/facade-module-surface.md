# `facade#module-surface` — vertical end-to-end (IR 1.50)

Estado: **bloqueado con motivo medido**. 3 de 5 lenguajes funcionan; Go y Rust
quedan para P1.6. La fila sigue `design`.
Fecha: 2026-09-13. Base: `a197510`.

## Qué se intentó

En lugar de seguir acumulando capacidades de IR, se tomó **una** variante del
inventario y se llevó hasta el final: fixtures, query y tests. El objetivo era
obtener un binario claro —la variante pasa a `ready`, o queda bloqueada con un
motivo concreto y reproducible—. Este documento registra el segundo caso.

## Lo que el IR ya daba (y no hizo falta tocar)

El traspaso productor→consumidor, que es el corazón del contrato, **ya funciona**
gracias a IR 1.48/1.49. Para una función de módulo:

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

El logging independiente (`metric = 1 + 2`, `print(metric)`) no rompe nada. Es
decir: el trabajo de P1 sí habilitó algo real; este vertical lo confirma.

## Lo que faltaba — dos huecos concretos

### 1. `EXPORT` no se emitía nunca

`EXPORT_SYNTAX` se emitía solo para `export_statement` (JS/TS) como texto crudo.
La relación `EXPORT` **no la producía nadie**, y Python, Go y Rust no tenían
ninguna evidencia de visibilidad. `requires = ["exports", "call_graph"]` de la
fila no estaba satisfecho.

Implementado en `frontend.py`: `mark_export` emite `module EXPORT <símbolo>` para
declaraciones de nivel de módulo, con la regla de visibilidad **propia de cada
lenguaje** (nunca una convención de proyecto):

| Lenguaje | Regla | `basis` |
|---|---|---|
| javascript / typescript | `export function` / `export class` envolvente | `explicit-export` |
| javascript / typescript | `export { a, b }`, `export default a` | `export-clause` |
| rust | modificador `pub` | `visibility-modifier` |
| go | inicial mayúscula | `public-name` |
| python | nombre de nivel de módulo sin `_` inicial | `public-name` |

`__all__` **no** se interpreta: un nombre público de módulo sigue siendo
importable aunque no se re-liste ahí. Es una limitación declarada, no una
garantía.

### 2. La entidad módulo no emitía su hecho `IS`

`require $module IS MODULE` no daba ningún match: el módulo se construye a mano
en `Lowerer.__init__` y no pasa por `entity()`, así que era la única entidad sin
su hecho de tipo. Corregido añadiendo `module IS MODULE`.

Sin ese arreglo la query era inescribible con un sujeto tipado.

## Contrato validado

```kenql
query facade_module_surface {
 require $module IS MODULE;
 require $module EXPORT $entry;
 require $entry IS CALLABLE;
 require $entry HAS_CALL $producer;
 require $producer RESULT $produced;
 require $entry HAS_CALL $consumer;
 require $consumer ARGUMENT $argument;
 require $argument VALUE $input;
 path $produced VALUE_FLOW{0,3} $input as $flow;
 different $producer $consumer;
 emit $module, $entry, $producer, $consumer;
}
```

Resultado en el positivo (python, con nombres arbitrarios `fetch`/`store`/`run`):

```text
$module    facade.py::module
$entry     CALLABLE:run@77
$producer  CALL:107@107:121    # fetch(key)
$consumer  CALL:170@170:187    # store(carried)
```

## Cobertura real: 3 de 5

| Lenguaje | Evidencia de export | Procedencia del traspaso | Estado |
|---|---|---|---|
| python | ✅ 3 `EXPORT` | ✅ `must` | **detecta** |
| javascript | ✅ 3 `EXPORT` | ✅ `must` | **detecta** |
| typescript | ✅ 3 `EXPORT` | ✅ `must` | **detecta** |
| go | ✅ 3 `EXPORT` | ❌ `unsupported: language` | bloqueado |
| rust | ✅ 3 `EXPORT` | ❌ `unsupported: language` | bloqueado |

Negativos verificados en los tres lenguajes cubiertos (todos sin match): entrada
no pública, entrada pública sin coordinación, resultado sobrescrito antes de
consumir, consumo antes de la producción, y consumidor que recibe una constante.

## El bloqueo exacto

El pase `structured-locals/3` solo admite los lenguajes de su lista blanca
(`return_flow.py`, `reason='language'`). La extensión a Go, Rust y C++ es
**P1.6** en el plan, con contratos explícitos de asignación múltiple, `move` y
referencias, y con la advertencia de no simular semántica Python.

Medición del intento, para que la próxima sesión no repita el trabajo:

- **Rust**: agregar `'rust'` a la lista blanca **ya produce** `supported` y el
  traspaso correcto (`must origins=[CALL:140]`) en este fixture. **No se
  habilitó**: P1.6 exige antes los contratos de `move`/`borrow`, y publicar el
  lenguaje sin ellos arriesga hechos falsos en código con ownership real.
- **Go**: no alcanza con la lista blanca. `ReadData`/`WriteData` salen
  `nested-return` y `Execute` sale `nonlocal-or-nested-write`. Go necesita
  trabajo real de P1.6 (declaración corta `:=`, retornos `(valor, error)`).

## Por qué la fila sigue `design`

Dos razones independientes, ambas verificables:

1. **Criterio de cierre del plan**: «todos sus lenguajes objetivo cubiertos». La
   fila declara cinco y solo tres funcionan. Recortar la lista a tres sería
   exactamente lo que el plan prohíbe («cubrirlos sin recortar la lista
   silenciosamente»).
2. **Contrato del catálogo**: `test_catalog_ir_contracts.py` exige
   `assert not item.get('query')` para toda variante `design` — «a pending
   variant is visible metadata, not a silently enabled query». Por eso la query
   validada vive en el test y **no** en el TOML: no puede publicarse sin
   promover la fila, y no puede promoverse sin Go y Rust.

No se dividió la fila en dos para que una mitad quedara `ready`: la diferencia
es cobertura de análisis, no un contrato de lenguaje distinto, y el plan advierte
que el conteo es «una consecuencia, no una métrica que justifique duplicar
queries».

## Archivos

- `src/ken/structural/frontend.py`: `mark_export`, `export_basis`,
  `export_clause_names`, `exported_names`, `module IS MODULE`.
- `src/ken/structural/model.py`: `IR_VERSION` 1.49.0 → 1.50.0.
- `src/ken/structural/patterns/facade.toml`: metadatos reales de la fila
  (`requires`, `missing_capability`, `fixtures_status`); sin query.
- `tests/structural/test_facade_module_surface.py`: 24 tests.

## Validación

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_facade_module_surface.py
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_catalog_ir_contracts.py
.venv/bin/python -m mypy src/ken
```

- Matriz nueva: **24 passed**.
- Catálogo + Facade + contratos IR: **307 passed**.
- Suite estructural completa: **6.631 passed, 146 xfailed**, sin fallos
  (baseline previo: 6.607 / 146; el delta son los 24 tests nuevos).
- `mypy src/ken`: 107 archivos, sin errores.

Hashes de esta entrega:

| Archivo | sha256 |
|---|---|
| `src/ken/structural/frontend.py` | `031ea620a2247a7aefee0a7c9f71274bd3c4cf00ace89b0ad08a1bdd49089188` |
| `src/ken/structural/model.py` | `5edfff38c100cd844f4d12b34a3a04afd08f22b0601de357e45cb9d08800bc5d` |
| `src/ken/structural/patterns/facade.toml` | `0d965d09e49fb4f335c5b54b88aed9fe5d0c92cece57c3418d19d85b112abc37` |
| `tests/structural/test_facade_module_surface.py` | `254842f896d7cf44b64da6d3bb1b72d5e8fcba226033e2354bcd9f42fd39f49e` |

## Siguiente paso concreto

1. **P1.6 para Go**: empezar por `short_var_declaration` (`:=`) como escritura
   reconocida y por los retornos `(valor, error)`. Es el bloqueo real de la fila.
2. **P1.6 para Rust**: habilitar el lenguaje en la lista blanca **junto con** los
   contratos de `move`/`borrow`, no antes. El fixture de este documento ya sirve
   como positivo.
3. Cuando ambos pasen, mover `QUERY` del test al TOML, poner
   `status = "ready"`, actualizar `missing_capability` y comprobar la raíz
   `gof.facade` con un positivo exclusivo de la variante.
