# Manifiesto de xfail — P0

Fecha: **2026-09-13**. Base: `8f68e74` (post IR 1.48). Suite: **6.586 passed, 146 xfailed**.

Este archivo cumple el requisito de **P0** del [PLAN.md](../../PLAN.md):
manifest por pytest node ID, no por función; clasificación individual de cada caso.

## Resumen

| Patrón | IR | CO | EE | FR | Total |
|---|---:|---:|---:|---:|---:|
| abstract_factory | 0 | 3 | 0 | 0 | 3 |
| adapter | 0 | 9 | 0 | 0 | 9 |
| bridge | 0 | 3 | 0 | 0 | 3 |
| builder | 3 | 3 | 0 | 0 | 6 |
| chain_of_responsibility | 3 | 9 | 0 | 0 | 12 |
| command | 0 | 13 | 0 | 0 | 13 |
| composite | 3 | 6 | 0 | 0 | 9 |
| decorator | 3 | 9 | 0 | 0 | 12 |
| flyweight | 3 | 6 | 0 | 0 | 9 |
| interpreter | 0 | 12 | 0 | 0 | 12 |
| iterator | 0 | 6 | 0 | 0 | 6 |
| mediator | 3 | 6 | 0 | 0 | 9 |
| memento | 0 | 3 | 0 | 0 | 3 |
| observer | 6 | 0 | 0 | 0 | 6 |
| prototype | 0 | 6 | 0 | 0 | 6 |
| proxy | 6 | 0 | 0 | 0 | 6 |
| singleton | 7 | 0 | 0 | 0 | 7 |
| state | 0 | 9 | 0 | 0 | 9 |
| visitor | 3 | 3 | 0 | 0 | 6 |
| **Total** | **40** | **106** | **0** | **0** | **146** |

## Leyenda de categorías

Cada caso se clasifica según las cuatro categorías de [PLAN.md §7](../structural-validation/gof-completion/P1-argument-occurrences.md):

- **IR — Error de IR/query:** corregir el detector, IR o query. La capacidad de fondo ya existe,
  pero no emite los hechos necesarios. Típicamente depende de P1.x, P2.x o P3.
- **CO — Contrato más fuerte:** el patrón funciona en su variante base; este xfail prueba una
  variante opcional/refinamiento. Resolver requiere implementar una operación pública adicional
  que el test pueda usar, sin endurecer la raíz.
- **EE — Expectativa errónea:** el test asume algo del lenguaje o patrón que no se sostiene.
  Requiere justificación y cambio de test. (No usar esta categoría para esconder una capacidad
  sin implementar.)
- **FR — Falta de resolución:** el test depende de un módulo/lenguaje/capacidad no modelada.
  Mantener tarea abierta y documentar unknown hasta que la capacidad exista.

## Detalle por categoría

### IR — Error de IR/query (40 casos)

#### builder (3 casos)

