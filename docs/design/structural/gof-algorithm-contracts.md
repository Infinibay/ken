# Los 23 GoF: del comportamiento al núcleo de instrucciones

Revisión de septiembre de 2026. Complementa los [archivos por patrón](gof.md)
y el [método](algorithms-to-ir.md). El contrato de cada variante antecede a la
elección de instrucciones. Estos fragmentos son pseudocódigo objetivo, no KenQL
ejecutable. `load object.field` abrevia field.addr + memory.load; `store` sobre
un campo usa memory.store. `call` conserva receptor, destino y argumentos.
`choose` evalúa sólo el brazo seleccionado; `iterate` conserva una región
repetida y la procedencia del elemento. Las notaciones family, copy, capture,
dispatch, once, intern y lock son obligaciones de análisis, no opcodes actuales.

Para todos los patrones, «trabajo independiente» significa trabajo cuyos efectos
no destruyen las propiedades seleccionadas. Logging puede lanzar, mutar por un
alias o ejecutar callbacks; su nombre no prueba pureza. Los controles negativos
que siguen rompen la variante descrita, no demuestran ausencia de cualquier otra
variante del mismo patrón. Una secuencia en palabras tampoco demuestra orden entre
métodos: éste necesita un escenario de uso con receptores correlacionados.

## 1. Abstract Factory

**Algoritmo.** Elegir una familia de productos. Usar el mismo proveedor para
solicitar productos de categorías diferentes; cada resultado debe pertenecer a
la familia elegida y cumplir el contrato de su categoría. La elección de familia
se hace fuera del consumidor, que usa esos contratos.

```text
%factory = load @selected_factory
%a = call %factory.create_a()
%b = call %factory.create_b()
call @consume(%a, %b)
```

**Invariantes.** Misma selección de familia, categorías distintas y compatibilidad
entre resultados. Dos métodos que construyen clases diferentes no bastan.
**Variantes.** Java/C#/C++ usan interfaces y overrides; Python/JS, objetos o pares
de closures capturando una familia; Go usa interfaces y funciones; Rust traits,
associated types y genéricos. Un registry exige resolver la selección por clave.
**Pruebas.** Insertar métricas entre creaciones; negativo: cambiar el proveedor
por otra familia entre llamadas. **IR pendiente:** contratos de familia y flujo
de selección/capturas; conservar call/construct no prueba compatibilidad.

## 2. Builder

**Algoritmo.** Recibir configuración en varios pasos, conservarla y usarla para
entregar un producto. En la variante mutable, los pasos modifican partes del
producto retenido. En otra variante, sólo se construye al finalizar.

```text
%product = load %builder.pending
store %product.part.value, %input
%finished = load %builder.pending
return %finished
```

**Invariantes.** Flujo desde la entrada a la parte configurada y desde esa
configuración al producto final; preservar la identidad pertinente entre pasos.
**Variantes.** Mutable en Java/Python/JS; builders inmutables devuelven sucesores;
Rust puede consumir self, usar typestate o clone derivado; Go acumula opciones.
**Pruebas.** Logging y cálculos independientes; negativos: sobrescribir la entrada,
entregar otro producto o mezclar dos instancias de builder. **IR pendiente:**
estados entre llamadas y ownership. La matriz ejecutable actual comprueba seis
lenguajes para producto almacenado; no todos los builders de esta sección.

## 3. Factory Method

**Algoritmo.** Un algoritmo solicita un producto a un punto de extensión. Una
implementación del punto decide el tipo concreto; el algoritmo usa el resultado
a través del contrato esperado, sin tomar esa decisión.

```text
%product = call %creator.make() [dispatch = extension-slot]
call %product.use()
```

**Invariantes.** La llamada pertenece al slot reemplazable y el valor usado
proviene de esa llamada. **Variantes.** Override Java/C#/C++; duck typing Python;
trait Rust, interfaz Go. Callback constructor JS/TS es variante funcional y
no prueba el GoF basado en herencia. **Pruebas.** Insertar validación que conserva
el producto; negativo: descartar el retorno y construir un tipo fijo.
**IR pendiente:** resolver el conjunto de destinos y correlacionar contratos;
un nombre make o un opcode construct aislado no alcanza.

