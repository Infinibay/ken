# Adapter: traducción entre contratos

Revisión por algoritmo, 13 de septiembre de 2026. Complementa el
[diseño de Adapter](../patterns/adapter.md) y la
[regla ejecutable](../../../../src/ken/structural/patterns/adapter.toml).

## Algoritmo en palabras

El cliente solicita una operación mediante un contrato objetivo. El adaptador
cumple ese contrato utilizando otro servicio cuyo contrato es diferente. Traduce
la operación solicitada y, cuando hace falta, los argumentos al formato que admite
el servicio. Invoca ese servicio y traduce su resultado o sus errores al contrato
que espera el cliente.

La traducción más sencilla es cambiar el nombre de una operación sin cambiar
sus datos. Otra variante conserva el nombre pero convierte unidades, formatos,
orden de argumentos, tipos o representación de ausencia/error. Que dos métodos
tengan nombres distintos no prueba la transformación; que tengan el mismo nombre
tampoco descarta adaptación.

Una conversión concreta puede describirse así: tomar el valor recibido, convertirlo
a la unidad del servicio, guardar el resultado de la llamada y convertirlo a la
unidad esperada por el cliente antes de devolverlo. Las pruebas de esta revisión
usan multiplicar por dos y sumar uno como transformaciones sencillas y explícitas.
No se atribuye una unidad de negocio a esos números.

La adaptación de procedimientos puede devolver void y producir efectos. La
adaptación a una API que configura un valor por defecto puede ignorar un argumento
opcional. Por eso los contratos de preservación de entradas y resultados deben
ser seleccionables: no son requisitos absolutos de todos los Adapter.

## Roles e invariantes

| Requisito | Evidencia necesaria |
|---|---|
| Contrato objetivo | El método implementado corresponde a un slot de ese contrato concreto |
| Adaptee | Receptor de la llamada ligado al servicio almacenado o heredado |
| Diferencia de contratos | Contratos resueltos y pertinentes, no una interfaz marker arbitraria ni nombres distintos que son aliases |
| Entrada adaptada | El argumento del servicio procede de la entrada y de las transformaciones requeridas |
| Operación adaptada | Ocurrencia de llamada y target/callable correspondientes a la colaboración |
| Salida adaptada | El retorno procede del resultado del servicio mediante las transformaciones requeridas |
| Errores | La excepción/resultado de error original llega al mapeo de errores admitido por la variante |

Delegar al mismo contrato normalmente expresa otra colaboración. Delegar a un
servicio diferente es evidencia estructural, pero no demuestra la intención de
compatibilidad ni que la conversión sea correcta. Un modelo numérico tendría que
distinguir overflow, redondeo, escala y pérdida de precisión para verificar una
conversión de unidades, además del simple flujo de operandos.

## Traducción al IR objetivo

Este pseudocódigo usa instrucciones del núcleo para expresar la secuencia. No
agrega una gramática KenQL ni supone que el buscador actual ejecute el cuerpo.

```text
func request(value) {
  %input = slot.load @value
  %scale = const 2
  %converted = binary *, %input, %scale
  slot.store @converted, %converted
  %receiver_address = field.addr %self, "service"
  %receiver = memory.load %receiver_address
  %argument = slot.load @converted
  %raw = call %receiver.perform(argument[0]=%argument)
  slot.store @result, %raw
  %loaded = slot.load @result
  %offset = const 1
  %answer = binary +, %loaded, %offset
  return %answer
}
```

La búsqueda precisa enlaza el valor del parámetro de entrada con el operando de
la conversión, el resultado de esa conversión con el argumento de esa llamada,
y el resultado de la llamada con la conversión final y el return. Los nombres
converted y result no prueban ninguno de esos vínculos.

Guardar el resultado y realizar logging antes de retornarlo requiere comprobar
el intervalo de preservación del binding. Si el resultado es mutable y una
conversión cambia sus campos, esa modificación puede ser parte del algoritmo:
preservar el binding no equivale a prohibir toda escritura en el objeto.

Para adaptadores de callbacks, un argumento puede ser una closure que transforma
el evento cuando el servicio la invoca posteriormente. Se necesitan captura,
invocación diferida y flujo del argumento del callback; no basta con que el cuerpo
de la closure contenga texto parecido a la transformación.

## Variantes por lenguaje

Los esquemas siguientes son requisitos de diseño; la matriz nueva valida sólo
Python, Java y TypeScript. Las regresiones C++ existentes también se ejecutaron.

