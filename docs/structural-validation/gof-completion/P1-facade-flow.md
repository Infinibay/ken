# P1 / Facade producer→consumer flow

Estado: **validado** (P1.2 — bloque lineal, subconjunto único-escritura).

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

- `tests/structural/test_algorithm_facade.py` — 21 passed, 0 xfailed sobre
  commit `ee8605b`. Cobertura:
  - `test_strict_direct_value_handoff_survives_independent_work` × 6 casos
    (nested / nested-noise × py / java / ts) pasa en strict.
  - `test_two_delegations_do_not_prove_value_handoff` × 3 lenguajes: pasa
    (refined=False acepta, refined=True estricto descarta).
  - `test_possible_mode_can_discover_handoff_through_local` × 3 lenguajes
    pasa en modo `possible`.
  - `test_strict_handoff_through_unchanged_local_with_intermediate_work`
    × 3 lenguajes pasa ahora en `strict`.
  - `test_possible_flow_does_not_certify_assignment_stability_or_order`
    × 6 casos (overwritten / reversed × py / java / ts) sigue documentando
    la limitación: refined=False acepta, possible acepta, strict rechaza.
- `examples/bench/probe_ir_assignment_precision.py` — bench existente
  para `linear`/`overwritten`/`reversed` en modo strict/possible.

## Archivos cambiados

- `src/ken/structural/kenql.py` — `as_value` (kenql.py:628) recoge los
  hechos `UNIQUE_BINDING_WRITE` que ya emite `binding_writes.py` para
  callables estructurados con exactamente una escritura explícita por
  almacenamiento. Cuando el `source` de la carga aparece en ese conjunto,
  el `VALUE_FLOW` emitido desde el `result(producer)` hacia el
  `loaded-value` del argumento lleva `modality='must'`. Cuando hay
  múltiples escrituras (overwritten), ramas, dynamic-execution o
  control-or-indirect-write, no se emite `UNIQUE_BINDING_WRITE` y la
  modalidad se conserva en `'may'`, que strict rechaza.
- `tests/structural/test_algorithm_facade.py` — se elimina el marcador
  `xfail(strict=True)` del test ahora satisfecho. Razón previa obsoleta:
  "Local call argument loads lack reaching-definition proof; VALUE_FLOW
  is may".

## Comandos ejecutados + resultados

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_facade.py
# 21 passed, 0 xfailed in 1.13s   (sobre ee8605b)

.venv/bin/python -m pytest -o addopts='' -q \
  tests/structural/test_iterator_augmented_state.py \
  tests/structural/test_return_flow.py \
  tests/structural/test_binding_write_counts.py \
  tests/structural/test_algorithm_bridge.py \
  tests/structural/test_algorithm_strategy.py \
  tests/structural/test_path_convergence.py \
  tests/structural/test_alternative_proofs.py \
  tests/structural/test_discarded_results.py
# 259 passed, 3 xfailed in 3.90s   (sin regresiones)

.venv/bin/python -m pytest -o addopts='' -q \
  tests/structural/test_algorithm_*.py \
  tests/structural/test_gof_executable.py \
  tests/structural/test_lazy_fact_index.py \
  tests/structural/test_member_transfers.py \
  tests/structural/test_modern_patterns.py \
  tests/structural/test_returned_query_values.py \
  tests/structural/test_stored_product_builder.py
# 1187 passed, 146 xfailed in 53.78s

.venv/bin/python -m pytest -o addopts='' -q \
  tests/structural/test_cache_aside.py \
  tests/structural/test_cache_aside_flow.py \
  tests/structural/test_optional_cache_aside.py \
  tests/structural/test_read_through_cache.py \
  tests/structural/test_unit_of_work.py \
  tests/structural/test_memento_accessors.py \
  tests/structural/test_adapted_dispatch.py \
  tests/structural/test_adapted_continuation.py \
  tests/structural/test_exception_retry.py \
  tests/structural/test_dispatch_table.py \
  tests/structural/test_operators.py \
  tests/structural/test_iteration_values.py \
  tests/structural/test_indexed_arguments.py \
  tests/structural/test_kenql_literals.py \
  tests/structural/test_lazy_null_flow.py \
  tests/structural/test_implicit_lazy_fields.py \
  tests/structural/test_eager_singleton.py \
  tests/structural/test_java_packages.py \
  tests/structural/test_cpp_iterator.py \
  tests/structural/test_cpp_constructor_initializers.py \
  tests/structural/test_cpp_qualified_types.py \
  tests/structural/test_csharp_field_modifiers.py \
  tests/structural/test_retained_contract_command.py \
  tests/structural/test_rust_derived_clone.py \
  tests/structural/test_stored_command.py \
  tests/structural/test_callable_strategy.py \
  tests/structural/test_builder_input_writes.py \
  tests/structural/test_catalog.py \
  tests/structural/test_catalog_ir_contracts.py \
  tests/structural/test_gof_instruction_corpus.py
