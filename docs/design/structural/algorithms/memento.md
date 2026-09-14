# Memento: del algoritmo en palabras al IR

El [catálogo ejecutable](../../../../src/ken/structural/patterns/memento.toml)
combina `snapshot-object` y `accessor-snapshot`. Esta revisión estudia el recorrido
completo: qué se captura, dónde queda representado y de dónde proviene el estado
restaurado. Tener un objeto llamado Snapshot no prueba ese recorrido.

## Algoritmo en palabras

1. Elegir el estado del originador que pertenece a este contrato de restauración.
   Puede ser texto y cursor sin incluir métricas, conexiones ni todo el objeto.
2. Obtener una representación de ese estado en el momento de guardar.
3. Transferir esa representación a un memento y devolverlo o conservarlo mediante
   un caretaker, sin permitir que cambios posteriores destruyan la historia que
   el contrato promete preservar.
4. Más tarde, recibir el memento elegido y leer su representación guardada.
5. Restablecer el estado seleccionado a partir de esa representación. Al terminar
   la restauración, el estado efectivo debe corresponder al memento.

Captura y restauración son métodos separados. No se presume que ocurren de manera
consecutiva. El caretaker puede guardar varios snapshots, descartar algunos y
restaurar uno anterior. Memento no exige por sí mismo una pila LIFO ni deshacer
exactamente la última operación.

## Identidades e invariantes

| Elemento | Contrato |
| --- | --- |
| Originador y campo seleccionado | Captura y restauración se refieren al mismo componente de estado |
| Valor capturado | Procede de la lectura del estado en save, no de una constante independiente |
| Entrada de constructor | Su posición debe corresponder al campo o representación guardada |
| Memento retornado | Es el que recibió el estado; crear uno y devolver otro no alcanza |
| Payload restaurado | Procede del campo/decodificación que representa el estado capturado |
| Estado final | Una escritura posterior no debe anular la restauración antes de salir |
| Historia | Se preserva durante las modificaciones que el contrato permite al originador |
| Procedencia del memento | Puede restringirse a una instancia, documento o versión compatibles |

La última restricción es un refinamiento: algunos mementos son transferibles entre
originadores equivalentes. No imponer identidad de instancia en todas las queries.
La encapsulación de un memento también es una propiedad distinta de su flujo de
estado; los fixtures con campos visibles prueban el flujo, no privacidad.

## IR objetivo: captura, retención y restauración

Notación de diseño; no es texto ejecutable por un parser IR ni sintaxis KenQL nueva:

```text
function save(%origin) {
  %source = field.addr %origin [field = state]
  %at_save = memory.load %source
  %saved = capture %at_save [policy = immutable_value]
  %snapshot = construct @Snapshot(%saved)
  return %snapshot
}

function Snapshot.init(%self, %input) {
  %destination = field.addr %self [field = saved]
  memory.store %destination, %input
}

function restore(%origin, %snapshot) {
  %saved_address = field.addr %snapshot [field = saved]
  %saved = memory.load %saved_address
  %destination = field.addr %origin [field = state]
  memory.store %destination, %saved
  return
}
```

El núcleo puede representar cargas, direcciones, stores, argumentos y retornos.
`capture` y su política son **requisitos propuestos**, no opcodes implementados.
No inventar una copia al bajar una llamada opaca `clone`, `copy`, `serialize` o un
constructor: hace falta conocer la semántica y los campos alcanzados.

Para el caretaker, un flujo propuesto complementario conecta el resultado de
save con la colección/slot donde se conserva, su recuperación y el argumento de
restore. Las queries actuales reconocen el par de métodos sin demostrar todo
ese uso temporal, aunque los fixtures nuevos incluyen un caller explícito.

## Copia, alias y estabilidad histórica

No se requiere copia profunda universal. Las políticas válidas dependen del tipo
seleccionado y de qué mutaciones se permiten:

| Representación | Por qué puede preservar historia | Qué falta probar |
| --- | --- | --- |
| Entero o valor escalar | Copiar su valor separa una asignación posterior al originador | Sobrecarga/coerción si aplica |
| Objeto verdaderamente inmutable | Compartir identidad no altera su contenido | Inmutabilidad efectiva, no sólo el binding |
| Estructura persistente / copy-on-write | Las versiones comparten partes estables | Las escrituras producen nuevas versiones |
| Copia superficial | Basta si las partes compartidas no se mutan o no pertenecen al snapshot | Campos transitivos afectados por el contrato |
| Copia profunda selectiva | Aísla el subgrafo relevante | Aliases/ciclos y semántica de identidad |
| Bytes serializados | Pueden separar el estado vivo de su representación histórica | Modelos de encoder/decoder, schema, pérdidas de información |
| Referencia a array mutable | Puede preservar historia sólo mientras no lo muten | Escrituras por todos los aliases durante el intervalo |

Congelar `%snapshot` como binding no basta: `origin.state[0] = 99` puede modificar
el array al que también apunta `snapshot.saved`, sin reasignar ningún binding.
El IR necesita distinguir identidad, contenido y alcance de la preservación.

