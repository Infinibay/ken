# Segunda revisión: xfail, contratos KQL 2 y código abierto

Revisión iniciada el 14 y cerrada el 15 de septiembre de 2026. Motor IR **1.78.0**.

**El trabajo no elimina todos los pendientes.** De los 111 `xfail` de la revisión
anterior, 101 tienen ahora una comprobación sin `xfail`: **29 mediante correcciones
al IR o a consultas generales y 72 mediante contratos optativos nuevos**. Quedan
**10 expectativas pendientes**, desglosadas más abajo. No se borraron sus oráculos.
Los contratos nuevos se invocan explícitamente: no debe interpretarse que todas
las consultas GoF generales adquirieron esas garantías más fuertes.

En código abierto la mejora medida es modesta: **88 de 281 ejemplos** presentan
al menos un match de la etiqueta de su directorio, frente a **87** en la primera
pasada de esta revisión. Esa cifra **no es precisión ni recall**. La revisión
manual de 22 pares entidad/patrón da **10 TP, 5 TN, 1 FP, 4 FN y 2 ambiguos**.
Es una muestra seleccionada para inspeccionar aciertos y problemas; no representa
la distribución de todos los proyectos o lenguajes.

## Límite de la migración al lenguaje acordado

Los TOML siguen escritos principalmente como joins `edge` sobre relaciones del
grafo. Esto es un perfil de bajo nivel con parser KQL 2, **no la migración completa
a la autoría con `class`, `method`, `body`, iteraciones e intervalos protegidos**.
Los dos perfiles de ejecución siguen separados; no se permite mezclar sus
cláusulas. Las verificaciones de esta revisión validan ese perfil y sus contratos
acotados, no la conformidad completa con la especificación del lenguaje.
La integración pendiente debe compilar ambos estilos a operadores compatibles
y preservar identidad, flujo, incertidumbre y presupuestos. Renombrar relaciones
o envolverlas con azúcar sintáctico sin cumplir la semántica de BODY no lo resuelve.

Verificación final de esta revisión: **11.298 tests pasan, 10 xfail, cero fallos**,
en 296,33 s, para `tests/structural`, `tests/kql2` y `tests/common_ast`.
Mypy pasa en los seis módulos centrales indicados en `tests.json`.

## Qué se corrigió y cómo se comprueba

El [ledger de 111 casos](xfail-ledger.json) conserva nombre original, motivo,
estado, fichero de test y mecanismo de resolución. Distingue una corrección de
la raíz de un contrato nuevo. La [verificación final](tests.json) confronta cada
ID con el resultado de pytest. El catálogo actual contiene **154 consultas
públicas ejecutables: 33 raíces, 91 variantes y 30 operaciones**. De estas últimas,
15 se incorporaron en esta revisión, además de una variante Interpreter.

Cambios de IR que sostienen las consultas:

- **Identidad de valores por intervalo de bytes.** Una expresión como `1 + 2`
  comparte el comienzo con el literal `1`. Usar solamente el comienzo fusionaba
  ambos nodos, producía una autoarista y agotaba el límite de análisis. Se incluye
  el final del intervalo y se deduplican proyecciones de operandos.
- **Procedencia evaluada en cada uso.** `VALUE_DEPENDS_ON` conserva los orígenes
  consumidos por expresiones aritméticas y comparaciones; `ARGUMENT_VALUE_ORIGIN`
  conserva el origen que llega a una llamada. Reasignar un parámetro antes de
  calcular un resultado difiere de hacerlo después. La dependencia es sintáctica:
  no demuestra que `x * 0` varíe matemáticamente con `x`.
- **Versiones explícitas del receptor.** `RECEIVER_BINDING_VERSION` y
  `RECEIVER_UNREPLACED` impiden unir pasos sobre bindings explícitamente
  reemplazados. Son un inventario léxico conservador, no SSA completo ni prueba
  de aliasing del heap. Los contextos con escrituras opacas no publican la garantía.
- **Constructores y retención.** Prototype correlaciona argumento, parámetro y
  campo conservado. Java/C# permiten seleccionar entre sobrecargas cuando todas
  tienen firmas posicionales fijas y una sola coincide por aridad. Firmas con
  `params`, valores opcionales o referencias no se fuerzan a ese modelo.
  Un `this()` inicial sin argumentos en un constructor Java permite analizar
  las escrituras posteriores; no inventa el estado escrito por el constructor
  delegado. Una fuga posterior de `this` sigue invalidando el resumen.