## 4. Prototype

**Algoritmo.** Recibir un objeto existente, derivar otro según una política de
copia y devolverlo. El estado seleccionado del nuevo objeto procede del original;
los campos que deban ser independientes no quedan compartidos accidentalmente.

```text
%state = load %original.state
%copied = copy %state [policy = selected-fields]
%result = construct @Product(%copied)
return %result
```

**Invariantes.** Origen del estado, nueva identidad cuando se exige y política de
sharing explícita. **Variantes.** Constructores de copia C++, Clone Rust,
Object.assign/spread JS, copy Python y MemberwiseClone C# tienen contratos distintos.
**Pruebas.** Métricas entre copia y retorno; negativos: devolver el original o
rellenar estado constante. **IR pendiente:** modelos de copia y aliases; el token
clone no acredita copia profunda. Copiar un valor puede compartir sus referencias.

## 5. Singleton

**Algoritmo.** En un ámbito definido, obtener la instancia compartida. Si todavía
no existe, crearla y publicarla una vez; devolver la instancia publicada.

```text
%current = load @shared
if is_absent(%current) { store @shared, construct @Service() }
return load @shared
```

**Invariantes.** Misma ubicación leída/escrita/devuelta, polaridad de ausencia y
restricciones de creación. **Variantes.** Eager en módulo Python/JS, static Java,
Lazy C#, static local C++, sync.Once Go, OnceLock Rust. Lazy concurrente necesita
semántica de publicación/once; el if por sí solo tiene carreras.
**Pruebas.** Métricas sin reset del slot; negativos: construcción en hit o devolver
otra instancia. **IR pendiente:** ámbito runtime, exclusión y orden de memoria;
las queries actuales no prueban unicidad global ni seguridad concurrente.

## 6. Adapter

**Algoritmo.** Recibir una solicitud bajo un contrato, transformar sus argumentos
a la representación requerida por otro servicio, invocarlo y transformar su
resultado al contrato ofrecido.

```text
%input = call @convert_input(%request)
%raw = call %adaptee.perform(%input)
%result = call @convert_output(%raw)
return %result
```

**Invariantes.** Flujo desde entrada a servicio y desde resultado a salida; los
contratos son distintos pero compatibles mediante la conversión.
**Variantes.** Composición universal, herencia múltiple C++, closure Python/JS,
newtype Rust, función adaptada a interfaz Go. Async/sync necesita un contrato de
suspensión explícito. **Pruebas.** Logging sobre datos independientes; negativo:
ignorar raw y devolver un valor ajeno. **IR pendiente:** modelos de conversión y
contratos; un wrapper con delegación sólo es un candidato.

## 7. Bridge

**Algoritmo.** Mantener una abstracción y una implementación elegible por separado.
Una operación de la abstracción lee la implementación retenida y usa sus primitivas
para realizar el trabajo; una abstracción refinada reutiliza esa colaboración.

```text
%implementation = load %abstraction.backend
%part = call %implementation.primitive(%input)
return call @compose(%part)
```

**Invariantes.** Backend retenido, slot de contrato y ejes de variación separados.
**Variantes.** Dos jerarquías nominales Java/C++; traits Rust, interfaz Go,
protocolos Python/TS. La inyección de una función sola no prueba dos ejes Bridge.
**Pruebas.** Cálculo local en la abstracción; negativo: invocar siempre un backend
global ignorando el retenido. **IR pendiente:** relacionar evidencia nominal con
la procedencia del receptor y límites del mundo abierto.

## 8. Composite

**Algoritmo.** Ofrecer una operación común a hojas y contenedores. Un contenedor
recorre sus componentes y aplica a cada uno esa operación, combinando resultados
si el contrato lo exige. Los hijos pueden ser otros contenedores.

