# Builder: configuración, director y sucesores

Estado: extensión del [ejercicio inicial](../algorithms-to-ir.md) y del
[contrato general](../gof-algorithm-contracts.md#2-builder). Esta revisión añade
director, estado acumulado y builders inmutables. La matriz anterior de
`test_builder_interleaving.py` conserva sus 48 casos de producto almacenado;
las [pruebas nuevas](../../../../tests/structural/test_algorithm_builder.py)
no repiten esa matriz.

## Algoritmos en palabras

**Configuración acumulada.** Recibir entradas en pasos distintos. Conservar la
configuración de la misma construcción. Al finalizar, obtener esos valores y
usarlos para construir el producto devuelto. Un paso puede validar o transformar
su entrada, pero la variante debe expresar qué relación se conserva.

**Producto mutable almacenado.** Crear un producto pendiente, modificar sus
partes y entregarlo al finalizar. El builder y el producto son objetos distintos;
la identidad que debe conservarse es la del producto pendiente. Si el builder
se reinicia, empieza otra construcción y las escrituras anteriores no deben
atribuirse al producto nuevo.

**Director.** Seleccionar una construcción, aplicar los pasos necesarios y
solicitar su producto. Las llamadas pueden tener logging entre ellas. No deben
unirse pasos de un builder con la finalización de otro sólo porque comparten
tipo o el nombre de una variable.

**Builder inmutable.** Cada paso obtiene un builder sucesor que incorpora el
cambio y conserva la configuración pertinente del anterior. El siguiente paso
debe recibir ese sucesor, y `finish` debe usar el estado actualizado. Descartar el
sucesor y finalizar el original rompe ese contrato de uso.

**Builder que consume estado.** Un paso mueve el builder o cambia su estado de
tipo. La finalización requiere el estado permitido y no puede reutilizar una
instancia ya consumida. Un `self` Rust por valor y un `&mut self` no son la misma
operación, aunque ambos escriban campos.

## IR objetivo y valores que deben conservarse

Este texto muestra obligaciones de diseño, no una gramática ejecutable nueva.
Las operaciones básicas de slots, memoria y llamadas existen; los contratos de
estado entre llamadas y ownership aún no están completos.

```text
function Director.build(%selected) {
  call %selected, slot: Assembly.first, argument[0]: 1
  %metric = binary.add 1, 2
  call @log, argument[0]: %metric
  call %selected, slot: Assembly.second, argument[0]: 2
  %product = call %selected, slot: Assembly.finish
  return %product
}

function Assembly.first(%self, %input) {
  %address = field.addr %self, "x"
  memory.store %address, %input
}

function Assembly.finish(%self) {
  %x_addr = field.addr %self, "x"
  %y_addr = field.addr %self, "y"
  %x = memory.load %x_addr
  %y = memory.load %y_addr
  %product = construct @Product, argument[0]: %x, argument[1]: %y
  return %product
}
```

Correlacionar el receptor del director es necesario, pero no suficiente: entre
pasos puede haber un reset del producto, una escritura externa o configuración
condicional que nunca ocurra. Una prueba fuerte necesita estados de memoria y
precondiciones por construcción, conservando `unknown` cuando falte información.

Para builders inmutables la identidad de objeto **debe cambiar**:

```text
%initial = call @Assembly.new, argument[0]: 0, argument[1]: 0
%with_x = call %initial, slot: Assembly.first, argument[0]: %x
%with_xy = call %with_x, slot: Assembly.second, argument[0]: %y
%product = call %with_xy, slot: Assembly.finish
```

La relación correcta aquí es sucesión de configuración. Un `preserve(object)`
global sería un requisito equivocado. Debe expresarse qué parte del estado pasa
de `%initial` a `%with_x`, cuál cambia y qué sucesor llega a la finalización.

## Contratos separables

| Contrato | Evidencia | Mutación relevante |
|---|---|---|
| Entrada configura estado | Flujo parámetro→escritura de campo | Reemplazar la entrada por constante |
| Estado llega al producto | Carga de estado→argumento/parte del producto retornado | Finalizar con constantes ajenas |
| Misma construcción | Identidad de receptor más etapa/lifetime | Reasignar binding o resetear producto pendiente |
| Director aplica pasos | Llamadas a operaciones de construcción correlacionadas | Repartir pasos entre receptores |
| Sucesor inmutable | Retorno del paso→receptor del siguiente | Ignorar el valor sucesor |
| Estado permitido al finalizar | Typestate, precondición o evidencia de pasos | Finalizar antes de pasos obligatorios |

No todo Builder requiere dos pasos distintos ni un director. El umbral de dos
operaciones de `builder#director` identifica esa variante concreta. Tampoco todo
paso tiene que contribuir a un argumento del constructor: puede validar o
seleccionar una opción. Exigir aportación de todos los pasos corresponde a un
contrato refinado, no a una regla universal.

## Composición KenQL comprobada

La [regla existente](../../../../src/ken/structural/patterns/builder.toml)
permite combinar la colaboración del director con configuración consumida en
la construcción:

```kenql
query directed_state {
 match "builder#director"(builder:$builder,finish:$finish,product:$product);
 match "builder#mutable-product"(builder:$builder,finish:$finish,product:$product);
 emit $builder,$finish,$product;
}
```

Las pruebas ejecutan esta query como `SavedRule` temporal. Ambas subqueries deben
coincidir en **el mismo builder, finalizador y producto**. Los positivos de tres
lenguajes pasan. Si `finish` construye `Product(0,0)`, la firma de director sigue
apareciendo, pero el refinamiento ya lo rechaza sin cambios al motor.

La composición prueba que existe un paso configurador relevante y una
colaboración de director. No enlaza necesariamente ese paso con uno de los dos
pasos concretos contados por el director ni demuestra que todas las entradas
lleguen al producto; exponer el rol del paso y la escritura permitiría una
correlación adicional. Tampoco resuelve lifetime ni orden entre llamadas.

## Variantes por lenguaje

| Lenguaje | Formas habituales | Obligaciones específicas |
|---|---|---|
| Python | Mutable, dataclass reemplazada, director funcional | Aliases, objetos compartidos, `replace` superficial frente a copia profunda |
| Java | Mutable/fluent, director, builders de objetos inmutables | Identidad de instancia, métodos que devuelven `this` o sucesor, estado final |
| TypeScript / JavaScript | Fluent mutable, objetos sucesores, spread | Spread superficial, tipos opcionales y uniones de etapas |
| C# | Builder mutable, records con `with` | Copia de referencia/campos y sucesión del record |
| C++ | Builders por valor o referencia, `&&` y move | Vida útil, constructor de copia/movimiento y objeto movido |
| Go | Struct por valor, puntero, functional options | Copiar struct puede conservar mapas/slices compartidos; capturas de opciones |
| Rust | `&mut self`, `self -> Self`, `Builder<State>` | Borrow, consumo, tipos asociados/genéricos y `build` habilitado por estado |

La matriz nueva cubre Python/Java/TypeScript. La variante almacenada previa tiene
pruebas Rust con producto movido o clon derivado; eso no equivale a soporte
completo de `consuming-typestate`, que sigue en diseño junto con
`immutable-product`.

## Resultados y limitaciones observadas

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_builder.py
```

Resultado inicial: **24 passed, 6 xfailed estrictos**.

- Seis positivos del director, con/sin ruido por lenguaje.
- Doce negativos: otro receptor en un paso, otro receptor al finalizar, un solo
  paso distinto repetido y producto de finalización descartado.
- Seis comprobaciones de la composición de estado: tres positivos y tres
  rechazos de producto constante.
- Tres gaps de rebinding: configurar `parts`, ejecutar `parts=other` y finalizar
  sigue haciendo match. La igualdad actual de `RECEIVER` no invalida esa unión
  según el valor que tiene el binding en cada llamada.
- Tres falsos negativos de la variante inmutable: pasos que retornan sucesores
  nuevos y finalización en el último sucesor. Están marcados `xfail(strict=True)`
  porque esa variante continúa en diseño.

Los xfail no son negativos correctos ni soporte de la variante. Las fuentes se
parsean y los queries se ejecutan; no se compilan ni se ejecutan los builders.
El ruido conserva el algoritmo ensayado, pero el motor no demuestra que una
función arbitraria de logging sea pura, no lance o no modifique estado oculto.
