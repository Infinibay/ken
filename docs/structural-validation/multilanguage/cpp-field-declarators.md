# Declaradores C++ y receptores tipados — IR 1.36.0

## Cambio y pruebas

El IR conecta el tipo de cada declarador de campo C++ con el mismo slot que usan
sus lecturas y llamadas. Antes, el slot existía pero el tipo de *campo podía quedar
en un VALUE sintáctico distinto. Se conservan punteros, referencias, cualificación,
arrays y declaradores opacos, sin aplanarlos a un tipo escalar conveniente.
Los campos se declaran antes de resolver métodos, y cada inicializador de campo
queda asociado a su declarador, incluso en declaraciones múltiples.

TYPE_HEAD_STATUS evita que Driver** o un callback se resuelvan por anotación a
Driver después de eliminar asteriscos. TYPE_QUALIFIER expone const/volatile por
capa; reference y rvalue_reference distinguen & de &&. CPP_FIELD_DECL_STATUS
publica la normalización de identidad, sin certificar validez, inicialización ni
resolución completa. Las formas con precedencia parentizada quedan opacas como
conjunto. Ver [diseño y ejemplos](../../design/structural/cpp-field-declarators.md).

Se agregan **112 tests**: 46 de declaradores, 23 de cualificación y controles en
otros lenguajes, 37 de patrones C++, cinco de raíces nominales C++ y un ejemplo
KenQL de la guía. Incluyen campos antes/después del uso, declaraciones múltiples,
modificadores, callbacks, métodos con nombre parentizado, punteros a arrays,
indirecciones múltiples, tipos cualificados ajenos y roundtrip del IR.

La suite pasa **4.085 tests en 163,18 s**; mypy pasa en **99 archivos**. Se verificaron
los módulos y TOML del wheel offline contra los hashes del motor. Fuera del checkout
se comprobaron tipos cualificados, tipos opacos, exclusión de un contrato escalar
para doble indirección y controles Adapter. Los 37 fixtures de patrones se volvieron
a ejecutar tras hacer const el método de la API ilustrativa para admitir los
receptores const de los positivos. No se ejecutó ni compiló código objetivo.

## Matriz controlada

Se analizaron las mismas 37 fuentes de patrones con el wheel IR 1.35 y el motor
IR 1.36. La matriz conserva hashes y parámetros de los generadores de tests.

| Versión | TP | TN | FP | FN |
|---|---:|---:|---:|---:|
| IR 1.35.0 | 6 | 22 | 0 | 9 |
| IR 1.36.0 | 15 | 22 | 0 | 0 |

[Referencia](cpp-field-patterns-before.json), [resultado](cpp-field-patterns-after.json).
Adapter recupera ocho positivos; Bridge recupera uno. Los seis positivos Strategy
ya funcionaban por propagación del tipo desde la asignación de un parámetro y se
conservan como regresiones. Los negativos prueban contratos ajenos, falta de uso,
una sola implementación, ausencia de inyección y familias Bridge relacionadas.
Esto mide esos fixtures estructurales, no precisión/recall global ni corrección de
runtime, const-correctness general o validez de punteros.

## Corpus externo: una recuperación y una ambigüedad nueva

La [regresión completa](ir136-corpus-regression.json) pasa de **61 a 62 ejemplos
con presencia esperada, entre 281**. Conserva los mismos commits, 736 archivos
únicos, 745 apariciones por caso y 6.463 consultas completas. No elimina matches.
Aparecen sólo estas dos clases nuevas:

| Clase y ubicación | Evidencia | Evaluación |
|---|---|---|
| Facade, cpp-patterns/facade/Facade.cpp:56 | operation1 invoca suboperation sobre los campos de SubsystemA y SubsystemB, declarados como punteros en las líneas 76–77. | **TP estructural Facade.** Un punto de entrada coordina dos subsistemas distintos. |
| NonterminalExpression, cpp-patterns/interpreter/Interpreter.cpp:83 | interpret invoca lop y rop, ambos AbstractExpression, y combina resultados con AND. | **FP de intención Decorator.** La segunda llamada es otro operando de una expresión binaria; no comportamiento agregado alrededor de un único componente. |

Los [testigos](cpp-field-declarator-witnesses.json) registran campos, tipos, métodos,
llamadas, commits y hashes. La presencia esperada nueva es únicamente Facade;
el candidato Decorator no se suma como cobertura Interpreter ni como TP.

