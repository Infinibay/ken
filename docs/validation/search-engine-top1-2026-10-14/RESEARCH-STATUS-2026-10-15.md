# Estado verificable del motor de búsqueda — 15 de octubre de 2026

El mejor resultado válido de la API experimental es **286/400 (71,5%) top‑1
estricto**, frente a233/400 (58,25%) del control API anterior. Son53 respuestas
correctas adicionales (+13,25 puntos). La política3 de evidencia74b reproduce
ALL400 con fuente7, mismos16modelos251 y consultaCPUreal. Exige archivo, entidad canónica o fragmento
prepermitido y TODAS las líneas decisivas originales visibles. **No alcanzamos
90%, no superamos todavía la comparación pública de Semble y no promovimos el
perfil al checkout original.** La reserva independiente sigue sin abrirse.

## Evidencia principal

- `output/development/cpu-complete-owned-api-v74b-loo/`:286strict/298identidad,
  ALL400/16workers0, política de evidencia3 explícita. Cada unidad/evidencia
  reproduce72c preparado; respuestas completas byteidénticas a74symbol, SHA
  `58c24a5525ad8d8ab3dc9281b494f2de403eb6278ee49648d6926c6acf553c99`.
  EN171/240,ES115/160,implementación223/320,identidad44/48,tests19/32.
  Los102 fallos de entidad y12deanclas siguen siendo misses, sin bajar criterios.
  Revisión: `output/analysis/complete-owned-api-v74b-review.{md,json}`.
- Política3 muestra unión propia completa≤40líneas/3fragmentos cuando cabe;
  conserva el top1/score de69.77consultas cambian evidencia y4tails10→9 por12kJSON,
  permitido por el límite superior10, sin excluirconsultas. Un selector compartido
  preserva el dedup de archivos en ambos caminos; POCfile de74 corregido en74b.
  397tests amplios,6módulosmypy y16perfileslegacy exactos; revisión21.860casos
  de selección sin cambios al orden/budgets. Commitdbcfb95.
- API74b p50=722,81ms,p95=1506,18ms,max=3082,27ms,RSSmáximo1275,92MiB.
  15/16repos cumplen p95 aproximado1s/100ci_files; Logrus641,42ms vs640ms.
  Corridas concurrentes, no certificado aislado. Ningún resultado usaGPU.
- Serie69 anterior (fuente7 y vistas251, misma clasificación de owners):

- `output/development/cpu-source7-context-views-v69-loo/`:285strict/298identidad,
  ALL400,16workers exit0, fuente7 real,251features y modelos excluyen su repo.
  Revisión independiente: cada resultado/evidencia de las400 consultas coincide
  con el preparado69 salvo score;0faltantes/errores/stale, máximo10hits/40líneas/
  12000charsJSON. EN170/240, ES115/160, implementación222/320, identidad44/48,
  tests19/32; macro71,25%. CandidateRecall@100395/400, disponibilidad no top1.
  Fuente: `output/analysis/source7-context-views-api-v69-review.{md,json}`.
- API69 p50=677,75ms,p95=1406,61ms,max=2889,27ms; RSS máximo1273,86MiB,
  llamadas al encoder contextual0:37/1:219/2:144. Son observaciones concurrentes;
  falta certificar el presupuesto porci_files y RAM sin contención.
- Los puntos siguientes conservan la serie previa235 como control histórico:

- `output/development/cpu-contextual-v42-loo/`:277strict/290identidad,16workers,
  400IDs únicos, sin faltantes. Cada modelo excluye todo el repositorio evaluado.
- `cpu-token-reuse-v46-loo`, `cpu-distinct-terms-v50-loo` y
  `cpu-stem-reuse-v56-loo` y `cpu-stem-reuse-v56b-loo`: las400 respuestas COMPLETAS son idénticas a42,
  SHA256 `e3ae62e0cc3aade1b26b4de094d11a1f72adb17acbd29c1cc8f7fe2fdbed7ca6`.
  La igualdad incluye score, orden, fragmentos y metadatos públicos; no sólo top1.
- EN169/240 (70,42%); ES108/160 (67,5%); implementación213/320 (66,56%);
  identidad44/48; tests20/32; macro por repositorio69,25% (serie histórica42).
- Revisión43:123 fallos =110 de ordenamiento con owner elegible,8 de fragmento,
  5 de partición/delegación. CandidateRecall@100392/400 (98%) es disponibilidad,
  no acierto del primer resultado ni respuesta bajo presupuesto.

## Qué se probó y qué se descartó

Todos los controles numéricos de esta tabla mantienen400 consultas, referencias,
scorer estricto, presupuestos y16folds con exclusión completa del repositorio.
Son controles preparados, salvo las filas que nombran explícitamente API.

