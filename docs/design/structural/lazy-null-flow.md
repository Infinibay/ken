# Inicialización lazy: nulidad y flujo directo

Estado: implementado y verificado en IR 1.44.0. Diseño escrito antes del código;
ver [auditoría](../../structural-validation/multilanguage/lazy-null-flow.md).

GUARDS_WRITE sólo identifica que una condición menciona el binding escrito.
No distingue `value == null`, `value != null` o `value == null || force`.
La variante lazy anterior aceptaba los tres y podía admitir retornos/escrituras
sin relación temporal suficiente. El objetivo es corregir ese contrato.

## IR genérico

NULL_TEST ya representa comparaciones directas de nulidad y su polaridad. Se
extiende a negaciones lógicas explícitas alrededor de la comparación, conservando
la operación nativa. `when` indica qué resultado booleano de la condición significa
que el valor es null; `operator` conserva el comparador interior y `negated` registra
la paridad de negaciones. No se descomponen conjunciones ni disyunciones. No se
interpreta truthiness como nulidad ni se resuelven operadores sobrecargados.

El cambio reutiliza CFG_STATUS/CFG_ENTRY/CFG_NEXT, ASSIGNMENT_TARGET/VALUE,
BINDING_WRITE_STATUS/COUNT y RETURN_OPERAND. No necesita inventar RETURN_ORIGIN
para escrituras no locales: el pase de orígenes marca correctamente esas funciones
como unsupported. La evidencia de esta búsqueda es flujo directo de statements,
no reaching definitions general de memoria compartida.

## Operación y variante

Una operación pública `singleton.lazy_instance`, escrita en el mismo TOML, expone
unit, storage, accessor y creation. Requiere campo static con asignación NULL en
el cuerpo de la clase, un accessor estático con CFG estructurado e inventario de
escrituras soportado, y exactamente una escritura explícita de ese slot en el
accessor. La primera operación del CFG es la comparación NULL_TEST del mismo slot.

La rama no-null debe devolver directamente el slot y terminar el callable. La
rama null debe empezar con la asignación directa de una construcción de esa clase
y pasar inmediatamente a un retorno del mismo slot, que termina el callable.
El nodo de asignación puede estar envuelto en su statement nativo; el recorrido
SYNTAX_PARENT queda acotado. Se cubren las dos polaridades, retorno compartido al
final, else con retornos separados y guardia temprana de no-null. Bloques vacíos
o puramente estructurales se normalizan por el CFG existente.

La variante canónica lazy reutiliza esa operación; no exigirá nombres ni un
constructor privado ficticio en Python/JS. La privacidad y exclusividad siguen
siendo dimensiones separadas. No se afirma bloqueo, atomicidad, estabilidad ante
otros métodos, descriptores/setters o unicidad global. Se documentan como gaps
las versiones con logging intermedio, temporales, doble chequeo y bloques de lock
hasta tener modelos específicos, sin etiquetarlas como TN.

## Validación

Matriz en Python, Java, JavaScript, TypeScript y C#: polaridades, comparación
invertida, negación simple/doble, comentarios, renombrado, else y retornos tempranos.
Negativos: non-null que recrea, OR forzado, guardia de otro slot, escritura fuera
de la rama, reset previo/posterior, otro retorno, escritura compuesta, campo no
static y null histórico asignado en otro método. Añadir tests del predicado genérico,
composición de la operación, límites de presupuesto y errores de parsing.
Revisar ConfigurationManager TS del corpus y escaneos comparables; registrar
pérdidas o nuevos matches con evidencia y actualizar guías antes del cierre.

La verificación pasa 5.562 tests y mypy en 102 archivos. La matriz de 110
fuentes corrige 45 FP y cinco FN; quedan 45 TP/65 TN. El corpus mantiene 73/281
presencias y los escaneos comparables no cambian. Se documentan dos FN Java por
null implícito con modificaciones de diagnóstico en memoria, sin tocar upstream.
