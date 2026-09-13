# Facade: de los campos a la coordinación entre resultados

Estado: ejercicio algoritmo→IR con una query refinada ejecutable y pruebas
Python/Java/TypeScript. La [firma actual](../../../../src/ken/structural/patterns/facade.toml)
detecta una operación que delega en dos campos de tipos distintos. Ese hecho
no demuestra orden, traspaso de resultados ni frontera arquitectónica.

## Algoritmo en palabras

Una fachada ofrece una operación que simplifica el uso de uno o varios
subsistemas. Puede coordinar pasos independientes o transformar datos entre
ellos. Para una variante de **lectura seguida de escritura**:

1. Recibir una clave del cliente.
2. Solicitar al subsistema lector un valor relacionado con esa clave.
3. Conservar el valor obtenido hasta entregarlo al subsistema escritor.
4. Ejecutar el segundo paso con ese valor y devolver la respuesta pertinente.
5. Admitir logging y cálculos independientes entre los pasos, siempre que no
   cambien el valor usado, el subsistema seleccionado o las precondiciones.

La relación de datos obliga a que la producción preceda al consumo. Llamar
primero al escritor con un valor antiguo y luego realizar la lectura no cumple
este algoritmo, aunque ambas llamadas aparezcan en el mismo método.

No toda Facade requiere ese traspaso. Encender luces y abrir una pantalla puede
coordinar dos acciones independientes. La variante de flujo es un refinamiento
seleccionable, no una redefinición universal de Facade.

## Traducción a instrucciones y obligaciones

El siguiente texto es conceptual: se apoya en instrucciones existentes, pero no
constituye sintaxis ejecutable de un nuevo lenguaje de contratos.

```text
function Surface.execute(%self, %key) {
  %reader_addr = field.addr %self, "reader"
  %reader = memory.load %reader_addr
  %obtained = call %reader, slot: Reader.read, argument[0]: %key
  @value = slot.declare int
  slot.store @value, %obtained

  %metric = binary.add 1, 2
  call @log, argument[0]: %metric

  %writer_addr = field.addr %self, "writer"
  %writer = memory.load %writer_addr
  %input = slot.load @value
  %result = call %writer, slot: Writer.write, argument[0]: %input
  return %result
}
```

El requerimiento esencial es que la definición que alcanza `%input` sea la
escritura de `%obtained`. `slot.store @value, 0` entre ambos debe invalidarlo.
La igualdad del nombre `value` no basta. Una copia local que retenga el valor
puede ser válida, aunque el binding original se reasigne posteriormente.

Para un entero se conserva el valor. Si el dato es un objeto, conservar el
binding no conserva su estado: una mutación por alias puede cambiarlo. El
contrato debe poder exigir identidad, estado completo o sólo los campos que
consume el segundo subsistema, según el algoritmo.

Una futura búsqueda de cuerpo necesitaría poder decir:

```text
// Contrato objetivo, todavía no ejecutable.
inside $operation {
  %obtained = call receiver: $reader, argument[0]: $key;
  capture %obtained as $handoff;
  ... independent operations ...
  call receiver: $writer, argument[0]: same_reaching_value($handoff);
}
```

La elipsis permite trabajo independiente; no introduce permiso para ignorar
escrituras, cambios de rama o efectos desconocidos. Si el análisis no puede
establecer el origen del valor, debe conservar la incertidumbre.

## Query de grafo que ya funciona y su límite

La [matriz](../../../../tests/structural/test_algorithm_facade.py) ejecuta:

```kenql
query facade_flow {
 match "facade"(unit:$unit);
 require $unit HAS_METHOD $operation;
 require $unit HAS_FIELD $first;
 require $unit HAS_FIELD $second;
 require $first TYPE $first_type;
 require $second TYPE $second_type;
 different $first_type $second_type;
 require $operation HAS_CALL $producer;
 require $producer RECEIVER $first;
 require $producer RESULT $produced;
 require $operation HAS_CALL $consumer;
 require $consumer RECEIVER $second;
 require $consumer ARGUMENT $argument;
 require $argument VALUE $input;
 path $produced VALUE_FLOW{0,3} $input as $flow;
 emit $unit,$operation,$producer,$consumer,$flow;
}
```

