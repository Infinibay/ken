# Revisión independiente RepoQA / CORE v224

**APTO para el protocolo y el grader revisado**, limitado a los SHA de este informe y a sus guardas de cierre. No queda un defecto bloqueante concreto de scoring identificado. Esto permite que el finalizador puntúe **cada track después de cerrar todas sus respuestas**; RepoQA exige además cerrar la repetición de infraestructura preregistrada. No certifica que las capturas actuales hayan cerrado ni afirma ningún resultado de calidad.

Revisé los cinco archivos pedidos, los dos archivos nuevos del grader autorizados después, el registro y los evaluadores públicos fijados. No leí respuestas/capturas/reportes reales, qrels reales, `repoqa-references.json`, reservas o Gold privados; tampoco ejecuté motores, modelos, preparación o benchmarks. Del gzip público sólo analicé corpus/metadata de funciones y referencias oficiales para la identidad y sus rangos, sin comparar con salidas de Ken. No modifiqué código, consultas ni referencias.

## Hallazgos corregidos antes de calificar

1. **Identidades nulas.** El helper original `public_benchmarks_v222.py:46–56` intentaba `entity.get` antes de rechazar una pieza de archivo; `entity=None` o `entity_span=None` causaban un crash. `grade_public_v224.py:15–18` ahora devuelve falso si esos campos no son dicts. El grader usa ese wrapper en su bucle de scoring. La copia original del helper, fijada por los capturadores, permanece intacta. Tres fixtures null verificadas no reciben crédito y no abortan el denominador.
2. **Ligadura de referencias RepoQA.** El grader comprueba el SHA del gzip original, reconstruye los600 IDs por idioma/repo/ordinal y sus referencias, y exige igualdad completa de `name`, `path`, rangos de líneas/bytes, idioma y repo con el archivo generado (`grade_public_v224.py:103–113`). Ya no basta conservar los IDs mientras cambian las respuestas esperadas.
3. **Ligadura de metadata CORE.** El grader ahora valida `core-sources.json` contra `sources_sha256` **antes** de interpretar `raw_folder`/`public_query_id` (`132–135`). Los mapas de documentos y los qrels leídos después conservan sus comprobaciones de SHA (`134`, `143–150`).

El conjunto de **14 pruebas focales pasó** independientemente. Dos probes de `main` con tracks sintéticos sin cierre demostraron rechazo antes de cualquier lectura de referencias/qrels; sólo se abrieron registro y requests de esas fixtures. No ejecuté `main` contra datos/capturas reales.

## Identidad RepoQA: soporte y límites del proxy

La clave usada para esta comprobación es **(repo de la consulta, archivo exacto, hoja normalizada del nombre, fin de definición)**. Archivo y contexto de repo son indispensables: no afirmo unicidad de hoja+fin ignorando ambos.

Examiné **todos los46.152 registros `functions` oficiales**, no sólo las needles:

| Lenguaje | Funciones |
|---|---:|
| Python | 11.164 |
| C++ | 3.617 |
| Java | 14.049 |
| TypeScript | 1.857 |
| Rust | 10.565 |
| Go | 4.900 |
| Total | 46.152 |

**Cero colisiones de la clave. Las600 needles resuelven exactamente un registro cada una.** Sus rangos de líneas/bytes están dentro del contenido publicado. En Python,100/100 needles coinciden además con el inicio/fin de `ast.FunctionDef`/`AsyncFunctionDef`;20 tienen decoradores y ninguna necesita retroceder más de10líneas para incluirlos. La publicación incluye600 consultas en6lenguajes/60repos; la mención a500/5 del README del evaluador no describe esta versión descargada.

Por tanto, la regla ya registrada —archivo+tipo callable+hoja+fin exacto y comienzo hasta10líneas antes— tiene soporte como **proxy de identidad para este corpus**. No mide exactitud de un fragmento ni suficiencia. Rechaza crédito por clase o archivo. Un DTO inventado con otro qualname y los mismos hoja/fin puede pasar el helper: la unicidad se verificó sobre las declaraciones oficiales, no sobre metadatos arbitrarios, callables no listados por la gramática oficial o una extensión futura del corpus. También el gate de inicio es una tolerancia registrada, no una prueba sintáctica de que todas esas líneas sean decoradores. No se cambió esa regla tras observar salidas.

Una correspondencia futura más precisa podría fijar desde toda la fuente, sin resultados, la clave canónica del callable que contiene el intervalo público y comparar esa clave completa; no la implementé ni se aplicó a esta corrida. Una ausencia o ambigüedad de identidad no debe convertirse en crédito por archivo.

## Métricas: no son intercambiables

