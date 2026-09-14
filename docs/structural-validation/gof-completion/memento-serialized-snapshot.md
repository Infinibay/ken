# `memento#serialized-snapshot` (8 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **ocho** lenguajes declarados.
Fecha: 2026-09-14. Base: `fc0f1cf` (IR 1.65.0), IR 1.66.0.

## Qué la separa de sus vecinas

`snapshot-object` y `accessor-snapshot` guardan el estado en un **tipo snapshot**. Ésta
es la otra mitad de la ficha —*una cadena opaca sin modelo queda parcial*— donde el
estado se codifica y se decodifica con el códec propio del lenguaje. La correspondencia
se prueba sobre el **flujo**: el codificador recibe el estado y el decodificador lo
devuelve.

## El códec se identifica por nombre, y los dos lados se anclan distinto

Eso no fue una decisión de estilo: lo midió la implementación.

- El **codificador** se ancla al final del nombre porque en Rust el nombre del callee es
  `serde_json::to_string`, no `to_string`. Un ancla al principio o un literal exacto
  fallan —probé ambos y dieron cero—.
- El **decodificador** se busca **sin anclar** porque en C# es `Deserialize<string>`: un
  ancla final falla, y además `Serialize` como búsqueda suelta matchearía *Deserialize*,
  así que el ancla final del codificador es lo que mantiene los dos lados separados.

Es identificación de protocolo por nombre, la misma concesión que el resto del catálogo
hace con `__iter__`, `next` o `computeIfAbsent`, y `query_claim` lo dice.

## Tres formas de decodificar, una por lenguaje

La primera versión asumía una sola —el valor del decodificador fluye al estado— y daba
**6 de 8**. Las otras dos son grafías reales, no variantes cosméticas:

| Lenguaje | Cómo llega el valor decodificado al slot |
|---|---|
| Python, JS, TS, Java, C++, C# | el valor del decodificador fluye al slot |
| Rust | el decodificador es el **receptor** de `unwrap()`, y es `unwrap` quien fluye |
| Go | el estado se pasa como **argumento destino** (`&e.state`) |

En Rust la cadena exacta es `unwrap --RECEIVER--> from_str` y `unwrap --FLOWS_TO--> state`,
así que `path $decode FLOWS_TO{1,3} $state` no alcanza y hubo que añadir la rama del
envoltorio. En Go no hay asignación ninguna: el destino viaja como argumento.

## La capacidad: `&slot` denotaba nada

Go necesitó IR 1.66. `&e.state` es un `unary_expression` que no estaba entre los
envoltorios, así que caía al camino genérico y producía un `VALUE` anónimo con
`native_kind: unary_expression`; el slot destino era irrecuperable. Ahora `&slot` y
`*puntero` resuelven al almacenamiento que nombran. `pointer_expression` y
`reference_expression` ya se desenvolvían; lo que faltaba era **comprobar el operador**
en `unary_expression`, de modo que `-x` y `!x` conservan su propio valor.

## Negativos cubiertos

26 pruebas en `tests/structural/test_memento_serialized_snapshot.py`: 8 positivos, 8 de
renombrado, 7 negativos, 2 del contrato publicado y 1 de la capacidad.

| Negativo | Por qué se rechaza |
|---|---|
| el estado se devuelve tal cual, sin códec (Python, JS, Go, Rust) | no hay llamada de codificación ni de decodificación |
| el codificador recibe una constante (Python, Go) | el argumento no proviene del estado |
| el decodificador escribe **otro** campo (Go) | el destino no es el estado |

Dos de estos negativos los escribí mal y los corrigió su propio fallo: el de C++
renombraba **el códec** (`pack`/`unpack`), que es el protocolo y no un identificador del
usuario; y el de Go llamaba a `json.Unmarshal(payload, &e.state)` —que **sí** escribe el
estado— y por eso matcheaba con razón. El fixture correcto decodifica en un campo
distinto.

## Límites declarados

`query_claim` **no** prueba que la decodificación reconstruya el estado de forma fiel ni
completa: la correspondencia se prueba sobre el flujo, no sobre el contenido. El schema y
las pérdidas de información siguen fuera, tal como la tabla del documento de diseño
anticipaba. Los nombres de API son evidencia de forma, no resolución de biblioteca.

## Validación

`tests/structural/` completo, sin regresiones, más las 26 pruebas nuevas.
`mypy src/ken` limpio.
