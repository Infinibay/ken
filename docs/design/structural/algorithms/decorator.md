# Decorator: comportamiento alrededor del componente

Revisión por algoritmo, 13 de septiembre de 2026. Complementa el
[diseño de Decorator](../patterns/decorator.md) y la
[regla ejecutable](../../../../src/ken/structural/patterns/decorator.toml).

## Algoritmo en palabras

El cliente usa una operación de un contrato. El decorador ofrece ese contrato y
conserva un componente al que puede delegar la operación. Antes, después o durante
esa delegación agrega una responsabilidad, por ejemplo tracing, medición, cambio
de formato, transformación del resultado o manejo de recursos.

En un decorador de tracing transparente, se registra el comienzo, se llama al
componente recibido con la entrada pertinente, se registra el final y se devuelve
el resultado de esa llamada. El algoritmo tolera cálculos independientes entre
esas etapas, pero reemplazar el resultado por una constante rompe la transparencia.

Otros decoradores transforman deliberadamente entrada o salida, acumulan estado,
atrapan errores o reintentan. No corresponde exigir transparencia de argumentos,
resultado, efectos ni número de invocaciones a todas las variantes. Una búsqueda
debe poder seleccionar qué contrato pretende verificar.

En una variante funcional, una función recibe otra función y devuelve una closure
que la captura y agrega comportamiento. Un decorador sintáctico de Python puede
implementar esa colaboración, registrar metadatos o devolver otro objeto: el
símbolo @ no constituye por sí solo evidencia de GoF Decorator.

## Roles e invariantes

| Requisito | Evidencia requerida |
|---|---|
| Contrato común | Slot ofrecido por wrapper y componente, con resolución pertinente |
| Componente envuelto | Valor/receiver capturado o almacenado y utilizado en la llamada |
| Delegación | Ocurrencia de llamada a la operación correspondiente, no otro método auxiliar |
| Responsabilidad adicional | Efecto o transformación alcanzable relacionado con la operación |
| Orden seleccionado | Antes/después/finalmente/en error, según la variante concreta |
| Transparencia opcional | Flujo de argumentos/resultado preservado salvo las transformaciones permitidas |
| Composición | El resultado del constructor/wrapper puede alimentar otro wrapper compatible cuando se exige composición observada |

Logging puede ser precisamente la responsabilidad agregada o simplemente ruido
respecto de otra responsabilidad buscada. La clasificación depende del contrato
de búsqueda. Un nombre log no acredita un efecto observable ni ausencia de
mutaciones. Una llamada extra en código inalcanzable no agrega comportamiento.

## Traducción al IR objetivo

Este pseudocódigo combina el vocabulario del núcleo con una operación trace cuyo
modelo tendría que justificarse. No es una nueva gramática de búsqueda aceptada.

```text
func run(value) {
  %metric = const begin
  call @trace(%metric)
  %address = field.addr %self, "inner"
  %component = memory.load %address
  %input = slot.load @value
  %answer = call %component.run(argument[0]=%input)
  slot.store @result, %answer
  %end = const finish
  call @trace(%end)
  %output = slot.load @result
  return %output
}
```

La búsqueda del decorador transparente relaciona %input con el parámetro de
entrada y %output con el resultado de la llamada. Necesita alcanzar la definición
de @result a través del intervalo y distinguir modificación de binding de
mutación del objeto resultante. Puede permitir logging con argumentos primitivos
y mantener unknown si una función desconocida recibe un objeto relevante.

Un decorador que incrementa el resultado tiene un algoritmo válido distinto:

```text
%answer = call %component.run(%input)
%one = const 1
%decorated = binary +, %answer, %one
return %decorated
```

Esta transformación no necesita una segunda llamada. El motor debe reconocer
operadores, escrituras y regiones como comportamiento, además de contar calls.
Que exista un binary sin flujo al resultado tampoco basta: un cálculo muerto
puede ser ruido y no una responsabilidad observable.

Para una operación que debe registrar el final incluso al fallar, el contrato
requiere try/finally y salidas excepcionales. Colocar dos llamadas alrededor de
una delegación en orden textual no demuestra que la segunda ocurra si la primera
lanza una excepción.

## Variantes por lenguaje

Los siguientes esquemas establecen requisitos; la matriz nueva ejecuta sólo
Python, Java y TypeScript.

