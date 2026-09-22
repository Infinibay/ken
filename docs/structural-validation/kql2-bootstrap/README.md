# Validación del bootstrap KQL 2

14 de septiembre de 2026. [Capacidades y pendientes](../../design/kql2/implementation-status.md).
Esta entrega no completa el plan ni migra el catálogo GoF/moderno a KQL2.

## Pruebas ejecutadas

```sh
.venv/bin/pytest tests/kql2 tests/structural/test_lazy_fact_index.py tests/structural/test_graph_cache_invalidation.py tests/structural/test_documented_kenql_queries.py tests/test_mcp_schema.py tests/test_tools_cli.py -q
.venv/bin/mypy src/ken/kql2 src/ken/structural_store --follow-imports=silent
```

**390 tests pasan:** 338 KQL2, 37 de regresión KQL1 y 15 de CLI/MCP. Mypy sin errores
en los 30 módulos KQL2/store. No se ejecutó de nuevo la suite completa del catálogo.

El [registro de conformidad](../../design/kql2/conformance-status.json) enumera los
96 contratos: 34 tienen un caso enfocado, 18 cobertura parcial y 44 siguen pendientes.
«Caso enfocado» no significa cobertura de todos los lenguajes/variantes.

Cobertura: familias de sintaxis/ejemplos, 300 mutaciones deterministas de entradas,
UTF-8/límites, rechazo de capacidades no implementadas, ramas correlacionadas,
higiene en invocaciones anidadas, condiciones por lenguaje/directorio y unknown;
scans indexados contra full scan, ownership/posición del receptor en cinco
lenguajes; migraciones, rollback inyectado, ownership/DDL/checksum, snapshots,
concurrencia de reader/writer, caché 0/pequeña/default, edit/add/delete y cambio
de frontend contra rebuild, invalidación aun conservando mtime y acceso por CLI.
Incluye caché LRU en memoria, single-flight local, recuperación real de planes y
resultados en otro proceso, corrupción de artefactos, migración 1↔2 preservando
el grafo, caché desactivada y exclusión de resultados incompletos. Los cálculos
tienen casos de alcance/tipos, barreras de errores, agregaciones distintas por
valor/tupla y cuantificadores sobre dominios vacíos o incompletos.

Se agregaron predicados/SCC, modelos y bibliotecas, enums, anti-joins, optional e
inventarios exactos; tipos fuente, enlace global, operaciones y BODY con
declaraciones/asignaciones/retornos/llamadas, ruido, adyacencia y prohibiciones de
escritura/llamada directa. Los casos BODY y proyección de contextos incluyen Python,
TypeScript, Java, C#, Go, Rust y C++. No extrapolar esa matriz a todos los contratos.
Hay regresiones de shadowing, argumentos nombrados/packs no resueltos, aislamiento
de ramas, semántica all de intervalos, errores ocultados por joins vacíos y ámbitos
de predicados internos de modelos. Las migraciones llegan a schema 5, con proyección
perezosa de unidades previas. GC/leases, captura entre procesos y reducción de cuota
con lectores activos tienen pruebas dedicadas.

La referencia full-scan comparte evaluación de expresiones/joins con el backend:
prueba equivalencia de acceso/planes, pero **no sustituye un oráculo semántico
independiente completo**. Los tests con resultados explícitos cubren errores que
esa comparación compartida no detectaría.

## Grafo sintético de 100.000 nodos

Las mediciones siguientes son históricas del bootstrap, anteriores a los nuevos
cálculos y cachés; sus archivos registran la revisión medida.

Reproducción:

```sh
.venv/bin/python examples/bench/kql2_bootstrap.py --output /tmp/kql2-100k.json
```

[Muestras, entorno, hashes y EXPLAIN](synthetic-100k.json).

| Medida | Resultado |
|---|---:|
| Construir/persistir/publicar el grafo ya generado | 1.096 s |
| Store asignado, incluidos índices | 12.72 MB decimales |
| Consulta exacta indexada, mediana de 7 | 0.035 ms |
| Full scan de referencia, mediana de 7 | 237.90 ms |
| Reabrir conexión/store y ejecutar consulta | 2.22 ms |
| Candidatos inspeccionados por consulta indexada | 1 |
| Candidatos inspeccionados por full scan | 100.000 |

EXPLAIN confirma acceso `k2_nodes_kind_name` por kind/name y membership indexada
por snapshot/unit. No hay memo de resultados: cada muestra ejecuta el buscador.
La reapertura conserva page cache del SO; no equivale a arranque frío de máquina.
No publicar p95 fiable con siete muestras ni extrapolar este caso al catálogo,
BODY, regex general o joins con gran fan-out. El tiempo de generación sintética
del IR no está dentro del tiempo de persistencia y se distingue del parsing real.

## Consulta estructural real: infinidev/src

