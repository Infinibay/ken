# Comandos almacenados y procesamiento de lotes de trabajo

Estado: implementado en IR 1.30.0. Ver la [auditoría](../../structural-validation/multilanguage/queued-command.md).

TaskScheduler (across-languages, TypeScript) recibe Command, lo añade a tasks,
itera esa colección y espera execute() antes de asignar una lista vacía a tasks.
Los comandos concretos implementan el contrato y conservan receiver y datos.
Las variantes actuales no unen ese ciclo de almacenamiento con los implementadores.

## Estructura compartida y queries

La operación pública `architecture.batch-work-queue.drain` expone colección,
registro, parámetro registrado, método consumidor, iteración, elemento, llamada de
activación y vaciado posterior. La regla moderna `architecture.batch-work-queue`
reutiliza esa operación. Command añade `queued-object`: además de ese uso,
exige una implementación concreta del contrato cuyo método sin parámetros
explícitos delegue en un receiver retenido. El nombre execute/run no será fijo.

La entrada insertada debe ser el parámetro original sin reasignaciones, la
iteración debe usar el mismo campo y la activación debe tener como receptor el
mismo elemento iterado sin reasignación. El registro y el consumidor deben ser
métodos distintos. La llamada de activación debe carecer de argumentos explícitos
y descartarse como sentencia, admitiendo await. Una lista de listeners persistente
sin vaciado no satisface esta variante. Un registro one-shot de callbacks puede
compartirla: no se afirma exclusividad de intención ni FIFO/exactly-once.

Para contratos nominales se vinculan el tipo del parámetro registrado, el método
del contrato y su implementación. En código dinámico se exige además una llamada
observada que pase una construcción/valor del tipo concreto al parámetro de registro.
Esa evidencia identifica una posibilidad estructural, no todos los objetos runtime.

## Nuevos hechos generales

- `EMPTY_COLLECTION`: nodo de colección → su categoría; únicamente literales vacíos
  sin elementos ni huecos (un array JavaScript `[,,]` tiene longitud distinta de cero),
  preservados por el frontend. No inferir que una función o constructor con nombre
  list/Array siempre devuelve un contenedor vacío.
- `CLEARS_COLLECTION`: asignación o llamada → almacenamiento. Admite reemplazo
  directo por literal vacío y APIs clear/Clear sin argumentos en Python/Java/C#.
  Es forma de API, no prueba de la identidad de una biblioteca ni de efectos reales.
- `AFTER_ITERATION`: evento de vaciado → iteración; ambos son statements hermanos
  en el mismo bloque y callable, el vaciado está después y no hay statement de
  retorno/throw/break/continue directo entre ambos. Es orden léxico normal, sin
  prometer que el bucle termina ni que excepciones/suspensión permiten llegar allí.
- `call(explicit_arguments: 0)`: cantidad de argumentos escritos, no aridad del
  callee. Un spread cuenta como argumento escrito, nunca como cero. No reemplaza
  los bindings correlacionados del IR.

No usar spans solos para vincular scopes diferentes, vaciados dentro de ramas,
callbacks o loops anidados. No promover automáticamente el clearing a garantía de
consumo: aliases de la colección anterior, retornos dentro del bucle, concurrencia,
nuevas inserciones y reentrancia necesitan modelos posteriores.

## Pruebas requeridas

Python, JavaScript, TypeScript, Java y C#: positivos síncronos/async donde corresponda,
renombrado, otra colección, otro elemento, activación con argumentos, ausencia de
registro/vaciado, vaciado anterior/en otra rama/otro método, retorno intermedio,
spreads, parámetro/elemento reasignado y construcción sin caller válido.
Comprobar relaciones públicas, serialización, queries guardadas y operación nombrada.
Repetir corpus y escaneos reales con los mismos archivos, sin ejecutar los programas.


## Implementaciones probadas

| Lenguaje | Registro | Activación | Reset |
|---|---|---|---|
| Python | append del parámetro | foreach, llamada directa o await | `tasks=[]` o `tasks.clear()` |
| JavaScript | push del parámetro | for-of, llamada directa o await; caller observado para tipo concreto | `tasks=[]` |
| TypeScript | push, campos explícitos o parámetros-propiedad del Command | contrato nominal, for-of, async/await | `tasks=[]` |
| Java | add del parámetro | enhanced-for y operación del contrato | `tasks.clear()` |
| C# | Add del parámetro | foreach y operación del contrato, también Task/await | `tasks.Clear()` |

Los fixtures propios se parsean y consultan, no se ejecutan ni compilan. El modelo
no transforma getters que devuelven listas, slices, snapshots, pop/shift/take o
canales en este recorrido directo. La ausencia de una coincidencia en esas formas
indica un límite de cobertura, no que el código no implemente Command o una cola.
