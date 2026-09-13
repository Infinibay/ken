# Composite: del algoritmo a los contratos de IR

Estado: revisión del algoritmo con pruebas de fuente Python, Java y TypeScript.
La query actual identifica una firma estructural. El IR propuesto abajo expresa
obligaciones más precisas; no es sintaxis ejecutable de KenQL ni del exportador.
Véanse el [contrato general](../gof-algorithm-contracts.md#8-composite), el
[patrón declarativo](../../../../src/ken/structural/patterns/composite.toml) y las
[pruebas](../../../../tests/structural/test_algorithm_composite.py).

## Algoritmo en palabras

1. Un componente ofrece una operación que un cliente puede invocar sin conocer
   si está ante una hoja o un contenedor. La compatibilidad puede ser nominal,
   por interfaz o por una variante de un tipo algebraico.
2. Una hoja cumple la operación con su propio estado. Un contenedor conserva
   otros componentes, que pueden ser hojas u otros contenedores.
3. Al ejecutar la operación del contenedor, recorrer los hijos seleccionados.
   Para cada elemento obtenido, invocar la operación correspondiente sobre ese
   elemento. El receptor debe conservar la identidad obtenida de la colección
   hasta la llamada; reutilizar el nombre de la variable no basta.
4. Cuando la operación recibe contexto, propagarlo de acuerdo con su contrato.
   Puede ser el mismo contexto, una proyección o un contexto derivado por hijo.
   No exigir identidad de argumentos a todos los Composite.
5. Si la operación produce un resultado agregado, combinar cada resultado hijo
   relevante con el acumulador y devolver el resultado definido por el contrato.
   Una operación como `render` puede producir efectos y devolver `void`: no
   corresponde exigir reducción a esa variante.

No se deduce de estos pasos que el grafo de objetos sea un árbol acíclico, que
todos los hijos sean alcanzables ni que el algoritmo termine. Un límite de
profundidad, un conjunto de visitados o una política de selección pueden formar
parte de otra variante válida.

## Identidades y obligaciones seleccionables

| Objeto o valor | Obligación | Razón |
|---|---|---|
| `container` | Cumple el contrato del componente o es el tipo nominal recursivo | Una lista de listeners por sí sola no demuestra Composite |
| `children` | Colección almacenada en el contenedor para esta variante | Un parámetro con objetos ajenos no demuestra uso de sus hijos |
| `child` | Procede del elemento de esa iteración y llega al receptor de la llamada | Reasignar `child = this` rompe la colaboración aunque conserve el nombre |
| `operation` | Invoca el mismo slot de contrato, o una operación equivalente declarada | Coincidir en nombre es evidencia nominal limitada |
| `context` | Conserva la relación de flujo exigida por la variante | Un `child.operation(0)` no propaga el parámetro original |
| `child_result` | Llega a la actualización del acumulador si se exige agregación | Ejecutar la llamada y descartar su resultado no calcula el agregado |
| `accumulator` | Su valor de salida llega al retorno seleccionado | Sobrescribirlo después del bucle rompe esa salida |

El contrato debe separar `recursive-dispatch`, `aggregate-results` y
`context-propagation`. Los últimos dos refinan al primero; sus negativos no deben
eliminar una implementación válida de Composite con otro comportamiento.

## Traducción objetivo al IR

Ejemplo conceptual: sumar un valor local y el resultado de los hijos. Las
operaciones marcadas `proposed` todavía requieren diseño e implementación.

```text
function count(%self, %context) {
  %children_addr = field.addr %self, "children"
  %children = memory.load %children_addr
  @total = slot.declare int
  slot.store @total, %context

  // proposed: región con origen de elementos y valor de agotamiento explícitos
  iterate %child in %children {
    %value = call %child, slot: Component.count, argument[0]: %context
    %old = slot.load @total
    %next = binary.add %old, %value
    slot.store @total, %next
  }

  %result = slot.load @total
  return %result
}
```

`field.addr`, `memory.load`, `slot.declare/load/store`, `call`, `binary` y `return`
existen en el núcleo de instrucciones. La forma textual mostrada, `iterate`,
el despacho por slot y una prueba de reducción entre iteraciones son objetivos,
no una promesa de soporte actual. Exportar un cuerpo como `partial/native` y
pasar el verificador estructural no verifica esas obligaciones.

Una búsqueda más fuerte necesitaría expresar, sin depender de nombres:

```text
// Contrato objetivo; no es KenQL ejecutable.
select component_operation as $outer;
inside $outer {
  iterate element: $child, collection: field($container, $children) as $walk;
  call receiver: $receiver, slot: same_contract_slot($outer) as $dispatch;
  require reaches_same_value($walk.element, $dispatch.receiver);
  optional_contract "context-propagation" {
    require value_flow($outer.argument[0], $dispatch.argument[0]);
  }
  optional_contract "aggregate-results" {
    require loop_carried_flow($dispatch.result, $accumulator, within: $walk);
    require value_flow($walk.output($accumulator), $outer.return);
  }
}
```

El origen debe asociarse al **valor del elemento**, con escrituras que invalidan
su llegada al receptor. Un alias local que conserva el valor puede aceptarse;
una reasignación a otro objeto debe rechazarse. La reducción requiere flujo de
valores a través de iteraciones, no sólo orden textual entre dos instrucciones.

## Variantes por lenguaje

| Lenguaje | Implementación | Normalización necesaria / límite |
|---|---|---|
| Python | `for child in self.children: total += child.count(ctx)` | Elemento del iterable, rebinding y suma posiblemente sobrecargada; listas dinámicas pueden quedar en `unknown` |
| Java | `for (Component child : children) total += child.count(ctx)` | Despacho por interfaz, enhanced-for y acumulador; `stream().mapToInt(...).sum()` precisa modelos de biblioteca |
| TypeScript / JavaScript | `for (const child of children)` o `children.reduce(...)` | Distinguir `of` de `in`; identidad de objetos y cierre/reductor. La variante nominal necesita tipos o evidencia alternativa |
| C# | `foreach (Component child in children)` o LINQ `Sum` | Enumeración y slot de interfaz; delegado de LINQ y sumas nullable necesitan contratos propios |
| C++ | `for (auto const& child : children) child->count(ctx)` | Valor del puntero frente a objeto apuntado; referencias, virtual dispatch y posible invalidación de iteradores |
| Go | `for _, child := range n.children { child.Count(ctx) }` | El índice no es el hijo; copia del elemento, punteros frente a structs e interfaces implícitas |
| Rust | `children.iter().map(|c| c.count(ctx)).sum()` o `match Node` | Borrow del elemento, closure, trait object o enum recursivo; mover hijos con `into_iter()` tiene efectos distintos |

El catálogo actual contiene `recursive-contract` y `recursive-nominal` listos;
`algebraic-tree` y `higher-order-traversal` siguen en diseño. La matriz nueva
prueba Python/Java/TypeScript, no certifica las demás formas de esta tabla.

## Ruido permitido y mutaciones que deben cambiar el resultado

Se permiten cálculos locales independientes y logging de constantes o valores
primitivos que no alteren hijos, receptor, contexto o acumulador. Las pruebas
insertan ambas cosas dentro del bucle y renombran tipo, colección y operación.
Ese logging usa los nombres estándar de los ejemplos, pero una prueba estática
fuerte requeriría resolver sus efectos: el buscador actual no demuestra pureza,
ausencia de excepciones ni que una función no haya sido reemplazada dinámicamente.

Negativos de la colaboración básica: quitar la llamada recursiva, invocar otra
operación, usar un receptor fijo, cambiar el tipo de elemento a uno ajeno o
recorrer un parámetro externo conservando el campo `children` sin usarlo.

Negativos de contratos refinados: reemplazar el contexto con una constante,
descartar los resultados cuando se exige agregación, sobrescribir el acumulador
antes del retorno, o cortar la iteración cuando se exige visitar todos los hijos.
Mutar la colección durante el recorrido necesita semántica de lenguaje y API:
puede ser un error, un snapshot válido o una política intencional; no debe
clasificarse universalmente como ausencia del patrón.

## Resultado reproducible y gaps

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_composite.py
```

Resultado inicial: **24 passed, 9 xfailed**. Son 9 positivos (3 lenguajes ×
baseline/ruido/renombrado), 15 negativos básicos y 9 obligaciones pendientes.
Todos los archivos son fuente analizada; no se ejecuta el algoritmo de ejemplo.

Los `xfail(strict=True)` no cuentan como rechazos correctos: hoy la query sigue
encontrando los tres casos siguientes en los tres lenguajes. Cuando se corrija
uno, un `XPASS` hará fallar la prueba para exigir revisar su estado.

1. **Rebinding del hijo:** `child = self/this` antes de la llamada mantiene el
   match. Falta invalidar la procedencia de `ITERATED_CALL` tras una escritura.
   Éste sí rompe la colaboración que pretende identificar la variante nominal.
2. **Contexto sustituido:** `child.Count(0)` mantiene el match. La query no pide
   propagación del argumento; se necesita un contrato refinado seleccionable.
3. **Resultado descartado:** `total = total + 0` mantiene el match aunque la
   llamada retorne `value`. La firma actual no pide reducción ni retorno del
   agregado; es una insuficiencia respecto del algoritmo sumatorio, no prueba de
   falso positivo para toda forma de Composite.

Además, `recursive-contract` requiere que la operación sobrescriba un slot y
que invoque hijos, pero no expresa en su texto la identidad entre ese slot y el
slot despachado al hijo. La terminación, aciclicidad, captura de closures y
semántica de bibliotecas de colecciones tampoco se deducen de la firma.