- **Usos estáticos Python.** Se enlazan llamadas directas a métodos con un único
  `@classmethod` o `@staticmethod` reconocido. Decoradores extra, shadowing y
  reemplazos explícitos se excluyen. No se prueba la identidad de descriptores
  importados ni monkey-patching dinámico.
- **Orden entre operaciones.** Los atributos de intervalo de `OPERATION` se
  consultan en KQL 2. Permiten exigir lectura antes de actualización y retorno,
  sin confundir orden textual con factibilidad de un camino de ejecución.

Los 29 casos corregidos mediante IR/raíces cubren Adapter con nombres iguales,
Builder con receptores reemplazados, Composite con hijos reemplazados, Command
con parámetros de ejecución y receptor retenido, Mediator con dos instancias del
mismo tipo, Prototype que descarta estado, uso de Singleton Python y Visitor que
reemplaza al visitante. Además, Strategy exige el origen de entrada del argumento:
la ampliación del análisis de reasignaciones expuso que su consulta antes dependía
accidentalmente de que esos cuerpos quedaran sin analizar.

### Contratos optativos añadidos

Cada operación tiene controles positivos y negativos de código fuente a través
del servicio público. Python, Java y TypeScript están cubiertos salvo
`observer.event_delivery`, cuya matriz usa Python, JavaScript y TypeScript.
Las pruebas adicionales incluyen ruido, reasignaciones, orden adverso,
identidad de valores, sobrecargas y serialización del grafo.

| Operación | Exigencia adicional y límite |
| --- | --- |
| `adapter.input_conversion` | El argumento adaptado consume la entrada; dependencia sintáctica, no equivalencia algebraica. |
| `adapter.output_conversion` | El resultado retornado consume el resultado delegado; no prueba la especificación de la conversión. |
| `visitor.result_forwarding` | Retorna el resultado de la visita; un Visitor general puede legítimamente retornar `void`. |
| `decorator.result_forwarding` | Conserva el resultado delegado; un Decorator general puede modificarlo. |
| `bridge.injected_returned_primitive` | La selección inyectada llega a la invocación y su resultado se devuelve. |
| `command.captured_payload` | El dato capturado llega al argumento del receptor al ejecutar. |
| `mediator.event_delivery` | El evento recibido llega a los participantes correlacionados. |
| `observer.event_delivery` | El evento llega al observador iterado; no demuestra intención de notificación. |
| `interpreter.binary_result` | Dos evaluaciones de hijos con el contexto original contribuyen al resultado; no fija suma como único operador. |
| `state.event_transition` | Correlaciona estado activo, contexto y evento original probado; no prueba factibilidad general de transiciones. |
| `flyweight.stable_intrinsic` | Un único almacenamiento explícito del estado intrínseco en el inventario soportado; no prueba ausencia de mutaciones ocultas. |
| `proxy.single_guarded_dispatch` | Un único sitio sintáctico de delegación cubierto por el modelo de guarda; no prueba cualquier política de acceso. |
| `chain-of-responsibility.single_exclusive_handler` | Procesamiento y reenvío se retornan directamente desde sitios distintos y usan el mismo request. No acepta toda implementación con temporales. |
| `composite.additive_aggregate` | Acumulación explícita con flujo, escrituras y orden correlacionados; no prueba cualquier fold ni un punto fijo del loop. |
| `iterator.advancing_element` | Retorna el elemento leído y avanza el índice en uno después de leer y antes de retornar. **No prueba límites ni terminación**, pese al nombre histórico del test `finite_sequence`. |

La variante nueva **`interpreter#context-free-binary`** reconoce gramáticas cuyo
contexto está en los terminales y cuyos nodos binarios combinan dos evaluaciones
sin argumentos. Se comprueba en Python, Java y TypeScript, con ruido y contrastes.
Recupera `PlusExpression`, `MinusExpression` y `MultiplyExpression` en iluwatar.

## Los 10 xfail que siguen abiertos

