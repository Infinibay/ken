# `visitor#generic-visitor` (2 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **dos** lenguajes declarados.
Fecha: 2026-09-14. Base: `00f4196` (IR 1.62.0), IR 1.63.0.

## La tercera forma de despacho

`named-dispatch` exige un tipo de visitante **resoluble** (`$visitor TYPE $visitor_type`);
`overloaded-dispatch` exige un conjunto de sobrecargas sobre uno. Ésta es la forma de
tiempo de compilación: el método del elemento liga un parámetro de tipo propio, el
parámetro visitante está tipado por **ese** parámetro, y el elemento se pasa a sí mismo.
No hay tipo de visitante que resolver en la llamada porque la selección es por tipo.

La separación con `named-dispatch` es complementaria y se comprueba en las dos
direcciones y en los dos lenguajes:

| Fixture | `generic-visitor` | `named-dispatch` |
|---|---|---|
| `void accept(ShapeVisitor& visitor)` | no | sí |
| `template <typename V> void accept(V& visitor)` | sí | no |

## El negativo que la ficha nombra

La ficha es explícita: *match sin visitor separado no satisface esta variante*. Se
cubre en las dos grafías —un `switch` de C++ sobre un `enum class` y un `match` de Rust
sobre un `enum`— y ambos se rechazan. Contar casos no es un visitante, y la variante no
debe confundir un tipo suma recorrido con un despacho a un visitante.

## La capacidad que faltaba: la decoración escondía el nombre

El parámetro visitante está tipado por el parámetro de tipo, pero su tipo declarado
lleva la decoración: `Visitor &` en C++, `&V` en Rust. El método publica que liga
`Visitor` (o `V`) y el parámetro publica que su tipo es `Visitor &` (o `&V`), así que
**no hay nada que unir** y una query que pregunte por ello devuelve cero matches sin
fallar.

El hecho nuevo quita la decoración **solo para la comparación**:

```
<parámetro> --TYPE_PARAMETER--> <nombre del parámetro de tipo>
```

Se despojan `&`, `&&`, `*`, `const` y `mut`. Un parámetro cuyo tipo sea cualquier otra
cosa conserva su nombre y no publica este hecho. La decoración original sigue en
`TYPE_NAME`, que no se toca: el cambio es aditivo y no reinterpreta un hecho existente.

Es la misma familia de problema que el `TYPE_NAME` de un campo en
`strategy#static-policy`, y la misma solución —un hecho que normaliza lo que la
decoración esconde—, que era previsible: la ligadura de parámetros de tipo de IR 1.62
resolvía el lado de la declaración, y ésta resuelve el lado del uso.

## Negativos cubiertos

12 pruebas en `tests/structural/test_visitor_generic_visitor.py`: 2 positivos, 2 de
renombrado, 4 de complementariedad con `named-dispatch`, 3 negativos, 1 comprobación
del contrato publicado y 1 de la capacidad.

| Negativo | Por qué se rechaza |
|---|---|
| el método es genérico pero el parámetro de tipo **no** tipa al visitante | el visitante no está ligado al parámetro |
| el elemento no se pasa a sí mismo | el argumento no es el receptor |
| `switch`/`match` sobre un tipo suma, sin visitante separado | no hay parámetro visitante |
| visitante con un tipo concreto (no genérico) | no hay `BINDS_TYPE_PARAMETER`: es `named-dispatch` |

## Límites declarados

`query_claim` no prueba sustitución de tipos, ni que la instanciación del sitio de uso
sea la elegida, ni exhaustividad del visitante. Prueba que la selección del visitante es
**de compilación** y que el elemento se despacha a él pasándose a sí mismo.

## Validación

`tests/structural/` completo, sin regresiones, más las 12 pruebas nuevas.
`mypy src/ken` limpio.
