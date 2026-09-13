# P1.4 — branch awareness for UNIQUE_BINDING_WRITE

Estado: **validado** (gating de `UNIQUE_BINDING_WRITE` a escrituras en cuerpo).

Tarea exacta: que `binding_writes/1` no emita `UNIQUE_BINDING_WRITE` cuando la
única escritura vive dentro de un brazo `if`/`elif`/`else`, conservando el
upgrade a `modality='must'` solo para el caso lineal sin ramas.

## Contrato

Para una `STORAGE` con un único `ASSIGNMENT_TARGET` en el callable:

- Si la escritura está en el cuerpo del callable (no dentro de ningún brazo
  condicional) → se emite `UNIQUE_BINDING_WRITE`.
- Si la escritura está dentro de un `if_statement`, `elif_clause` o
  `else_clause` → no se emite `UNIQUE_BINDING_WRITE`.

Razón: cuando solo uno de los brazos asigna el binding, el otro brazo deja
el binding indefinido o con un origen distinto. El plan P1.4 exige explícitamente
"si difieren o uno queda desconocido, no inventar un único origen cierto".
La forma mínima y reversible de respetar esa regla sin construir todavía el
walk per-arm completo es cortar la señal de upgrade en su origen.

## Archivos cambiados

- `src/ken/structural/binding_writes.py`
  - Helper nuevo `_inside_branch_arm(operations, op)` que recorre la cadena
    de padres hasta encontrar un `FUNCTION` (no es rama) o un
    `if_statement`/`elif_clause`/`else_clause` (sí es rama).
  - Importación de `operations` por id al inicio del pase para que el helper
    pueda subir.
  - Emisión de `UNIQUE_BINDING_WRITE` condicionada a `not _inside_branch_arm`.
  - `BINDING_WRITE_COUNT` se sigue emitiendo siempre: el conteo es un hecho
    diagnóstico, no una señal de flujo.
- `tests/structural/test_binding_write_branches.py` — 4 casos sobre Python:
  - `test_linear_unique_write_in_body_is_marked` (positivo: body write debe
    emitir `UNIQUE_BINDING_WRITE`).
  - `test_single_arm_conditional_write_is_not_marked_unique` (negativo:
    `if flag: x = make()` sin else).
  - `test_two_arm_conditional_writes_are_not_marked_unique` (negativo:
    ambos brazos escriben, mismo spelling).
  - `test_body_write_followed_by_arm_overwrite_is_not_marked_unique` (negativo:
    cuerpo asigna, brazo sobreescribe).

Las pruebas filtran por `STORAGE` con `name == 'value'` para no ser
contaminadas por las `reader` / `writer` del `__init__`, que también son
unique-write legítimos.

## Comandos ejecutados + resultados

```sh
.venv/bin/python -m pytest -o addopts='' -q \
  tests/structural/test_binding_write_branches.py
# 4 passed in 0.07s   (sobre aff9320)

.venv/bin/python -m pytest -o addopts='' -q \
  tests/structural/test_algorithm_facade.py
# 21 passed in 1.15s   (sin regresión: P1.2 sigue verde)

.venv/bin/python -m pytest -o addopts='' -q \
  tests/structural/test_algorithm_facade.py \
  tests/structural/test_algorithm_strategy.py \
  tests/structural/test_algorithm_bridge.py \
  tests/structural/test_binding_write_counts.py \
  tests/structural/test_binding_write_branches.py \
  tests/structural/test_branch_return_flow.py \
  tests/structural/test_return_flow.py \
  tests/structural/test_iterator_augmented_state.py \
  tests/structural/test_member_transfers.py \
  tests/structural/test_modern_patterns.py \
  tests/structural/test_returned_query_values.py \
  tests/structural/test_stored_product_builder.py \
  tests/structural/test_path_convergence.py \
  tests/structural/test_alternative_proofs.py \
  tests/structural/test_discarded_results.py \
  tests/structural/test_gof_executable.py \
  tests/structural/test_lazy_fact_index.py
# 935 passed, 3 xfailed in 28.09s   (sin regresiones)
```

## Casos cubiertos y por qué

- `x = make(); use(x)` — escritura en cuerpo, una sola escritura:
  `UNIQUE_BINDING_WRITE` se emite y `kenql.as_value` eleva `VALUE_FLOW` a
  `must`. El test `test_strict_handoff_through_unchanged_local_with_intermediate_work`
  sigue pasando en `strict`.
- `if flag: x = make(); use(x)` (sin `else`) — escritura dentro de
  `if_statement`, una sola escritura: `UNIQUE_BINDING_WRITE` NO se emite;
  `VALUE_FLOW` se queda en `may`; `strict` rechaza; `possible` aceptaría.
  Esto respeta la regla "uno queda desconocido, no inventar".
- `if flag: x = make() else: x = make(); use(x)` — dos escrituras dentro de
  brazos: ya sin `UNIQUE_BINDING_WRITE` (count == 2); ahora además el gate
  de rama refuerza la no-emisión. `may` en ambos modos de evidencia.
- `x = make(); if flag: x = 0; use(x)` — escritura en cuerpo + sobreescritura
  en brazo: count == 2; ya sin `UNIQUE_BINDING_WRITE`. `may` en ambos modos.

## Casos que P1.4 sigue sin cubrir

Esta entrega solo cierra el gating de la señal de upgrade. Quedan fuera
del scope de este commit:

- Walk per-arm que recorra cada `CALL` dentro del callable y emita
  `ARGUMENT_ORIGIN` / `ARGUMENT_REACHES` análogos a los `RETURN_ORIGIN`
  / `RETURN_REACHES` que ya produce `return_flow.sequential_returns`.
  La infraestructura (regiones, snapshots, join sin producto cartesiano)
  ya existe; falta extenderla para capturar cargas en argumentos y no
  solo operandos de retorno.
- Tests end-to-end de Facade con ramas que verifiquen
  `path $produced VALUE_FLOW $input` en `strict` para los casos positivos
  y `may` para los negativos. Hoy solo se prueba el hecho
  `UNIQUE_BINDING_WRITE` a nivel de pase; el contrato P1.4 sobre el match
  completo aún no se ejercita.

Estos dos huecos se atacarán en pasos posteriores siguiendo el orden
recomendado por el plan (P1.5 regiones expresivas, P1.3 argumento/callee).

## Corpus / commit / hash

- Baseline: `ee8605b feat(structural): upgrade VALUE_FLOW to must when argument storage has a unique write`.
- P1.4 (esta entrega): `aff9320 feat(structural): gate UNIQUE_BINDING_WRITE on body writes only (P1.4)`.