```text
%children = load %node.children
iterate %child in %children {
  %value = call %child.operation(%context)
  call %accumulator.include(%value)
}
```

**Invariantes.** Elementos procedentes de children, mismo contrato recursivo,
propagación del contexto y combinación pertinente. **Variantes.** Listas de
interfaces Java/C#, pointers C++, trait objects Rust o enums recursivos; slices
Go y colecciones dinámicas Python/JS. **Pruebas.** Logging por hijo; negativos:
invocar un objeto fijo o ignorar resultados si se exige agregarlos.
**IR pendiente:** recursion/call graph, procedencia de elementos y reducción;
iterate por sí solo no demuestra árbol acíclico ni terminación.

## 9. Decorator

**Algoritmo.** Conservar un componente compatible con el contrato propio. Al
recibir una operación, agregar comportamiento antes/después o alrededor de la
delegación, manteniendo las obligaciones seleccionadas de entrada y salida.

```text
call @before(%input)
%inner = load %wrapper.inner
%result = call %inner.operation(%input)
call @after(%result)
return %result
```

**Invariantes.** Contrato compatible y receptor delegado retenido; forwarding o
retorno idéntico sólo si la variante lo exige. **Variantes.** Clases nominales,
decoradores Python, closures JS/Go, wrappers Rust; async y finally alteran el
contrato de salida. **Pruebas.** Añadir trabajo independiente; negativo: ejecutar
before/after sin delegar. **IR pendiente:** efectos en salidas excepcionales y
correlación de capturas. No toda función decorada usa el GoF Decorator.

## 10. Facade

**Algoritmo.** Recibir una petición de alto nivel, coordinar pasos de varios
servicios internos y entregar una respuesta que resume la operación compuesta.
Los resultados intermedios pueden alimentar pasos posteriores.

```text
%prepared = call %first.prepare(%request)
%completed = call %second.execute(%prepared)
return call @summarize(%completed)
```

**Invariantes.** Servicios distintos, orden y flujo requeridos por la operación;
el cliente usa la frontera pública. **Variantes.** Clase Java/C#, módulo
Python/JS, paquete Go, API Rust; no exige almacenar ambos servicios como campos.
**Pruebas.** Logging entre pasos; negativos: pasar otra preparación o exponer sólo
dos llamadas sin la coordinación exigida. **IR pendiente:** frontera de API y
escenario de uso. La query HAS_FIELD/DELEGATES_TO actual es una firma más débil
y no demuestra este algoritmo ni la intención arquitectónica.

## 11. Flyweight

**Algoritmo.** Recibir una clave de estado intrínseco, buscar el objeto compartido
correspondiente y crearlo/publicarlo si falta. Reutilizarlo en solicitudes
equivalentes; suministrar el estado extrínseco en cada operación.

```text
%entry = call %pool.lookup(%key)
%result = choose present(%entry) {
  hit: output value(%entry)
  miss: %new = construct @Shared(%key); call %pool.put(%key, %new); output %new
}
return %result
```

**Invariantes.** Misma clave y pool; separación de estado compartido/extrínseco.
**Variantes.** Map/dict, intern pool, weak references, Arc Rust, sync.Map Go.
Igualdad y hash de claves requieren modelos. **Pruebas.** Métricas de hit/miss;
negativos: guardar bajo otra clave o modificar estado intrínseco por cliente.
**IR pendiente:** semántica de ausencia, sharing, vida de weak refs y concurrencia.

## 12. Proxy

**Algoritmo.** Interceptar una operación compatible con el servicio real, decidir
si debe delegarse y realizar el acceso mediante el servicio retenido o adquirido
perezosamente. La variante de protección rechaza accesos no autorizados.

```text
if call %policy.allowed(%request) {
  return call %subject.operation(%request)
} else { throw @Denied }
```

