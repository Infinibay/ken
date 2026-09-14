# `flyweight#entry-api` (4 lenguajes) — cerrada

Estado: **cerrada**. La variante es `ready` en sus **cuatro** lenguajes declarados.
Fecha: 2026-09-14. Base: `6965fc5` (IR 1.61.0), **sin cambio de IR**.

## Octava variante que no necesitó capacidad nueva

`explicit-interning` cubría el pool escrito a mano: buscar, fallar, construir, insertar
y devolver, todo dentro del método analizado. `entry-api` es la otra mitad de la ficha:
el **API de entrada del propio mapa** es quien retiene el objeto, así que el método
nunca escribe el pool. Por eso el papel de *receptor* del campo es la sustancia de esta
variante: la llamada de entrada tiene que hacerse **sobre el campo**, no sobre un local
ni sobre un parámetro que casualmente contiene un mapa.

Los cuatro lenguajes lo escriben distinto, y la diferencia no es cosmética:

| Lenguaje | Llamada de entrada | Forma del objeto retenido |
|---|---|---|
| Java | `entries.computeIfAbsent(key, k -> new Value(k))` | la propia llamada |
| C# | `entries.GetOrAdd(key, k => new Value(k))` | la propia llamada |
| C++ | `entries.try_emplace(key, key).first->second` | una cadena `MEMBER_OF` sobre el `pair` |
| Rust | `self.entries.entry(key).or_insert_with(\|\| Value::new())` | el envoltorio cuyo receptor es la llamada |

Las tres formas del «objeto retenido» se aceptan con una disyunción de dos ramas:
`path $returned MEMBER_OF{0,2} $entry` cubre Java/C# (distancia 0) y C++ (dos saltos,
`first` y `second`), y `$returned RECEIVER $entry` cubre el `or_insert_with` de Rust.

En Rust, además, el call que lleva el receptor del pool y el argumento clave es el
`entry(key)` **interno**, mientras que el que se devuelve es el externo: la variante
liga ambos por el receptor del segundo.

## Lo que la ficha prohíbe afirmar

*no afirmar factory exactly-once*. La variante **no** cuenta invocaciones del factory ni
prueba que la construcción ocurra una sola vez: solo que el API de entrada es quien
retiene el objeto. Es la lectura literal de la ficha y está en el `query_claim`.

## Una trampa de proyección, otra vez la misma familia

La primera versión filtraba la posición del argumento así:

```kenql
require $entry ARGUMENT $argument [position: 0];
```

Cero matches, en los cuatro positivos. En el grafo de fuente el hecho lleva
`position: 0`, pero KenQL **proyecta** `ARGUMENT` a un nodo de ocurrencia y el hecho
proyectado va **sin atributos**; la posición vive en el `ENTITY ARGUMENT` de ese nodo.
La forma correcta es la que ya usaba `state.toml`:

```kenql
require $entry ARGUMENT $argument;
require $argument ENTITY ARGUMENT [position: 0, kind: positional];
```

Es la misma familia de fallo que el `ARGUMENT` de `iterator#callback-iterator`: un
filtro que se lee bien contra el IR de fuente y devuelve silenciosamente cero matches.
`test_the_argument_position_lives_on_the_occurrence_not_on_the_relation` lo fija.

## Negativos cubiertos

16 pruebas en `tests/structural/test_flyweight_entry_api.py`: 4 positivos (uno por
lenguaje), 4 de renombrado, 7 negativos y 1 comprobación de la proyección.

| Negativo | Por qué se rechaza |
|---|---|
| `get`/`at` simple, sin API de entrada | el nombre del callee no es ninguno reconocido |
| clave constante (`computeIfAbsent("fixed", …)`) | el argumento no viene del parámetro clave |
| el API se llama sobre un **local** (Java, C++) | el receptor no es un campo del tipo |
| el API se llama sobre un **parámetro** (Java, Rust) | ídem |
| el método no recibe clave | no hay parámetro del que provenga el argumento |
| el método no devuelve el objeto retenido | devuelve una construcción nueva y ajena al API |

## Límites declarados

La identificación del API es **por nombre**, no por resolución de biblioteca: una
función de usuario con ese nombre contaría. Es la misma concesión que el resto del
catálogo hace con los nombres de protocolo. Tampoco se prueba la identidad de clave
bajo reasignación, la estabilidad temporal del pool ni el estado intrínseco/extrínseco,
y las garantías de concurrencia de cada API quedan fuera por decisión.

## Validación

`tests/structural/` completo, sin regresiones, más las 16 pruebas nuevas.
`mypy src/ken` limpio. Sin bump de `IR_VERSION`: el grafo no cambia.
