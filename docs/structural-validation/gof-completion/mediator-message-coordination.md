# `mediator#message-coordination` (8 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados
(`python`, `javascript`, `typescript`, `java`, `csharp`, `cpp`, `go`, `rust`).
Fecha: 2026-09-14. Base: IR 1.69.0. **Sin cambio de IR**: la query se escribe con hechos
que ya existían.

## Qué se publica

Un centro con un método que **despacha por tag**, y colegas que se anuncian a sí mismos:

```
colleague.notify(tag)  ->  centre.coordinate(self, tag)          PASSES_SELF_TO
centre.coordinate(origin, tag):
    if tag == N: first.apply(tag) else: second.apply(tag)
    ^ CONDITIONAL_DELEGATION a dos campos del propio centro, con el tag como argumento
```

La evidencia completa, toda ella por identidad salvo la comparación de nombre de
llamada:

| Rol | Hecho |
|---|---|
| El centro | `$coordinator IS CLASS` + `HAS_METHOD $operation` |
| Los dos destinos | `$operation CONDITIONAL_DELEGATION $first_target/$second_target` + `$coordinator HAS_FIELD` cada uno, distintos |
| El tag | `$operation HAS_PARAMETER $tag` y las **dos** llamadas llevan un argumento `--VALUE--> <loaded-value> --LOADED_FROM--> $tag` |
| Los colegas | `$notifier_a/$notifier_b PASSES_SELF_TO` en **dos tipos distintos**, y el `CALLEE_NAME` de su llamada igual al nombre del despachador |

## Por qué el enlace es por nombre de llamada, y por qué eso es correcto aquí

El diseño avisa de que "el receptor y el payload deben correlacionarse", y la variante
`direct-colleagues` (ya `ready`) exigía referencias nominales en las dos direcciones:
`$coordinate DELEGATES_TYPE $colleague` y `$caller CALLS $coordinate`. Eso no existe en
JavaScript sin tipos: allí el centro inyectado (`this.coordinator`) **no tiene tipo
registrado**, así que no hay arista del colega al tipo del centro.

Lo que sí existe es la llamada: `CALLEE_NAME` del anuncio (`coordinate`) y el nombre del
método despachador (`Coordinate`). La comparación es la misma que usa
`composite#recursive-nominal` desde que se cerró (`where $operation.name ==
$child_call.name`), y une las dos mitades sin exigir tipado. `PASSES_SELF_TO` es lo que
aporta la mitad "el colega se entrega a sí mismo" y está en los ocho lenguajes: se midió
que en C++ sólo aparece con la definición **inline** del método del colega (con
`inline void Colleague::notify(...)` fuera de la clase no hay `THIS`), así que el fixture
de C++ declara el centro primero y define todo dentro de las clases.

## Lo que se dejó sin resolver a propósito

* **`then`/`else` de un mismo test.** El contrato exige delegación **condicional** a dos
  campos distintos, no que las dos ramas sean las dos ramas del mismo `if`. Dos `if`
  separados satisfacen la firma.
* **Valores del tag distintos.** No se comprueba que las ramas se alcancen con tags
  diferentes, ni que la decisión dependa de comparar el tag con algo.
* **Identidad runtime de los destinos.** Los destinos son campos del centro; que apunten a
  objetos distintos, y que el campo no se reasigne entre ramas, no se prueba.
* **Retorno y efectos.** La notificación puede no retornar, y la llamada al destino puede
  no ser alcanzable en ejecución.
* **Alcance por lenguaje.** Los ocho lenguajes son los validados; la query no filtra por
  lenguaje, así que un proyecto de otro lenguaje con la misma forma también matchea.

## Simetría del match

Los dos destinos y los dos colegas son simétricos, así que la evidencia vuelve en las
**cuatro** permutaciones y el test afirma sobre el conjunto de unidades, no sobre el
número de filas. `direct-colleagues` tiene la misma propiedad. No se puede canonicalizar
con `where $a.name < $b.name`: `_compare` de `query.py` sólo compara **números** para
`<`/`>`/`<=`/`>=` y devuelve `False` para cadenas (medido: la variante con esas cláusulas
da cero matches).

## Validación

* `tests/structural/test_mediator_message_coordination.py`: 73 tests. Positivo y
  renombrado en los ocho lenguajes, cinco negativos por lenguaje (`no-branch`,
  `same-target`, `no-tag-argument`, `no-self`, `one-colleague`), la consulta raíz y la
  comprobación de que `PASSES_SELF_TO` está presente en el positivo y ausente en
  `no-self`.
* Suite estructural completa: **7371 passed / 140 xfailed** (antes: 7297 / 140; los 74
  nuevos son los 73 del fichero más la entrada que el contrato del catálogo añade por
  variante `ready`). Ningún test existente cambió de expectativa: la regla raíz
  `mediator` gana una rama y los fixtures de `direct-colleagues` no la satisfacen.
* `mypy src/ken`: limpio (109 ficheros).
* El fichero completo **no corre** contra el catálogo anterior: la variante era `design`
  y `named_rule` no la registra.