**Invariantes.** Guardia controla la delegación; sujeto y argumentos pertinentes.
**Variantes.** Protección, virtual/lazy, remoto, caché; dynamic Proxy JS,
interceptores Java/C#, descriptors Python, smart pointers C++/Rust no son
intercambiables. **Pruebas.** Auditoría en cada brazo; negativo: llamada antes de
la autorización. **IR pendiente:** caminos, excepciones y efectos; un if cualquiera
cerca de una llamada no prueba control de acceso.

## 13. Chain of Responsibility

**Algoritmo.** Recibir una petición. Si este eslabón puede atenderla, producir el
resultado local; si no, pasarla al siguiente y propagar su resultado o ausencia.
La variante middleware puede ejecutar trabajo antes y después del siguiente.

```text
if call %self.accepts(%request) { return call %self.handle(%request) }
%next = load %self.next
return call %next.handle(%request)
```

**Invariantes.** Petición correlacionada, decisión y eslabón siguiente; los caminos
de la variante exclusiva no ejecutan ambos handlers. **Variantes.** Objetos,
closures next Python/JS/Go, Result/Option Rust; distinguir broadcast.
**Pruebas.** Métricas de rechazo; negativos: pasar otra petición o llamar a todos
sin decisión. **IR pendiente:** resultados con ausencia, ciclos y continuación
capturada. Las variantes de pipeline no deben etiquetarse como manejo exclusivo.

## 14. Command

**Algoritmo.** Capturar receptor y datos de una acción en una unidad retenible.
Entregarla a un invocador que, quizá después, ejecuta la acción con esos datos.
Undo requiere además guardar y aplicar una compensación válida.

```text
store %command.receiver, %receiver
store %command.input, %input
%saved = load %command.input
call (load %command.receiver).act(%saved)
```

**Invariantes.** Procedencia de receptor/datos y transferencia al invocador;
captura por valor y referencia tienen comportamientos distintos si cambian.
**Variantes.** Clase Java/C++, closure Python/JS/Go, FnOnce Rust; colas async
añaden orden y ownership. **Pruebas.** Logging en el invocador; negativo: ejecutar
otro receptor o usar datos actuales cuando se requiere snapshot al capturar.
**IR pendiente:** closures, escapes y ejecución diferida. Retener callback no
prueba entrega exactamente una vez ni reversibilidad.

## 15. Interpreter

**Algoritmo.** Representar una expresión mediante nodos. Un terminal interpreta
su dato contra un contexto; un compuesto evalúa sus operandos y combina los
resultados según su operación. Puede evaluar perezosamente algunos operandos.

```text
%left = call %node.left.evaluate(%context)
%result = short_circuit %left [operator = and] {
  output call %node.right.evaluate(%context)
}
return %result
```

**Invariantes.** Contexto correlacionado, resultados consumidos y evaluación
condicional correcta. **Variantes.** Árbol de clases, enum/match Rust, closures
compiladas, visitor externo; cada uno cambia el dispatch. **Pruebas.** Contador
independiente; negativo: evaluar el brazo derecho incondicionalmente o descartar
el izquierdo. **IR pendiente:** semántica del lenguaje interpretado, no asumir que
un operador llamado and tiene la semántica del lenguaje anfitrión.

## 16. Iterator

**Algoritmo.** Mantener una posición o continuación. En cada avance producir el
siguiente elemento y conservar el estado necesario para continuar; al agotarse,
señalar fin conforme al protocolo. La posición debe progresar en la variante
finita y ordenada; un stream infinito requiere otro contrato.

```text
iterate %element in %source { yield %element }
return
```

**Invariantes.** Origen y orden de elementos, progreso, fin y estado entre
suspensiones. **Variantes.** yield Python/JS/C#, cursor Java/C++, Iterator Rust,
range-over-function Go; async requiere await y cancelación. **Pruebas.** Logging
entre yields; negativos: repetir siempre un elemento o avanzar sin entregarlo.
**IR pendiente:** resume/cleanup y protocolo de fin. Yield aislado también puede
pertenecer a context managers o corutinas, sin intención GoF Iterator.

## 17. Mediator