| Grupo | Casos | Por qué sigue abierto | Corrección necesaria |
| --- | ---: | --- | --- |
| Abstract Factory, familia uniforme | 3: Python/Java/TypeScript | El fixture declara categorías Button/Panel, pero la compatibilidad Ocean/Land sólo está en el oráculo externo. Inferirla por prefijos de nombres inventaría semántica. | Metadatos explícitos de compatibilidad de productos y un contrato seleccionable, con comportamiento para ausencia, conflicto y mezcla de familias. |
| Abstract Factory, objeto literal | 1: TypeScript | El literal es una colección; sus funciones no son slots de un proveedor de objetos en el modelo nominal usado por la consulta. | Identidad de objetos, miembros callable y versiones de propiedades; adaptar la consulta estructural sin fabricar clases nominales. |
| Memento, historia mutable | 3: Python/Java/TypeScript | La captura y restauración conservan el mismo array; una escritura intermedia altera el supuesto pasado. La consulta estructural no modela ese heap compartido. | Identidad de ubicaciones al capturar, aliasing, escrituras de elementos y su orden entre save/edit/restore; diferenciar valores inmutables, copias y unknown. |
| Prototype, estado independiente | 3: Python/Java/TypeScript | La copia superficial es un Prototype válido, pero no cumple una política de independencia. El fixture exige esa política a la raíz general. | Contrato explícito de independencia con evidencia de inmutabilidad o ubicaciones disjuntas; incluir contenedores anidados y efectos externos desconocidos. |

No basta añadir un `not exists WRITES` para los dos últimos casos: ausencia de
escrituras visibles no demuestra que no haya mutaciones mediante aliases o código
externo. Tampoco basta rechazar todos los arrays: excluiría copias independientes
válidas. Los tests siguen ejecutándose como expectativas pendientes estrictas.

## Segunda revisión contra repositorios abiertos

Se analizaron fuentes locales del corpus ya descargado, **sin ejecutar código de
los proyectos**. Se fijaron commits y hashes de fuentes. La comparación usa grafos
por ejemplo; no mezcla todos los ejemplos de un repositorio en una única familia.
Se ejecutaron las 23 consultas GoF raíz en cada ejemplo seleccionado.

| Repositorio | Ejemplos | Etiqueta encontrada, primera → final |
| --- | ---: | ---: |
| Eng-Elias/design-patterns-across-languages | 69 | 30 → 30 |
| JakubVojvoda/design-patterns-cpp | 24 | 10 → 10 |
| faif/python-patterns | 22 | 7 → 7 |
| iluwatar/java-design-patterns | 23 | 11 → 12 |
| RefactoringGuru/design-patterns-rust | 31 | 3 → 3 |
| ZoranPandovski/design-patterns | 110 | 25 → 25 |
| tmrts/go-patterns | 2 | 1 → 1 |
| **Total** | **281** | **87 → 88** |

PHP y Swift se inventariaron pero no se escanearon con un frontend estructural
soportado: sus cero casos no son negativos. Esta pasada no cubre todos los
ficheros de esos repositorios ni pretende medir cobertura de sus patrones web.
El [manifiesto final](corpus/manifest.json) conserva selección, commits, licencias
halladas, presupuestos y hashes del motor/runner; los JSON por repositorio conservan
matches y diagnósticos. La [primera pasada](corpus-initial/manifest.json) ya incluía
correcciones tempranas de este trabajo: **no es una línea base limpia de IR 1.77**.

Endurecer Prototype introdujo temporalmente una regresión real: `EmployeeRecord`
(Pandovski) dejó de encontrarse por sus constructores sobrecargados y `this()`.
La corrección de binding/retención lo recuperó, y se añadieron controles de
sobrecargas ambiguas, firmas variádicas y estado descartado. No se registra esa
recuperación como un aumento neto frente a la primera pasada.

### Auditoría manual: fallos comprobados y ambigüedades

[Etiquetas revisadas](reviewed-labels.json) y [resultados reproducidos](reviewed-results.json).
El oráculo se establece por entidad y comportamiento, no por el nombre de su
carpeta. Una consulta incompleta o un negativo con evidencia `unknown` no se
convierte en TN. Un match cierto puede contar como TP aunque otras alternativas
del mismo patrón tengan incertidumbre; esa información queda en el resultado.

