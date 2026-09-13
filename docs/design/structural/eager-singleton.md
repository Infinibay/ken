# Singleton con instancia compartida inicializada en la clase

Estado: implementado y verificado en IR 1.41.0; el diseño se escribió antes de
la implementación. Ver [auditoría](../../structural-validation/multilanguage/eager-singleton.md).

La variante lazy no reconoce IvoryTower de iluwatar ni SingletonEager de
Pandovski. Ambos inicializan un campo estático con una construcción de su propia
clase y lo devuelven desde un accessor estático. El IR ya conserva los operandos
de inicialización, propietario, tipo construido y CFG; la consulta no necesita
una relación específica de Singleton. Las pruebas exponen además dos defectos
generales de lowering/enlace que sí requieren invalidar la caché con IR 1.41.0.

## Correcciones del IR necesarias

- JS/TS private_property_identifier debe declarar almacenamiento, igual que el
  property_identifier público. El inicializador de `static #instance` terminaba
  asignado a un VALUE distinto del STORAGE leído por `Class.#instance`.
  Las declaraciones de campo deben crear su propio slot aun cuando exista un
  método homónimo o un campo en una clase exterior. La prueba anidada usa una
  class_declaration dentro de un método; las expresiones `class` de JS/TS siguen
  siendo un límite del frontend y no se incluyen en la garantía.
- Un RECEIVER que ya está resuelto a una clase Java/C#/JS/TS puede invocar sus
  métodos static propios. La resolución anterior sólo buscaba tipos de instancias
  y omitía `Class.get()`. Se publican TARGET/CALLS para un candidato único y
  MAY_TARGET/MAY_CALLS para sobrecargas, con basis=direct-class-static. No se
  añadirá DELEGATES_TYPE: una llamada de clase no es delegación a una instancia.
  No se adivinarán métodos heredados ni nombres externos. En JS/TS un campo con
  el mismo nombre impide afirmar que se invoque la declaración del método.
  Los getters/setters no son destinos de una invocación directa: un getter
  puede devolver otra función. Los receptores importados que todavía no están
  resueltos a una entidad CLASS siguen pendientes.

La corrección no equivale a selección de overload, validación de accesibilidad,
invocación runtime de getters ni análisis de monkey patching.

## Contrato ejecutable

`singleton#eager-shared` reutiliza la operación pública
`singleton.shared_instance`, con roles unit, storage, accessor y creation:

1. Un campo estático pertenece a unit. Una declaración de campo de esa clase
   tiene una asignación cuyo valor construye unit. La llamada también pertenece
   a la clase, no a un método ejecutado cada vez que se solicita la instancia.
2. Un método estático sin argumentos explícitos tiene CFG_STATUS structured y
   comienza directamente en un return cuyo RETURN_OPERAND es ese campo.
3. El return termina en CFG_EXIT. Los comentarios y bloques sintácticos no
   cambian el recorrido; los accessors con ramas, trabajo previo o aliases
   requieren una variante de flujo más amplia y quedan pendientes.

La cobertura actual incluye Java, C#, TypeScript y JavaScript. Los módulos
Python/JS, el local static C++ y las primitivas once Go/Rust tienen ámbitos y
mecanismos distintos; permanecen como propuestas separadas.

## Significado y límites

La firma acredita inicialización de clase y devolución directa de almacenamiento
compartido. No demuestra instancia única global, constructor privado, campo
inmutable, ausencia de reset, comportamiento de un getter o seguridad de threads.
Un default compartido puede tener la misma forma sin intención Singleton; debe
anotarse como ambigüedad de intención, no ocultarse mediante nombres.

No se exige ausencia de otras escrituras mediante count=0 sobre hechos abiertos:
el motor devuelve cardinality:open_world para esa consulta, correctamente. Tampoco
se promueve ASSIGNED_FROM histórico a prueba de retención permanente. Un método
de reset no invalida el hecho de que el accessor devuelve el slot compartido;
estas coincidencias no certifican una única construcción durante toda la vida.

## Validación y evidencia

Matriz en los cuatro lenguajes: inicializador correcto, renombrado, campo privado,
comentarios/paréntesis/bloques, campos y tipos distintos, instancia por objeto,
constructor invocado dentro del accessor, parámetro de lookup y accessor que
devuelve otra expresión. Ramas, aliases y efectos previos se registrarán como
limitaciones, no como TN. Se probaron composición nombrada, roles correlacionados,
roundtrip, conservación de lazy y el presupuesto con muchas clases.

Se compararon el mismo corpus y alcances externos con el catálogo anterior,
se revisó cada coincidencia añadida y se midió consulta separada del parseo.
Las guías IR/KenQL y el catálogo reflejan los resultados.

La verificación pasa 5.116 tests. Se recuperan dos ejemplos del corpus y una
instancia compartida de Commons IO; no se pierden presencias. La ubicación del
campo privado #init de RxJS se corrige a su declaración. El detalle, la matriz
controlada y el rendimiento están en la auditoría.
