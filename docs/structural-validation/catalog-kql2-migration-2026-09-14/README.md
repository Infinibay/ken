# Migración del catálogo a KQL 2

14 de septiembre de 2026. La migración del catálogo activo está implementada:
**33 TOML, 138 consultas ejecutables** (23 GoF + 10 modernos; 90 variantes listas
+ 15 operaciones, además de las 33 raíces).

Los archivos mantienen sus explicaciones, restricciones, idiomas y claims. Cada
entrada ejecutable declara `language "kql/2"`, su módulo, un `pattern detect` con
roles públicos y una query `results`. Los IDs públicos anteriores se conservan.
Las variantes que representan contratos/algoritmos distintos siguen disponibles;
no se exige conservar variantes redundantes por compatibilidad. El único diseño
sin query, `persistence.unit-of-work#transactional-change-set`, sigue explícitamente
pendiente: no se confundió el seguimiento de cambios con una transacción probada.

## Implementación

* El parser KQL 2 acepta `edge`, `walk` y `tally`, composición con `use`, alternativas,
  comparaciones y alias. Sus contratos y ejemplos están en
  [consultas sobre el grafo](../../design/kql2/graph-queries.md).
* `structural/relational.py` contiene el plan y ejecutor compartido, separado del
  parser KenQL 1. El compilador KQL 2 produce esos operadores directamente: no
  imprime una query antigua, no entra en su parser y no genera código Python.
* Los grupos alternativos permanecen en el plan; no se expanden todas sus
  combinaciones. Una query que sólo proyecta un patrón elimina su llamada
  envolvente. Esto evita trabajo y preserva diagnósticos de pruebas alternativas.
* Los planes del catálogo son inmutables, con retención máxima de 8 MB; el catálogo
  medido ocupa aproximadamente 2,5 MB. La sintaxis empaquetada tiene una instantánea
  separada de unos 3,1 MB. Las filas y presupuestos son locales a cada ejecución.
  Se valida sólo la clausura de imports de cada consulta durante compilación.
* El servicio KQL 2 retiene un artefacto del grafo semántico normalizado en SQLite.
  El test de reapertura prohíbe cargar unidades o llamar al linker y aun así obtiene
  el mismo resultado. La cuota de disco sigue siendo configurable, 500 MB por
  defecto. Una captura de bibliotecas se conserva durante toda la petición para
  que una edición concurrente no publique una compilación bajo la clave equivocada.
* Se reutiliza schema 6. Las claves de resultados incluyen la nueva revisión del
  ejecutor; los artefactos incluyen las fuentes de bibliotecas y fingerprints de
  implementación. La migración no necesita borrar la DB.
* La selección pública de variantes, las ubicaciones y la presentación compacta
  siguen funcionando; el reporte reconoce los módulos KQL 2 además de los IDs `#`.
  El modo histórico sigue seleccionándose explícitamente.

## Validación

La ejecución completa terminó con **11.043 tests pasados, 111 xfail preexistentes
y cero fallos**, en 258 segundos. Después del último ajuste de captura de
bibliotecas, los **482 tests KQL 2/AST común** volvieron a pasar, incluido un test
adicional de rechazo explícito de perfiles incompatibles. Mypy: **42 archivos,
cero errores**. [Conteo y lista de pendientes](tests.json).

El fixture `tests/structural/catalog_matrix/pre_kql2_catalog.json` congela las
consultas originales antes de la migración. Es una referencia independiente del
texto nuevo, aunque ambos compiladores comparten el ejecutor relacional. La
comparación cubre todas las entradas sobre los **79 ejemplos multilenguaje** de
sus patrones padres, comparando bindings, status, incertidumbre y completitud.
No se modificaron los oráculos positivos/negativos para acomodar la migración.

La matriz adversarial existente tiene **2.314 tests verdes y 1 xfail previo**.
Se añadieron pruebas de literal frente a lista, regex, valores falsy, higiene,
correlación, alias, límites/ciclos de recorridos, modalidades, cierre para conteos,
rechazos antes de I/O, codec, inmutabilidad, invalidación de bibliotecas y caché
persistente. Hay tests que hacen fallar el parser antiguo si el catálogo intenta
entrar en él. También se valida la importación empaquetada desde el servicio KQL 2.