| Lenguaje | Implementación representativa | Requisito del IR |
|---|---|---|
| Python | Clase contenedora o función que decode bytes del servicio | Flujo de llamadas encadenadas, protocolo dinámico y errores de decode |
| JavaScript | Función/closure que convierte callbacks o devuelve Promise | Capturas, efectos diferidos y resultado normal frente a rechazo |
| TypeScript | Clase que implementa Reader y utiliza un backend | Tipos estructurales, adaptación que puede conservar nombre del método |
| Java | Implementación de interfaz, servicio contenido y conversión | Correspondencia del slot con interfaz específica; checked exceptions |
| C# | Wrapper con async y mapeo de tareas/resultados | Diferencia entre Task retornada, valor esperado y cancelación |
| C++ | Object adapter o herencia múltiple de target/adaptee | Ajuste del receiver, overloads, lifetime y const/reference |
| Go | Struct que satisface interfaz implícita | Conversión explícita de error y múltiples valores de retorno |
| Rust | Implementación de trait, From/TryFrom o wrapper newtype | Ownership, conversiones falibles y Result sin confundir propagación con transformación |

Un generador puede adaptar un stream elemento por elemento sin materializarlo.
La búsqueda debe distinguir transformación lazy por yield de conversión eager a
una lista: construir el generador no significa que se haya consultado el servicio.
El adaptador que cruza threads o convierte una API blocking en async requiere
modelar ejecución/sincronización; envolver una llamada en otra función no prueba
por sí solo ese cambio de comportamiento.

## Pruebas y resultados

[test_algorithm_adapter.py](../../../../tests/structural/test_algorithm_adapter.py)
parsea fuentes y consulta gof.adapter. No ejecuta ni compila el código analizado.

| Casos nuevos | Estado | Interpretación |
|---|---|---|
| 18 positivos | Pasan | Conversión de entrada/salida, ruido antes/después/ambos, con y sin renombrado |
| 9 negativos básicos | Pasan | Servicio sin usar, otro receiver, ausencia de slot objetivo |
| 3 interfaces marker ajenas | Pasan tras corregir query | El contrato distinto debe ser el del slot implementado |
| 3 entradas descartadas | xfail estricto | Falta el contrato específico de procedencia de entrada transformada |
| 3 resultados descartados | xfail estricto | Falta el contrato específico de procedencia de salida transformada |
| 3 adaptaciones con igual nombre | xfail estricto | Falso negativo de la firma basada en nombres diferentes |

Los seis casos de entradas/resultados son fallos del contrato fuerte solicitado,
no necesariamente falsos positivos del patrón amplio. Los tres de nombre igual
mantienen ambas conversiones: son variantes válidas omitidas. Ningún xfail se
cuenta como requisito satisfecho; XPASS obliga a revisar y quitar la marca.

Las pruebas propias y las regresiones Adapter del catálogo y de C++ dieron
**80 passed, 9 xfailed, 445 deselected**, en 6.34 segundos:

```text
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_adapter.py tests/structural/test_gof_executable.py tests/structural/test_cpp_field_patterns.py tests/structural/test_cpp_method_contracts.py -k adapter
```

## Corrección realizada

La query ya requería que el método sobrescribiera un slot y que el adaptador fuera
subtipo de algún contrato distinto del adaptee. Sin embargo, ambos requisitos se
comprobaban independientemente. Una interfaz vacía Marker podía aportar la
diferencia nominal aunque el método realmente perteneciera al mismo Contract
que el servicio llamado.

Se agregó sólo esta relación a adapter.toml:

```text
require $method OVERRIDES $slot;
require $contract HAS_METHOD $slot;
```

Así el contrato utilizado para comparar con el adaptee es precisamente el que
declara el slot sobrescrito. No se cambió frontend, motor ni query legacy. Las
tres regresiones de marker reproducen el fallo antes y lo rechazan después.

## Extensiones necesarias

El núcleo ya preserva operandos, cargas/escrituras, llamadas y returns, pero faltan
reaching definitions y análisis de memoria que conviertan esa representación en
prueba de procedencia de entrada/salida. Los aliases de tipo y contratos
estructurales necesitan resolución antes de afirmar incompatibilidad nominal.

El lenguaje de búsqueda debería exponer contratos de adaptación de operación,
adaptación de entrada, salida y error que puedan componerse. Una query que busque
la conversión concreta podrá imponer operadores, modelos de decode o relaciones
de unidades; otra admitirá una transformación desconocida con evidencia parcial.
No conviene reemplazar la heurística de nombres distintos simplemente quitando
la condición: hace falta evidencia positiva de adaptación para la variante de
nombre igual.

Los adaptadores de clase y funcionales siguen en diseño en este catálogo; su
soporte no queda acreditado por las pruebas de object-adapter ni por la existencia
de otras reglas modernas que reconocen wrappers de callbacks.