**RepoQA.** Este control recupera piezas sobre todo el contenido **shipped**, con10slots nativos. El scorer produce Top1/Top10 de identidad, MRR@10 y NDCG de una única pieza relevante; el crédito por archivo se publica aparte. Eso **no es** el SNF generativo oficial. En el evaluador original, `needle_evaluator` sanea código generado, opcionalmente elimina comentarios, calcula BLEU suavizado frente a las diez needles del repo y exige que la mayor similitud corresponda al target más un umbral (`repoqa/compute_score.py:154–189`, `repoqa/metric.py:10–20`). El contexto oficial se construye alrededor de la needle con presupuesto/posición, en lugar de buscar en todo el snapshot. No procede presentar estas métricas de identidad como score del leaderboard SNF o como evidencia de superioridad frente a sus valores publicados.

**CORE.** La unidad es el documento/chunk publicado identificado por `_id`; no una función canónica ni necesariamente un archivo original. Los qrels pueden ser multirrelevantes: Hit@10 significa encontrar **alguno**, Recall@10 es la fracción de documentos relevantes, y NDCG@10 pondera su posición. El `acc@10` del colector oficial exige **todos** los relevantes en el top10 (`collect_core_bench_results.py:145–161`); no es el Hit@10 local. Recall@100 no se mide con diez slots.

Contrasté las fórmulas locales con `calculate_metrics` del colector oficial en **1.000 fixtures binarias con relevantes no vacíos**, órdenes de distintas longitudes y relevancia múltiple: Hit@10, Recall@10 y NDCG@10 fueron exactamente iguales. El grader exige qrels binarios (`149`) y que sus positivos estén presentes en el filtro público (`154`); no intersecta etiquetas para reducir artificialmente su denominador. No se verificaron aquí los qrels reales ni se calcularon aciertos. El piloto de18casos/3repos/2niveles no equivale al conjunto ni a un grupo oficial completo.

## Filtro CORE y wrapper de texto

El uso de `filtered_corpus_id` **está autorizado por el propio evaluador público**: los loaders lo guardan separado de `relevant_docs` (`src/tasks/core_bench_level2_tasks.py:77–101`, igual en Level3), y `run_mteb.py:93–106` / `run_bm25.py:134–152` filtran por pertenencia. `register_core_v224.py:53–67` toma esa lista pública, o todo el corpus si falta; no usa qrels para escoger candidatos. La elección de los tres repos pequeños también se confirmó usando exclusivamente tamaños públicos: Flask2.426.170B, seaborn4.502.186B y requests4.629.274B sumando ambos corpus. Son los tres menores de los12repos presentes en ambos niveles de Verified. No es una selección por facilidad o aciertos.

Escribir cada `text` original como UTF-8 bajo `documents/<UUID>.txt` conserva **los bytes del texto publicado** según el writer (`register_core_v224.py:56–60`) y da una identidad de documento reversible por el mapa fijado. No inventa una ruta o lenguaje de origen. Sin embargo, eso **no conserva todas las señales de una búsqueda sobre repositorio original**: extensión/lenguaje para parser, módulos/clases/callables y ownership, proximidad entre fragmentos de un mismo archivo, jerarquía de directorios y nombres de ruta semánticos pueden perderse o cambiar. El texto literal que ya contenga esos datos permanece; el wrapper no los restaura estructuralmente. «Neutral» significa ausencia de etiquetas añadidas, no igualdad matemática o de prestaciones con el índice original.

Además, CORE oficial recupera sobre el corpus completo y aplica el filtro después; aquí se construye un proyecto por subconjunto elegible. La pertenencia es la misma, pero estadísticas lexicales, agrupación e IDF/preselección pueden diferir. Es una **variante de pipeline declarada**, no evidencia de contaminación por qrels ni equivalencia exacta con resultados oficiales.

El capturador registra archivos no indexados y exige que los indexados pertenezcan al snapshot (`capture_public_v224.py:111–118`), pero no exige cobertura total. Si un wrapper `.txt` no fuera indexable o perdiera estructura, el fallo debe seguir contado y explicarse como límite del adaptador; esta revisión, sin leer capturas, no certifica que toda la fuente se haya indexado realmente.

## Separación de etiquetas, cierres y recursos

Los requests RepoQA contienen descripción original y metadata operacional, sin `name/path/rangos`; los CORE contienen texto público y el root filtrado. Las referencias se guardan fuera de los snapshots. El registrador descarga qrels pero no los interpreta para crear corpus o requests. Los workers de captura no abren referencias/qrels. Esto evita una vía directa de contaminación de etiquetas en estos scripts; **no prueba ausencia de exposición de los modelos preentrenados a proyectos públicos** ni sustituye una auditoría de su entrenamiento previo.

