# `iterator#callback-iterator` (Go) — cerrada

Estado: **cerrada**. La variante es `ready` en su único lenguaje declarado.
Fecha: 2026-09-14. Base: `a4c02a5` (IR 1.59.0), **sin cambio de IR**.

## Sexta variante que no necesitó capacidad nueva

Todo lo que el contrato pide ya estaba en el grafo, de tres capacidades construidas
antes por otros motivos:

| Necesidad | Hecho existente |
|---|---|
| El callback es un parámetro invocado | `CALLEE_VALUE` sobre el `PARAMETER` |
| Recibe **el elemento** | `ARGUMENT` → `VALUE` → `LOADED_FROM` → `ITERATION_BINDING` |
| Su booleano es lo que se prueba | `TRUTH_TEST` (ya existía, con polaridad por negación) |
| Gobierna continuar | `CFG_NEXT` de la rama a un `return` o un `break` |

`TRUTH_TEST` fue la sorpresa agradable: el `if_statement` ya emitía a qué valor prueba,
descontando hasta 32 negaciones lógicas y ajustando `when`. Es decir, la mitad del
contrato estaba resuelta desde antes y nadie la había usado.

## El error que costó la iteración: `ARGUMENT` no liga el almacenamiento

La primera versión hacía lo obvio:

```kenql
require $call ARGUMENT $element;
require $loop ITERATION_BINDING $element;
```

Cero matches, en los siete negativos **y** en los cuatro positivos. Sobre el grafo de
fuente los dos hechos apuntan a la misma entidad —`Each/STORAGE:value`— así que la
query parece correcta al leerla contra el IR de fuente.

Pero KenQL **proyecta** `ARGUMENT`: no liga el almacenamiento, liga un nodo de
ocurrencia sintético `<call>/argument/<posición>`, y desde ahí el valor se alcanza por
`VALUE` y luego `LOADED_FROM`:

```
CALL:99@99:111 --ARGUMENT--> CALL:99@99:111/argument/0          (ocurrencia de callsite)
                             …/argument/0 --VALUE--> …/argument/0/loaded-value
                             …/loaded-value --LOADED_FROM--> Each/STORAGE:value
```

La comparación correcta es contra el último eslabón. Lo grave del modo de fallo es que
**no falla**: devuelve cero matches, que es indistinguible de «el patrón no está». Ese
es el motivo de que `test_the_element_link_is_storage_identity_not_a_call_site_occurrence`
fije la cadena explícitamente, y de que el `docstring` del fichero lo diga antes de
nada.

## La polaridad, deliberadamente no exigida

Las cuatro combinaciones de `TRUTH_TEST.when` y el `kind` del `CFG_NEXT` que para son
todas «el booleano gobierna continuar». La ficha pide eso, no una convención concreta,
así que la query **no** restringe la polaridad y admite por igual:

| Forma | Lectura |
|---|---|
| `if !yield(v) { return }` | falso → parar (convención de `iter.Seq`) |
| `if !yield(v) { break }` | falso → parar el bucle |
| `if yield(v) { } else { return }` | falso → parar |
| `if yield(v) { return }` | verdadero → parar (convención invertida) |

Exigir «falso para parar» habría sido codificar una convención que la ficha no pide.

## Negativos cubiertos

14 pruebas en `tests/structural/test_iterator_callback_iterator.py`:

| Negativo | Por qué se rechaza |
|---|---|
| el resultado del callback no se prueba | no hay rama con `TRUTH_TEST` sobre esa llamada |
| el callback recibe una constante | el enlace de elemento no llega al binding del bucle |
| el callback recibe **otro** valor | ídem, y es el negativo que verifica que el enlace sea por identidad de almacenamiento |
| la rama prueba una llamada no relacionada | `TRUTH_TEST` apunta a otra llamada |
| la rama prueba un valor no relacionado | no hay `TRUTH_TEST` sobre la llamada al callback |
| el callback nunca se invoca | falta `CALLEE_VALUE` |
| el resultado se prueba pero el desenlace no detiene | `CFG_NEXT` no llega a `return` ni a `break` |

## Límites declarados

`query_claim` no prueba agotamiento, tipos de elemento ni progreso. Un desenlace que
detenga **de forma no inmediata** (por ejemplo un `return` dentro de un `if` anidado
bajo la rama) queda fuera: `CFG_NEXT` es el paso siguiente de la rama, no su clausura
transitiva.

## Validación

`tests/structural/` completo, sin regresiones, más las 14 pruebas nuevas.
`mypy src/ken` limpio. Sin bump de `IR_VERSION`: el grafo no cambia.