Se usa como `SavedRule` temporal, sin endurecer la regla general del catálogo.
En modo `strict`, funciona para `writer.write(reader.read(key))`: productor y
argumento consumidor comparten directamente el resultado, sin una carga local
intermedia. Admite logging antes de la expresión y rechaza dos delegaciones
independientes cuando el escritor recibe una constante.

Para `value = reader.read(key); log(123); writer.write(value)`, la vista actual
crea un `VALUE_FLOW` con modalidad `may` desde las asignaciones conocidas a la
carga del argumento. Es evidencia sin resolución de qué definición alcanza
esa carga. Por eso el mismo patrón tiene comportamientos distintos:

| Fuente | `strict` | `possible` | Interpretación |
|---|---|---|---|
| Resultado anidado directamente | Match | No necesario para esta prueba | Traspaso directo comprobable |
| Local sin cambios entre llamadas | Sin match | Match | Falso negativo del refinamiento estricto actual |
| Local sobrescrito antes de consumir | Sin match | Match | Candidato falso del refinamiento de flujo posible |
| Consumo antes de asignar resultado de lectura | Sin match | Match | Candidato falso: falta orden/definición alcanzante |

Los últimos dos rechazos estrictos no demuestran que el modo estricto comprenda
la mutación o el orden: rechaza también el positivo local. No corresponde
presentarlos como una mejora de exactitud por análisis de esos comportamientos.

## Contratos que deben seguir separados

| Contrato | Datos necesarios | Límite actual |
|---|---|---|
| Firma de colaboración | Campos de tipos distintos y delegaciones | No explica qué hace el método |
| Traspaso de valor | Resultado productor→argumento consumidor | Directo soportado; carga local es `may` |
| Orden de efectos | Control y dependencia entre operaciones | Orden textual no prueba ejecución ni exclusión de ramas |
| Datos preservados | Definiciones alcanzantes, aliases y escrituras | No es equivalente a no reasignar un nombre |
| Frontera simplificada | Exports, clientes y contratos del subsistema | La intención arquitectónica sigue requiriendo revisión |
| Manejo de fallos | Try/finally, transacciones, compensación | Una cadena de llamadas no prueba atomicidad |

## Variantes por lenguaje

| Lenguaje | Forma posible | Necesidad del IR |
|---|---|---|
| Python | Clase coordinadora o función de módulo | Bindings dinámicos, resultado local y aliases; `async` puede suspender entre pasos |
| Java | Objeto con servicios inyectados | Campos, contratos y flujo de argumentos; excepciones y transacciones |
| TypeScript / JavaScript | Clase, módulo exportado o función async | Exports, promesas, `await` y capturas |
| C# | Clase/servicio con tareas y `await` | Estado entre suspensiones y cancelación |
| C++ | Clase o función libre con subsistemas | Referencias, ownership, copia/move y excepciones |
| Go | Función/struct con interfaces | Retornos `(value,error)`, branches de error y goroutines |
| Rust | Módulo/struct sobre traits | `Result`, operador `?`, borrow y movimientos |

`module-surface` sigue en diseño. Las pruebas nuevas cubren únicamente cuerpos
síncronos en Python, Java y TypeScript. La tabla enumera requisitos de diseño,
no soporte certificado de cada variante.

## Resultado reproducible

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_facade.py
```

Resultado inicial: **18 passed, 3 xfailed estrictos**:

- Seis positivos de traspaso directo, con y sin ruido.
- Tres negativos con delegaciones presentes pero resultado productor descartado.
- Tres positivos de descubrimiento del traspaso local en modo `possible`.
- Tres `xfail(strict=True)` para el mismo traspaso local válido en modo `strict`.
- Seis controles explícitos de limitación: sobrescritura y orden invertido
  siguen haciendo match en `possible`. Estos seis tests pasan porque documentan
  el comportamiento observado; **no son seis detecciones correctas**.

Los fixtures se parsean y las queries se ejecutan; no se ejecutan los servicios.
La mejora necesaria es resolver el origen de cargas de argumentos en cada punto,
componerlo con control y mantener efectos desconocidos. Añadir más requisitos
`HAS_FIELD` no resuelve este problema algorítmico.