# 1892 passed in 57.55s
```

## Corpus / commit / hash

- Baseline: `cba4543 chore(structural): freeze P0 baseline before GoF-variant work`.
- P1.2 (esta entrega): `ee8605b feat(structural): upgrade VALUE_FLOW to must when argument storage has a unique write`.

## Cobertura real de P1

Esta entrega cubre únicamente **P1.2 para el caso de bloque lineal con
almacenamiento de única escritura explícita** dentro del callable. La
aceptación mínima del plan exige además:

- `x=make(); saved=x; x=0; use(saved)` positivo (alias local conservando
  estado tras reasignación del binding original). Sigue sin modelarse;
  el `as_value` actual emite `VALUE_FLOW` desde cada `ASSIGNED_FROM` del
  `source`, no desde los del alias.
- Shadowing y ramas mutuamente excluyentes sin join espurio. No se ha
  extendido `return_flow.py` con uniones por brazo.
- Dos argumentos con el mismo spelling y orígenes independientes. No se
  distingue por ocurrencia.

Estos tres casos siguen dependiendo de un módulo `reach.py` paralelo a
`return_flow.py` que recorra el cuerpo del callable y ate cada `LOADED_FROM`
a un conjunto de definiciones alcanzantes con su región. La señal
`UNIQUE_BINDING_WRITE` aquí reutilizada es suficiente para el subconjunto
lineal-no-rama; los demás casos necesitan análisis explícito por
ocurrencia/región, como propone P1.4–P1.5.

## Casos desconocidos y por qué

- `value = reader.read(key); log(123); writer.write(value)`: ahora se
  reconoce en modo `strict` porque `binding_writes` ya marca
  `UNIQUE_BINDING_WRITE(value)` y `kenql.as_value` eleva la modalidad a
  `must`. El motor `Engine.facts` acepta hechos `must` sin marcar
  `possible:` en el `unknown` del row.
- `overwritten` (`value = reader.read(key); ... value = 0; writer.write(value)`):
  el almacenamiento tiene dos `ASSIGNED_FROM`; `UNIQUE_BINDING_WRITE` no
  se emite; la modalidad se queda en `may`. Strict rechaza el match.
- `reversed` (`value = 0; result = writer.write(0); ... value = reader.read(key);`):
  el argumento del consumidor es literal `0`, no `LOADED_FROM`. No se
  emite `VALUE_FLOW` alguno, así que el camino `path $produced VALUE_FLOW{0,3} $input`
  no existe. Strict no hace match. Possible tampoco, salvo que la prueba
  `assert detect(language, 'reversed', evidence_mode='possible')` espere
  el comportamiento por contrato del modo `possible` sobre reglas sin
  flujo. Se mantiene el test tal cual porque documenta esa limitación.

## Siguiente paso concreto

P1.4 — modelar estados por brazo (`if`/`else`, `elif_clause`) sin formar
el producto cartesiano. Reutilizar la infraestructura de
`return_flow.sequential_returns` (entornos por región, snapshots por
binding) para emitir un nuevo par mínimo: `x = make(); if cond: x = 0;
use(x)` debe rechazar en strict (origenes distintos), `if cond: x = make();
else: x = make(); use(x)` debe aceptar como `may` (origenes
independientes, mismo lado). Sin este paso, las variantes que conservan
estado tras alias (`saved = x; x = 0; use(saved)`) no entran todavía al
conjunto de positivos cubiertos.
