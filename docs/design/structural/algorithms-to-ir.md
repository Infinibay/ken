# Del algoritmo en palabras al IR

Este documento guía el rediseño del [núcleo de instrucciones](instruction-ir.md).
El punto de partida es el comportamiento que queremos reconocer, no las aristas
que casualmente publica el analizador actual. Los fragmentos de IR de este capítulo
son contratos objetivo: incluyen operaciones y análisis aún no implementados.
No son consultas que el parser KenQL acepte hoy.

Para comparar con una salida ya implementada, este
[IR generado](../../structural-validation/multilanguage/instruction-rename.txt)
corresponde a «buscar un elemento por clave, almacenarlo en item, modificar su
campo name usando un parámetro, ejecutar logging y retornar item». Distingue
`slot.store` de `memory.store` y muestra los efectos desconocidos de la llamada.

## Método de trabajo

1. Escribir el algoritmo sin nombres de clases, métodos ni bibliotecas concretas.
2. Identificar entradas, salidas, objetos, bindings y estado relevante.
3. Explicar cada lectura, modificación, selección, llamada y transferencia de valor.
4. Indicar qué condiciones y caminos permiten llegar a cada paso.
5. Delimitar las propiedades que deben mantenerse entre pasos. Decir dónde
   empieza y termina la protección; no usar «nunca cambia» sin un alcance.
6. Describir implementaciones alternativas que cumplen el mismo propósito con
   mecanismos distintos. No forzarlas a tener la misma secuencia de instrucciones.
7. Traducir cada paso a instrucciones y relaciones de flujo con evidencia.
8. Probar transformaciones que conserven las propiedades, y mutaciones cercanas
   que las rompan. Si una transformación válida pierde el match, localizar si
   falta una instrucción, una relación de flujo o flexibilidad en la consulta.

La unidad de comparación es el contrato escrito. Agregar logging cambia efectos
observables del programa, pero puede conservar el producto construido, su identidad
y su configuración. Los tests no deben llamar a eso equivalencia total de programas.
Las excepciones o callbacks del logger pueden impedir esa conservación en runtime;
el análisis debe declarar cuándo sólo comprueba escrituras explícitas.

## Builder con producto almacenado

### Algoritmo en palabras

Al crear un constructor de productos, crear un producto y guardarlo en su estado.
En una operación de configuración, recibir una entrada, recuperar el producto
guardado y escribir esa entrada en una parte de ese producto. Una operación de
finalización recupera el producto configurado y lo entrega al cliente.

Pueden existir varios pasos y varios campos. Entre recuperar, configurar y entregar
puede haber trabajo independiente: logging, mediciones o cálculos sobre otros
bindings. Ese trabajo no debe reemplazar el producto pertinente ni sobrescribir
el valor cuya configuración estamos comprobando.

### Identidades e invariantes

- El producto configurado y el entregado son el mismo objeto en esta variante.
- El campo actualizado pertenece a ese producto, incluso si se llega por una
  parte anidada: producto → parte → valor.
- La entrada proviene del parámetro de configuración y llega a la escritura
  relevante. Reasignar el parámetro a una constante antes de usarlo rompe esa prueba.
- La vida del builder abarca varias llamadas. Relacionar métodos por nombres de
  campos no prueba por sí solo que un cliente haya ejecutado esa secuencia sobre
  la misma instancia. La prueba de uso necesita bindings de llamadas y estados.

### Traducción al IR objetivo

```text
func initialize(%builder) {
  %product = construct @Product()
  %pending = field.addr %builder, "pending"
  memory.store %pending, %product
  return
}

func configure(%builder, %input) {
  %pending = field.addr %builder, "pending"
  %product = memory.load %pending
  %part_addr = field.addr %product, "part"
  %part = memory.load %part_addr
  %value_addr = field.addr %part, "value"
  memory.store %value_addr, %input
  return %builder
}

func finish(%builder) {
  %pending = field.addr %builder, "pending"
  %product = memory.load %pending
  return %product
}
```

La consulta debe correlacionar el objeto y los estados; no exigir que las
instrucciones sean adyacentes. Proteger todo el objeto desde initialize sería
incorrecto: configure debe modificarlo. Se protege la identidad del producto
y, después del paso, el campo configurado hasta el punto de entrega pertinente.

Variantes separadas: un builder inmutable devuelve un sucesor; otro acumula
configuración y crea el producto sólo al finalizar; Rust puede consumir el
builder o entregar una copia derivada. Esta última exige comprobar el origen y
contrato de la copia, sin convertirla en identidad del objeto original.

### Pruebas que distinguen el algoritmo

Conservar: logging antes/después de la escritura y antes del retorno; local
independiente; nombres distintos; campos de producto anidados; finalización
mediante copia Rust modelada. Romper: escribir una constante encima del dato,
reasignar la entrada, configurar un producto y entregar otro. Si una llamada
intermedia puede mutar el producto mediante un alias, el contrato estricto queda
unknown hasta resolver sus efectos; no se la declara inocua por su nombre.

La [matriz ejecutable](../../../tests/structural/test_builder_interleaving.py)
cubre Python, JavaScript, TypeScript, Java, C# y Rust. Ejecuta las queries actuales
sobre fuentes; además verifica que puedan exportarse al núcleo, declarando partial
donde corresponda. Esto no significa que esas queries ya ejecuten el nuevo núcleo.

## Memento: guardar y restaurar estado

### Algoritmo en palabras

Leer el estado seleccionado de un objeto y guardarlo en un snapshot. Entregar el
snapshot para conservarlo mientras el objeto original puede seguir cambiando.
Más tarde, recibir ese snapshot y restaurar en el objeto el estado que representa.