| Control | Top‑1 estricto | Decisión |
|---|---:|---|
| API contextual235 (42/46/50/56/56b/65) |277/400,69,25%| API histórica; superada por69 |
| Geometría centrada / ABTT / whitening45 |275 /275 /278| El único hit adicional preparado no justifica su complejidad; no promovido |
| Documentación correcta47b/c, pool/contexto antiguo fijo |271/400,67,75%| Conservar corrección de fuente; descartar su ranking |
| Relaciones sintácticas agregadas51 |270/400,67,5%| No incorporar67 señales sin mejora |
| Esquema117 columnas, objetivo trunc1 (52) |276/400,69%| Sin mejora; aún no evita calcular campos en runtime |
| Transporte geométrico53, mejor fusión fija |252/400,63%| Descartado |
| Reranker22,7M entrenado34b, CPU |152/400,38%| Descartado |
| Quantización pareada44, embeddingsFP32 |160/400,40%| No rescata al reranker |
| 12 fusiones fijas de ventanas49, mejor |211/400,52,75%| Todas inferiores al API235 |
| Grafo de llamadas54/54b |No elegibles| Rechazados por destinos de llamada incorrectos; resultados y testigos preservados |
| Sólo declaraciones parent/child54c |274/400,68,5%| Geometría fiel, calidad inferior |
| Adaptador contrastivo pequeño55, mejor fusión |252/400,63%| Descartado; sin otro encoder |
| Hechos individuales y cláusulas57 |272/400,68%| Fuente fiel, matemática probada insuficiente |
| Índice completo extractor6 + propuestas nuevas58 |277/400,69,25%;291identidad| Mismo acierto estricto; integridad relativa verificada, defecto C heredado descubierto después |
| Ventanas entrenadas dentro de cada owner60b |269/400,67,25%;290identidad| Orden de owners fijo; descartar selector |
| Vistas contrato/cuerpo59b y API67 |283/400,70,75%;297identidad| Fuente6 diagnóstica; no transferir a7 |
| Vistas contrato/cuerpo69, API fuente7 |285/400,71,25%;298identidad| Misma clasificación que74b; aún lejos del90% |
| Token interacción mismo137M61 |284/400,71%;299identidad| Preparado267 en fuente6; sin API/fuente7 |
| ColBERT pequeño33,4M70b,267/283 |272 /277 de400| No mejora; descartar incorporación |
| Geometría local por archivo71c,264/264/272 |285 /277 /284 de400| Ninguna mejora estricta; no incorporar |
| Contexto propio completo72c/API74b |286/400,71,5%;298identidad| +1 confirmado en API, mismo orden, política3 explícita |
| Owners dentro del archivo62 |270/400,67,5%;283identidad| No mejora; archivo top1 conservado |
| Quitar marco inicial de consulta63b |277/400 reemplazo;276 añadido| Ninguna mejora; consultas/negación/identificadores preservados |
| Contexto de ocurrencias literales64 |276/400,69%;290identidad| Fuente mecánicamente verificada; no son destinos de llamada; no mejora |

54/54b no certifican destinos: CALLEE_VALUE puede elegir sobrecargas incorrectas,
redefiniciones anteriores y miembros de clase donde Python busca un global.
No se rebautizaron esas hipótesis como targets válidos para conservar su score.
El subgrafo de27384 parent/child canónicos sí pasó auditoría; su control separado
54c tampoco mejoró. Informes independientes bajo `output/analysis/`.

En57 se recodificaron independientemente TODOS los271625 textos fuente únicos:
vectores exactos y448100 relaciones con spans propios.429 textos superan512tokens
bajo la política explícita. Las cláusulas son señales textuales; combinar hechos
de ramas distintas no prueba simultaneidad, orden, negación ni ausencia.
Se corrigieron dos bordes de comillas sin cambiar la segmentación de ninguna de
las400 expansiones medidas; identidad de entradas registrada, no estimación nueva.

## CPU y RAM: mejora medida, certificación pendiente

En56, p95 por repositorio va de~0,748 a3,161s. Ejemplos50→56: Regex3,957→3,161s,
JUnit2,218→1,849s. Los16 perfiles/modelos/requests/contextos coinciden y las400
respuestas son idénticas. **Corridas concurrentes: no son un certificado final
sin contención ni permiten atribuir universalmente toda diferencia a una edición.**

Pico RSS del worker principal:~555,94–1139,08MiB, sin Torch/Transformers cargados,
proveedoresCPU explícitos. No es RAM agregada de procesos ni una medición aislada.
Seis repos pequeños aún superan el presupuesto p95 aproximado de1s/100ci_files:
Anyhow,Attrs,Boltons,CommonsCSV,Logrus,Packaging. No se ocultan esos incumplimientos.

