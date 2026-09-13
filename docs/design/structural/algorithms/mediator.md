# Mediator: origen, decisión y participantes coordinados

Revisión por algoritmo, 13 de septiembre de 2026. Complementa el
[diseño de Mediator](../patterns/mediator.md) y su
[regla ejecutable](../../../../src/ken/structural/patterns/mediator.toml).

## Algoritmo en palabras

Un participante informa al coordinador de un cambio o evento. El coordinador
interpreta el origen, los datos y su propio estado para seleccionar acciones
sobre los participantes pertinentes. La lógica que relaciona esas acciones vive
en el coordinador, reduciendo la necesidad de que los participantes conozcan
las reglas de colaboración entre sí.

En el ejemplo ensayado, dos participantes pueden llamar a coordinate con un tag;
el coordinador selecciona un destino según ese tag y le entrega el dato de la
notificación. La operación puede también consultar el estado de un participante,
transformarlo y activar a otro. Preservar el dato sin transformarlo es un
contrato particular, no una obligación universal de Mediator.

Los participantes pueden ser instancias de clases distintas o varias instancias
de una misma clase. Su identidad en la colaboración no se reduce al nombre del
tipo. Una lista de nodos homogéneos puede estar coordinada por un mediador válido.

Observer describe suscripción y notificación a receptores seleccionados. Mediator
añade reglas de colaboración entre participantes. Un mediador puede usar Observer
como mecanismo de transporte; esas categorías no son excluyentes. Una llamada
de broadcast no prueba por sí sola las reglas de coordinación.

## Roles e invariantes

| Requisito | Evidencia pertinente |
|---|---|
| Origen | Participante o mensaje que suministra la notificación |
| Evento/datos | Valores recibidos que alcanzan la decisión o acciones cuando el contrato lo exige |
| Coordinador | Operación que decide la colaboración y recibe las notificaciones |
| Destinos | Instancias/roles de participantes ligados a acciones concretas |
| Relación de colaboración | Correspondencia entre participantes que notifican y participantes coordinados |
| Selección | Condición o protocolo que gobierna las llamadas salientes pertinentes |
| Ejecución | Caminos alcanzables, incluidos errores, retornos y acciones diferidas |

Dos métodos CALLS del mismo tipo no prueban que invoquen la misma instancia del
coordinador. Dos campos de tipos distintos no prueban que sus objetos sean los
participantes reales que originaron los eventos. Un contrato exacto necesita
alias/identidad y flujo interprocedural, además del grafo de tipos y llamadas.

## Traducción al IR objetivo

El siguiente pseudocódigo representa una coordinación por tag. No introduce una
gramática KenQL nueva. Los roles origin/first/second requieren enlaces entre
instancias que el ejemplo deja explícitos como obligaciones.

```text
func notify(origin, coordinator, tag) {
  call %coordinator.coordinate(argument[0]=%origin, argument[1]=%tag)
}

func coordinate(origin, tag) {
  %tag_value = slot.load @tag
  %one = const 1
  %select_first = compare ==, %tag_value, %one
  if %select_first {
    then {
      %target = memory.load (field.addr %self, "first")
      call %target.apply(argument[0]=%tag_value)
    }
    else {
      %target = memory.load (field.addr %self, "second")
      call %target.apply(argument[0]=%tag_value)
    }
  }
}
```

Una query precisa enlazaría la ocurrencia de notificación, el parámetro recibido,
el valor que controla el branch y la llamada al destino seleccionado. Para una
regla `origin == first implica actuar sobre second`, el lenguaje debe expresar
identidades y relaciones entre regiones, no sólo que hay dos llamadas en el método.

El núcleo conserva parámetros, compare, if/choose, llamadas y campos. Usar esos
operandos en búsquedas exige reaching definitions, dependencia de control y
correlación entre llamadas y argumentos; su representación no acredita por sí
sola que el evento gobierne la acción.

Una búsqueda que requiera ausencia de comunicación directa entre colegas debe
definir el alcance cerrado y devolver unknown ante destinos no resueltos. No
encontrar una arista en el índice no demuestra que los participantes nunca se
comuniquen mediante callback, red, reflexión o un contenedor compartido.

