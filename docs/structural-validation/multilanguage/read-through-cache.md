# Read-Through Cache — IR 1.33.0

## Implementación y pruebas

La novena regla moderna/web, `architecture.read-through-cache`, conserva en su
TOML el recorrido de hit con retorno temprano y miss con carga/escritura/retorno.
La operación pública `.read_fill` expone ese uso sin afirmar ownership; la query
canónica añade un campo de caché construido por un método de la misma clase.

El IR incorpora TRUTH_TEST y el inventario de escrituras por callable:
UNREASSIGNED_BINDING, UNIQUE_BINDING_WRITE y BINDING_WRITE_STATUS. La query combina
esos hechos con CFG_NEXT y RETURN_ORIGIN, evitando unir rebindings o asignaciones
históricas con el valor final. Los [contratos y ejemplos](../../design/structural/read-through-cache.md)
publican las garantías y sus límites.

**213 pruebas nuevas**: 147 del patrón/operación en cinco lenguajes, 50 de predicados,
14 del inventario de escrituras y dos ejemplos ejecutables de la guía. Incluyen
controles compuestos, sobrescrituras, destinos/argumentos equivocados, salidas
antes de carga/escritura, argumentos expandidos, caché recibida desde fuera y
serialización del IR. Son fixtures de análisis; no programas objetivo ejecutados.

La suite completa pasa **3.703 tests en 141,23 s**; mypy pasa en **98 archivos**.
El wheel offline contiene todos los módulos y TOML estructurales, verificados byte
por byte contra el manifiesto. También se verificaron las consultas y el fragmento
fuente del capítulo de diseño mediante el analizador. El paquete extraído del wheel
pasó además el catálogo de nueve reglas, un positivo y un negativo por valor
sobrescrito, cargando sus módulos fuera del checkout.

## Dos recorridos externos confirmados

Se analizaron los mismos **14 archivos Java** de `caching/src/main/java/` de
iluwatar/java-design-patterns, commit `41625d8d354cdf6b6f10a82e29c2392b3efd5d20`.
La referencia [IR 1.32.0](ir132-iluwatar-caching.json) se ejecutó desde su wheel;
el [escaneo IR 1.33.0](ir133-iluwatar-caching.json) conserva fuentes y reglas anteriores.

| Método de CacheStore | Presencia / retorno de hit | Carga / escritura / retorno de miss | Evaluación |
|---|---|---|---|
| readThrough, línea 74 | contains en 75; get y return en 77 | readFromDb en 80; set en 81; return en 82 | Recorrido Read-Through confirmado. |
| readThroughWithWriteBackPolicy, línea 121 | contains en 122; get y return en 124 | readFromDb en 127; set en 133; return en 134 | Recorrido Read-Through confirmado; el protocolo adicional de write-back no queda certificado. |

Son **dos métodos de una misma clase proveedora**, no dos clases independientes.
CacheStore.initCapacity construye el LruCache en la línea 62; el constructor llama
a ese método. La inspección de LruCache confirma el almacenamiento con HashMap,
la lectura por clave y la organización LRU. Las llamadas contains/get/set no se
clasificaron únicamente por sus nombres al revisar estos dos resultados.
Fuentes: [CacheStore](https://github.com/iluwatar/java-design-patterns/blob/41625d8d354cdf6b6f10a82e29c2392b3efd5d20/caching/src/main/java/com/iluwatar/caching/CacheStore.java#L74)
y [LruCache](https://github.com/iluwatar/java-design-patterns/blob/41625d8d354cdf6b6f10a82e29c2392b3efd5d20/caching/src/main/java/com/iluwatar/caching/LruCache.java#L72).

Los [testigos completos](read-through-cache-witnesses.json) conservan campo,
construcción, clave, test de presencia, receptor del loader, llamadas y ambos
retornos. Las evaluaciones terminan completas y sus matches son structural_match.
El match Cache-Aside de AppManager.findAside y los doce de inyección de dependencias
anteriores permanecen. El nuevo detector no sustituye esa clasificación ni afirma
resolver invalidación, evicción, escritura diferida o flush.

## Regresión del corpus y otros proyectos

La [regresión GoF](ir133-corpus-regression.json) conserva todos los matches y
**59/281 presencias esperadas**, sobre 736 archivos únicos, 745 apariciones por
caso y 6.463 consultas completas. Los dos recorridos de caché son evidencia
moderna separada y no se suman a ese numerador.

[Requests](ir133-requests.json), 19 archivos; [Flask](ir133-flask.json), 24;
[RxJS](ir133-rxjs.json), 123; [Commons IO](ir133-commons-io.json), 277; y
[log](ir133-rust-log.json), nueve, conservan todos los matches y roles anteriores.
Flask ejecuta ahora las nueve reglas modernas y no tiene matches de Read-Through.
Todos los escaneos completan sin diagnósticos de parsing en su alcance registrado.

Esto no mide precisión/recall global ni certifica TN en todo archivo sin matches.
Las ambigüedades de intención y los FN ya documentados siguen abiertos. La matriz
propia demuestra rechazo de contraejemplos concretos, no cobertura de todas las
implementaciones de caché de esos lenguajes.

## Rendimiento observado

Sobre el grafo completo del módulo caching de catorce archivos:

| Etapa | Muestras | Mediana | p95 de la muestra |
|---|---:|---:|---:|
| Read-Through canónico | 30 | 1,829 ms | 1,938 ms |
| Operación pública read_fill | 30 | 1,712 ms | 1,948 ms |
| Cache-Aside canónico | 30 | 0,829 ms | 0,914 ms |
| Construcción de vista de consulta | 5 | 22,364 ms | 24,702 ms |

Las queries usan índice/registro ya construidos; excluyen parseo/enlace, caché de
disco y CLI. La vista se mide aparte. p95 usa rango más cercano y describe sólo
las muestras. El escaneo registró 206,44 ms de parseo/enlace con carga concurrente;
no es una comparación controlada entre versiones. La caché continúa en 500 MB
decimales configurables.

## Reproducción

```sh
.venv/bin/python -m pytest tests/structural/test_read_through_cache.py tests/structural/test_truth_tests.py tests/structural/test_binding_writes.py tests/structural/test_documented_ir_queries.py
.venv/bin/python -m pytest -o addopts='' -q
.venv/bin/mypy src/ken
.venv/bin/python examples/bench/validate_structural_repo.py /tmp/ken-pattern-corpus/java-patterns --prefix caching/src/main/java/ --collection modern --output /tmp/caching-ir133.json
.venv/bin/python examples/bench/validate_pattern_corpus.py --corpus /tmp/ken-pattern-corpus --output /tmp/corpus-ir133
```

Los manifiestos registran commits, hashes de fuentes/motor, presupuestos y
exclusiones. No se ejecutan scripts, builds, macros o programas de los repositorios
objetivo. Async, serialización, indexadores, miss por sentinel y protocolos de
invalidación/concurrencia necesitan modelos adicionales.
