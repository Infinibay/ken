# Observer: registro, selección y entrega

Revisión por algoritmo, 13 de septiembre de 2026. Complementa el
[contrato de los 23 GoF](../gof-algorithm-contracts.md#19-observer) y el
[diseño previo de Observer](../patterns/observer.md). El detector ejecutable está
en [observer.toml](../../../../src/ken/structural/patterns/observer.toml).

## Algoritmo en palabras

Una entidad mantiene un registro de receptores. Una operación recibe un receptor
y lo incorpora al registro pertinente. Otra operación recibe una notificación,
selecciona los receptores que correspondan y llama a cada receptor seleccionado.
La operación de retirada, si existe, quita del registro al receptor o a su token;
no equivale necesariamente a destruir el objeto receptor.

En una variante push, el argumento que recibe cada callback procede del evento
entrante, directamente o mediante una transformación declarada. En una variante
pull, la llamada anuncia un cambio y el observador consulta el estado del sujeto:
no exigir un argumento de evento a todas las variantes.

Para tolerar que un callback cancele una suscripción durante la notificación, una
implementación puede copiar primero el registro y recorrer esa copia. Hay dos
identidades distintas: la colección copiada es nueva, pero los receptores que
contiene son los mismos. Vaciar el registro original después de copiarlo no
elimina por sí solo los receptores del snapshot. La política de entrega determina
si esos receptores deben recibir todavía el evento.

## Roles e invariantes verificables

| Rol o requisito | Evidencia necesaria |
|---|---|
| Sujeto y registro | Dirección de campo ligada a una instancia; dos campos llamados listeners no son el mismo registro |
| Alta | El receptor suministrado, o un wrapper/token con procedencia explícita, se inserta en ese registro |
| Selección | Recorrido del registro, sus valores/claves pertinentes o snapshot de sus elementos |
| Receptor invocado | El elemento seleccionado alcanza el receptor/callee de la invocación sin ser reemplazado |
| Evento push | El evento o transformación aprobada alcanza la posición pertinente del argumento |
| Baja | Identidad de registro y token/receptor relacionada con el alta, si la variante la exige |
| Ejecución | La invocación está en un camino alcanzable dentro del recorrido, no en una función anidada que nunca se consume |
| Snapshot | Copia del contenedor con procedencia de elementos; separar esto de copia profunda de receptores |

No se infieren entrega exactamente una vez, orden global, ausencia de excepciones,
ausencia de concurrencia ni ejecución efectiva de callbacks por encontrar una
firma. La selección vacía también es una ejecución válida de Observer.

## Traducción al IR objetivo

El siguiente pseudocódigo describe el contrato deseado. `collection.*`,
`element.origin` y las restricciones de búsqueda no son una gramática ejecutable
ya implementada. Las cargas, direcciones y llamadas corresponden al vocabulario
del núcleo; los contratos de colecciones necesitan modelos adicionales.

```text
func subscribe(subject, listener) {
  %registry_addr = field.addr %subject, "listeners"
  %registry = memory.load %registry_addr
  collection.insert %registry, %listener
}

func notify(subject, event) {
  %registry_addr = field.addr %subject, "listeners"
  %registry = memory.load %registry_addr
  %snapshot = collection.copy %registry [container=fresh, elements=shared]
  iterate %element in %snapshot [items=values, evaluation=once] {
    call %element.update(argument[0]=%event)
  }
}
```

Una búsqueda del contrato push enlazaría la inserción con la colección origen,
la procedencia de cada elemento con el receptor de la llamada y el evento con su
argumento. Tendría que definir si admite entrega condicional y qué transformación
del evento acepta. El contrato pull reutilizaría el registro y recorrido pero
expondría otra operación de consulta del sujeto. Esto evita una query monolítica
que confunda variantes legítimas con bugs.

En una variante con mapa, `items=keys` y `items=values` son alternativas diferentes.
En un registro filtrado por topic debe preservarse la relación entre topic del
alta y topic del publish; que ambas operaciones tengan una cadena no alcanza.
En una implementación asíncrona, encolar un mensaje es evidencia de envío, no
prueba de que el callback haya terminado.

## Variantes por lenguaje y límites

Estos son esquemas para diseñar fixtures; sólo la matriz indicada más abajo se
ejecutó durante esta revisión. No representan certificación de todas las APIs.

| Lenguaje | Forma de implementación | Requisito específico del IR |
|---|---|---|
| Python | append(listener); for item in list(listeners): item.update(event) | Modelo builtin no ocultado de list; alias del receptor frente a copia del contenedor |
| JavaScript | push(listener); for (const item of Array.from(listeners)) item.update(event) | for-of entrega valores; Array.from con mapper puede cambiar identidad de elementos |
| TypeScript | Callbacks tipados o interfaz con update(event) | Igual procedencia que JS; anotación de tipo no demuestra entrega ni pureza |
| Java | List<Listener>, add y for-each sobre copia del registro | Interfaces/callbacks y colección copiada; no equiparar stream.map con copia de identidad |
| C# | event Action<Event>, +=, -= y Changed?.Invoke(event) | Modelo de evento multicast y selección condicional; += no es suma numérica aquí |
| C++ | Vector de callbacks; copia del vector antes de invocar | Copiar std::function, capturas y receptor retenido no equivale a copiar el objeto observado |
| Go | Map de listener a token o slice de funciones | Distinguir recorrido de claves/valores y send en canal frente a llamada directa |
| Rust | Vec de callbacks/objetos trait, préstamos o canales | Ownership del registro y receiver; compartir Arc no demuestra aislamiento de estado |

Un generador puede producir receptores de manera perezosa. Crear ese generador
no ejecuta sus llamadas: el IR debe relacionar producción, consumo y suspensión.
Un stream infinito o una selección que hace yield tampoco es un snapshot estable.

## Ruido permitido y contraejemplos

El patrón debe sobrevivir a nombres diferentes, cálculo sobre literales y logging
que no recibe el registro, el evento mutable ni los receptores. Esto es una
propiedad de las fixtures concretas: una función llamada trace no recibe una
garantía universal de pureza por su nombre. En análisis estricto, sus efectos
desconocidos conservan ese estado hasta que se justifique un modelo.

Los negativos de procedencia alteran una sola relación: copiar otro registro,
invocar un objeto fijo en lugar del elemento, reemplazar el snapshot antes del
recorrido o reasignar el elemento antes de usarlo. Logging permanece presente para
evitar que el detector lo use como criterio de aceptación/rechazo.

Dos requisitos más fuertes siguen abiertos: rechazar una notificación después de
un return incondicional y comprobar el evento entregado en la variante push. El
segundo no es automáticamente un falso positivo del Observer amplio: notificar
sin payload puede ser un Observer pull legítimo. Es una falta de expresividad y
de validación para buscar específicamente el algoritmo push solicitado.

## Pruebas de esta revisión

[test_algorithm_observer.py](../../../../tests/structural/test_algorithm_observer.py)
parsea fuentes Python, JavaScript y TypeScript y ejecuta la regla pública Observer
con sus variantes, no el detector legacy. No ejecuta las fuentes inspeccionadas.
JavaScript y TypeScript pertenecen a la misma familia; esta matriz no valida los
modelos de Java, C#, C++, Go o Rust.

```text
.venv/bin/python -m pytest -o addopts='' -q tests/structural/test_algorithm_observer.py
30 passed, 6 xfailed in 2.58s
```

| Casos | Resultado | Interpretación |
|---|---|---|
| 18 positivos | Pasan | Tres ubicaciones de ruido, con/sin renombrado, en tres lenguajes |
| 12 negativos de procedencia | Pasan | Cuatro roturas del flujo en tres lenguajes |
| 3 negativos de evento push | xfail estricto | La query no correlaciona el argumento recibido con el entregado |
| 3 negativos de código inalcanzable | xfail estricto | La firma del grafo conserva una notificación detrás de return |

Los seis xfail conservan la aserción deseada y fallarán por XPASS si se corrige el
motor, para exigir revisión explícita. No se cuentan como cobertura satisfecha ni
como resultados de precisión de repositorios reales.

## Cambios necesarios en el lenguaje y el motor

1. Consumir desde la búsqueda la iteración con origen y modo de selección,
   evaluación del iterable y región repetida. El núcleo ya incorpora iterate,
   iteration.value y el slot.store del elemento; falta derivar desde allí la
   procedencia requerida por el contrato de entrega.
2. Contratos de insert/remove/copy y resolución de las APIs que los justifican.
   El nombre de un método no constituye prueba suficiente para un tipo arbitrario.
3. Reaching definitions de elemento y evento, y restricciones separadas sobre
   binding, colección y estado de receptor. Preservar todo el registro durante la
   notificación prohibiría cancelaciones válidas.
4. Alcanzabilidad de la invocación a través de salidas abruptas, excepciones y
   regiones diferidas. Una arista lexical HAS_CALL no acredita ejecución.
5. Named operations subscribe, notify.push, notify.pull y unsubscribe con roles
   estables que otras queries puedan consumir, sin exigir todas a cada variante.

El grafo actual ya contiene parte de la procedencia de snapshots y las queries
la aprovechan. Exportar el cuerpo a instrucciones no migra automáticamente esos
contratos ni convierte las seis limitaciones en propiedades verificadas.
