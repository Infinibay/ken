# Expresiones de clase y factories de subclases

Estado: implementado y verificado en IR 1.42.0. El diseño se escribió antes de
la implementación; ver [auditoría](../../structural-validation/multilanguage/class-expression-factories.md).

El corpus Pandovski contiene MilkCoffe, WhipCoffe y VanillaCoffe: funciones que
reciben un constructor y devuelven una clase que lo extiende. Este mecanismo
también sustenta mixins de componentes; el [manual de TypeScript](https://www.typescriptlang.org/docs/handbook/mixins.html)
describe factories que devuelven expresiones de clase derivadas de una base.
No equivale automáticamente al wrapper GoF ni prueba aplicación de un decorador.

## Identidad de la expresión

El nodo Tree-sitter `class` de JS/TS debe producir una entidad CLASS con identidad
por ocurrencia, incluso cuando varias expresiones usan el mismo nombre. Su nombre
interno sólo está vinculado dentro de la expresión, no en el ámbito exterior.
Las expresiones anónimas conservan un nombre sintético, sin inventar una
declaración externa. Ver [semántica de clases ECMAScript](https://tc39.es/ecma262/multipage/ecmascript-language-functions-and-classes.html#sec-class-definitions-runtime-semantics-evaluation).

La expresión es un valor: RETURN_OPERAND y ASSIGNMENT_VALUE pueden señalar la
entidad de clase, no una instancia ni un VALUE opaco. Los métodos, campos privados
y retornos internos pertenecen a la clase, no al factory o clase exterior.
CLASS_EXPRESSION conecta el nodo sintáctico con su entidad. DECLARES indica
propiedad sintáctica con kind=type-expression; no significa hoisting del nombre.
Cada entidad representa un sitio de definición, no una única clase runtime entre
invocaciones del factory. No se resolverá `new Alias()` por una asignación histórica
ni se expandirán automáticamente clases devueltas por llamadas.

## Base como referencia léxica

BASE_VALUE conecta la clase con una referencia base simple de Python/JS/TS,
con el nombre escrito y basis=lexical-base-syntax. Si la referencia es un parámetro,
almacenamiento declarado o callable, BASE_NAME no debe resolver por accidente a
una clase homónima exterior. BASE_VALUE no es SUBTYPE_OF de ese parámetro ni una
prueba de su valor actual. Las bases compuestas, llamadas a mixins, expresiones,
metaclases, substitución de genéricos y temporal dead zone quedan fuera del modelo.

El nombre interno de una expresión resuelve sus propias referencias de
tipo; se excluye de la búsqueda nominal por basename exterior. Se conserva
la resolución existente de bases nominales simples/importadas cuando no esté
oculta por un binding léxico.

## Consulta moderna

`architecture.subclass-factory`, en su propio TOML, busca un callable que
devuelve una clase definida dentro de él y cuya base simple es un parámetro no
reasignado explícitamente del factory. Usa RETURNS_VALUE del pase de retorno
soportado y UNREASSIGNED_BINDING, además de DECLARES y BASE_VALUE.
Las arrows concisas cuyo cuerpo es directamente la expresión de clase usan
BODY_VALUE, que ahora se publica también para JS/TS. No hay una secuencia de
statements intermedia en esa forma; los defaults de parámetros no prueban entrada
externa ni identidad runtime. El CFG no debe asignarse a la clase por el hecho
de ocupar el campo body de la arrow: propietario de cuerpo y función deben coincidir.

Los mixins SignalWatcher y FormAssociated de Lit devuelven `Clase as Tipo`.
TYPE_ASSERTION_VALUE conserva el valor bajo `as`, aserción angular, non-null
y `satisfies` de TypeScript; las operaciones originales se mantienen. Estas
aserciones se eliminan del programa emitido, no validan ni convierten el valor
en runtime; ver [aserciones TypeScript](https://www.typescriptlang.org/docs/handbook/2/everyday-types.html#type-assertions).
No se extiende esta transparencia a casts de C#/C++/Java ni se interpretan tipos
afirmados como evidencia de que una instancia tenga ese tipo. Tampoco se cambian
las reglas de proyección CALLEE_VALUE de expresiones invocadas con casts.

La forma Python usa una class_definition local; JS/TS admite expresiones anónimas,
nombradas y declaraciones locales. Los aliases locales de retorno sólo se aceptan
cuando el pase de flujo ya los soporta. La regla no exige nombres, constructores,
decoradores o APIs web concretas, ni certifica compatibilidad de tipos, C3/MRO,
forwarding de argumentos, aplicación del mixin o intención GoF.

## Pruebas y evidencia

Identidad, ámbito interno y shadowing; expresiones homónimas, anónimas y anidadas;
campos privados, funciones, getters, variádicos y generadores en la clase;
no filtración del nombre a otras funciones/archivos; clases retornadas frente a
instancias; bases nominales frente a parámetros homónimos; rebindings y aliases.
Matriz positiva/negativa en Python, JS y TS, prueba de composición y presupuesto,
revisión de los tres ejemplos externos y regresión de todos los GoF/modernos.
Las guías operativas se actualizan sólo con los contratos implementados.

La suite completa pasa 5.250 tests. La matriz nueva tiene 21 TP/18 TN sin
errores en 39 fuentes controladas; la corrección de ámbito elimina dos FP y
cuatro FN en doce candidatos Singleton. Se revisan cuatro factories de producción
de Lit, tres fixtures JS y tres ejemplos Pandovski. La normalización de aserciones
expone además una instancia compartida en RxJS que sería FP de Singleton estricto;
la auditoría registra la causa y la corrección pendiente.
