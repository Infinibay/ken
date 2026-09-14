# Iterator: protocolo, elementos, progreso y suspensión

Estado: ejercicio algoritmo→IR y pruebas adicionales a las variantes existentes.
La [regla declarativa](../../../../src/ken/structural/patterns/iterator.toml)
reconoce formas de protocolo. Esa clasificación debe mantenerse separada de
demostrar un recorrido correcto de una colección finita.

## Algoritmos en palabras

**Cursor explícito sobre una secuencia finita.** Retener la secuencia y la
posición. Al pedir el siguiente elemento, comprobar si quedan elementos;
obtener el correspondiente a la posición actual, avanzar el estado y entregar
el elemento obtenido. Al agotar la secuencia, emitir la señal definida por el
protocolo, sin volver a entregar elementos ni leer fuera de rango.

**Generador.** Conservar una continuación que suspende su ejecución al producir
un elemento. Al reanudarse, continuar desde ese punto con su estado local.
`yield` demuestra suspensión/productividad sintáctica, no progreso suficiente
ni cobertura de todos los elementos de una fuente.

**Delegación.** Encargar la producción a otro iterable/generador, conservando
las reglas de su protocolo: valores, agotamiento, cierre y propagación de errores
o valores enviados cuando el lenguaje los admite. `yield from` y `yield*` no
deben reducirse a una llamada ordinaria que devuelve una colección completa.

**Iteración asíncrona.** El avance puede requerir espera antes de disponer del
elemento o del fin. Mantener separado `await` de `yield`: esperar no produce un
elemento, y producirlo no implica crear un thread.

Un iterator puede ser infinito, filtrar elementos o producir valores calculados.
Exigir terminación o identidad con cada elemento de una colección sólo es
correcto para una variante que prometa esas propiedades.

## Traducción conceptual al IR

El núcleo actual tiene memoria, operaciones aritméticas, regiones y suspensión.
El texto siguiente expresa el algoritmo objetivo; sus nombres de protocolo y
anotaciones no son una gramática nueva ejecutable.

```text
function Cursor.next(%self) {
  %position_addr = field.addr %self, "index"
  %position = memory.load %position_addr
  %values_addr = field.addr %self, "values"
  %values = memory.load %values_addr
  %length = call @length, argument[0]: %values
  %exhausted = compare.ge %position, %length
  if %exhausted {
    throw @StopIteration
  }
  %element_addr = index.addr %values, %position
  %element = memory.load %element_addr
  %next_position = binary.add %position, 1
  memory.store %position_addr, %next_position
  return %element
}
```

La escritura debe cambiar el estado relevante. `index = index + 0` lee y escribe
el campo pero no avanza. Del mismo modo, retornar `0` tras leer el elemento no
demuestra que se devuelve ese elemento. Son obligaciones de valor y transición,
no sólo `READS`/`WRITES`.

Una posible normalización de generadores mantiene su suspensión:

```text
function entries(%values) generator {
  iterate %element in %values {
    yield %element
    // La continuación se reanuda aquí.
  }
  return exhausted
}

function delegated_entries(%values) generator {
  yield.delegate %values
}
```

`iterate` y las reglas completas de continuación/protocolo son objetivos de
normalización, no promesas de soporte íntegro del exportador actual. Un bucle
async necesita además suspensiones al avanzar y una transición explícita al fin.

## Obligaciones independientes

| Contrato | Evidencia requerida | Ejemplo que lo rompe |
|---|---|---|
| Forma del protocolo | Métodos y retornos nativos, o generador | Nombres parecidos sin comportamiento |
| Estado del cursor | Campo/estado que persiste entre avances | Variable local de logging tomada por posición |
| Progreso finito | Transición que acerca al agotamiento | `index = index + 0` |
| Procedencia del elemento | Fuente, posición y valor retornado | Leer un elemento y retornar una constante |
| Fin correcto | Comparador y señal del protocolo | Comparador desfasado que permite leer fuera de rango |
| Delegación | Iterable delegado y suspensión relacionada | Retornar el iterable sin delegar sus elementos |
| Consumo correcto | Continuación/cierre/cancelación según protocolo | Ignorar fin o seguir usando recurso cerrado |

La operación pública `iterator.iterate_over` expone fuente, binding de valor,
cuerpo y ocurrencia de un foreach. Sirve para componer búsquedas de uso; no
demuestra que el binding siga representando el mismo elemento después de una
reasignación, ni prueba todos los contratos de la tabla.