| Fuente / consulta | Resultado | Causa y siguiente mejora |
| --- | --- | --- |
| Python `CompositeGraphic` / Observer | **FP** | Registro más iteración de hijos comparte forma con Observer, pero aquí dibuja un árbol. Requerir evidencia de notificación/cambio de estado en un contrato preciso; no excluir por estar en una carpeta Composite. |
| Python `Adapter` / Adapter | **FN** | `__dict__.update(**adapted_methods)` y `__getattr__` instalan métodos dinámicamente. Modelar mapas de miembros y procedencia de callables con claves conocidas; claves desconocidas deben conservar incertidumbre. |
| Python `Visitor` / Visitor | **FN** | Despacho extrínseco mediante `__class__.__mro__`, nombre `visit_` construido y `getattr` con fallback. Requiere modelo acotado de búsqueda de método y resolución de claves calculadas. |
| Rust `TrainStation` / Mediator | **FN** | Coordinación de una colección, ownership y despacho dinámico de participantes. La consulta actual se centra en campos/colegas nominales fijos. Añadir variante de participantes registrados con entrega correlacionada. |
| Java `PartyImpl` / Mediator | **FN** | Registro de miembros, `joinedParty(this)` y envío de `Action` excluyendo al emisor. Faltan correlaciones colección–miembro–mediador y el predicado de exclusión. |
| C++ `ConcreteCommand` / Adapter | **Ambiguo** | Una envoltura de comando también puede adaptar interfaces; la intención de diferir ejecución no excluye automáticamente Adapter. |
| Rust `TrainStation` / State | **Ambiguo** | Flags de ocupación y ramas pueden verse como estado de dominio sin implementar State de comportamiento. No se etiqueta automáticamente como FP. |

Los 10 TP incluyen Composite y Observer Python; Adapter, Command y Visitor C++;
Prototype Rust; Interpreter, Singleton y Visitor Java; y Prototype Java de
Pandovski. Los 5 TN incluyen combinaciones claramente ajenas y el `ChatRoom`
Python: su ejemplo imprime/formatea mensajes, pero no entrega nada a otro
participante. No se lo cuenta como FN sólo porque el directorio diga Mediator.

## Rendimiento y reproducción

Los números de rendimiento se publican en [benchmark.json](benchmark.json).
Se miden 35 ficheros ordenados por ruta por repositorio, cinco repeticiones,
alternando orden de ejecución y usando la mediana por consulta. La construcción
del grafo se mide aparte. La columna legacy ejecuta el catálogo congelado anterior
sobre **el mismo IR actual**; no compara el coste del lowering viejo ni demuestra
por sí sola que KQL 2 sea un motor universalmente más rápido. Las consultas
cambiaron semánticamente en esta revisión, por lo que una diferencia de matches
no se trata como fallo de migración sin inspección.

```sh
.venv/bin/pytest tests/structural tests/kql2 tests/common_ast -q -o addopts='' \
  --disable-warnings --junitxml=/tmp/ken-xfail-review-clean.xml

.venv/bin/python examples/bench/validate_pattern_corpus.py \
  --corpus /tmp/ken-pattern-corpus \
  --output docs/structural-validation/xfail-second-review-2026-09-14/corpus

.venv/bin/python examples/bench/review_open_source_patterns.py \
  --corpus /tmp/ken-pattern-corpus \
  --labels docs/structural-validation/xfail-second-review-2026-09-14/reviewed-labels.json \
  --output docs/structural-validation/xfail-second-review-2026-09-14/reviewed-results.json

.venv/bin/python examples/bench/catalog_kql2_migration.py \
  --repo /tmp/ken-pattern-corpus/python-patterns \
  --repo /tmp/ken-pattern-corpus/cpp-patterns \
  --repo /tmp/ken-pattern-corpus/guru-rust \
  --repo /Users/andres/Projects/infinidev --max-files 35 --repeats 5 \
  --output docs/structural-validation/xfail-second-review-2026-09-14/benchmark.json
```

Documentación normativa de las relaciones y sus límites:
[IR, contratos por uso](../../structural-ir.md#read-site-contracts-ir-178) y
[KQL 2, consultas sobre el grafo](../../design/kql2/graph-queries.md).

### Medición antes de integrar los perfiles de KQL 2

| Proyecto (35 ficheros) | Hechos | Construcción ms | Legacy ms | KQL 2 ms | Matches actuales |
| --- | ---: | ---: | ---: | ---: | ---: |
| python-patterns | 50246 | 442.5 | 385.4 | 360.9 | 42 |
| cpp-patterns | 32521 | 313.0 | 210.4 | 199.8 | 29 |
| guru-rust | 30697 | 343.3 | 212.4 | 200.5 | 4 |
| infinidev | 97605 | 1055.0 | 1050.2 | 1016.7 | 4 |

Compilación de catálogo: fría 677.3 ms; mediana con caché 6.2 ms.
Los totales de búsqueda suman medianas de las 33 raíces. No incluyen el coste de construcción ni certifican precisión.
