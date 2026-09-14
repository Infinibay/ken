# `iterator#async-iterator` (4 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **cuatro** lenguajes declarados.
Fecha: 2026-09-14. Base: `32551bc` (IR 1.58.0), IR 1.59.0.

## Qué la separa de `iterator#generator`

`generator` ya cubría «hay una forma generadora»: `callable(generator: true)` con una
operación `yield`. Un async generator de JavaScript (`async function*`) satisface esa
forma **también**, y la ficha lo advertía: *un async generator puede coincidir con la
forma genérica de generador; ese match no certifica el protocolo asíncrono completo*.

`async-iterator` es esa certificación, y son dos hechos, no uno:

| Necesidad | Hecho |
|---|---|
| El consumo suspende | el **bucle** lleva `async` |
| El productor suspende al avanzar | callable async con `yield` **y** `await` |

## La capacidad que faltaba: el bucle que suspende

`async for` de Python, `for await` de JS/TS y `await foreach` de C# ya producían
`LOOP`, `ITERATION_SOURCE` y `ITERATION_BODY`. El problema es que producían
**exactamente los mismos hechos que un bucle sincrónico sobre la misma fuente**:

| Hecho | `for (const item of produce())` | `for await (const item of produce())` |
|---|---|---|
| operación `LOOP` | sí | sí |
| `ITERATION_SOURCE` | la llamada | la llamada |
| `ITERATION_BODY` | el bloque | el bloque |
| `TARGET` sobre la fuente | a `produce` | a `produce` |
| `async` del bucle | ausente | `True` |

La única traza de asincronía era la lista de tokens sin nombre de la operación, que
ninguna query puede alcanzar. Es decir: «este bucle suspende para avanzar» no era
expresable en absoluto.

La marca se pone desde los tokens **del propio bucle**, así que es una propiedad del
bucle y no del callable que lo contiene: el `for` de conteo dentro del `async def`
sigue sin marca. Eso se verifica en
`test_the_loop_itself_records_the_suspension`, que exige exactamente un bucle marcado
de los dos presentes en cada fixture.

## Una trampa de KenQL que costó una iteración

La primera versión usaba `require $producer HAS_YIELD $suspend`. KenQL valida cada
relación contra `RELATIONS | lo que el grafo realmente emite`, y `HAS_YIELD` /
`HAS_AWAIT` **no** están en el conjunto estático: se emiten dinámicamente como
`HAS_<kind>`. En un grafo sin ningún `yield` —el negativo «no es generador»— la query
fallaba con `unknown graph relation HAS_YIELD` en vez de simplemente no matchear.

La forma correcta es la que ya usaba `iterator#generator`:
`operation(kind: yield) as $suspend; require $producer HAS_OPERATION $suspend;`, que
solo nombra relaciones del conjunto estático. Vale la pena recordarlo: **una relación
por la que se pregunta tiene que existir en el grafo, o la query es un error, no un
no-match.**

## La obligación de `await`, y su exclusión

El contrato exige que el productor tenga un `await` además del `yield`. Es la lectura
concreta de *«producción/avance ... se rigen por protocolo async»* y es lo que
convierte «await no se transforma en thread» en algo verificable: un generador async
que nunca suspende declara el protocolo sin usarlo.

La exclusión es deliberada y está declarada en `query_claim`: un generador async que
nunca hace `await` **no** matchea. Es un falso negativo posible sobre código real, y
se documenta en vez de esconderse.

## Negativos cubiertos

20 pruebas en `tests/structural/test_iterator_async_iterator.py`:

| Negativo | Por qué se rechaza |
|---|---|
| bucle sincrónico sobre la misma fuente (4 lenguajes) | el bucle no lleva `async` |
| productor sincrónico (4 lenguajes) | `callable(async: true)` no se satisface |
| callable async que nunca hace `yield` | falta la operación `yield` |
| declarado async pero nada hace `await` | falta el `await` del productor |
| bucle async sobre una fuente sincrónica | el productor no es async |

## Límites declarados

`query_claim` no prueba agotamiento, tipos de elemento, ni que lo awaitado termine.
El modo `possible` no se usa: la evidencia es estructural y estricta.

## Validación

`tests/structural/` completo, sin regresiones, más las 20 pruebas nuevas.
`mypy src/ken` limpio.