El snapshot debe conservar el estado histórico seleccionado. Si sólo se guarda
una referencia a una colección mutable que luego cambia, ese almacenamiento puede
no ser un snapshot válido. No exigir copia profunda de todo: una parte inmutable
puede compartirse y una copia superficial puede bastar para el contrato elegido.

### Traducción al IR objetivo

```text
func save(%originator) {
  %address = field.addr %originator, "state"
  %state = memory.load %address
  %saved = copy.value %state [policy = selected-state]
  %snapshot = construct @Snapshot(%saved)
  return %snapshot
}

func restore(%originator, %snapshot) {
  %saved = snapshot.read %snapshot, "state"
  %address = field.addr %originator, "state"
  memory.store %address, %saved
  return
}
```

copy.value y snapshot.read son obligaciones semánticas propuestas. Pueden bajar
a instrucciones generales más modelos de API; no aparecerán automáticamente al
ver un método llamado copy o getState. Hay que relacionar el dato guardado con el
restaurado y comprobar qué memoria puede cambiar mientras se conserva el snapshot.

Conservar: logging, validación que no modifica el snapshot, campos no incluidos
en el estado seleccionado. Romper: restaurar otro campo, ignorar el snapshot,
sobrescribirlo o compartir una parte mutable que altera el estado que debía guardar.

## Observer: registrar y difundir

### Algoritmo en palabras

Recibir un observador y registrarlo en una colección de suscriptores. Cuando llega
un evento, recorrer los suscriptores pertinentes y comunicarles ese evento.
Otra operación puede retirar un suscriptor de la misma colección.

Una implementación puede recorrer la colección viva o una copia de suscriptores.
En el segundo caso, la colección recorrida es distinta, pero sus elementos
provienen de la colección registrada. No exigir identidad entre ambas colecciones.
Tampoco exigir inmovilidad global de los suscriptores: un callback puede cancelar
una suscripción legítimamente; hay que elegir qué variante se busca.

### Traducción al IR objetivo

```text
func subscribe(%subject, %observer) {
  %subscribers = collection.of %subject, "subscribers"
  collection.insert %subscribers, %observer
}

func notify(%subject, %event) {
  %subscribers = collection.of %subject, "subscribers"
  %snapshot = collection.copy %subscribers [elements = shared]
  foreach %observer in %snapshot {
    call %observer.update(%event)
  }
}
```

collection.of abrevia field.addr y memory.load. insert/copy/foreach necesitan
modelos que expliquen identidad, elementos, claves y orden. Los tokens push,
append o add no bastan para identificar una biblioteca concreta. Un array de
callbacks, un mapa con token de suscripción y un evento nativo C# requieren
variantes diferentes de representación.

Conservar: logging por evento, contador independiente y copia admitida de la
colección. Romper: registrar en una colección y recorrer otra sin relación,
notificar siempre un objeto fijo, descartar el evento y enviar otro dato cuando
el contrato exige transmitir el recibido.

## Cache-Aside: obtener o cargar

### Algoritmo en palabras

Recibir una clave y buscar su valor en una caché. Si existe, retornarlo. Si falta,
cargarlo desde la fuente usando la misma clave, guardarlo en la misma caché bajo
esa clave y retornarlo. La clave y las identidades de caché/fuente deben conservarse
durante el recorrido pertinente; el binding del resultado sí puede pasar de
«ausente» a «valor cargado».

### Traducción al IR objetivo

```text
func get(%cache, %source, %key) {
  (%present, %cached) = collection.lookup %cache, %key
  if %present {
    return %cached
  } else {
    %loaded = call %source.load(%key)
    collection.put %cache, %key, %loaded
    return %loaded
  }
}
```

Una lookup que lanza una excepción al faltar una clave no equivale a otra que
retorna null o Optional. Esos mecanismos se deben representar y modelar antes de
normalizar el camino de ausencia. Si null es un valor válido de la caché, una
comparación con null no demuestra miss sin otro contrato.

Conservar: logging de hit/miss, métricas y alias que mantengan las identidades.
Romper: cargar otra clave, escribir otra caché, guardar un valor y retornar otro,
rellenar fuera del camino de miss cuando la variante exige hacerlo sólo allí.
Concurrencia, single-flight, TTL e idempotencia son contratos adicionales.

## Qué revela este ejercicio para el IR

| Necesidad del algoritmo | Primitiva o análisis necesario |
|---|---|
| «Guardar el resultado en una variable» | Valor definido por una instrucción + slot.store |
| «Seguir usando el mismo objeto» | Procedencia de referencias y estados de memoria; no sólo igualdad de nombres |
| «Modificar ese campo usando la entrada» | field.addr/memory.store y flujo desde un parámetro |
| «Que ese campo no vuelva a cambiar» | Invariante con intervalo, aliases y efectos conocidos |
| «Transmitir el dato» | Ocurrencias de argumentos y bindings del callee; convención de paso separada |
| «Guardar una copia histórica» | Política de copia, inmutabilidad y relaciones de sharing |
| «Procesar lo registrado» | Inserción, eliminación, procedencia de elementos y región de iteración |
| «Hacerlo sólo si falta» | Condición, semántica de ausencia y caminos de control |
| «Retornar lo que se produjo» | Definiciones alcanzantes y joins correlacionados |
| «Permitir trabajo irrelevante» | Comparar efectos sobre las propiedades protegidas, sin exigir adyacencia |

Esta tabla es una lista de requisitos del nuevo núcleo y del buscador, no una
declaración de soporte completo. La exportación inicial ya separa valores,
bindings, direcciones, escrituras y regiones para formas soportadas; faltan
los análisis generales de aliases/heap, copy/ref, colecciones y la sintaxis de
cuerpos en KenQL. Los módulos actuales del grafo conservan capacidades parciales
que deben migrarse con pruebas, no suponerse completas por existir una relación.
