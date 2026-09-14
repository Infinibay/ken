# `composite#higher-order-traversal` (8 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados
(`python`, `javascript`, `typescript`, `java`, `csharp`, `cpp`, `go`, `rust`).
Fecha: 2026-09-14. Base: IR 1.67.0 (`singleton#once-primitive`), IR 1.68.0.

## Qué se publica

La operación del componente recorre su propia colección de hijos, invoca la operación
**del mismo nombre** sobre el elemento iterado, y el resultado de esa llamada se acumula
en el local que la operación devuelve:

```
%operation --ITERATES_CALLS--> %iterable        (name = el nombre invocado)
%child_call --ITERATED_CALL--> %iterable
%child_call --RECEIVER--> %element              (la variable del bucle)
%write --ASSIGNMENT_TARGET--> %accumulator
%write --ASSIGNMENT_VALUE--> %child_call
%operation --RETURNS_STORAGE--> %accumulator
```

Eso es lo que separa la variante de **`recursive-nominal`**, ya `ready` en cinco
lenguajes: aquélla prueba la llamada recursiva uniforme, y ésta prueba **qué pasa con el
resultado del hijo**. La recursión la da el nombre uniforme sobre el elemento
(`where $operation.name == $child_call.name`), no el tipo declarado de la colección: en
Python y JavaScript no hay anotación, y en Rust el iterable es la *llamada*
`self.children.iter()`, no un campo. Por eso el anclaje a la unidad es una disyunción:

* `$unit HAS_FIELD $iterable` — el iterable es el campo (siete lenguajes), o
* `$iterable RECEIVER $field` + `$unit HAS_FIELD $field` — el iterable es una llamada
  sobre el campo (Rust).

El `or` no es cosmético: sin él Rust no tiene por dónde unir el iterable con el
componente, y sin esa unión la variante matchearía cualquier agregación sobre una
colección ajena.

## El defecto real que había debajo (Rust)

`total += child.count(ctx)` de Rust se escribe `compound_assignment_expr`, y la rama de
asignación aumentada que ya usaban Python (`augmented_assignment`) y JS/TS
(`augmented_assignment_expression`) **no lo incluía**. La operación quedaba en el grafo
sin `ASSIGNMENT_TARGET` ni `ASSIGNMENT_VALUE`:

```
# antes de IR 1.68
compound_assignment_expr a.rs::op:272:297  tokens=['+=']     ← sin destino ni valor
# después
ASSIGNMENT_TARGET a.rs::op:272:297 -> total
ASSIGNMENT_VALUE  a.rs::op:272:297 -> <la llamada del hijo>
```

Java, C# y C++ llegan a la misma rama por `assignment_expression`, así que sólo Rust
estaba afectado. El modo de fallo es el peor: la query devolvía **cero matches sin
fallar**, no un error.

Medición: con el catálogo nuevo y el frontend anterior, **4 de los 76** tests fallan —
`test_aggregated_traversal_is_detected[rust]`,
`test_renamed_identifiers_preserve_detection[rust]`,
`test_a_reassigned_element_is_not_yet_rejected[rust-reassigned-element]` y
`test_root_rule_reports_the_aggregated_traversal[rust]`.

## La forma de callback queda declarada como no resuelta

`children.reduce((acc, child) => acc + child.count(ctx), 0)` expresa la misma travesía,
y la tabla de diseño la lista como alternativa para JS/TS y Rust
(`children.iter().map(|c| c.count(ctx)).sum()`). **No se resuelve**: el IR no emite
`ITERATED_CALL` para un callback, porque el parámetro de elemento del callback no se liga
a la colección que itera. Es la mitad `closure_capture` que la fila de la variante
declaraba, y está dicha en el `query_claim`. `test_the_callback_fold_shape_is_not_yet_detected`
la fija en Python, JavaScript y TypeScript.

## Lo que se dejó sin resolver a propósito

* **Elemento reasignado.** `child = self.children[0]; total += child.count(ctx)` dentro
  del bucle **matchea**: la reasignación no se modela como invalidación del valor iterado.
  No hay recuento disponible para exigir "el elemento no se reasignó": Go, C++ y Rust no
  tienen inventario de escrituras por callable, y en los ocho lenguajes el propio `+=` que
  publica el total marca el callable `binding-writes/1` **`unsupported`** con razón
  `indirect-write`. `test_a_reassigned_element_is_not_yet_rejected` fija el match.
* **Visita completa.** El contrato es existencial: no prueba que todos los hijos se
  visiten ni que el bucle termine, ni pureza de la operación, ni que el acumulador no se
  escriba fuera del bucle.
* **Contexto.** La firma no exige que la operación reciba contexto; `expression-objects`
  (la otra variante de composite) tampoco, y el `graph_requirements` de esta fila habla
  sólo del flujo del resultado.

## Validación

* `tests/structural/test_composite_higher_order_traversal.py`: 76 tests. Positivo y
  renombrado en los ocho lenguajes, cinco negativos por lenguaje
  (`discarded`, `other-accumulator`, `foreign-operation`, `no-iteration`,
  `local-collection`), dos fronteras por lenguaje (elemento reasignado; callback en tres
  lenguajes), la consulta raíz `composite` en los ocho y la comprobación de metadatos.
* Suite estructural completa: **7271 passed / 140 xfailed** (antes: 7194 / 140; los 77
  nuevos son los 76 del fichero más la entrada que el contrato del catálogo añade por
  variante `ready`).
* `mypy src/ken`: limpio (109 ficheros).
* El fichero completo **no corre** contra el catálogo anterior: la variante era `design`
  y `named_rule` no la registra.
