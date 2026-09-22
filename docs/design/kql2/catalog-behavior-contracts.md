# Contratos para reescribir el catálogo en KQL 2

15 de septiembre de 2026. Este documento fija el criterio de la nueva revisión;
no describe capacidades ya implementadas. El catálogo anterior no es el oráculo.
La migración debe escribirse a partir del comportamiento de cada concepto y de
fuentes positivas/negativas independientes. No se acepta traducir mecánicamente
`edge X` a una función con otro nombre.

Cada TOML debe mostrar los participantes con selectores anidados, la conducta
con BODY cuando corresponda, y las condiciones adicionales con predicados
públicos de semántica documentada. El compilador produce las relaciones internas.
Los helpers de biblioteca expresan conceptos reutilizables (origen de valor,
compatibilidad de contrato, intervalo sin efectos, asignabilidad), no esconden
un detector entero bajo un nombre.

## Criterios GoF

| Patrón | Obligación semántica | Variantes válidas | Contraejemplos esenciales |
| --- | --- | --- | --- |
| Abstract Factory | Un proveedor seleccionado produce categorías distintas de productos que pertenecen a una familia compatible. La creación consumida corresponde al proveedor elegido. | Clases, objetos literales, módulos y traits con productos asociados; constructores y funciones de creación. | Mezclar familias; dos métodos que crean objetos ajenos; un slot que descarta la construcción. Compatibilidad no declarada no se inventa por prefijos de nombres. |
| Builder | Pasos de configuración contribuyen al producto entregado al finalizar una construcción coherente. | Mutación de un producto retenido, acumulación de configuración seguida de creación, constructores persistentes/typestate, director opcional. | Finalizar otra instancia sin el estado configurado; reemplazar el producto; pasos cuyo efecto no llega al resultado. No exigir sintaxis fluida. |
| Factory Method | Una operación de creación delega en una implementación reemplazable que suministra el producto bajo un contrato. | Hook virtual/abstracto, trait/default y equivalente funcional inyectable. Una función de fábrica simple debe identificarse como tal. | Constructor arbitrario sin punto de variación; hook ignorado; producto creado por otro sitio mientras el hook sólo registra logs. |
| Prototype | Se produce un objeto nuevo a partir de un prototipo conservando el estado que define su contrato de copia. | Constructor de copia, protocolo de clonación, copia de campos, políticas superficiales o profundas explícitas. | Retornar el original; constructor que descarta el estado; retornar otra construcción. Independencia del heap es una política adicional, no requisito de toda copia superficial. |
| Singleton | Las obtenciones bajo un ámbito definido reutilizan la misma instancia inicializada una sola vez según el modelo de ejecución. | Eager, lazy con guarda correcta, once, módulo/namespace, registro por clave como variante con su ámbito. | Crear en cada acceso, publicar una instancia distinta, guarda con polaridad invertida, carrera no protegida si se afirma seguridad concurrente. |
| Adapter | Una interfaz requerida se implementa traduciendo operaciones hacia otra interfaz y conservando la correspondencia de entrada/salida necesaria. | Adaptación de objetos, herencia, conversión de formatos, instalación dinámica de métodos con claves acreditadas. | Delegación a un destino ajeno; conversión que ignora sus datos; transformación cuyo resultado se descarta. El nombre del método puede permanecer igual. |
| Bridge | Una abstracción realiza sus operaciones mediante un contrato de implementación que puede variar independientemente de ella. | Composición en runtime, traits y parámetros genéricos estáticos; varias abstracciones compartiendo implementaciones. | Campo nunca usado; genérico no relacionado; delegación donde no hay evidencia de las dos dimensiones de variación. Puede coexistir con Strategy: no inferir exclusión por nombre. |
| Composite | Hojas y compuestos exponen una operación común; el compuesto aplica esa operación a los hijos que contiene, recursivamente. | Efectos sin retorno, agregación de resultados, estructuras algebraicas, iteración funcional. | Invocar otro objeto reemplazando al hijo; colección ajena; operación incompatible. Devolver el último resultado no demuestra una agregación, pero no toda operación Composite necesita agregar. |
| Decorator | Se conserva el contrato del componente y se añade responsabilidad alrededor de la operación delegada sobre el componente envuelto. | Antes/después, validación, transformación, logging, wrappers de objetos o funciones. | Delegación transparente sin responsabilidad añadida cuando se afirma Decorator; receptor sustituido; resultado descartado cuando el contrato exige devolverlo. No exigir retorno idéntico a todos los decoradores. |
| Facade | Una entrada ofrece una tarea de mayor nivel coordinando subsistemas con fronteras identificables. | Objeto, módulo o función pública; orquestación secuencial/condicional. | Dos cálculos locales sin subsistemas; métodos que sólo almacenan dependencias. Composición aritmética no acredita por sí sola una fachada. |
| Flyweight | Se reutiliza una instancia de estado intrínseco compatible y el contexto extrínseco necesario se suministra por uso. | Pool/caché por clave, internado, instancias preconstruidas. | Reemplazo incondicional del pool; devolver otra instancia; escribir contexto extrínseco en un objeto compartido como si fuese intrínseco estable. |
| Proxy | La interfaz del sujeto se conserva mientras un intermediario controla su acceso, disponibilidad o localización. | Protección, carga diferida, proxy remoto, referencias inteligentes. | Camino de bypass que delega sin la restricción; carga descartada; resultado remoto no conectado con la respuesta. Verificar caminos relevantes, no sólo contar un sitio de llamada. |
| Chain of Responsibility | Una petición avanza entre handlers según un protocolo de aceptación/reenvío, manteniendo la petición o una transformación permitida. | Primer handler que acepta; middleware con continuación y responsabilidades antes/después. | Cambiar la continuación; reenviar otra petición sin transformación acreditada; procesar y reenviar cuando se promete exclusividad. No imponer exclusividad al middleware. |
| Command | Una petición se representa como valor/objeto retenible y su ejecución posterior usa el receptor y datos capturados. | Objetos con execute, closures, colas y comandos con contexto al ejecutar; undo opcional. | Descartar el payload capturado; ejecutar otro receptor; cola consumida después de borrar su contenido. No exigir aridad cero. |
| Interpreter | Los nodos representan una gramática; la evaluación de una producción combina las evaluaciones de sus términos bajo el contexto correspondiente. | Contexto explícito o retenido por terminales; árboles nominales/algebraicos; evaluación funcional. | Evaluar términos y descartar resultados; evaluar un hijo con contexto ajeno; devolver una constante donde se afirma combinación de términos. No restringir a suma ni a métodos sin argumentos. |
| Iterator | Un protocolo entrega elementos del agregado y evoluciona de manera coherente hacia el siguiente elemento y el fin, respetando su modalidad. | next/hasNext, sentinel, generadores yield/yield from, async, callbacks de continuación, iteradores nativos. | Repetir un índice sin progresión, avanzar antes de leer de forma que se pierda el elemento inicial, retornar el índice en vez del elemento, polaridad de continuación invertida. Un loop no es por sí solo Iterator. |
| Mediator | Participantes coordinan interacciones mediante un mediador que encamina eventos/solicitudes a los participantes pertinentes. | Campos fijos, registro/colección, despacho por tipo/etiqueta, canales. | Sólo imprimir un mensaje; evento enviado a otra llamada; participantes sin relación con el mediador. Dos participantes pueden tener el mismo tipo. |
| Memento | Un estado capturado puede restaurar posteriormente el estado representado sin que cambios intermedios destruyan esa historia. | Valores inmutables, copia independiente, estado persistente, serialización con contrato de codec. | Compartir un array que se modifica; restaurar otro campo; descartar la captura; decode de datos ajenos. La forma save/restore sola es candidata, no prueba aislamiento histórico. |
| Observer | Sujetos mantienen suscripciones y notifican eventos/cambios a los observadores pertinentes. | Lista de objetos, callbacks, eventos nativos, notificación con payload o lectura posterior del sujeto. | Registro distinto del notificado, payload ajeno, contenido borrado antes del recorrido, recorrido de hijos sin evidencia de evento/notificación. No exigir payload a todos los protocolos. |
| State | El estado activo determina comportamiento del contexto, y transiciones cambian el comportamiento posterior de acuerdo con eventos/reglas. | Objetos State, enum/discriminated union con transiciones, tablas de estado. | Selección que nunca influye; transicionar otro contexto; reemplazar el estado antes de despachar; condicional arbitrario sin protocolo de estados. |
| Strategy | El contexto selecciona una implementación intercambiable de un algoritmo bajo un contrato y usa esa selección al operar. | Objeto, callable, estrategia estática/generics; transformaciones de entrada/salida permitidas. | Selección inyectada ignorada; invocar otra función; resultado ajeno cuando se promete resultado del algoritmo. No exigir nombres ni dos clases concretas en el mismo fichero. |
| Template Method | Un esqueleto fija pasos y dependencias mientras operaciones sobrescribibles aportan partes del algoritmo. | Herencia, métodos default/traits y hooks con comportamiento por defecto. | Llamar funciones no reemplazables sin punto de extensión; invocar hooks y descartar su contribución requerida; pasos tomados de ejecuciones incompatibles. |
| Visitor | Una operación externa se selecciona según el tipo/variante del elemento visitado, separando esa operación de la estructura recorrida. | Doble despacho, overload, matching algebraico, visitor extrínseco con despacho por clase/MRO. | Visitante reemplazado; envío de otro elemento; despacho que no corresponde a la variante del elemento. Retornar resultados es opcional según contrato. |