## Corrección concreta de la query Python

El ejercicio encontró que quitar el avance del cursor pero conservar:

```python
metric = 1 + 2
print(metric)
```

seguía haciendo match en `explicit-cursor`: el local `metric` satisfacía
`__next__ WRITES/READS $state`. Se agregó:

```kenql
require $iterator HAS_FIELD $state;
```

Ahora la variante exige un campo del iterator como estado compartido. El
negativo que conserva logging y quita el avance ya se rechaza. Esta corrección
no convierte escritura en prueba de progreso ni verifica el agotamiento;
`index+0` sigue siendo un gap explícito del refinamiento de secuencia finita.

Otros mecanismos de estado, como un cursor delegado, cuentan con variantes
propias. Si el estado persistente no puede resolverse como campo en esta
variante, el análisis no debe inventarlo a partir de variables locales.

## Variantes por lenguaje

| Lenguaje | Formas | Distinciones necesarias |
|---|---|---|
| Python | `__iter__/__next__`, `yield`, `yield from`, `async for` | `StopIteration` frente a fin async, self-iterator frente a nuevo cursor, `send/throw/close` |
| Java | `Iterator<T>.hasNext/next`, streams | Elemento y fin; callback de stream no es automáticamente un cursor explícito |
| TypeScript / JavaScript | `{value,done}`, `function*`, `yield*`, async generators | `return` termina, `yield` produce; protocolos Symbol.iterator/asyncIterator |
| C# | `MoveNext/Current`, `yield return`, `IAsyncEnumerable` | Avance booleano separado de elemento, dispose/cancelación |
| C++ | Iterador/sentinel, incremento y desreferencia | Operadores sobrecargados, categorías de iterador e invalidación |
| Go | Range de colección o función iteradora | Binding índice frente a elemento; callback booleano controla continuación |
| Rust | `Iterator::next -> Option<Item>` y adaptadores | `Some/None`, consumo/borrow, transformaciones lazily y contratos de adaptadores |

`iterator#callback-iterator` (Go) pasó a `ready` sin capacidad nueva: el parametro
callback ya era callee (`CALLEE_VALUE`), la rama ya registraba que prueba
(`TRUTH_TEST`) y el bucle ya ligaba su elemento (`ITERATION_BINDING`). Lo que hubo que
resolver fue el **join**: `ARGUMENT` liga una ocurrencia de callsite, no el
almacenamiento. `async-iterator` pasó a `ready` en IR 1.59: el bucle que suspende
(`async for`, `for await`, `await foreach`) se registra en el propio bucle, porque
`ITERATION_SOURCE`, `ITERATION_BODY` y el tipo de bucle son idénticos a los de un bucle
sincrónico sobre la misma fuente. Un async
generator sigue coincidiendo con la forma genérica de generador —son dos hechos
distintos— pero el match genérico ya no es lo único que hay: la variante asíncrona
exige además que el productor suspenda al avanzar.

## Ruido y pruebas

La [matriz nueva](../../../../tests/structural/test_algorithm_iterator.py)
inserta cálculo local/logging entre lectura del elemento y avance del cursor,
y antes de una delegación. También incluye consumo `async for`/`for await` con
producción de elementos. Los fixtures se parsean; no se ejecutan ni se compilan.
No se afirma pureza de cualquier logger ni estabilidad de una colección mutable
modificada externamente durante la iteración.

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_iterator.py
```

Resultado nuevo: **21 passed, 6 xfailed estrictos**.

- Seis positivos de cursor explícito en Python/Java/TypeScript con y sin ruido.
- Tres negativos de cursor sin avance observable, conservando ruido local.
- Seis xfail: avance `+0` y retorno de constante, para el contrato más fuerte de
  recorrido de una secuencia finita. No invalidan cualquier iterator imaginable.
- Tres positivos de delegación con ruido y tres negativos que retornan el
  iterable sin producir elementos.
- Tres positivos de **forma generadora async**, sin atribuir corrección de fin.
- Tres negativos con nombre/logging pero sin producción ni protocolo explícito.

Regresiones relacionadas seleccionadas de GoF, generadores y cursor C++:
**54 passed, 6 xfailed, 282 deselected**. Los seis xfail son los del ejercicio
nuevo; no cuentan como corrección del recorrido. La mejora real de esta entrega
es evitar que bookkeeping local se confunda con estado de un cursor Python.
