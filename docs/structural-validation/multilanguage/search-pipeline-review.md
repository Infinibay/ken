# Rendimiento del pipeline de búsqueda estructural

Medición local reproducible con el
[runner](../../../examples/bench/validate_search_pipeline.py) y
[resultados completos](search-pipeline-baseline.json). Snapshot IR 1.47.0;
los hashes de cada módulo y regla están en el JSON. El runner comprobó que los
archivos del motor no cambiaron durante la ejecución.

La comparación final usa cinco muestras por caso antes y después, con el mismo
catálogo y sin suites/corpus propios ejecutándose simultáneamente. En los tres
scopes mejoró `search` completo, con resultados idénticos. Existe una regresión
del batch aislado en Flask; se conserva explícitamente abajo. Los tiempos no
miden precisión ni permiten extrapolar velocidad a un repositorio completo.

## Método y alcance

Se analizaron fuentes reales ya descargadas: **39 archivos, tres lenguajes**.
No se importó ni ejecutó código de esos repositorios. Los archivos seleccionados
se copiaron a directorios temporales conservando rutas relativas; la caché se
creó allí, sin modificar los checkouts upstream.

| Caso | Commit upstream | Alcance | Archivos | Bytes de fuente |
|---|---|---|---:|---:|
| Retry Java, iluwatar | `41625d8d354cdf6b6f10a82e29c2392b3efd5d20` | `retry/src/main/java/` | 8 | 22.451 |
| Flask Python | `d73fa1cdcbd8b1465c151db8924ba58b1dd14e35` | `src/flask/` | 24 | 348.253 |
| Chain Rust, RefactoringGuru | `f4a1499d13e8b27fa75e4e8ff9fd9bed645d23ca` | `behavioral/chain-of-responsibility/` | 7 | 4.315 |

Cinco repeticiones por caso, 33 queries (23 GoF y 10 modernas), modo `strict`.
Presupuesto independiente por query: 1.000 matches, 500.000 filas, 100.000
estados y 2.000 ms. Cada medición conserva tiempos individuales, completitud,
diagnósticos, estadísticas de caché y fingerprints de resultados.

«Fría» significa SQLite IR vacío, con parser/intérprete y páginas del sistema
operativo ya calientes. «Caliente» repite la misma búsqueda con un hit del grafo
completo. No mide arranque de un proceso nuevo ni vacía la caché del sistema
operativo. La capacidad utilizada es el valor predeterminado de **500.000.000
bytes**, pasado explícitamente para evitar variaciones por configuración local.

Esta caché del grafo **ya existía** antes de la optimización. Los cambios de esta
revisión reducen indexación y compilación repetidas; no añaden una caché persistente
de resultados de queries ni de índices. Un hit sigue reconstruyendo objetos
desde JSON y preparando la proyección de búsqueda.

Los percentiles usan nearest rank: con cinco observaciones, p95 es el máximo.
Es una muestra pequeña de diagnóstico, no una estimación robusta de una cola
de producción. Los perfiles cProfile y el pico tracemalloc proceden de pasadas
adicionales excluidas de los tiempos siguientes. Las etapas se miden de forma
independiente y algunas se solapan: **no deben sumarse**.

## Comparación final, motores estables

Los artefactos [antes](search-pipeline-quiet-before.json) y
[después](search-pipeline-quiet-after.json) registran archivos y reglas idénticos,
motores sin modificaciones durante cada corrida y fingerprints iguales en las
30 muestras de caso (15 antes y 15 después), entre las cuatro vías de ejecución.
Todas las búsquedas completaron. Se ejecutó primero el baseline y después el
motor actual: corridas secuenciales en condiciones tranquilas, no un experimento
aleatorizado. No se usan los tiempos de la pasada concurrente preliminar.