- **Director receiver equality does not invalidate reassigned bindings**
  - Plan ref: `G04#director / P1`
  - Acción propuesta: Necesita ARGUMENT_ORIGIN en receiver del director; depende de P1.3.
  - Node IDs (3):
    - `test_director_rebinding_does_not_mix_build_lifetimes[java]`
    - `test_director_rebinding_does_not_mix_build_lifetimes[python]`
    - `test_director_rebinding_does_not_mix_build_lifetimes[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### chain_of_responsibility (3 casos)

- **Early handled return requires control dependence beyond lexical branch containment**
  - Plan ref: `G05 / P2.1`
  - Acción propuesta: Requiere alcanzabilidad/Control dependence analysis; P2.1.
  - Node IDs (3):
    - `test_early_local_handling_still_controls_forwarding[java]`
    - `test_early_local_handling_still_controls_forwarding[python]`
    - `test_early_local_handling_still_controls_forwarding[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### composite (3 casos)

- **ITERATED_CALL does not invalidate element provenance after child rebinding**
  - Plan ref: `G07 / P1.5/P2.2`
  - Acción propuesta: ITERATED_CALL necesita invalidación correcta; depende de P1.5/P2.2.
  - Node IDs (3):
    - `test_rebound_child_is_not_the_iterated_element[java]`
    - `test_rebound_child_is_not_the_iterated_element[python]`
    - `test_rebound_child_is_not_the_iterated_element[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### decorator (3 casos)

- **Object-wrapper counts extra lexical calls without proving reachable added behavior**
  - Plan ref: `G08 / P2.1`
  - Acción propuesta: Requiere alcanzabilidad; P2.1.
  - Node IDs (3):
    - `test_unreachable_trace_does_not_add_a_responsibility[java]`
    - `test_unreachable_trace_does_not_add_a_responsibility[python]`
    - `test_unreachable_trace_does_not_add_a_responsibility[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### flyweight (3 casos)

- **Indexed key facts identify bindings but do not preserve their values through assignments; algorithms/flyweight.md**
  - Plan ref: `G11 / P1.2`
  - Acción propuesta: Indexed keys necesitan preservar valores; depende de P1.2.
  - Node IDs (3):
    - `test_interning_preserves_key_value_until_return[java]`
    - `test_interning_preserves_key_value_until_return[python]`
    - `test_interning_preserves_key_value_until_return[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### mediator (3 casos)

- **Mediator signature does not prove coordinate calls reachable after entry**
  - Plan ref: `G14 / P2.1`
  - Acción propuesta: Requiere alcanzabilidad tras entry; P2.1.
  - Node IDs (3):
    - `test_unreachable_coordination_is_not_an_executed_algorithm[java]`
    - `test_unreachable_coordination_is_not_an_executed_algorithm[python]`
    - `test_unreachable_coordination_is_not_an_executed_algorithm[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### observer (6 casos)

- **Observer signature does not correlate the incoming event with callback arguments**
  - Plan ref: `G16 / P1.3`
  - Acción propuesta: Correlación evento→callback requiere P1.3.
  - Node IDs (3):
    - `test_event_delivery_contract_rejects_discarded_event[javascript]`
    - `test_event_delivery_contract_rejects_discarded_event[python]`
    - `test_event_delivery_contract_rejects_discarded_event[typescript]`
  - Parametrizaciones (3): javascript, python, typescript

- **Observer graph signature does not reject unreachable snapshot notification**
  - Plan ref: `G16 / P2.1`
  - Acción propuesta: Notificación no reachable debe rechazarse; P2.1.
  - Node IDs (3):
    - `test_unreachable_notification_is_not_an_observer_algorithm[javascript]`
    - `test_unreachable_notification_is_not_an_observer_algorithm[python]`
    - `test_unreachable_notification_is_not_an_observer_algorithm[typescript]`
  - Parametrizaciones (3): javascript, python, typescript

#### proxy (6 casos)

- **Early denial controls later delegation without lexical branch containment**
  - Plan ref: `G18 / P2.1`
  - Acción propuesta: Control dependence; P2.1.
  - Node IDs (3):
    - `test_early_denial_is_a_valid_guarded_access_variant[java]`
    - `test_early_denial_is_a_valid_guarded_access_variant[python]`
    - `test_early_denial_is_a_valid_guarded_access_variant[typescript]`
  - Parametrizaciones (3): java, python, typescript

- **Conditional candidate does not prove all delegation paths obey access policy**
  - Plan ref: `G18 / P2.1`
  - Acción propuesta: Alcanzabilidad de delegación; P2.1.
  - Node IDs (3):
    - `test_access_enforcement_variant_rejects_unconditional_bypass[java]`
    - `test_access_enforcement_variant_rejects_unconditional_bypass[python]`
    - `test_access_enforcement_variant_rejects_unconditional_bypass[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### singleton (7 casos)

- **Lazy query requires immediate CFG entry/return adjacency even across pure independent arithmetic; algorithms/singleton.md**
  - Plan ref: `G19 / P2.5`
  - Acción propuesta: Preservación entre puntos no triviales; P2.5.
  - Node IDs (6):
    - `test_desired_lazy_algorithm_tolerates_pure_local_arithmetic[before-guard-java]`
    - `test_desired_lazy_algorithm_tolerates_pure_local_arithmetic[before-guard-python]`
    - `test_desired_lazy_algorithm_tolerates_pure_local_arithmetic[before-guard-typescript]`
    - `test_desired_lazy_algorithm_tolerates_pure_local_arithmetic[before-return-java]`
    - `test_desired_lazy_algorithm_tolerates_pure_local_arithmetic[before-return-python]`
    - … y 1 más
  - Parametrizaciones (6): before-guard-java, before-guard-python, before-guard-typescript, before-return-java, before-return-python, before-return-typescript

- **Python classmethod call target resolution is not modeled by direct-class-static**
  - Plan ref: `G19 / P4`
  - Acción propuesta: Resolución de classmethod Python; P4.
  - Node IDs (1):
    - `test_named_usage_keeps_called_owner_and_storage_scope[python-True]`
  - Parametrizaciones (1): python-True

#### visitor (3 casos)

- **Visitor parameter identity is not protected against earlier slot reassignment**
  - Plan ref: `G23 / P1.2`
  - Acción propuesta: Protección de identidad del parámetro visitor; P1.2.
  - Node IDs (3):
    - `test_replacing_received_visitor_breaks_received_visitor_contract[java]`
    - `test_replacing_received_visitor_breaks_received_visitor_contract[python]`
    - `test_replacing_received_visitor_breaks_received_visitor_contract[typescript]`
  - Parametrizaciones (3): java, python, typescript

### CO — Contrato más fuerte (106 casos)

#### abstract_factory (3 casos)

- **Uniform-family refinement needs explicit product-family compatibility evidence**
  - Plan ref: `G01#structural-families (TS/JS/Go)`
  - Acción propuesta: Implementar variante structural-families con evidencia de compatibilidad.
  - Node IDs (3):
    - `test_requested_uniform_family_refinement_rejects_mixed_provider[java]`
    - `test_requested_uniform_family_refinement_rejects_mixed_provider[python]`
    - `test_requested_uniform_family_refinement_rejects_mixed_provider[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### adapter (9 casos)

- **Broad object Adapter query does not implement input-transformation provenance**
  - Plan ref: `G02#functional-adapter`
  - Acción propuesta: Implementar variante functional-adapter con input transformation.
  - Node IDs (3):
    - `test_input_conversion_contract_rejects_discarded_input[java]`
    - `test_input_conversion_contract_rejects_discarded_input[python]`
    - `test_input_conversion_contract_rejects_discarded_input[typescript]`
  - Parametrizaciones (3): java, python, typescript

- **Broad object Adapter query does not implement output-transformation provenance**
  - Plan ref: `G02#functional-adapter`
  - Acción propuesta: Implementar variante functional-adapter con output transformation.
  - Node IDs (3):
    - `test_output_conversion_contract_rejects_discarded_result[java]`
    - `test_output_conversion_contract_rejects_discarded_result[python]`
    - `test_output_conversion_contract_rejects_discarded_result[typescript]`
  - Parametrizaciones (3): java, python, typescript

- **Same-name adaptation of arguments/results is excluded by object-adapter name inequality**
  - Plan ref: `G02#functional-adapter`
  - Acción propuesta: Levantar la exclusión por desigualdad de nombres cuando hay captura real.
  - Node IDs (3):
    - `test_conversion_does_not_require_renaming_operation[java]`
    - `test_conversion_does_not_require_renaming_operation[python]`
    - `test_conversion_does_not_require_renaming_operation[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### bridge (3 casos)

- **Injected-backend refinement does not correlate constructor input with stored implementation**
  - Plan ref: `G03#generic-composition`
  - Acción propuesta: Implementar variante generic-composition con correlación constructor→backend.
  - Node IDs (3):
    - `test_requested_injected_backend_contract_rejects_ignored_selection[java]`
    - `test_requested_injected_backend_contract_rejects_ignored_selection[python]`
    - `test_requested_injected_backend_contract_rejects_ignored_selection[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### builder (3 casos)

- **Immutable successor-builder variant remains design-only**
  - Plan ref: `G04#immutable-product`
  - Acción propuesta: Implementar variante immutable-product; bloqueada por P1.
  - Node IDs (3):
    - `test_immutable_configuration_reaches_finish_on_successor[java]`
    - `test_immutable_configuration_reaches_finish_on_successor[python]`
    - `test_immutable_configuration_reaches_finish_on_successor[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### chain_of_responsibility (9 casos)

- **Stronger same-request/result-preserving/exclusive-handler contracts are not established by conditional delegation; algorithms/chain-of-responsibility.md**
  - Plan ref: `G05#middleware-closures`
  - Acción propuesta: Refinamiento opcional con preservación exacta de request/resultado.
  - Node IDs (9):
    - `test_desired_exclusive_handler_contract_preserves_request_and_result[discard-result-java]`
    - `test_desired_exclusive_handler_contract_preserves_request_and_result[discard-result-python]`
    - `test_desired_exclusive_handler_contract_preserves_request_and_result[discard-result-typescript]`
    - `test_desired_exclusive_handler_contract_preserves_request_and_result[process-and-forward-java]`
    - `test_desired_exclusive_handler_contract_preserves_request_and_result[process-and-forward-python]`
    - … y 4 más
  - Parametrizaciones (9): discard-result-java, discard-result-python, discard-result-typescript, process-and-forward-java, process-and-forward-python, process-and-forward-typescript
    - …

#### command (13 casos)

- **Retained-contract signature does not prove field identity at runtime dispatch**
  - Plan ref: `G06#command-closure`
  - Acción propuesta: Variante refinada con identidad de campo en dispatch.
  - Node IDs (5):
    - `test_received_command_identity_contract_rejects_dispatch_after_clear[cpp]`
    - `test_received_command_identity_contract_rejects_dispatch_after_clear[csharp]`
    - `test_received_command_identity_contract_rejects_dispatch_after_clear[java]`
    - `test_received_command_identity_contract_rejects_dispatch_after_clear[python]`
    - `test_received_command_identity_contract_rejects_dispatch_after_clear[typescript]`
  - Parametrizaciones (5): cpp, csharp, java, python, typescript

- **Command actions with explicit execution context are excluded by zero-arity variants**
  - Plan ref: `G06#command-closure`
  - Acción propuesta: Levantar exclusión por aridad cero cuando hay contexto explícito.
  - Node IDs (5):
    - `test_execution_context_is_a_valid_command_parameter[cpp]`
    - `test_execution_context_is_a_valid_command_parameter[csharp]`
    - `test_execution_context_is_a_valid_command_parameter[java]`
    - `test_execution_context_is_a_valid_command_parameter[python]`
    - `test_execution_context_is_a_valid_command_parameter[typescript]`
  - Parametrizaciones (5): cpp, csharp, java, python, typescript

- **Command signature does not correlate constructor-captured payload with work arguments**
  - Plan ref: `G06#command-closure`
  - Acción propuesta: Correlacionar captura de payload con argumentos del work.
  - Node IDs (3):
    - `test_captured_payload_contract_rejects_discarded_data[java]`
    - `test_captured_payload_contract_rejects_discarded_data[python]`
    - `test_captured_payload_contract_rejects_discarded_data[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### composite (6 casos)

- **Composite signature does not enforce aggregation or argument propagation**
  - Plan ref: `G07#higher-order-traversal`
  - Acción propuesta: Refinamiento opcional de agregación en traversal.
  - Node IDs (6):
    - `test_requested_aggregate_contract_rejects_broken_value_flow[discard-result-java]`
    - `test_requested_aggregate_contract_rejects_broken_value_flow[discard-result-python]`
    - `test_requested_aggregate_contract_rejects_broken_value_flow[discard-result-typescript]`
    - `test_requested_aggregate_contract_rejects_broken_value_flow[replace-context-java]`
    - `test_requested_aggregate_contract_rejects_broken_value_flow[replace-context-python]`
    - … y 1 más
  - Parametrizaciones (6): discard-result-java, discard-result-python, discard-result-typescript, replace-context-java, replace-context-python, replace-context-typescript

#### decorator (9 casos)

- **Result transformation can decorate without a second call, which object-wrapper requires**
  - Plan ref: `G08#callable-wrapper`
  - Acción propuesta: Variante callable-wrapper con modificación aritmética del resultado.
  - Node IDs (3):
    - `test_arithmetic_result_decoration_needs_no_extra_call[java]`
    - `test_arithmetic_result_decoration_needs_no_extra_call[python]`
    - `test_arithmetic_result_decoration_needs_no_extra_call[typescript]`
  - Parametrizaciones (3): java, python, typescript

- **Result-transparency is a stronger optional contract than broad Decorator**
  - Plan ref: `G08#callable-wrapper`
  - Acción propuesta: Refinamiento opcional de transparencia de resultado.
  - Node IDs (3):
    - `test_transparent_tracing_variant_rejects_discarded_result[java]`
    - `test_transparent_tracing_variant_rejects_discarded_result[python]`
    - `test_transparent_tracing_variant_rejects_discarded_result[typescript]`
  - Parametrizaciones (3): java, python, typescript

- **Callable-wrapper variant remains design-only in the GoF catalog**
  - Plan ref: `G08#callable-wrapper`
  - Acción propuesta: Implementar variante callable-wrapper.
  - Node IDs (3):
    - `test_functional_decorator_is_a_valid_variant[java]`
    - `test_functional_decorator_is_a_valid_variant[python]`
    - `test_functional_decorator_is_a_valid_variant[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### flyweight (6 casos)

- **Pooling query does not prove miss-only creation or stable returned identity; algorithms/flyweight.md**
  - Plan ref: `G11#entry-api`
  - Acción propuesta: Refinamiento opcional entry-api con identidad estable.
  - Node IDs (3):
    - `test_interning_must_reuse_an_existing_entry[java]`
    - `test_interning_must_reuse_an_existing_entry[python]`
    - `test_interning_must_reuse_an_existing_entry[typescript]`
  - Parametrizaciones (3): java, python, typescript

- **Stronger stable-intrinsic-state contract: draw stores per-call position into shared font; generic pooling query does not inspect use**
  - Plan ref: `G11#entry-api`
  - Acción propuesta: Estado intrínseco estable: variante refinada.
  - Node IDs (3):
    - `test_desired_stable_intrinsic_state_rejects_extrinsic_overwrite[java]`
    - `test_desired_stable_intrinsic_state_rejects_extrinsic_overwrite[python]`
    - `test_desired_stable_intrinsic_state_rejects_extrinsic_overwrite[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### interpreter (12 casos)

- **Interpreter signature does not prove every operand context or combine/result consumption; see algorithms/interpreter.md**
  - Plan ref: `G12#expression-sum`
  - Acción propuesta: Implementar variante expression-sum con consumo de operandos.
  - Node IDs (12):
    - `test_desired_pure_binary_contract_requires_all_contexts_and_result_consumption[discard-both-java]`
    - `test_desired_pure_binary_contract_requires_all_contexts_and_result_consumption[discard-both-python]`
    - `test_desired_pure_binary_contract_requires_all_contexts_and_result_consumption[discard-both-typescript]`
    - `test_desired_pure_binary_contract_requires_all_contexts_and_result_consumption[discard-left-java]`
    - `test_desired_pure_binary_contract_requires_all_contexts_and_result_consumption[discard-left-python]`
    - … y 7 más
  - Parametrizaciones (12): discard-both-java, discard-both-python, discard-both-typescript, discard-left-java, discard-left-python, discard-left-typescript
    - …

#### iterator (6 casos)

- **Finite-sequence refinement does not prove numeric progress or returned element provenance**
  - Plan ref: `G13#callback-iterator`
  - Acción propuesta: Refinamiento opcional con progresión numérica o procedencia del elemento.
  - Node IDs (6):
    - `test_requested_finite_sequence_contract_rejects_broken_traversal[no-progress-java]`
    - `test_requested_finite_sequence_contract_rejects_broken_traversal[no-progress-python]`
    - `test_requested_finite_sequence_contract_rejects_broken_traversal[no-progress-typescript]`
    - `test_requested_finite_sequence_contract_rejects_broken_traversal[unrelated-result-java]`
    - `test_requested_finite_sequence_contract_rejects_broken_traversal[unrelated-result-python]`
    - … y 1 más
  - Parametrizaciones (6): no-progress-java, no-progress-python, no-progress-typescript, unrelated-result-java, unrelated-result-python, unrelated-result-typescript

#### mediator (6 casos)

- **Mediator signature requires distinct colleague types rather than distinct participant instances**
  - Plan ref: `G14#message-coordination`
  - Acción propuesta: Refinamiento: identidad de participantes, no tipos.
  - Node IDs (3):
    - `test_two_instances_of_one_colleague_type_can_be_mediated[java]`
    - `test_two_instances_of_one_colleague_type_can_be_mediated[python]`
    - `test_two_instances_of_one_colleague_type_can_be_mediated[typescript]`
  - Parametrizaciones (3): java, python, typescript

- **Payload preservation is an optional stronger coordination contract absent from broad Mediator**
  - Plan ref: `G14#message-coordination`
  - Acción propuesta: Refinamiento opcional con preservación exacta de payload.
  - Node IDs (3):
    - `test_payload_contract_rejects_discarded_event_data[java]`
    - `test_payload_contract_rejects_discarded_event_data[python]`
    - `test_payload_contract_rejects_discarded_event_data[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### memento (3 casos)

- **Stronger historical-snapshot contract: explicit shared array mutation invalidates saved history; not proved by structural Memento query**
  - Plan ref: `G15#serialized-snapshot`
  - Acción propuesta: Refinamiento opcional con serialización completa.
  - Node IDs (3):
    - `test_desired_historical_snapshot_rejects_shared_mutable_array[java]`
    - `test_desired_historical_snapshot_rejects_shared_mutable_array[python]`
    - `test_desired_historical_snapshot_rejects_shared_mutable_array[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### prototype (6 casos)

- **explicit-copy correlates constructor argument but not retained constructor state; algorithms/prototype.md**
  - Plan ref: `G17#language-copy`
  - Acción propuesta: Refinamiento opcional con estado retenido del constructor.
  - Node IDs (3):
    - `test_prototype_requires_constructor_to_retain_captured_state[java]`
    - `test_prototype_requires_constructor_to_retain_captured_state[python]`
    - `test_prototype_requires_constructor_to_retain_captured_state[typescript]`
  - Parametrizaciones (3): java, python, typescript

- **Stronger independent-state contract: shallow array reference copy shares later writes; generic Prototype permits sharing**
  - Plan ref: `G17#language-copy`
  - Acción propuesta: Independencia del estado requiere contrato explícito de copia profunda.
  - Node IDs (3):
    - `test_desired_independent_state_contract_rejects_shared_array[java]`
    - `test_desired_independent_state_contract_rejects_shared_array[python]`
    - `test_desired_independent_state_contract_rejects_shared_array[typescript]`
  - Parametrizaciones (3): java, python, typescript

#### state (9 casos)

- **Stronger event/current-owner/current-dispatch contract needs temporal data flow, not historical constructor/slot associations; algorithms/state.md**
  - Plan ref: `G20#state-enum`
  - Acción propuesta: Refinamiento con flujo temporal entre evento y dispatch.
  - Node IDs (9):
    - `test_desired_event_transition_preserves_event_owner_and_active_state[current-state-replaced-java]`
    - `test_desired_event_transition_preserves_event_owner_and_active_state[current-state-replaced-python]`
    - `test_desired_event_transition_preserves_event_owner_and_active_state[current-state-replaced-typescript]`
    - `test_desired_event_transition_preserves_event_owner_and_active_state[different-current-context-java]`
    - `test_desired_event_transition_preserves_event_owner_and_active_state[different-current-context-python]`
    - … y 4 más
  - Parametrizaciones (9): current-state-replaced-java, current-state-replaced-python, current-state-replaced-typescript, different-current-context-java, different-current-context-python, different-current-context-typescript
    - …

#### visitor (3 casos)

- **Broad Visitor signature does not implement the result-forwarding variant contract**
  - Plan ref: `G23#overloaded-dispatch`
  - Acción propuesta: Variante overloaded-dispatch con forwarding de resultado.
  - Node IDs (3):
    - `test_result_forwarding_variant_rejects_replaced_result[java]`
    - `test_result_forwarding_variant_rejects_replaced_result[python]`
    - `test_result_forwarding_variant_rejects_replaced_result[typescript]`
  - Parametrizaciones (3): java, python, typescript

## Reproducción

```sh
.venv/bin/python -m pytest -o addopts='' -q --junitxml=/tmp/ken-xfail-junit.xml tests/structural/
.venv/bin/python /tmp/build_manifest.py   # regenera este manifiesto
```

Datos extraídos en [xfail-classified.json](xfail-classified.json) (146 registros).

## Próximos pasos concretos

## Variantes design sin tests

Ocho de las 33 variantes con `status='design'` en el catálogo GoF todavía no
tienen tests xfail escritos (sus tests se materializan cuando se entrega P7).
Esto significa que la categoría **FR — Falta de resolución** del manifiesto
está **vacía por construcción**, no porque esas capacidades existan: cuando
se escriban los tests, la mayoría serán IR o CO. Las variantes pendientes de
pruebas son:

| Variante | Patrón | Lenguajes pendientes (de la ficha G##) |
|---|---|---|
| `abstract-factory#structural-families` | G01 | javascript, typescript, go |
| `abstract-factory#associated-products` | G01 | rust |
| `chain-of-responsibility#middleware-closures` | G05 | 8 lenguajes |
| `facade#module-surface` | G09 | python, javascript, typescript, go, rust |
| `factory-method#contract-slot` | G10 | go, rust |
| `strategy#static-policy` | G21 | cpp, rust |
| `template-method#trait-default` | G22 | rust |
| `template-method#composed-skeleton` | G22 | 8 lenguajes |

Cuando los tests de cada variante se escriban (P7), deben agregarse a este
manifiesto con la categoría correspondiente.

## Próximos pasos concretos

Orden sugerido por dependencias (no por cantidad de xfail):

1. **P1.1 shadowing** (necesario para xfail IR en flyweight#indexed-key y visitor#reassignment).
2. **P1.5 regiones expresivas** (necesario para xfail IR en composite#iterated-call).
3. **P2.1 alcanzabilidad** (necesario para 18 xfail IR en chain/decorator/mediator/observer/proxy).
4. **P4 classmethod resolution** (necesario para singleton#python-classmethod).
5. **Variantes pendientes**: 18 entradas CO corresponden a las 11 variantes con `status=design` más afinadas. Cada una requiere implementar su query y registrar operación pública adicional.

## Estado del worktree

Limpio. Sin cambios en código. `git status --short` vacío tras este commit.
La matriz de regresiones de IR 1.48 sigue verde (6.586 passed / 146 xfailed).
Inventario GoF sin cambios: 44 ready / 33 design.