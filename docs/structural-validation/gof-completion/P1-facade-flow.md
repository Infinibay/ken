# P1 / Facade producer→consumer flow

Estado: en curso (P1.2 — bloque lineal).

Tarea exacta: conseguir que `tests/structural/test_algorithm_facade.py::test_strict_handoff_through_unchanged_local_with_intermediate_work`
pase en modo `strict` para Python, Java y TypeScript, sin que pasen en modo
`strict` los negativos `overwritten` ni `reversed`.

## Contrato requerido

Para una operación de un objeto $unit que delega en dos campos de tipos
distintos:

- `$producer` (sobre `$first`) produce `$produced`.
- `$consumer` (sobre `$second`) recibe como argumento `$argument` cuyo valor
  `$input` debe ser exactamente `$produced`, no cualquier asignación histórica.
- Si entre la producción y el consumo hay escrituras a la misma `place` que
  no son alias del valor producido, el resultado debe rechazarse.
- Si el consumo aparece textualmente antes de la producción, debe rechazarse.

## Fuentes propias y negativos

- `tests/structural/test_algorithm_facade.py` — 18 passed, 3 strict xfailed
  en baseline `cba4543`. Tests relevantes:
  - `test_strict_direct_value_handoff_survives_independent_work` (pasa, modo strict)
  - `test_two_delegations_do_not_prove_value_handoff` (pasa con resultado
    directo descartado en strict)
  - `test_possible_mode_can_discover_handoff_through_local` (pasa, modo possible)
  - `test_strict_handoff_through_unchanged_local_with_intermediate_work` (xfail)
  - `test_possible_flow_does_not_certify_assignment_stability_or_order`
    (pasa, documenta limitación de `possible`)
- `examples/bench/probe_ir_assignment_precision.py` — bench existente
  para `linear`/`overwritten`/`reversed` en modo strict/possible.

## Archivos cambiados

(ninguno aún)

## Comandos ejecutados + resultados

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_facade.py
# 18 passed, 3 xfailed in 1.18s  (baseline sobre cba4543)
```

## Corpus / commit / hash

Baseline: `cba4543 chore(structural): freeze P0 baseline before GoF-variant work`.

## Casos desconocidos y por qué

- `value = reader.read(key); log(123); writer.write(value)` no se reconoce
  en modo `strict` porque `kenql.as_value` emite `VALUE_FLOW` con
  `modality='may'` desde el resultado del `produce` al valor cargado del
  argumento (kenql.py:643). El motor `Engine.facts` rechaza hechos `may` en
  modo `strict` salvo que la cláusula los pida explícitamente.
- `overwritten` y `reversed` no deben producir match en `strict`. La
  `return_flow.py` ya distingue "no rebinding" frente a "rebinding antes
  del uso" para RETURNS; todavía no emite nada para ARGUMENT reads.

## Siguiente paso concreto

Extender `return_flow.py` (o un nuevo módulo `reach.py` paralelo) para
recorrer el cuerpo lineal de callables estructurados en Python/Java/TS y
asignar a cada `LOADED_FROM` la(s) escritura(s) alcanzante(s) por scope.
Cuando el resultado del `$producer` sea el único origen alcanzante del
valor cargado en `$argument`, emitir `VALUE_FLOW` con `modality='must'`
desde `result(producer)` hasta `value_id` del argumento, en lugar del
`may` actual. Validar con:

1. `test_strict_handoff_through_unchanged_local_with_intermediate_work` — pasa.
2. `test_possible_flow_does_not_certify_assignment_stability_or_order` —
   sigue pasando (overwritten/reversed siguen siendo `may` o sin facts).
3. `test_possible_mode_can_discover_handoff_through_local` — sigue pasando
   (modo `possible` no exige `must`).
4. `test_strict_direct_value_handoff_survives_independent_work` — sigue
   pasando (nested directo es ruta soportada).
