# Inicializadores de constructor y Command retenido por contrato

Estado: contrato implementado en IR 1.38.0; diseño escrito antes de la implementación.
Ver [validación, resultados y límites](../../structural-validation/multilanguage/cpp-constructor-initializers.md).

Los ejemplos C++ de Command retienen receptores mediante `receiver(input)` o
`receiver{input}`. Antes de 1.38, el IR conservaba el AST sin representar esa inicialización.
Además, un invocador suele almacenar un contrato Command, mientras la acción
concreta vive en un subtipo. Exigir que el parámetro tenga directamente el tipo
concreto pierde estos usos incluso cuando ambas clases están presentes.

## Contrato de inicialización

Cada entrada de una lista de inicializadores mantiene una operación propia.
HAS_INITIALIZER conecta el constructor con esa operación; INITIALIZES_FIELD
identifica un campo de instancia declarado en la misma clase. INITIALIZER_ARGUMENT
conserva sus argumentos fuente, orden y posición, sin reutilizar ARGUMENT de la
vista de llamadas. Un inicializador de base o un constructor delegante no se
convierte en un campo inexistente. Se publica un estado explícito por entrada.

La primera transferencia precisa cubre campos escalares, punteros y referencias
con un único parámetro directo de tipo compatible escrito, y valor-inicialización
vacía de punteros. STORES_VALUE y CONSTRUCTOR_INITIALIZER_INPUT sólo se emiten
cuando esa forma está soportada. Un argumento de constructor de un campo de tipo
clase no es automáticamente su valor almacenado: puede ejecutar una conversión o
una copia. Se preserva como argumento sin inventar una identidad de valor.

La ejecución de miembros sigue el orden de declaración, no el orden textual de
la lista. No se emiten aristas CFG que confundan ambos órdenes. El pase lineal
de campos incorpora entradas soportadas como estado anterior al cuerpo y después
aplica las escrituras del cuerpo. Una sobrescritura del campo mata el input
anterior. La misma restricción conservadora sobre reasignación de parámetros y
cuerpos no lineales sigue vigente. Entradas no modeladas, bases, delegación,
packs, duplicados o efectos de otros inicializadores impiden afirmar un estado
final del constructor. No se resuelven bases ni miembros heredados por basename.

Se amplía FIELD_FLOW_STATUS y CONSTRUCTOR_FIELD_INPUT a esos cuerpos C++.
Eso no resuelve overloads de constructores ni demuestra ownership, ausencia de
efectos ocultos o una garantía de heap. Los defaults de campo y todas las formas
de inicialización implícita necesitan sus propios modelos; no se mezclan con
la lista explícita como si fueran asignaciones que siempre se ejecutan.

## Consulta reutilizable y variante Command

La operación pública `command.retained_dispatch` identifica un invocador que
retiene un parámetro con contrato nominal, y lo utiliza desde otro método mediante
una llamada sin argumentos al slot de ese contrato. La retención exige una última
transferencia soportada al campo, o un CONSTRUCTOR_FIELD_INPUT, no una asignación
histórica que pudo ser sobrescrita. Expone los roles invoker, setter, input,
storage, invoke, dispatch, contract y slot.

La variante `command#retained-contract` la combina con un subtipo concreto que
implementa ese slot, retiene un receptor desde su constructor y descarta el
resultado de una llamada al receptor dentro de la acción. Invocador y comando
son clases distintas. La operación pública permite otras búsquedas sin exigir
esa conducta adicional. No se afirma orden temporal entre llamadas, ejecución
exactamente una vez ni intención exclusiva frente a objetos de consulta u otros
patrones que puedan compartir la forma.

La validación cubre Python, TypeScript, Java, C# y C++ con contratos nominales,
renombrado, retención por setter/constructor, campos distintos, input sobrescrito,
receptor sobrescrito, ausencia de acción y método incorrecto. C++ tiene casos
adicionales para braces/paréntesis, nombres ocultados por parámetros, bases,
delegación, arrays, callbacks, campos por valor, lista reordenada y cuerpo no
lineal. Se compararon el corpus abierto y los proyectos modernos/web ya auditados.
Los 130 tests de Command y 53 de inicializadores pasan. La matriz controlada
de 120 fuentes tiene 20 TP y 100 TN; no estima precisión global. El corpus añade
cuatro TP estructurales y cinco FP de intención de Strategy que quedan registrados
para corregir su firma, sin ocultarlos por nombres o directorios.

Referencia para el orden y el significado de los inicializadores:
[class.base.init del borrador C++](https://eel.is/c++draft/class.base.init).
