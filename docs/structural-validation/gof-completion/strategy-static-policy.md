# `strategy#static-policy` (2 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **dos** lenguajes declarados.
Fecha: 2026-09-14. Base: `5c96b1e` (IR 1.61.0), IR 1.62.0.

## Qué la separa de `strategy-object`

`strategy-object` cubre un contexto con un campo tipado por un contrato y dos
implementaciones entre las que elegir **en ejecución**. Ésta es la *política por tipo*
de la ficha, y la diferencia está en lo que **no** exige:

| | `strategy-object` | `static-policy` |
|---|---|---|
| Contrato | `$strategy TYPE $contract` | — |
| Implementaciones | dos subtipos distintos | — |
| Elección | en ejecución | en la declaración |
| Evidencia | `DECLARED_TARGET`/`TARGET` | el campo está tipado por un parámetro de tipo |

`query_claim` lo dice explícitamente: no se pide contrato, ni subtipo, ni conteo de
implementaciones, porque pedir cualquiera de esas cosas sería pedir un objeto runtime.
La separación se verifica en `test_no_runtime_object_is_required`, que comprueba que el
fixture de esta variante **no** matchea `strategy-object`.

## La capacidad que faltaba: C++ no ligaba sus parámetros de tipo

Rust ya lo hacía —`Context` publicaba `type_parameters: ['P']` y el campo `policy`
tenía `TYPE_NAME → P`—, pero C++ daba `tp=None`. La causa es de gramática:
`bound_type_parameters` caminaba hacia arriba buscando un campo `type_parameters`, y
C++ no lo tiene: su `template_declaration` pone el grupo en el campo **`parameters`**,
con miembros `type_parameter_declaration`. Ese nombre de campo es el mismo que una
función usa para su lista de argumentos, así que la lectura se acota a dos condiciones
a la vez —el ancestro es un `template_declaration` **y** el miembro es un
`type_parameter_declaration`— para que los argumentos de una función no se confundan
con parámetros de tipo.

Además, el enlace se publica como **hecho**, no solo como atributo:

```
<declaración> --BINDS_TYPE_PARAMETER--> <nombre del parámetro>
```

Una lista en un atributo no es alcanzable desde KenQL, y la pregunta que hace la query
es por qué parámetro *se tiene* el `TYPE_NAME` de un campo. Con el hecho, los dos se
unen directamente. Es una capacidad que sirve a las cuatro variantes de la familia de
genéricos (`strategy#static-policy`, `visitor#generic-visitor`,
`bridge#generic-composition`, `builder#consuming-typestate`), no solo a ésta.

## Negativos cubiertos

18 pruebas en `tests/structural/test_strategy_static_policy.py`: 2 positivos, 2 de
renombrado, 8 negativos, 2 de separación con `strategy-object`, 2 de la capacidad y 2
del contrato publicado.

| Negativo | Por qué se rechaza |
|---|---|
| el campo tiene un tipo concreto, no un parámetro | no hay `BINDS_TYPE_PARAMETER` |
| el parámetro de tipo no tipa el campo | el `TYPE_NAME` del campo no es el parámetro |
| el campo es del parámetro pero el método no delega | falta la llamada con ese receptor |
| el parámetro aparece **solo en la firma** | no hay campo |
| el parámetro pertenece a **otro** tipo | el enlace se exige sobre la unidad que tiene el campo |

## Límites declarados

`query_claim` no prueba **resolución de instanciación**: que el sitio de uso
(`Context<FastPolicy>`) corresponda al parámetro, ni sustitución de tipos, ni
especialización parcial, ni que el campo llegue a asignarse. Prueba que la política
está fijada por tipo **en la declaración**, que es la lectura estructural de
«política por tipo determina algoritmo».

## Validación

`tests/structural/` completo, sin regresiones, más las 18 pruebas nuevas.
`mypy src/ken` limpio.
