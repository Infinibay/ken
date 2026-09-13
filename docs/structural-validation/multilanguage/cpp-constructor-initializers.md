# Inicializadores C++ y Command retenido por contrato — IR 1.38.0

## Cambio y alcance

El IR representa cada entrada explícita de una lista de inicializadores C++ con
identidad propia, campo declarado y argumentos fuente. Resuelve el nombre del
miembro en la clase y sus argumentos en el constructor: `receiver(receiver)`
conserva las dos identidades. Los campos pueden declararse antes o después del
constructor. Bases y constructores delegantes no generan campos ficticios.

El modelo distingue argumento sintáctico, valor directo soportado y entrada que
sigue retenida al terminar el cuerpo lineal. Las escrituras posteriores pueden
eliminar la retención inicial. Una entrada de clase por valor, una conversión no
modelada, packs, duplicados o bases impiden afirmar retención final del constructor.
Los defaults de campo y el valor NULL de una ocurrencia no se convierten en un
estado global de todas las instancias. No se impone el orden textual de la lista
en el CFG: C++ inicializa miembros en orden de declaración.
Ver [diseño](../../design/structural/cpp-constructor-initializers.md) y
[referencia de relaciones y consultas](../../structural-ir.md#c-constructor-initializers-and-retained-command-dispatch).

La nueva variante `command#retained-contract` usa la operación pública
`command.retained_dispatch`. Conecta el contrato nominal retenido por el invocador
con el slot sobrescrito por un comando concreto. La implementación concreta debe
retener un receptor desde su constructor y descartar el resultado de una llamada
al receptor en su acción. La operación pública por sí sola también reconoce
servicios inyectados; no prueba intención Command ni despacho runtime a un subtipo.
Los contratos de las variantes anteriores no cambian.

## Matriz controlada y pruebas

Las mismas 120 fuentes se analizaron con el wheel IR 1.37 y el motor IR 1.38 usando
la regla canónica Command. Cubren Python, TypeScript, Java, C# y C++, retención por
setter o constructor, renombrado, escritura en otro campo, input/campo/receptor
sobrescritos, contrato ausente y acción incorrecta o sin trabajo.

| Versión | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| IR 1.37.0 | 0 | 100 | 0 | 20 |
| IR 1.38.0 | 20 | 100 | 0 | 0 |

[Referencia](retained-contract-command-before.json),
[resultado](retained-contract-command-after.json). Son contrastes de estructura
controlados, algunos con contratos deliberadamente incompletos; no una estimación
de precisión global ni una validación del compilador de cada lenguaje.

Se agregan 130 tests de Command: los 120 contrastes y diez pruebas de composición
y correlación de roles. Otros 53 tests cubren inicializadores, clases/arrays/callbacks
no soportados, punteros/referencias/cualificadores, sobrescrituras, orden de lista,
retorno antes de código muerto, control no lineal, campos homónimos y relaciones
KenQL sobre grafos que no contienen C++. Estos últimos también verifican que las
relaciones de firmas virtuales, antes emitidas pero no registradas globalmente,
sean consultables en grafos sin hechos C++ y devuelvan vacío completo.

Se suman dos ejemplos ejecutables de la guía IR. La [verificación final](ir138-checks.json)
pasa **4.453 tests en 180,94 s**, incluyendo todo Ken; mypy pasa en 101 archivos.
Los 28 ejemplos KenQL de las dos guías operativas parsean y los 23 de la guía IR
se ejecutan en tests contra fuentes. Todos los módulos y TOML del wheel coinciden
con los hashes del motor escaneado. Fuera del checkout se verificaron inicialización
con paréntesis/braces, Command positivo, exclusión por sobrescritura, operación
pública y serialización de ida y vuelta. El cambio de IR_VERSION invalida la
caché de la semántica anterior.

## Corpus abierto: revisión de las nueve coincidencias nuevas

La [comparación](ir138-corpus-regression.json) conserva los mismos commits y hashes:
281 ejemplos, 736 archivos únicos, 745 apariciones de archivos en los distintos
alcances y 6.463 consultas completas. Las presencias esperadas pasan de **68 a 71**;
no se pierde ninguna coincidencia anterior. Son etiquetas de ejemplos upstream,
no una matriz TP/TN/FP/FN. Se revisaron las nueve coincidencias agregadas:
**cuatro TP estructurales y cinco FP de intención**.

| Fuente / unidad / regla | Evaluación |
|---|---|
| cpp-patterns command/Command.cpp — ConcreteCommand, Command | TP: Invoker almacena Command y ejecuta su slot; ConcreteCommand retiene Receiver desde `receiver(r)` y llama action descartando su resultado. |
| Pandovski Behavioral/Command/C++ — FlipUpCommand y FlipDownCommand, Command | Dos TP: Switch retiene dos referencias Command; cada comando conserva Light desde su inicializador y ejecuta turnOn/turnOff. |
| cpp-patterns strategy/Strategy.cpp — Context, Strategy | TP: retiene Strategy desde el parámetro `Strategy *const s` y delega a algorithmInterface; hay implementaciones concretas alternativas. |
| Pandovski Behavioral/Command/C++ — Switch, Strategy | FP de intención: los colaboradores son acciones Command. La firma Strategy existente acepta inyección y delegación sin discriminar ese uso. |
| Pandovski Structural/Decorator/cpp — CandyDecorator, Strategy | FP de intención: retiene Candy y reenvía Make para decorar el componente. |
| cpp-patterns bridge/Bridge.cpp — RefinedAbstraction, Strategy | FP de intención: la colaboración une las dos familias de Bridge. |
| cpp-patterns decorator/Decorator.cpp — Decorator, Strategy | FP de intención: el objeto conserva el mismo contrato que su componente envuelto. |
| cpp-patterns interpreter/Interpreter.cpp — NonterminalExpression, Strategy | FP de intención: retiene hijos de expresión y combina sus resultados de interpretación. |

Los [testigos](cpp-constructor-initializer-witnesses.json) conservan roles, hechos,
ubicaciones y hashes de los siete alcances cambiados. El IR ahora expone entradas
de constructor a la firma anterior de Strategy; esto explica sus cinco FP nuevos.
Los FP anteriores de Adapter sobre Commands permanecen: añadir la variante correcta
no suprime automáticamente otras reglas. Tampoco se excluyen clases por nombre,
directorio o presencia de otro patrón, porque una clase puede cumplir varios roles.

## Bibliotecas reales y rendimiento

[Requests](ir138-requests.json), [Flask](ir138-flask.json), [RxJS](ir138-rxjs.json),
[Commons IO](ir138-commons-io.json), [log](ir138-rust-log.json) e
[iluwatar caching](ir138-iluwatar-caching.json) mantienen exactamente sus fuentes
y coincidencias en los alcances medidos: 19, 24, 123, 277, nueve y 14 archivos.
Todas las consultas terminan dentro de sus presupuestos. Esta comparación detecta
regresiones de resultados; no revisa de nuevo cada coincidencia histórica.

[fmt](ir138-fmt.json) mantiene cero matches y 677 diagnósticos en 16 cabeceras
con override .h→cpp. La falta de expansión de macros impide tratar ese resultado
como evidencia de TN. No se compiló ni ejecutó código de los repositorios objetivo.

Las [mediciones](cpp-constructor-initializers-performance.json) comparan dos archivos
del corpus, versiones ejecutadas secuencialmente: 30 muestras por consulta después
de warmup sobre índice y registro precalculados, diez de parseo/enlace y diez de
proyección del grafo por separado.

| Regla | Consulta 1.37, mediana ms | Consulta 1.38, mediana ms | Parseo/enlace 1.38, mediana ms |
|---|---:|---:|---:|
| Command | 0,435 | 0,802 | 5,624 |
| Strategy | 0,083 | 0,171 | 5,580 |

La versión anterior no encontraba esos patrones en estos archivos; ahora cada
consulta devuelve un TP. El costo adicional no es una mejora de velocidad. Los
p95 y tiempos de proyección están en el JSON. Son observaciones del host sin
caché persistente; no representan latencia de CLI ni rendimiento global o memoria.
La caché mantiene su límite configurable de **500 MB decimales por defecto**.

## Problemas pendientes y posibles causas

- Strategy sigue confundiendo colaboradores polimórficos con algoritmos
  intercambiables. Hace falta evidencia de roles y comportamiento del cliente;
  herencia o nombres por sí solos no bastan para separarlo de Command, Bridge,
  Decorator e Interpreter. La revisión debe incorporar esos cinco contraejemplos
  y preservar estrategias válidas compuestas, sin convertir categorías en exclusivas.
- La retención final de constructores con bases, delegación, objetos por valor,
  conversiones, packs o efectos no modelados queda fuera. Requiere resúmenes de
  inicialización y efectos; no se debe atribuir al campo cualquier argumento
  que aparezca en su constructor.
- Los cuerpos no lineales, escapes, alias de heap y efectos ocultos siguen limitando
  las transferencias. Las relaciones directas no prueban pureza, ownership ni orden
  temporal entre configuración e invocación del objeto.
- Persisten los límites C++ de macros, templates, namespaces/aliases, firmas y
  definiciones fuera de clase documentados en la [auditoría 1.37](cpp-method-contracts.md).
  Un grafo parcial y una consulta completa no equivalen a cobertura semántica completa.