El baseline es el motor de `ken_rank-0.14.0-py3-none-any.whl` anterior a estas
optimizaciones **con las 33 reglas actuales superpuestas** para fijar el trabajo.
No es una medición del wheel intacto. El [manifiesto de origen](search-pipeline-baseline-wheel-origin.json)
conserva SHA del wheel y catálogo; cada JSON conserva los hashes efectivos del
motor importado. Ambas corridas usaron el mismo Python y parsers.

Milisegundos, **p50 / p95**. La razón usa p50 antes / después:

| Caso | Búsqueda | Antes | Después | Razón |
|---|---|---:|---:|---:|
| retry-java | Caché fría | 288.5 / 299.7 | 169.4 / 177.5 | 1.70× |
| retry-java | Caché caliente | 161.4 / 164.1 | 68.0 / 74.4 | 2.37× |
| flask-python | Caché fría | 7495.3 / 7524.7 | 5039.7 / 5221.9 | 1.49× |
| flask-python | Caché caliente | 2717.5 / 2804.0 | 2207.6 / 2300.3 | 1.23× |
| chain-rust | Caché fría | 188.9 / 208.3 | 98.2 / 114.6 | 1.92× |
| chain-rust | Caché caliente | 118.8 / 133.7 | 50.7 / 51.9 | 2.35× |

La mejora combina índices de extremos bajo demanda, reutilización de compilación
dentro de la petición y deduplicación de recorridos convergentes. Esta medición
no aísla cuánto aporta cada cambio. El caso sintético del recorrido no representa
el speedup de estos repositorios. La caché de grafo de 500 MB ya existía.

| Caso | Enlace semántico antes → después p50 | Batch público antes → después p50 | Pico Python antes → después |
|---|---:|---:|---:|
| retry-java | 48.8 → 33.5 ms | 55.3 → 25.0 ms | 6.03 → 4.83 MB |
| flask-python | 3636.0 → 1066.1 ms | 376.0 → 722.9 ms | 164.94 → 130.30 MB |
| chain-rust | 16.2 → 8.6 ms | 48.1 → 17.7 ms | 3.13 → 2.61 MB |

**Flask sigue tardando 2,21 s p50 con caché caliente para sólo 24 archivos.**
`build_project` caliente ocupa 1,15 s p50; siguen pendientes deserialización,
reconstrucción de objetos e índices y proyección. El pico Python no es un límite
de memoria de producción: la pasada instrumentada construye/proyecta/exporta
manteniendo otras representaciones vivas.

### Regresión del batch y probes descartados

En Flask, `execute_rules` aislado pasó de **376,0 / 865,3 ms** a
**722,9 / 770,4 ms** p50/p95. Engine preparado pasó de 115,4 a 179,5 ms p50.
Parte del trabajo se movió desde crear el índice a consultar sus extremos, pero
la regresión del batch completo incluye esa preparación y no se oculta como un
simple cambio de etapa. El perfil actual atribuye 854 ms instrumentados a
`_endpoint`, principalmente durante la estimación del planner; el anterior
atribuía 232 ms al constructor eager. No deben compararse esos tiempos
instrumentados con los percentiles sin instrumentación.

Se probaron dos alternativas sin modificar producción:

- [Materializar ambas propiedades](search-pipeline-hybrid-probe.json) tras
  proyectar: batch 803,0 ms y warm 2.413,4 ms p50, peores que el motor actual;
  sólo desplaza coste y aumenta asignaciones. Descartado.
- [Constructor eager original sólo para queries](search-pipeline-query-index-gc-probe.json),
  conservando pases fuente lazy: cinco muestras alternadas por política, un solo
  grafo fuente retenido, sin exportación ni tracemalloc, GC habilitado. Batch
  lazy/eager **516,8 / 505,0 ms p50**, **574,5 / 675,8 ms p95**; warm
  **1.611,3 / 1.555,3 ms p50**, **1.660,0 / 1.575,1 ms p95**. El 2,3–3,5% de
  mejora de mediana y la peor cola del batch no justifican otro cambio. Las 20
  ejecuciones conservaron fingerprints y completitud. GC consumió medianas
  cercanas a 246 ms batch y 964 ms warm con lazy; eager hizo más colecciones y
  gastó aproximadamente 246/927 ms. No se deshabilitó GC ni se alteraron umbrales.