**Algoritmo.** Un participante informa un evento al coordinador. El coordinador
decide qué colaboradores deben reaccionar, transforma datos si corresponde y
envía las órdenes relacionadas. Los participantes no necesitan conocerse entre sí.

```text
call %mediator.changed(%sender, %event)
if selected(%event) { call %other.react(%event) }
```

**Invariantes.** Evento/sender provienen de un participante y gobiernan la
coordinación. **Variantes.** Objetos, event bus, actores o channels Go/Rust;
un bus indiscriminado puede ser Observer, no mediación específica.
**Pruebas.** Métricas de eventos; negativo: ignorar el evento y actuar siempre
sobre un servicio no relacionado. **IR pendiente:** límites de participantes,
comunicación async y correlación interprocedural. Ausencia de aristas encontradas
no demuestra ausencia de comunicación directa entre colegas.

## 18. Memento

**Algoritmo.** Guardar el estado seleccionado en un snapshot que preserve su
historia mientras el origen cambia. Más tarde, restaurar desde ese snapshot.

```text
%saved = copy (load %origin.state) [policy = historical-state]
%snapshot = construct @Snapshot(%saved)
store %origin.state, load %snapshot.state
```

**Invariantes.** Mismos componentes guardados/restaurados, procedencia del
snapshot y aislamiento suficiente. **Variantes.** Copias de campos, immutable
values, estructuras persistentes Rust/C++, serialización Python/JS/Java/C#;
compartir inmutables puede ser correcto. **Pruebas.** Logging y cambio de campos
fuera del snapshot; negativo: compartir una lista mutable que destruye la historia.
**IR pendiente:** política de copia, acceso y heap temporal; asignación no acredita
snapshot. La secuencia mostrada resume dos métodos, no afirma llamada consecutiva.

## 19. Observer

**Algoritmo.** Registrar un suscriptor. Al recibir un evento, recorrer los
suscriptores pertinentes y entregarles el evento; otra operación puede retirarlos.
Si se recorre un snapshot, sus elementos provienen del registro original.

```text
call %registry.insert(%listener)
%listeners = call %registry.snapshot()
iterate %listener in %listeners { call %listener.update(%event) }
```

**Invariantes.** Registro y selección relacionados, mismo evento cuando se exige,
identidad de elementos distinta de identidad de la colección. **Variantes.**
Callbacks Python/JS, eventos C#, interfaces Java, tokens/mapas Go, channels Rust.
**Pruebas.** Logging por evento; negativos: recorrer otra colección o notificar
siempre un objeto fijo. **IR pendiente:** insert/remove/copy modelados, reentrancia
y política de cambios durante recorrido. No prohibir cancelación legítima en callback.

## 20. State

**Algoritmo.** Conservar el estado actual como valor que decide el comportamiento.
Delegar un evento a ese estado y, cuando una transición lo indique, reemplazarlo
por el siguiente. Los eventos posteriores deben consultar el estado actualizado.

```text
%current = load %context.state
%next = call %current.handle(%event)
store %context.state, %next
```

**Invariantes.** Slot de dispatch y transición correlacionados y orden entre
eventos. **Variantes.** Estado modifica contexto, contexto almacena resultado,
enum/match Rust/Go, tablas o funciones Python/JS. **Pruebas.** Métricas de transición;
negativo: guardar next en otro campo o seguir usando current indefinidamente.
**IR pendiente:** estados entre llamadas y condiciones de transición; una
dependencia intercambiable sin transición puede ser Strategy, no State.

## 21. Strategy

**Algoritmo.** Recibir o seleccionar una política, conservarla y usarla para
realizar una operación sobre la entrada suministrada. El consumidor usa un contrato
común y no depende de los detalles del algoritmo elegido.

```text
store %context.policy, %supplied
%policy = load %context.policy
return call %policy.run(%input)
```