Los tests que inspeccionaban cadenas de sintaxis antigua se adaptaron a KQL 2;
los tests que ejecutan ejemplos positivos y negativos conservan sus expectativas.
La migración detectó y corrigió una pérdida de `cardinality:open_world` al añadir
una llamada envolvente, la etiqueta de variante del reporte compacto y la
selección explícita del dialecto histórico.

## Repositorios y performance

[Datos completos](benchmark.json), con revisión Git, selección de archivos,
lenguajes y SHA-256 de cada fuente. Son archivos de las copias locales; no se
compilaron ni ejecutaron los programas analizados. Se limita a los primeros 35
archivos elegibles por repositorio (C++ tiene 24). No es un escaneo integral de
infinidev ni una nueva clasificación manual de cada hallazgo.

Se compararon los 33 patrones en cada muestra: **132 comparaciones, cero
diferencias de resultados/incertidumbre/completitud y ningún análisis incompleto**.
En total: **129 archivos y 79 coincidencias**, iguales a las consultas anteriores.

Cinco repeticiones alternando el orden de ejecución. Los tiempos son la suma de
las medianas por patrón sobre el mismo grafo, con validación y sin cachear resultados.
No incluyen parseo/enlace, compilación del catálogo ni presentación. Son mediciones
locales, no límites de rendimiento ni intervalos estadísticos.

| Muestra | Archivos | Hechos | Matches | Queries anteriores | KQL 2 | Reducción |
|---|---:|---:|---:|---:|---:|---:|
| python-patterns | 35 | 49,785 | 42 | 398.4 ms | 328.6 ms | 17.5% |
| cpp-patterns | 24 | 32,400 | 29 | 187.0 ms | 167.9 ms | 10.2% |
| guru-rust | 35 | 30,238 | 4 | 182.4 ms | 165.7 ms | 9.2% |
| infinidev | 35 | 96,969 | 4 | 938.5 ms | 915.1 ms | 2.5% |

La carga fría del catálogo completo fue **614 ms**. Reutilizar el
registro ya leído costó **5.4 ms** de mediana; releer también los TOML
costó aproximadamente 25 ms en una medición separada. La primera implementación
validaba las 138 bibliotecas para cada entrada y tardaba unos 4 segundos; esa
repetición se eliminó antes de cerrar la migración.

Reproducción:

```sh
.venv/bin/python examples/bench/catalog_kql2_migration.py \
  --repo /tmp/ken-pattern-corpus/python-patterns \
  --repo /tmp/ken-pattern-corpus/cpp-patterns \
  --repo /tmp/ken-pattern-corpus/guru-rust \
  --repo /Users/andres/Projects/infinidev \
  --max-files 35 --repeats 5 \
  --output /tmp/catalog-kql2-benchmark.json
```

## Límites y continuación

La paridad demuestra que la migración no cambió esos resultados; **no demuestra
que todos sean TP/TN**, ni corrige los FP/FN conocidos. Los xfail siguen siendo
trabajo pendiente. Los claims sobre algoritmos y sus límites se conservaron.

Este perfil usa índices `FactIndex` en RAM, recuperables desde el artefacto de
disco; no traduce todo el catálogo a SQL ni implementa spill o cuotas globales de
memoria. Los selectores estructurales/AST de KQL 2 mantienen su backend de scans
SQLite. Todavía no se mezclan ambos perfiles en una misma query. BODY/control
completo, heap/alias/preserve, efectos transitivos, protocolos y concurrencia
siguen pendientes según el [estado](../../design/kql2/implementation-status.md).

El [inventario](inventory.json) mantiene por entrada el archivo, estado, idiomas,
módulo, imports, exports y hash de query. Permite seguir mejoras de los 23 GoF y
modernos sin confundir una variante propuesta con una consulta ejecutable.