Este último harness retiene menos representaciones: sus tiempos absolutos no
se mezclan con el pipeline completo. El coste de asignación/GC y la preparación
de índices siguen siendo objetivos de trabajo futuro; no se integró ninguno de
los dos experimentos.

### Smoke de todas las definiciones ejecutables

Una pasada adicional ejecutó **104 definiciones únicas: 33 roots, 56 variantes
ready y 15 operaciones ready**, con los mismos presupuestos. Los
[resultados completos](search-pipeline-all-definitions.json) contienen tiempo,
estados, filas y los cinco casos más lentos por corpus. **312/312 completaron**.
Son tiempos de una sola pasada sobre grafos preparados, no percentiles ni
latencias públicas end-to-end:

| Caso | Total 104 definiciones | Definición más lenta |
|---|---:|---|
| retry-java | 33.2 ms | `resilience.exception-retry`: 3.6 ms |
| flask-python | 663.5 ms | `resilience.exception-retry`: 166.1 ms |
| chain-rust | 20.5 ms | `strategy#strategy-callable`: 0.4 ms |

Que una definición complete con cero matches no prueba cobertura positiva de su
patrón; la matriz de precisión y los contratos multilenguaje son verificaciones
separadas.

## Diagnóstico inicial anterior a las optimizaciones

Milisegundos, **p50 / p95**:

| Etapa | Retry Java | Flask Python | Chain Rust |
|---|---:|---:|---:|
| Parseo/lowering | 16,3 / 33,0 | 458,2 / 807,2 | 8,7 / 9,7 |
| Enlace semántico | 46,8 / 48,9 | 3.671,9 / 3.772,0 | 14,1 / 25,3 |
| Índice del grafo fuente | 1,6 / 21,2 | 70,6 / 133,2 | 0,8 / 15,1 |
| Proyección e índice de query | 6,0 / 11,0 | 220,9 / 764,4 | 3,0 / 17,2 |
| Exportar instrucciones | 2,4 / 2,6 | 565,7 / 592,2 | 1,4 / 1,5 |
| Verificar instrucciones | 0,2 / 0,3 | 9,1 / 22,9 | 0,1 / 0,2 |
| Ejecutar 33 queries ya preparadas | 11,0 / 27,1 | 115,9 / 121,2 | 5,0 / 5,2 |
| `execute_rules` público | 53,6 / 70,2 | 371,8 / 893,6 | 45,8 / 46,4 |
| `search` público, caché fría | 273,4 / 276,3 | 7.055,8 / 7.485,3 | 178,5 / 184,0 |
| `search` público, caché caliente | 153,8 / 160,0 | 2.544,9 / 2.705,2 | 115,5 / 130,9 |
| Sólo `build_project`, caché caliente | 29,1 / 30,1 | 1.473,1 / 1.565,1 | 15,1 / 16,0 |

La caché del grafo reduce el tiempo p50 end-to-end aproximadamente 1,78×, 2,77×
y 1,55× en estos casos. No es una caché del resultado de búsqueda: siguen
ocurriendo reconstrucción del grafo, proyección, validación y evaluación de las
queries. Los tiempos de motor preparado excluyen compilación del registro,
creación del índice y enriquecimiento de resultados de la API pública.

## Tamaños y completitud

| Medida | Retry Java | Flask Python | Chain Rust |
|---|---:|---:|---:|
| Entidades | 190 | 6.064 | 98 |
| Operaciones fuente | 1.197 | 32.497 | 720 |
| Hechos fuente / query | 5.877 / 6.213 | 164.120 / 173.863 | 2.953 / 3.055 |
| JSON grafo fuente | 2,54 MB | 52,10 MB | 1,22 MB |
| JSON proyección query | 2,76 MB | 57,20 MB | 1,28 MB |
| JSON instrucciones | 0,193 MB | 5,397 MB | 0,091 MB |
| SQLite físico | 225.280 B | 4.362.240 B | 122.880 B |
| Pico Python, construir/proyectar/exportar | 6,03 MB | 163,98 MB | 3,14 MB |
| Funciones de instrucciones lowered / partial | 3 / 20 | 38 / 362 | 3 / 13 |