La caché lexical limita16384 identificadores de hasta256codepoints; la de stems,
32768 palabras de hasta128codepoints. Sólo conserva transformaciones puras.
La revisión56 midió20,54MiB de heap retenido en su probe de stems; no es RSS total
ni cota universal. El refinamiento56b conserva la API batch e incluye la factory
en la clave para no reutilizar otra implementación inyectada.357 pruebas de
parsers/retrieval/bench pasan, incluido el test concurrente anterior sin cambios;
la primera ejecución fallida y la corrección quedaron guardadas. El pareado API56b
también completó400/400:277strict/290identidad,16workers exit0 y exactamente el
mismo SHA de respuestas completas. Tiene su propio recibo de ejecución; las
medidas de heap de la clave anterior no se atribuyen a la nueva clave con factory.

## Comparación pública y trabajo en curso

La comparación pública COMPLETA48 usa las1251 consultas originales/63pins y el
scorer original: Ken macroNDCG@10 **0,8365028637**, micro0,8368466502, top1906/1251
(72,42%), frente a Semble macro **0,8543853796** y935/1251. El anterior21 era
0,8189553482 y857/1251. Mejora+0,0175475; brecha restante0,0178825. No se excluyeron
consultas ni repositorios y no hubo errores/faltantes. El235model sólo se entrenó
en los16repos de desarrollo disjuntos; esta comparación pública es investigación,
no aceptación ciega. Las referencias públicas son mayormente archivo, no nuestro
contrato estricto. Semble sigue arriba. El perfil experimental y el default del
checkout original siguen separados.

48 completó100235owners/248452pasajes/12074archivos fuente antes de consultas.
Los63workers terminaronexit0. El parent falló únicamente al importar Semble para
el scorer final en la venv de API;48b conserva1251 respuestas intactas, valida
hashes originales y puntúa con la venv de Semble instalada, sin cambiar el scorer.
Ambos intentos y recibo suplementario quedan guardados. RSS descriptivo porworker
394,45–749,48MiB, sin Torch/Transformers importados; p95 entre160,10–14212,50ms.
31/63repos exceden el presupuesto aproximado1s/100ci_files en estas corridas
concurrentes. No es certificación aislada ni victoria en recursos.

58 reconstruyó16 índices reales6:6314ci_files/hashes/lenguajes,6139conpasajes,
50967owners/124839pasajes;2535docs corregidos,48384vectores iguales+2523nuevos.
La auditoría relativa verificó geometría heredada, no toda la propiedad sintáctica:
64 descubrió el parserC antiguo aplicando offsets de texto sin comentarios al
original, y contando llaves de strings/comentarios. Los objetivos400 no incluyen
archivosC, pero el defecto impide una afirmación universal de fidelidad de fuente.
Los277strict/291identidad de58 siguen siendo la medición de ese índice concreto.

La correcciónC revisada y commit5eeae99 usa el grammar ya instalado y bytes
originales, firmas/docs/scopes reales, macros reconocidas por tokens AST, ramas
elifdef y funciones GNU anidadas canónicas.20 pruebasC focales, testigos físicos,
los5archivosC públicos y256parses concurrentes verificados independientemente.
EXTRACTOR_VERSION7 obliga reparse real por la comprobación existente de versión
retrieval.66/66b quedan intentos anteriores a los bordes de revisión;66c es el
freeze revisado, no fueron mutados.66c completó todos16índices/contextos antes de
consultas:6314archivos/50967owners/124851pasajes,0cambios de identidad deowner,
50884vectoresfull byteidénticos+23nuevos. Propuestas/fits frescos7 completos:278/400strict y292identidad con235columnas.
69 añade las vistas propias correctas:285/400, reproducido en API.

59b completó400/251features y16folds:283strict/297identidad en fuente6;
API67 reproduce283/297 sin faltantes. Auditoría independiente de50967owners/
101934unidades y167374filas confirma texto propio y16nuevas+8heredadas columnas.
Commit ef974ba: API pública251, un encoderCPU/query compartido, pool fullowner
fijo, vistas mapeadas sólo para candidatos, hashes/spec/generación fijados.

69 regeneró fuentes/vistas/pools para7 y volvió a ajustar los16folds:285/298.
API69 también285/298 con ALL400, sin heredar el resultado6. Se verificaron todas
las6314fuentes/50967owners,124851pasajes y23vectores nuevosCPU byteexactos;
0identidades cambiadas. La suite completa fue387tests, no386; core5mypy limpios.

61 completó fuente16/400features y267fits:284/400strict,299identidad, fuente6.
Es la misma graph137M con proyección128dim/int8/mmap, no un ColBERT entrenado.
La guardia de overflow pasó7tests+mypy y20000filas ordinarias independientes
exactas; freeze original61 intacto. No se promovió ni se transfirió su score a7.

