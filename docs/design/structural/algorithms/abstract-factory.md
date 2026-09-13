# Abstract Factory: categorías, familias y uso del proveedor

Estado: ejercicio algoritmo→IR y matriz de fuente en Python, Java y TypeScript.
El [patrón actual](../../../../src/ken/structural/patterns/abstract-factory.toml)
reconoce una firma nominal de creación. No comprueba aún todas las obligaciones
del [algoritmo general](../gof-algorithm-contracts.md#1-abstract-factory).

## Algoritmo en palabras

1. Definir categorías de productos que colaboran: por ejemplo un botón y un
   panel. Cada categoría establece su propio contrato.
2. Definir un proveedor capaz de entregar productos de esas categorías. El
   consumidor conoce ese contrato y recibe una selección de proveedor.
3. Cada implementación del proveedor elige productos compatibles con la familia
   seleccionada: por ejemplo un botón Ocean y un panel Ocean, o ambos Land.
4. El cliente solicita las categorías al proveedor elegido, conserva los
   resultados y los usa mediante sus contratos. El cliente puede registrar una
   métrica entre solicitudes sin cambiar la selección ni los resultados.
5. Si el contrato exige compatibilidad de familia, los productos que finalmente
   colaboran deben conservar esa relación, aunque se obtengan con métodos,
   closures o un registro de constructores distinto en cada lenguaje.

**Categoría y familia son ejes diferentes.** `Button` y `Panel` son categorías;
Ocean y Land son familias de implementaciones. Dos subtipos distintos de una
misma categoría no prueban dos categorías. Dos categorías diferentes tampoco
prueban que sus implementaciones sean compatibles entre sí.

No siempre se requiere construir un objeto nuevo: un proveedor puede usar
caché, devolver un singleton o clonar prototipos. La regla actual exige
`RETURNS_NEW`, por lo que esas implementaciones necesitan variantes propias.

## Traducción conceptual al IR

Las instrucciones básicas ya permiten representar las llamadas y valores.
La resolución de slots y las obligaciones de familia siguientes son propuestas,
no sintaxis ejecutable del exportador ni una gramática nueva de KenQL.

```text
function configure(%provider) {
  %button = call %provider, slot: Provider.button
  %metric = binary.add 1, 2
  call @log, argument[0]: %metric
  %panel = call %provider, slot: Provider.panel
  call %panel, slot: Panel.attach, argument[0]: %button
}

function Ocean.button(%self) {
  %product = construct @OceanButton
  return %product
}

function Ocean.panel(%self) {
  %product = construct @OceanPanel
  return %product
}
```

El IR de llamadas debe conservar por separado el receptor, el slot resuelto,
los argumentos y el resultado. La elección de proveedor es un **valor**, no el
nombre de una variable. Si se reasigna `provider = other_provider` entre ambas
llamadas, dos cargas del mismo binding no representan la misma selección.

El refinamiento de familia necesitaría evidencia independiente de los nombres:

```text
// Contrato objetivo, todavía no ejecutable.
match factory_definition as $provider_contract;
select creation_slot(category: $category_a) as $slot_a;
select creation_slot(category: $category_b) as $slot_b;
require different($category_a, $category_b);
require both_slots_belong_to($provider_contract);

inside $client {
  %a = call receiver: $selected_a, slot: $slot_a;
  %b = call receiver: $selected_b, slot: $slot_b;
  require same_selection($selected_a, $selected_b);
  require category(%a, $category_a);
  require category(%b, $category_b);
  optional_contract "uniform-family" {
    require compatible_family(%a, %b, evidence: $family_evidence);
  }
  require consumed_as_collaborators(%a, %b);
}
```

`same_selection` es más flexible que identidad de objeto: dos proveedores
inmutables equivalentes pueden representar la misma familia. A la inversa, un
proveedor mutable puede cambiar de configuración manteniendo su identidad.
Para ese caso se debe preservar el estado que controla la selección durante
el intervalo entre creaciones, y no simplemente el binding.

La pertenencia de familia puede justificarse mediante tipos asociados, un
parámetro genérico compartido, un discriminante constante o un contrato declarado
en un archivo de patrón. No debe inferirse sólo de prefijos de clases. Si faltan
pruebas, la respuesta adecuada al refinamiento es `unknown`.

## Invariantes y fallos diferenciados

| Obligación | Evidencia necesaria | Mutación reveladora |
|---|---|---|
| Categorías distintas | Contratos de producto y sustitución de tipos | Ambos productos pasan a la misma categoría |
| Slots del proveedor | Resolución del contrato y de cada override | Dos métodos ajenos coinciden accidentalmente |
| Producto devuelto | Flujo desde construcción/obtención al retorno | Construir el producto y devolver otro valor |
| Selección estable | Identidad o equivalencia más estado relevante | Reasignar proveedor o cambiar su configuración |
| Familia compatible | Evidencia declarada o derivada de tipos/valores | Un slot devuelve un producto de otra familia |
| Cliente desacoplado | Uso del resultado por su contrato | Ignorar el retorno y construir un tipo concreto |

Estas obligaciones deben poder seleccionarse. Encontrar una definición de
Abstract Factory no exige encontrar todos sus clientes. Un cliente que mezcla
productos no elimina la definición válida de la fábrica: debe reportarse como
un incumplimiento del contrato de uso, con el cliente como evidencia.

## Variantes por lenguaje

| Lenguaje | Forma | Necesidad del IR |
|---|---|---|
| Python | Clases con contratos nominales, protocolo o objeto con métodos | Tipos opcionales, return flow y selección dinámica; los protocolos no se equivalen automáticamente con herencia |
| Java | Interfaz/abstract class y productos por interfaz | Slots, covarianza y genéricos; familias no son sólo superclases diferentes |
| TypeScript | `implements`, objeto literal o closures | Contratos estructurales y capturas; clases vacías son estructuralmente compatibles aunque tengan nombres distintos |
| JavaScript | Objeto `{button: () => ..., panel: () => ...}` | Relacionar closures con la misma selección capturada |
| C# | Interfaz genérica, delegates y métodos de creación | Sustitución genérica, delegates, valores retornados |
| C++ | Interfaz virtual, templates, `unique_ptr<Button>` | Separar wrapper/ownership del contrato del producto y resolver especializaciones |
| Go | Interfaz implícita, struct proveedor o funciones | Relación estructural entre métodos; errores múltiples `(Product, error)` |
| Rust | Trait con tipos asociados `Button` y `Panel` | Sustituir tipos asociados por implementación y separar `Result` del producto |

`structural-families` y `associated-products` siguen en diseño en el catálogo.
La matriz de este ejercicio cubre únicamente la variante nominal de tres
lenguajes, con dos proveedores y dos categorías cada uno.

## Pruebas y resultado

[Matriz ejecutable](../../../../tests/structural/test_algorithm_abstract_factory.py):

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_abstract_factory.py
```

Resultado inicial: **18 passed, 3 xfailed**.

- Nueve positivos: baseline, métricas/logging y renombrado por lenguaje. Se
  conservan ambos proveedores detectados, incluso con logging entre solicitudes
  del cliente. Esa conservación comprueba la definición, no valida su cliente.
- Nueve negativos: quitar creación de la segunda categoría, romper el tipo de
  esa categoría o quitar el contrato nominal. Cada mutación elimina sólo el
  proveedor afectado; la otra familia sigue detectándose.
- Tres `xfail(strict=True)`: el proveedor Ocean devuelve el panel Land. La
  firma actual sigue detectándolo; el refinamiento `uniform-family` aún no
  existe. La familia es ground truth de la fixture, no evidencia que el motor
  pueda adivinar de sus nombres.

Los fixtures se parsean, no se ejecutan ni se compilan. El negativo de categoría
rompe intencionalmente la compatibilidad declarada; la validación sintáctica no
equivale a una compilación Java/TypeScript. Un `xfail` no es un negativo correcto
y se convierte en fallo si empieza a pasar, para revisar el contrato pendiente.

## Gaps concretos de la regla actual

La query exige dos overrides que retornan productos nuevos, con supertipos
distintos. Sus variables `$family1` y `$family2` representan en este ejercicio
**categorías de producto**, no familias de implementaciones compatibles.
El texto tampoco exige explícitamente que los dos slots pertenezcan al mismo
contrato `$contract`, ni analiza clientes o configuración mutable del proveedor.

La mejora del IR debe incorporar procedencia de selección, sustitución de tipos,
relación entre slots y evidencia de compatibilidad. Una regla fuerte debe
preservar `unknown` cuando esa evidencia falta, en lugar de promover una firma
de dos constructores a prueba de un algoritmo completo.
