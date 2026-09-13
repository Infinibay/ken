# IR 1.46: algoritmos, instrucciones y continuidad de handlers

El [diseño en palabras](../../design/structural/algorithms-to-ir.md) describe
Builder, Memento, Observer y Cache-Aside antes de traducirlos a identidades,
operaciones, regiones e invariantes. El [núcleo](../../design/structural/instruction-ir.md)
separa valores temporales, bindings y direcciones de memoria; un grafo de
relaciones continúa siendo útil como índice de búsqueda.

## Implementado y pendiente

Hay exportación de cuerpos Tree-sitter al esquema `ken-instructions/1`, JSON
con roundtrip, impresor textual, verificador y CLI. Incluye declaración, lectura
y escritura de binding; direcciones de campos/índices y acceso a memoria;
llamadas, operadores, regiones if/while y suspensión. Conserva tipos y fuente.
Las formas sin lowering soportado son native/partial con efectos desconocidos.
`lowered` indica cobertura de las reglas de traducción, no exactitud semántica
completa: incluso una función lowered puede contener llamadas desconocidas.

`preserve_binding` comprueba un intervalo dentro de una región y distingue
preserved, violated y unknown. El modo explicit-writes sólo inventaría escrituras
explícitas; el modo strict además exige efectos conocidos. No certifica el heap,
aliases ni convenciones de paso. No hay todavía gramática body/preserve en KenQL;
las queries siguen ejecutándose sobre el grafo existente. Copy/ref, operaciones
generales de colecciones y la migración del buscador siguen pendientes.

La [salida rename](instruction-rename.txt) es generada por el código actual.
Las operaciones copy.value y collection.* del diseño son contratos propuestos,
no instrucciones ya disponibles.

## Builder en seis lenguajes

La nueva matriz tiene **48 casos: 30 positivos y 18 negativos**, en Python,
JavaScript, TypeScript, Java, C# y Rust. Usa un producto almacenado con una parte
anidada; Rust finaliza mediante clone derivado. Agrega logging antes/después de
configurar y al finalizar, cálculos independientes y renombrado. Los negativos
entregan otro producto, sobrescriben el dato o reasignan la entrada.

Todos pasan con la query existente: estas transformaciones no requirieron
relajar Builder. Eso demuestra estabilidad sobre esta muestra; no una mejora
de recall global ni equivalencia de programas. El análisis no prueba que un logger
arbitrario sea puro o que nunca lance una excepción. Son tests de parsing y
análisis de fuentes propias, no compilación de los seis lenguajes.

## Mejora externa de Retry

NORMAL_COMPLETION distingue terminación normal posible, abrupta y no soportada.
LOOP_BODY_TAIL identifica el último statement del cuerpo; HANDLER_FALLTHROUGH
conecta un handler normal con su try. La nueva variante exige además el retorno
del intento dentro del try. Finalmente, `do_statement` se normaliza como bucle:
el CFG ya lo conocía, pero el inventario de operaciones no, impidiendo el enlace.
Finally/recursos, factibilidad de condiciones y dispatch de excepciones no
se consideran resueltos; el CFG de excepciones continúa siendo partial.

Los [escaneos comparados](ir146-modern-comparison.json) usan exactamente los
mismos archivos y commits antes/después, diez reglas modernas y un control de
generadores. Todas las queries finalizan y no hay diagnósticos de parsing.

| Alcance | Archivos | Retry antes → después | Revisión |
|---|---:|---:|---|
| iluwatar, retry/src/main/java | 8 | 0 → 2 | TP: Retry.perform y RetryExponentialBackoff.perform |
| Tenacity, tenacity/ | 12 | 0 → 0 | FN conocido: coordinación mediante estado y acciones |
| Flask, src/flask/ | 24 | 1 → 1 | FP de intención Retry: fallback entre loaders distintos |

Los dos casos Java terminan naturalmente el catch y repiten un do/while tras
fallar la llamada retornada. La regla identifica la estructura, sin certificar
backoff, idempotencia o seguridad concurrente. Flask muestra por qué falta
correlacionar el destino entre iteraciones. Los JSON por proyecto registran
roles, fuente, hashes, commits, presupuestos y resultados:
[iluwatar](ir146-iluwatar-retry-after.json), [Tenacity](ir146-tenacity-after.json),
[Flask](ir146-flask-after.json). No se ejecutó código de estos proyectos.

## Rendimiento observado

| Alcance | Parseo/enlace antes → después, ms | Query Retry antes → después, ms |
|---|---:|---:|
| iluwatar retry | 86.41 → 93.05 | 0.209 → 3.389 |
| Tenacity | 794.09 → 823.56 | 0.225 → 0.319 |
| Flask | 2218.02 → 2369.31 | 37.159 → 37.105 |

Son observaciones individuales locales, no un benchmark estadístico antes/después.
Retry ahora evalúa otra variante; no se afirma mejora de velocidad. El
[microbenchmark de exportación](ir146-instruction-performance.json) mide 50
iteraciones después de cinco warmups sobre grafos preparados. Las medianas de
exportar y verificar rename son 0.079–0.120 ms en ocho lenguajes; Retry.java tarda
0.249 ms y conserva cuatro funciones parciales. Excluye parsing, queries, impresión
y caché. Corrió con la suite de tests concurrente; no mide rendimiento de escaneo
de un repositorio ni costo de un buscador sobre el nuevo núcleo.

La caché existente conserva su configuración de 500 MB por defecto. No se añadió
Rust ni una caché de instrucciones en esta entrega.

## Regresión GoF y empaquetado

La [comparación del corpus](ir146-corpus-regression.json) conserva **74 presencias
esperadas en 281 ejemplos**, con cero cambios en los conjuntos de matches y
**6.463 consultas completas**. Los archivos, scopes y commits son idénticos a la
medición 1.45; los hashes de los reportes y el manifiesto están en el JSON. Las
presencias no constituyen una matriz de precisión/recall por implementación.

El [wheel verificado](ir146-wheel.json) contiene los mismos 67 módulos/TOML que
el motor de los escaneos. Se construyó con uv y pasó roundtrip JSON, preservación
de binding e impresión fuera del checkout. No se ejecutaron repositorios ajenos.

La [verificación final](ir146-checks.json) pasa **5.931 tests en 304.72 s** y mypy
en 107 archivos. Los nuevos módulos de tests suman 212 casos: 107 de terminación
normal, 37 de instrucciones, 20 de preservación y 48 de Builder. La selección de
261 incluye además los tests de ejemplos de ambas guías. El JSON registra hashes
del motor y los tests; los enlaces locales de los documentos modificados fueron
verificados.