Los 15 grupos de mediciones conservaron fingerprints idénticos entre motor
preparado, batch público, búsqueda fría y búsqueda caliente. Todas las queries
terminaron dentro del presupuesto y todos los alcances tuvieron cobertura de
archivos sin diagnósticos ni recortes. Cada búsqueda caliente tuvo un hit de
grafo, cero misses y cero evicciones; cada fría tuvo `archivos + 1` misses.

La verificación de instrucciones pasó en los tres casos, pero predominan cuerpos
`partial`: la validez estructural de la exportación no significa modelado
semántico completo. Tampoco que `coverage_complete` sea verdadero implica que
todos los símbolos externos o todos los comportamientos estén resueltos.

Los 500 MB limitan el archivo SQLite, **no la memoria RAM del análisis**. El pico
tracemalloc mide asignaciones Python de una pasada adicional; no incluye todos
los recursos nativos. El JSON guarda también el máximo RSS acumulado del proceso
instrumentado (aproximadamente 1,24 GB), que retiene múltiples representaciones
durante el benchmark y no es una medición aislada de una llamada de producción.

## Cuellos observados en el diagnóstico inicial

1. **Registro y parsing repetidos en scopes pequeños.** En Retry, el perfil
   instrumentado de `execute_rules` fue 152 ms: `parse` acumuló 103 ms y
   `query_registry` 78 ms. En la búsqueda caliente, parsing acumuló 234 de
   363 ms y el registro 171 ms. Son tiempos solapados, no porcentajes sumables.
   La API valida antes de escanear y vuelve a compilar el registro al ejecutar.
   Reutilizar un registro validado e inmutable dentro de una petición puede
   quitar trabajo sin cambiar presupuestos ni semántica. Si se añade caché entre
   peticiones, debe invalidarse por contenido de las reglas y dependencias.
2. **Construcción repetida de índices durante el enlace.** En Flask, cProfile
   atribuyó 3,49 s a siete construcciones de `FactIndex` dentro de un enlace de
   5,31 s instrumentados. `collection_snapshots`, `binding_writes` y
   `call_bindings` acumularon cerca de 0,9 s cada uno. El índice fuente aislado
   del benchmark no es el único índice que se construye: el pipeline semántico
   lo rehace varias veces. Conviene reutilizar índices por etapa o revisar qué
   relaciones necesita cada pase, manteniendo invalidación al agregar hechos.
3. **Rehidratación y proyección en caché caliente.** En Flask, `build_project`
   caliente aún toma 1,47 s p50. El perfil de búsqueda atribuye 834 ms a
   `IR.from_dict` y 347 ms a decodificar JSON; `query_graph` acumula 1,32 s en
   esa pasada instrumentada. Hay trabajo sobre decenas de megabytes aunque
   SQLite sólo ocupe 4,36 MB comprimidos. Una proyección serializada o un
   caché de índice en proceso necesita contrato de versión y límites de RAM.
4. **La evaluación preparada no domina estos repositorios.** Las 33 queries
   toman aproximadamente 5–116 ms p50 con grafo y registro preparados. Retry
   es la regla más costosa en Flask (~38 ms en la primera muestra), pero no
   explica los segundos de extremo a extremo. Un speedup sintético de traversal
   no debe proyectarse automáticamente a estos scopes.

La prioridad depende del tamaño: eliminar compilación repetida tiene impacto
visible en scopes pequeños; reducir reconstrucción, deserialización y proyección
es más relevante en Flask. Este runner no modifica el motor.

## Optimización del índice derivada del perfil