[Consulta exacta, manifiesto con hashes, muestras y métricas](infinidev.json).
Se usó `ken.kql2.service.search(root, query, path="src", cache_mb=0,
timeout_ms=10000)`. No se ejecutaron fuentes del repositorio ni se escribió una
base en infinidev; el store temporal se cerró al terminar.

* 685 unidades parseadas; 1.747 pares clase–método; 2.394 candidatos inspeccionados.
* Captura/frontend: cobertura reportada completa; ejecución terminada; cero
  candidatos desconocidos para las propiedades concretas consultadas.
* Construcción: 42.80 s. Consulta: 93.21 ms. Total: 42.91 s.
* Una sola muestra end-to-end; no es una mediana ni comparación contra KQL1.

Se contrastaron tres pares contra sus líneas fuente: `AddStepTool._run`,
`AdversarialVerifier.__init__` y `AdversarialVerifier.verify`. Coincidían con las
clases y métodos declarados. La query filtra nombres de clase con inicial
mayúscula y ubicación en `src`; **no prueba visibilidad public ni patrones GoF**.
No se etiquetaron manualmente todos los 1.747 resultados: no hay una matriz
TP/TN/FP/FN exhaustiva de esta corrida.

El costo dominante fue la extracción del IR actual. Las pruebas incrementales
verifican que archivos sin cambios no se reparsan; todavía falta medir esa ruta
sobre este corpus completo y optimizar extracción/análisis, no sólo el SELECT.

## Límites que siguen abiertos

P11/P12 completos, resolución semántica universal de ámbitos, store tipado por
segmentos, valores producidos y BODY/control/efectos/iteración/concurrencia completos;
catálogo migrado; estadísticas/DP de joins; caché compartida con KQL1;
presupuesto global de memoria/spill y benchmarking completo Linux/macOS.
No interpretar ni estos resultados ni el parser como cierre de esas entregas.

## BODY sobre código real y optimización por contexto

[Consulta, manifiesto, resultados y verificaciones](infinidev-body-2026-09-14.json).
Sobre `infinidev/src/infinidev/code_intel`, 35 archivos, cache 0: una consulta busca
declaración de variable local seguida de retorno del mismo binding. Encontró 36
filas y 44 candidatos unknown. Los 36 retornos se contrastaron con `ast.Return`
de Python y todos retornan el identificador reportado. Se revisaron además los
cuerpos de `get_pooled_connection` y `_replace`; sus declaraciones y retornos
coinciden. No es un oráculo exhaustivo de flujo ni una medición de precisión GoF.

| Medida | Antes | Contextos indexados por callable |
|---|---:|---:|
| Captura/persistencia | 2.936 s | 3.411 s |
| Consulta, incluido enlace global demandado | 10.940 s | 4.749 s |
| Total | 13.884 s | 8.168 s |
| Estados | 116.749 | 116.749 |
| Filas / unknown | 36 / 44 | 36 / 44 |

El perfil detectó medición y descompresión repetida de unidades completas por
BODY. Schema 5 guarda padres/rangos/operaciones por owner; BODY recupera sólo el
callable requerido. Consulta aproximadamente 2.3× más rápida y total 1.7× en estas
muestras, a cambio de más trabajo de persistencia. Son muestras individuales,
sin vaciar cachés del SO; no una mediana ni garantía general. El manifiesto y los
resultados como conjuntos coinciden; los metadatos conservan las revisiones medidas.

## Comparación directa con KQL1

[Datos, consultas equivalentes y entorno](direct-engine-comparison.json), generados
por `examples/bench/kql2_compare_engines.py`: selección exacta sobre 100.000 clases,
15 repeticiones alternando motores, mismos IDs de resultado, sin memo de resultados.

| Consulta | KQL1 | KQL2 |
|---|---:|---:|
| Primera ejecución | 32.916 ms | 0.323 ms |
| Mediana con índices calientes | 0.0151 ms | 0.0371 ms |

KQL2 mejora el arranque de esta consulta, pero KQL1 gana con índices calientes.
La preparación medida realiza tareas diferentes (RAM frente a persistencia),
KQL1 incluye metadatos de evidencia adicionales y la caché del SO no se vació.
No demuestra que un motor sea universalmente más rápido ni mide parsing,
actualización incremental o búsquedas GoF completas.

La [repetición sobre schema 5](engine-comparison-2026-09-14.json) conserva ese
resultado cualitativo: primera consulta KQL1 **29.304 ms**, KQL2 **0.462 ms**;
medianas calientes KQL1 **0.0147 ms**, KQL2 **0.0457 ms**. Mismos 100.000 nodos y
15 repeticiones alternadas; el archivo incluye hashes de los módulos medidos.

## Entrega posterior: AST común

El [reporte del AST común](../common-ast-2026-09-14/README.md) actualiza esta
baseline con schema 6, normalización/ámbitos/símbolos, consultas y mediciones.
Los 390 casos anteriores describen la corrida previa, no el total actual.