## Variantes por lenguaje

La matriz nueva cubre referencias directas en Python, Java y TypeScript. Las
otras formas son requisitos de diseño, no soporte certificado por esos tests.

| Lenguaje | Implementación representativa | Requisito del IR |
|---|---|---|
| Python | Objetos con callback al coordinador | Tipos parciales, closures y selección por estado/evento |
| JavaScript | Callbacks o bus con coordinador que enruta mensajes | Identidad de topic, registro y consumo del callback |
| TypeScript | Interfaces de widgets y hub tipado | Identidad de instancias, unión de eventos y narrowing |
| Java | Objetos colega que notifican una interfaz mediator | Dispatch virtual, evento y receiver correctos |
| C# | Eventos/delegates o coordinador asíncrono | Suscripción y ejecución, await y cancelación |
| C++ | Interfaces/callbacks hacia coordinador | Lifetime y punteros, evitar inferir identidad por tipo |
| Go | Coordinador con channels y select | Origen/destino del mensaje, envío frente a recepción |
| Rust | Actor/message enum o callbacks sin ciclo de ownership | Ownership de mensajes, exhaustividad y selección de destino |

Un coordinador puede esperar varias respuestas antes de continuar. Las acciones
concurrentes y su reunión requieren estados y happens-before; el orden textual
de dos envíos no implica el de ejecución remota. Un generador que produce acciones
con yield tampoco las ejecuta hasta que otro componente las consume.

## Ruido, negativos y resultados

[test_algorithm_mediator.py](../../../../tests/structural/test_algorithm_mediator.py)
parsea fuentes y ejecuta gof.mediator. Los positivos agregan logging con datos
primitivos y aritmética local a la notificación y a la coordinación; no se toma
el nombre de una función como garantía de pureza. No se ejecutan ni compilan
las fuentes analizadas.

| Casos nuevos | Estado | Evidencia |
|---|---|---|
| 12 positivos | Pasan | Con/sin ruido y renombrado, tres lenguajes |
| 9 negativos de colaboración | Pasan | Quitar notificación de un colega, quitar destino o llamar otro receptor |
| 6 contrastes Observer/Facade | Pasan | Fixtures que carecen de colaboración bidireccional pertinente |
| 3 colegas del mismo tipo | xfail estricto | Dos instancias legítimas rechazadas por exigir tipos diferentes |
| 3 coordinaciones inalcanzables | xfail estricto | Calls después de return aún aportan evidencia léxica |
| 3 payloads descartados | xfail estricto | Falta contrato opcional de conservación del dato, no criterio universal de Mediator |

Los contrastes Observer/Facade no afirman exclusividad de patrones. Los negativos
inalcanzables pueden ser rechazados por compiladores; aquí prueban qué garantiza
el detector al inspeccionar su estructura. Los xfail no cuentan como cobertura
satisfecha y XPASS requiere revisión.

Pruebas propias **27 passed, 9 xfailed**. Con las regresiones GoF Mediator:
**39 passed, 9 xfailed, 264 deselected**, en 3.59 segundos:

```text
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_mediator.py tests/structural/test_gof_executable.py -k mediator
```

## Estado de la query y próximos requisitos

direct-colleagues usa DELEGATES_TYPE hacia dos tipos distintos y exige que métodos
de ambos llamen al método coordinador. Ya correlaciona ambos extremos por tipos,
lo que excluye muchas fachadas y broadcasts simples. No modela selección por
evento, identidad de instancias ni ejecución efectiva de las llamadas.

No se modificó el TOML. Quitar different entre tipos sin introducir roles de
instancia admitiría una sola relación repetida como si fueran varios colegas.
Exigir siempre el mismo payload eliminaría coordinaciones legítimas que lo
transforman. Los límites necesitan evidencia adicional, no sólo otra condición
nominal.

El IR y buscador deben permitir componer operaciones de notificación, selección
y actuación con roles estables. Para la variante de mensajes hacen falta modelos
de transporte/consumo y bindings de eventos; esa variante permanece design en el
catálogo. La salida debe indicar qué colaboración demuestra y qué intención o
garantía temporal sigue abierta.
