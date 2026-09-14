# `proxy#lazy-subject` (8 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados.
Fecha: 2026-09-14. Base: `672799a`, IR 1.56.0.

## Qué la separa de `guarded-access`

`guarded-access` ya cubría delegación condicional sobre el mismo contrato.
`lazy-subject` es el caso en que la guarda **inicializa por primera vez** el
almacenamiento y el resto de la operación delega sobre ese mismo campo. El
contrato publicado exige las cuatro cosas a la vez:

| Necesidad | Hecho |
|---|---|
| El accessor guarda un campo | `GUARDS_WRITE` (la guarda referencia **ese** campo) |
| El campo se llena con una construcción | `HAS_CALL` + `ALLOCATES_TYPE` |
| La construcción es de **otro** tipo | `different $created $unit` |
| Se delega sobre el mismo campo | `DELEGATES_TO` |

## La única capacidad nueva: `condition_clause` de C++

Siete lenguajes ya satisfacían el contrato. C++ no, por una razón acotada: el
grammar envuelve la condición de un `if`/`while` en un nodo `condition_clause`, que
es un envoltorio puro. Sin desenvolverlo, `if (subject == nullptr)` no llegaba al
`NULL_TEST` sobre el miembro y la variante no podía ver la guarda.

`condition_clause` se agregó a `WRAPPERS` junto a `parenthesized_expression`. Es un
cambio de núcleo, y por eso la suite completa es la que lo valida: no hubo
regresiones.

El contrato **no** exige una grafía concreta del test de ausencia. Lo que exige es
que la guarda referencie el propio campo, así que una comparación nula, el
`Option` de Rust y un flag quedan separados por la misma obligación.

## Negativos cubiertos

Los seis se verifican en `tests/structural/test_proxy_lazy_subject.py`:

| Negativo | Por qué se rechaza |
|---|---|
| `EAGER` | el subject se crea al construir, sin guarda |
| `UNGUARDED` | la asignación no está bajo ninguna guarda |
| `NO_DELEGATION` | el accessor guarda pero no delega sobre el campo |
| `OTHER_FIELD_DELEGATED` | delega sobre un campo distinto del guardado |
| `CREATION_NOT_STORED` | construye pero no almacena el resultado |
| `GUARD_ON_ANOTHER_FLAG` | `GUARDS_WRITE` exige que la guarda referencie el campo guardado |

## Límites declarados

`query_claim` no afirma alcanzabilidad en ejecución ni identidad runtime del
receptor. Tampoco prueba que la construcción ocurra una sola vez bajo concurrencia:
`GUARDS_WRITE` es una relación estructural entre la guarda y el campo, no una
prueba de exclusión mutua.

## Validación

`tests/structural/` completo, sin regresiones, más 15 pruebas nuevas en
`tests/structural/test_proxy_lazy_subject.py`.