| Lenguaje | Implementación representativa | Diferencia relevante |
|---|---|---|
| Python | Clase wrapper o def que devuelve closure con *args/**kwargs | Captura, expansión y forwarding; @ puede tener otros significados |
| JavaScript | Función que devuelve (...args) => inner(...args) con comportamiento adicional | this binding, argumentos expandidos y Promise |
| TypeScript | Wrapper que implementa interfaz o higher-order function tipada | Contratos estructurales y tipos genéricos preservados |
| Java | Componente por interfaz o lambda que captura Action | Captura frente a campo y resolución de método de interfaz |
| C# | Wrapper, delegado, métodos async | Retornar Task o esperar su resultado no produce el mismo orden de efectos |
| C++ | Composición con interfaces virtuales o templates | Perfect forwarding, referencias, const y lifetime |
| Go | Struct por interfaz o función que retorna closure | Contexto/error en múltiples resultados y captura de variables |
| Rust | Wrapper genérico por trait o closure | Fn/FnMut/FnOnce, préstamos, consumo y adaptación de Result |

Un wrapper generador puede hacer yield de valores producidos por el componente,
transformarlos o agregar valores. La creación del generador no ejecuta ese cuerpo:
el contrato de orden debe situarse en cada reanudación/consumo. En async, una
llamada de cierre antes de await puede ocurrir antes de completar la operación;
para tracing de duración eso rompe el algoritmo aunque el orden de calls parezca
correcto. Threads y tareas requieren separar el envío del trabajo de su finalización.

## Pruebas y resultados

[test_algorithm_decorator.py](../../../../tests/structural/test_algorithm_decorator.py)
parsea fuentes y ejecuta gof.decorator. No ejecuta ni compila los ejemplos. Los
negativos de código inalcanzable describen fuentes que un compilador puede
rechazar; la prueba mide qué afirma Ken al inspeccionar su estructura.

| Casos nuevos | Estado | Qué verifican |
|---|---|---|
| 18 positivos | Pasan | Tracing con aritmética independiente antes/entre/después, con y sin renombrado |
| 12 negativos básicos | Pasan | Quitar decoración, quitar llamada al componente, cambiar receiver o slot |
| 3 traces inalcanzables | xfail estricto | Llamada extra léxica no prueba comportamiento adicional ejecutable |
| 3 transformaciones aritméticas | xfail estricto | Decoración válida omitida por requerir segunda llamada |
| 3 contratos transparentes rotos | xfail estricto | Falta contrato opcional de retorno del resultado, no criterio universal de Decorator |
| 3 wrappers funcionales | xfail estricto | Variante válida cuyo estado sigue siendo design en el catálogo |

La aritmética independiente de los positivos no realiza llamadas: eliminar trace
en el negativo no deja otra llamada que satisfaga accidentalmente el requisito
de extra. Los xfail conservan las aserciones deseadas y no se contabilizan como
cobertura satisfecha; XPASS demanda revisión.

Pruebas nuevas y regresiones Decorator de GoF: **42 passed, 12 xfailed,
264 deselected**, en 3.86 segundos:

```text
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_decorator.py tests/structural/test_gof_executable.py -k decorator
```

## Estado de la query y necesidades del IR

La regla object-wrapper comprueba contrato compartido, override, receiver de la
delegación, nombre de operación y una segunda llamada distinta en el método.
No prueba que la segunda llamada produzca efecto, se ejecute, suceda después de
la delegación ni use su resultado. Tampoco conoce todas las responsabilidades
que pueden implementarse sin una llamada adicional.

No se modificó el TOML en esta revisión. Restringir arbitrariamente la segunda
llamada a un lugar textual arreglaría unos ejemplos y eliminaría decoraciones
válidas: transformaciones de retorno, finally, callbacks o efectos en regiones
alternativas. El defecto requiere contratos de efectos y control, no otro nombre
de método ni una regla universal de return.

El núcleo ya representa llamadas, operadores, memoria, regiones y suspensión.
Para usarlo en esta búsqueda hacen falta reaching definitions, alcanzabilidad,
resultados/efectos de regiones y resúmenes de llamadas que distingan el origen de
la evidencia. Named operations para delegate, around, transform_result y finally
podrían componer variantes sin convertir cada patrón en una excepción del IR.
Estas son operaciones propuestas de búsqueda, no APIs ya publicadas.

Proxy y Decorator pueden compartir la misma colaboración y responsabilidades.
Detectar tracing no excluye un control de acceso, y detectar una condición no
excluye decoración. La salida debe conservar evidencia y declarar el contrato
reconocido, en lugar de fingir categorías de intención mutuamente excluyentes.