`FactIndex` ahora construye inicialmente sólo la agrupación por relación. Los
índices de sujeto y objeto se materializan por relación y dirección al pedirlos.
Los pases que sólo recorren determinadas relaciones dejan de crear buckets para
todos los extremos de todos los hechos del grafo.

Se conserva el snapshot de pertenencia: agregar hechos al IR después de crear
el índice no los introduce retroactivamente. Las propiedades públicas
`by_subject` y `by_object` materializan la vista completa, conservando orden de
inserción, duplicados originales y listas ya devueltas. Cuando se piden ambos
extremos, `rows` sigue devolviendo el bucket menor, con preferencia por sujeto
en empate; no cambia silenciosamente a una intersección.

Las [pruebas diferenciales](../../../tests/structural/test_lazy_fact_index.py)
comparan con la implementación eager anterior, incluyen snapshots, vistas
públicas, lecturas concurrentes y una query sobre un grafo de fuente real.
Pasaron 197 pruebas junto con KenQL/paths y 433 con pases semánticos/GoF
seleccionados. Esos conjuntos se solapan; no deben sumarse. El archivo nuevo contiene 20
pruebas propias. La validación integradora posterior terminó con 7.257 passed y
149 xfailed; el corpus de regresión mantuvo sus 6.463 ejecuciones completas y
resultados exactos. Estos totales no convierten xfails en funcionalidad soportada.

Parte del trabajo de indexación se desplaza a la primera consulta que pide un
extremo. Por eso el tiempo de Engine «preparado» puede crecer mientras baja el
tiempo total. El límite de tiempo de una query también puede incluir esa primera
materialización; no se promete identidad de tiempos ni estadísticas de coste,
sino conservar filas candidatas, evidencia, orden y resultados para presupuesto
suficiente. Los índices son snapshots de hechos inmutables durante su uso.

## Resultados no equivalen a precisión

Se conservaron cuatro candidatos en Retry, 23 en Flask y cero en el scope Rust.
Estos conteos comprueban estabilidad del benchmark, no TP/TN/FP/FN. No se
volvieron a etiquetar manualmente todos los matches. En particular, el candidato
Retry de Flask ya tenía una ambigüedad conocida de fallback entre proveedores;
que la query complete rápido no convierte ese candidato en verdadero positivo.

## Reproducción

```sh
.venv/bin/python examples/bench/validate_search_pipeline.py \
  --case retry-java /tmp/ken-pattern-corpus/java-patterns retry/src/main/java/ \
  --case flask-python /tmp/ken-real-repos/flask src/flask/ \
  --case chain-rust /tmp/ken-pattern-corpus/guru-rust behavioral/chain-of-responsibility/ \
  --repeats 5 --require-stable \
  --output /tmp/ken-search-pipeline.json
```

Las rutas y commits exactos, versiones de parsers, muestras individuales,
estadísticas por regla y perfiles están incluidos en el JSON. Las mediciones
proceden de macOS ARM64 y no controlan la carga de otros procesos; para comparar
cambios pequeños conviene repetirlas en condiciones similares y alternar orden.

Para reproducir las pasadas auxiliares, usar los mismos `--case` y añadir
`--all-definitions-only`. El probe de índices usa únicamente el caso Flask con
`--query-index-probe --repeats 5`; `--eager-query-endpoints` reproduce el otro
experimento. Son políticas temporales del runner, no configuraciones del motor.
La comparación baseline requiere extraer el wheel cuyo SHA está registrado,
superponer el catálogo registrado y señalar esa extracción con `PYTHONPATH`.

Nota de procedencia: el encabezado genérico `diagnostics_enabled` de los JSON
de smoke/probe históricos refleja la opción CLI, aunque esos modos no ejecutan
cProfile/tracemalloc. Su campo `mode` y el método del caso describen la ejecución
efectiva. El runner actual corrige ese metadato; no se retocaron los artefactos
medidos ni sus hashes para hacerlo parecer retrospectivamente igual.