El ejemplo Facade inicializa sus punteros con (), y luego los desreferencia. Su
estructura ilustra el patrón, pero no se certifica que sea seguro ejecutarlo.
El modelo actual no interpreta esas listas de inicialización de constructor como
valores nulos ni detecta ese posible defecto. Es un caso pendiente de análisis de
inicialización y uso de punteros, separado de la identificación estructural.

## Separación de Bridge y límites de la corrección

Al conectar campos C++ surgían tres Bridge espurios en ejemplos Decorator:
WithFruits (Pandovski) y ConcreteDecoratorA/B (cpp-patterns). La ruta C++ de
runtime-composition ahora exige raíces nominales explícitas distintas. Eso rechaza
una abstracción que pertenece a la misma familia que el componente envuelto.
NOMINAL_ROOT incluye C++ con los mismos límites de resolución, ciclos y profundidad.

Aplicar esa condición globalmente perdía ExtendedAbstraction del Bridge Python de
Pandovski por abc.ABC no resuelto. La versión final conserva el comportamiento
anterior de runtime-composition en los demás lenguajes, incluyendo sus FP conocidos
Java/C#; no se oculta esa limitación ni se interpreta desconocimiento como separación.
La consulta refined-composition mantiene el contrato de IR 1.35.

Quedan pendientes las listas de inicialización de constructor, prototipos de
métodos virtuales sin cuerpo, resolución C++ completa de namespaces/aliases/macros
y variantes de Bridge con raíces no resueltas. Los prototipos ausentes impiden
correlacionar ciertos overrides aun cuando el campo ahora tiene tipo. El puntero
no se convierte en prueba de ownership, inicialización ni destino runtime.

## Biblioteca C++ real: fmt

Se descargó fmt, commit `e91e92761aa31d6d493297763cd9f77a361aaa2d`, y se analizaron
sus **16 cabeceras de include/fmt/**. El runner recibió una asignación explícita
.h→cpp para ese alcance; no se modificó el descubrimiento de extensiones por defecto.
Se conservaron la licencia y las fuentes en el clon temporal, sin compilar ni ejecutar.

[IR 1.35](ir135-fmt.json) e [IR 1.36](ir136-fmt.json) usan los mismos archivos y
producen cero matches, con consultas completas y **677 diagnósticos en 15 cabeceras**.
Parte de los errores aparece alrededor de FMT_BEGIN_NAMESPACE y otros macros que
el analizador recibe sin expandir. Esto bloquea garantías de análisis de esas
unidades; **cero matches no es evidencia de TN ni ausencia de patrones**.
El escaneo aporta una limitación reproducible de C++ de producción, no cobertura
positiva de fmt. Los diagnósticos y el problema de preprocesamiento quedan pendientes.

## Regresión y rendimiento

[Requests](ir136-requests.json), [Flask](ir136-flask.json), [RxJS](ir136-rxjs.json),
[Commons IO](ir136-commons-io.json), [log](ir136-rust-log.json) e
[iluwatar caching](ir136-iluwatar-caching.json) conservan fuentes, commits, matches
y completitud en sus alcances anteriores: 19, 24, 123, 277, nueve y 14 archivos.
Las mediciones siguientes usan los dos archivos C++ del corpus, una consulta de
warmup y 30 muestras de motor sobre índice/registro precalculados; parseo/enlace
se midió aparte con diez muestras.

| Etapa / fuente | Mediana IR 1.35 | Mediana IR 1.36 | p95 IR 1.36 |
|---|---:|---:|---:|
| Query Facade | 0,037 ms | 0,097 ms | 0,147 ms |
| Query Decorator sobre Interpreter | 0,057 ms | 0,110 ms | 0,174 ms |
| Parseo/enlace de Facade | 4,907 ms | 4,953 ms | 5,202 ms |
| Parseo/enlace de Interpreter | 10,105 ms | 10,347 ms | 13,228 ms |

[Datos](cpp-field-declarators-performance.json). La consulta anterior no encontraba
esos candidatos; no se presenta el coste adicional como una mejora de velocidad.
Son observaciones del host sobre dos archivos, sin CLI ni caché persistente,
no una extrapolación a repositorios grandes. [Comprobaciones finales](ir136-checks.json).