70 preparó con un ColBERT oficial33,4M/ONNX33,95MB todos los101316textos fuente7
únicos antes de consultas. Query128 se declara extensión de32; fuente300,96dim,
compactaciónint8 con error medido.70b añade guardia completa antes del fit de
68archivos/167360posiciones/800textos;9tests y mypy, parent251prefijo exacto.
El70 original se conserva, sus entradas reales coincidían pero su comprobación
genérica no rechazaba una futura reordenación del cache.70b267=272/400 y283=277/400:
ambos inferiores a69, no incorporar el modelo adicional ni atribuirle scoreBEIR.

71c usa los mismos768vectores porowner/query y medias de los6139archivos, sin
encoder nuevo. Centrado264=285, ortogonal264=277, juntos272=284; ninguna mejora
estricta.71b numéricamente idéntico se conserva con error de procedencia: declaraba
Potion256 aunque los DB/query reales eran CodeRank768.71c deriva todo de nuevo y
verifica registro contextual/grafo/tokenizer/proyección exactos, no renombra71b.

72c muestra la unión propia completa si cabe40líneas/3fragmentos;5tests+mypy,
no cruza gaps de hijos y no cambia pesos/orden/scorer. ALL400:286strict/298identidad,
77consultas cambian evidencia.72/72b fallaron sólo assertions del controlador
antes de puntuar (número visible bajo12k y spellingtarget), preservados.72c exige
baseline idéntica a69 y prefijo del mismo orden completo; el recorte bajo12k sigue
contando todos los misses. API74/74b reprodujeron286/298;74b corrige selección porarchivo y la política3
queda explícita/optin. No se promueve al checkout original ni se abre aceptación.

Auditoría suplementaria posterior64: los545textos públicos únicos/800vistas de
400consultas recodifican byteexacto contra31. Cada ID/texto/prefijo/vector queda
ligado porhash y16recodesCPU independientes coinciden. Cierra la incertidumbre de
procedencia de entradas, sin inventar un registro de startup original en31.

65 agrupa coberturas independientes sin cambiar6valores, parámetros ni fuentes.
Revisión33924vistas/96filas completas exactas más16000filas raíz y prueba real
ALL400API:277strict/290identidad,16workers0, respuestas completas SHA e3ae62e0cc3aade1b26b4de094d11a1f72adb17acbd29c1cc8f7fe2fdbed7ca6.
P95descriptivo56b→65 Regex3212→2993ms,Attrs1678→1410,JUnit1887→2035;
RSS554,25–1142,03MiB. No se ocultan regresiones ni se atribuye causalidad aislada.
Commit01a487a. Suite completa posterior387tests;8tests de API/vistas focales
incluyen el uso público de search con251features y bypass exacto. Core5módulos
mypy limpio; el worker experimental conserva2import-untyped preexistentes
ORT/tokenizers, sin supresiones ni cambios de criterios.

73 evalúa dos modelos generales de pares4,4M/22,7M, ONNXCPU de4,52/23,20MB.
Tiny ya completó16repos/400features;Mini y los3controles259/259/267 siguen en curso.
75 prepara adaptación Tiny4,386,049parámetros enCPU con3epochs fijos y16folds
excluyendo todo el repo.75 completó sólo el baseline pretrained400 y se detuvo
intencionalmente antes del primer fit: revisión encontró falta de binding esperado
DATA/scores y empate raw distinto al protocolo. Las167360filas/scores actuales
fueron independientemente correctos.75b añade SHA esperado66c/69/72c y ties69→pool;
falló antes de ajustar porque el checkpoint oficial tiene un buffer no persistente
position_ids extra.75c verifica ese buffer canónico y los41tensores persistentes
exactos, hash/freeze/cache y16probes porrepo bitidénticos. La revisión independiente
pre-fit75c pasó sin bloqueos; ajuste fijo de16folds ahora en curso.75/75b conservan
0folds y sus fallos. Parámetros/modelos/grupos/criterios iguales;7tests/mypy del
sampler. Todavía sin calidad adaptada ni adopción.

76 repite la comparación pública actual7/251/evidencia3 sobre1251/63pins. Reindexado
real y fullcontext+vistas fuente completas antes de consultas públicas; un251modelo
fijo entrenado sólo en16reposdev disjuntos ya está exportado con igualdad nativa
en167360filas. El adapter de investigación exige corpus explícito completo para63
y conserva compatibilidad16;19tests focales+8core y mypy1 verdes. Fuentes en curso,
API espera preparación completa y revisión antes de consultas. Sin resultado aún.

Faltan90% estricto y sus estratos, superar Semble en su métrica original, la
aceptación ciega, el perfil final CLI/MCP y la validación aislada de CPU/RAM.
Ninguno se declara resuelto por estas pruebas de desarrollo.