`load_closed_results` exige cierre, denominador y exactamente los IDs esperados, rechaza duplicados/mutaciones y conserva errores. Para RepoQA, la política WasmEdge v225 limita la repetición a un fallo de infraestructura previamente identificado, exige cerrar también ese reemplazo y sólo sustituye un grupo cuyos resultados originales son errores (`grade_public_v224.py:90–100`). Esto ocurre antes de abrir referencias; la política y ambos cierres quedan ligados al resultado. Se revisó la política, **no la evidencia de ejecución/captura real ni sus salidas**. Esa verificación corresponde al cierre posterior, sin selección por labels.

El capturador valida el manifiesto del engine y los bytes fuente, separa preparación, registra providers CPU y presupuesto del reranker, y el grader reporta `timed_queries`. Los tiempos incluyen el trabajo visible de consulta/render; RSS es el pico del proceso, con preparación hija aparte, no memoria exclusiva de una única consulta. Pueden correr otros trabajos concurrentes. **No se certifica latencia aislada, aceleración causal ni memoria global sumada de la máquina.**

## Finalizador v226: revisión de código adicional

`finish_public_v226.py` cierra la repetición antes de entrar en el bucle de grading, conserva fallos como respuestas vacías con error y luego exige simultáneamente el marker de revisión con SHA exacto del grader y el cierre total del track. Revalida el SHA del grader en cada ciclo (`44–55`); el grader, a su vez, valida todos los pins/IDs de los cierres. Un fallo del grader detiene el finalizador y no se ignora. El worker v225 difiere de v224 **sólo en el directorio de destino**; no hay cambio de queries/configuración/engine en ese diff.

No ejecuté el finalizador ni abrí su log o sus capturas. Su espera inicial reconoce `AssertionError` en el log del hijo anterior (`24–26`): esto no es por sí solo una prueba independiente de terminación de ese proceso. El cierre real de la repetición y la ausencia de carreras deben verificarse en la auditoría de ejecución, no se infieren de esta lectura. El marker liga el grader, no todos sus imports: esta aprobación supone también que el helper transitorio `public_benchmarks_v222.py` conserva el SHA listado abajo; se verificó que actualmente lo conserva. No se observó drift ni se califica la guarda como un sistema universal a prueba de mutaciones arbitrarias.

## Pines de esta revisión

Registro: `6baac2ad522d0df30d812c6427c75ec90b9b403e6ea0677aa00bc4317e790a0b`. Gzip RepoQA: `c050a2ad90a7df89d9dc1f1c3b3b20683edd20a56293b35fcaae43dec115d681`.

Evaluador RepoQA HEAD: `ae876deb1365dbf5a15b0533723c8ed123eee586`; CORE HEAD: `5d00cdcaade77796fa6e5ac4852404002029c00a`. Los archivos oficiales examinados no tienen diff respecto a esos HEAD. Dataset CORE registrado: `23da5d97a8a4495d4bd6d5616aa86d5a12a60699`.

| Archivo | SHA256 |
|---|---|
| `public_benchmarks_v222.py` | `d1ff983c46f260520275d222d2fe605f283ce606c10297531f0d7ecde26109d8` |
| `test_public_benchmarks_v222.py` | `28807f16beed3e5df3efbcc5e4e30ceb86b28f9a72abe1af92669783bca46867` |
| `register_public_v222.py` | `36c97f2bd813e323ef82b505e768f8c29549c87fb276ab741d89fa8d8b6b7dcd` |
| `register_core_v224.py` | `7bc068b83fa31a13ab4dcb4d69f99f735ae6e5ebeb868adc9d2231ab035b06f9` |
| `capture_public_v224.py` | `8396469c7631b53d5af67268e814c9fe3f78e0399ad852038223225a683f4897` |
| `grade_public_v224.py` | `b9a7c6e3b1e3e7ea99ba010a04f22ceddaf07675eb480359fb002e7bcfa74c1a` |
| `test_grade_public_v224.py` | `e5a2f3d12b9c2fdba0d32fecc01e897e1be5b571656a0140c86810a8435eb25f` |
| `capture_public_v225.py` | `00182da028db998f152b6981faac475404ef58bb6db89349a466c75b2fafbbdb` |
| `finish_public_v226.py` | `6c0cd6107c8d70b427574c8a3f0814f0e0f1cb34763714e1bfd19298cf903df9` |

Probes sintéticos: `3678f79af9811ac867540c87b952963b45d2eedb6d7acc4ae4aadfb9b6d39540`. Política de repetición: `eab177f00c283aa553057a421e3684c5ecfe1af0c889dac6eacf493aa3df115c`. Recibo JSON de esta revisión: `a3b59b3eeb68bda27f5bbaaa2c9321bad7ae7f8b9a8a17d0178c686a3caa78a7`.

Este cierre no abre ningún marcador ni reserva, no aprueba un resultado aún no auditado y no autoriza ajustar el engine con estos benchmarks.