**Invariantes.** Valor seleccionado llega al receptor/callee y no fue sustituido
por una política fija. **Variantes.** Interfaces, función Python/JS/Go, closures
Rust, plantilla C++ con selección en compilación. **Pruebas.** Logging antes de
dispatch; negativo: ignorar supplied y crear siempre la misma política.
**IR pendiente:** defaults, rebindings, capturas y selección estática. Un callback
aislado no establece que existan alternativas del mismo contrato.

## 22. Template Method

**Algoritmo.** Definir un esqueleto de pasos y delegar algunas decisiones a puntos
de extensión. Las implementaciones concretas cambian esos pasos mientras el
esqueleto mantiene el orden y las dependencias seleccionadas.

```text
%prepared = call %self.prepare() [dispatch = extension-slot]
%result = call %self.process(%prepared) [dispatch = extension-slot]
call %self.finish(%result)
return %result
```

**Invariantes.** Slots reemplazables del receptor correcto, orden y flujo entre
pasos. **Variantes.** Métodos virtuales Java/C#/C++, hooks Python/TS, default
trait methods Rust; pipeline de callbacks es variante funcional diferente.
**Pruebas.** Logging entre hooks; negativos: llamar otro receptor o invertir
pasos cuya dependencia lo prohíbe. **IR pendiente:** targets virtuales y caminos;
la consulta actual de slot virtual es más débil que este algoritmo completo.

## 23. Visitor

**Algoritmo.** Un elemento recibe un visitante y le entrega su propia identidad
mediante la operación correspondiente a su tipo. El visitante contiene el
comportamiento; al recorrer elementos, se elige la operación apropiada para cada uno.

```text
%result = call %visitor.visit_element(%self) [dispatch = element-contract]
return %result
```

**Invariantes.** Visitor recibido es el invocado; self llega al argumento del
slot correspondiente y el resultado se transmite si lo exige el contrato.
**Variantes.** Overload Java/C#/C++, nombres distintos Python/Go/JS, traits y
associated output Rust. Enum/match exhaustivo sin visitante separado no prueba
Visitor clásico. **Pruebas.** Logging previo; negativos: pasar otro elemento o
invocar un callback genérico que no discrimina el tipo. **IR pendiente:** resolución
de overload, contratos de familia y dispatch; call con self sólo es una forma débil.

## Cambios del núcleo derivados de este ejercicio

1. **Evaluación perezosa:** choose y short_circuit con resultados regionales.
   Necesarios para expresar variantes de Flyweight, Singleton, Proxy, Chain e
   Interpreter sin ejecutar incondicionalmente ramas que podrían mutar estado.
2. **Iteración:** iterable evaluado una vez, elemento por iteración, cuerpo
   repetido y salida por agotamiento. Útil para Composite, Observer e Iterator.
   No convertir for-in JS (claves) en for-of (valores), ni for-await en recorrido sync.
3. **elif:** condiciones posteriores dentro del brazo de rechazo anterior.
   Evita convertir una selección State/Proxy en varias condiciones independientes.
4. **Verificación:** aridad de regiones/resultados y procedencia del elemento;
   impedir que un temporal local de una rama escape sin resultado de choose.

Estas extensiones no resuelven los pendientes semánticos de las 23 secciones.
El siguiente límite común es flujo de valores/memoria entre instrucciones y
métodos, seguido por contratos de llamadas, copias, colecciones y concurrencia.
La revisión establece requisitos para todos; no certifica detección completa.

### Contrato de bucles antes de ampliarlos

El núcleo debe distinguir while (test → body), do/while (body → test) y for
clásico (init una vez; test → body → update repetidos). continue va al test en
while/do y a update en for; break sale sin ejecutar update. Un test omitido en
for tiene resultado true implícito, con procedencia sintética explícita. No se
inventan condiciones ni updates omitidos. Las expresiones de un update aún pueden
ser native si falta su modelo. Esta estructura es necesaria para cursores Iterator,
recorridos Composite y algoritmos con intentos o estados, independientemente de
sus nombres. Etiquetas, goto, excepciones y limpieza al salir siguen requiriendo
modelos adicionales; el orden regional no acredita alcanzabilidad runtime.