La fila de bytes serializados pasó a `ready` como `memento#serialized-snapshot` en
IR 1.66, para los ocho lenguajes. Identifica el códec **por nombre de API** y prueba la
correspondencia sobre el **flujo**: el codificador recibe el estado y el decodificador lo
devuelve, por una de tres formas que hubo que medir —el valor fluye al slot, el
decodificador es el receptor de otra llamada cuyo valor fluye al slot (el `unwrap()` de
Rust), o el estado se pasa como argumento destino (el `&e.state` de Go)—. Lo que **no**
prueba es el schema ni las pérdidas de información: que el valor decodificado reconstruya
el estado de forma fiel y completa sigue fuera, y una cadena opaca sin modelo queda
parcial, como la tabla anticipaba.
En Rust, `Clone` de un `Arc<Mutex<T>>` comparte el estado mutable; no es equivalente
a clonar un `Vec<i32>`. En C++, copiar un contenedor de `shared_ptr` tampoco aísla
los pointees. Estas variantes no se han validado con los tests de este documento.

## Variantes por lenguaje

- **Python:** entero/string inmutable, dataclass/tuple, lista copiada o referencia.
  `copy.copy` y `deepcopy` son políticas distintas; atributos dinámicos pueden
  requerir efecto desconocido.
- **Java:** valores primitivos, records con componentes potencialmente mutables,
  DTOs y getters. Copiar la referencia de un array no copia sus elementos.
- **TypeScript:** números/strings, objetos `readonly` y arrays. `readonly` no
  demuestra inmutabilidad profunda de runtime ni invalida aliases externos.
- **C#/Go:** structs con campos de referencia y slices requieren distinguir copia
  del encabezado respecto del almacenamiento compartido.
- **Rust/C++:** movimiento, copia, préstamo y ownership cambian las obligaciones;
  no todos los snapshots tienen constructor nominal o método getter.
- **Serialización:** snapshot en texto/bytes tiene una variante `design` en el
  catálogo. Aún no hay una prueba genérica de round trip para codecs arbitrarios.

La nueva validación usa Python, Java y TypeScript; las otras variantes describen
requisitos, no cobertura demostrada.

## Ruido permitido, negativos y resultados

[`test_algorithm_memento.py`](../../../../tests/structural/test_algorithm_memento.py)
analiza ejemplos completos sin ejecutar su código. Los ejemplos escalares
incluyen save → edit → restore en un caller. El ruido suma aritmética local y
logging de ese número, sin pasar estado, originador ni snapshot al logger.

Tras corregir la query con hechos ya existentes: **27 passed, 3 xfailed** en tres
lenguajes (antes: 18 passed, 12 xfailed):

- 6 positivos directos, con/sin ruido.
- 3 positivos de snapshots con getter y logging intercalado entre construcción
  y retorno.
- 9 negativos rechazados: save recibe otra constante, restore escribe otro campo
  del originador o restore no lee el memento.
- 9 negativos adicionales ahora rechazados: el constructor descarta su entrada,
  restore lee otro campo del snapshot o una escritura posterior anula el estado
  restaurado. Antes de la corrección producían matches y estaban como xfail;
  ahora son regresiones normales.
- 3 gaps del contrato de historia aislada: guardar la misma referencia de array,
  editar un elemento y restaurarla no recupera su contenido anterior.

Los últimos 3 casos son `xfail(strict=True)`, con la expectativa deseada de
rechazo. **No son true negatives.** Los casos de array se refieren al historial
prometido por ese fixture, no a una prohibición de compartir objetos en Memento.

```sh
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_memento.py
```

## Corrección acotada y límites pendientes

La query anterior `snapshot-object` conectaba una lectura del estado con un
argumento de construcción, pero no demostraba que alimentase el miembro leído
por restore. `WRITES`/`ASSIGNED_FROM` tampoco probaban la última escritura.
La alternativa `accessor-snapshot` ya utilizaba hechos más específicos.

La query directa ahora reutiliza `CONSTRUCTOR_TARGET` y un `CALL_BINDING` directo
para correlacionar estado, parámetro y constructor; exige `FINAL_FIELD_INPUT` en
la inicialización del snapshot y `FINAL_FIELD_VALUE` en la restauración. Vincula
el campo guardado con el nombre del miembro leído sobre el parámetro nominal del
snapshot. Los nueve negativos directos pasan tras ese cambio, sin cambiar el
motor ni imponer copias profundas.

Esto sigue siendo un modelo lineal: resolución dinámica de miembros, efectos
ocultos y reasignación del parámetro de restore no están demostrados. El nombre
del miembro y su tipo nominal son evidencia de esta variante, no una prueba de
dispatch completo. Los snapshots sin constructor explícito o con inicialización
fuera del modelo necesitan otra variante; el endurecimiento puede reducir matches
que antes carecían de evidencia suficiente. No se midió ese impacto en repos
externos en este ejercicio.

Para mejorar el IR y el buscador:

1. Usar un flujo común de captura → representación → restauración para campos
   directos y accessors, conservando sus distintas pruebas de resolución.
2. Exigir procedencia del valor **final** restaurado, con intervalos de
   preservación y control explícito; no basta con que hubo alguna escritura.
3. Añadir contratos opcionales de historia estable, con regiones de memoria,
   aliases y resúmenes de copia/mutación. Sin evidencia suficiente, devolver
   desconocido para esa propiedad.
4. Mantener por separado contratos de privacidad, propietario/versionado y
   caretaker. No hacerlos requisitos universales de una única forma sintáctica.