## Criterios modernos y web

| Patrón | Obligación | Contraejemplo |
| --- | --- | --- |
| Dependency Injection | Una dependencia suministrada desde fuera se conserva o usa en el punto de consumo bajo el contrato requerido. | Sobrescribirla y consumir una dependencia distinta; asignación histórica que nunca se usa. |
| Cache Aside | Obtener por clave; reutilizar hit; en miss obtener del origen, poblar con la misma clave/valor y entregar el resultado correspondiente. | Fetch siempre; write ajeno; retorno que ignora hit o fetch; claves desconectadas. |
| Read Through Cache | La abstracción de caché administra el fallback al proveedor y entrega/retiene el valor asociado a la solicitud. | Invocar loader sin usarlo; claves/resultados desconectados; retry confundido con caché. |
| Dispatch Table | Una selección por clave determina el handler invocado y se mantienen los argumentos pertinentes. | Handler sobrescrito antes de usarlo; lookup de tabla ajena; invocación de otro callable. |
| Continuation Wrapper | La continuación recibida se retiene y se invoca de acuerdo con el wrapper, con los datos correspondientes. | Reemplazarla; capturar y nunca llamar; pasar datos a otra llamada. |
| Adapted Continuation Wrapper | Se transforma una continuación a un callable compatible y el wrapper usa el callable producido. | Adaptador que retorna escalar o descarta el handler; resultado adaptado ignorado. |
| Batch Work Queue | Registrar trabajo y consumir el lote correspondiente, con política explícita de eliminación/finalización. | Vaciar antes de consumir; consumir otra colección; marcar finalizado antes del efecto si se exige después. |
| Unit of Work | Registrar cambios de entidades y coordinar su persistencia como unidad con la política de commit/rollback declarada. | Erasar cambios antes de commit; tratar un flush por lotes como transacción atómica sin evidencia. El contrato transaccional sigue pendiente si el IR no modela transacciones. |
| Exception Retry | Un fallo elegible conduce a reintentar la operación relevante según una política de salida/reintentos. | continue anulado por finally; repetir sólo logging; retry de otra operación; política finita sin progreso del contador. |
| Subclass Factory | Una fábrica produce una clase derivada de la base seleccionada, conservando identidad de esa base a través de aliases y contextos. | Base ajena, clase creada pero no retornada, confundir una instancia con una clase. |

## Orden de implementación y aceptación

1. Habilitar selección estructural y BODY en reglas guardadas, compartiendo el
   grafo/CFG y los presupuestos existentes. No crear otro parser ni reparsear fuentes.
2. Completar las primitivas usadas por los algoritmos: valores de llamadas,
   construcción, lectura/escritura de lugares, iteración, regiones, guards e
   intervalos. Evidencia ausente produce unknown, no una prueba falsa.
3. Escribir TOML desde estas obligaciones. Mantener variantes sólo por diferencias
   de algoritmo/contrato. Las declaraciones de diseño sin query permanecen visibles.
4. Por patrón y lenguaje, comprobar positivos, negativos, ruido y mutaciones que
   rompen una obligación concreta. Los tests antiguos se revisan contra este
   contrato; no se cambian sus expectativas para aprobar el detector.
5. Repetir el corpus externo con oráculos por entidad y revisar pérdidas/ganancias.
   Comparación diferencial con el catálogo anterior es diagnóstico, no aceptación.
6. Medir búsqueda y construcción por separado, conservar límites y cachés. Rechazar
   regresiones de coste sin causa explicada y sin alternativa evaluada.
