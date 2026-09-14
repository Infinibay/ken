# `visitor#overloaded-dispatch` (3 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **tres** lenguajes declarados.
Fecha: 2026-09-14. Base: `18d1c7b` (IR 1.61.0), **sin cambio de IR**.

## La gemela de `named-dispatch`, y qué la separa exactamente

`named-dispatch` ya cubría «el elemento se pasa a sí mismo a una operación del
visitante», y exige `$dispatch TARGET $visit`: un objetivo **resuelto**. Ésta es su
gemela para el caso en que el objetivo no puede resolverse porque el visitante declara
**varias operaciones con ese nombre**.

La separación se midió en las dos direcciones y es exacta:

| Fixture | Hechos `TARGET` | `named-dispatch` | `overloaded-dispatch` |
|---|---|---|---|
| visitante con **una** operación | resuelve | sí | no |
| visitante con **sobrecargas** | ninguno | no | sí |

No es una coincidencia afortunada: es la misma razón vista desde los dos lados. Con una
sola operación la llamada tiene un destino único; con un conjunto de sobrecargas no hay
destino único que ofrecer, y por eso lo que se exige aquí es que el **conjunto exista**,
no cuál de sus miembros se elige.

Esa tabla está en
`test_the_two_visitor_variants_are_complementary`, que comprueba las cuatro celdas en
los tres lenguajes.

## El contrato

| Necesidad | Hecho |
|---|---|
| El elemento recibe un visitante | `HAS_PARAMETER` sobre un parámetro no receptor |
| El elemento tiene receptor propio | `INSTANCE_RECEIVER` |
| El visitante está tipado | `TYPE` |
| El elemento se pasa a sí mismo | `ARGUMENT` → `VALUE` → el receptor |
| La llamada va al visitante | `RECEIVER` |
| Hay un conjunto de sobrecargas | `count distinct $overload >= 2` sobre `HAS_METHOD` |

El conteo es una **cota inferior**, no una cardinalidad exacta: un conjunto de tres
sobrecargas sigue siendo un conjunto, y una cota inferior se establece con testigos, así
que no necesita la clausura de mundo cerrado de IR 1.61.

En C++ el elemento se pasa como `*this`, y el envoltorio `pointer_expression` ya estaba
entre los que el frontend desenvuelve, así que la evidencia del autorreceptor es la
misma que en Java y C#.

## Negativos cubiertos

15 pruebas en `tests/structural/test_visitor_overloaded_dispatch.py`: 3 positivos (uno
por lenguaje), 3 de complementariedad con `named-dispatch`, 3 de renombrado, 5
negativos y 1 comprobación del contrato publicado.

| Negativo | Por qué se rechaza |
|---|---|
| el elemento no se pasa a sí mismo (Java, C++) | el argumento no es el receptor |
| las sobrecargas están bajo **otro** nombre | el `where` liga el nombre de la llamada |
| el receptor de la llamada es un **campo**, no el parámetro | `RECEIVER` no es el visitante |
| el método nunca llama al visitante | no hay llamada |
| el conjunto de sobrecargas está en **otro** tipo | `HAS_METHOD` se exige sobre el tipo del visitante |
| visitante con una sola operación | el conjunto no existe: es el caso de `named-dispatch` |

## Límites declarados

`query_claim` **no** prueba resolución de sobrecarga: que el lenguaje elija la
sobrecarga que corresponde al tipo del elemento, ni exhaustividad del visitante, ni que
la sobrecarga elegida sea la del tipo declarado. El nombre del método receptor tampoco
se fija, igual que en `named-dispatch`: la evidencia es estructural, y renombrar
`accept` no cambia el contrato.

El campo que la ficha pedía —*overload corresponde a tipo de elemento*— queda por tanto
**parcialmente** cubierto: se prueba que existe un conjunto de sobrecargas y que el
elemento se despacha contra él, no que el miembro elegido sea el correcto para su tipo.
Es un límite de precisión, no de sonoridad.

## Validación

`tests/structural/` completo, sin regresiones, más las 15 pruebas nuevas.
`mypy src/ken` limpio. Sin bump de `IR_VERSION`: el grafo no cambia.
