# Estado verificable del motor de búsqueda — 15 de octubre de 2026

El mejor resultado válido de la API experimental es **277/400 (69,25%) top‑1
estricto**, frente a233/400 (58,25%) del control API anterior. Son44 respuestas
correctas adicionales (+11 puntos). Exige archivo, entidad canónica o fragmento
prepermitido y TODAS las líneas decisivas originales visibles. **No alcanzamos
90%, no superamos todavía la comparación pública de Semble y no promovimos el
perfil al checkout original.** La reserva independiente sigue sin abrirse.

## Evidencia principal

- `output/development/cpu-contextual-v42-loo/`:277strict/290identidad,16workers,
  400IDs únicos, sin faltantes. Cada modelo excluye todo el repositorio evaluado.
- `cpu-token-reuse-v46-loo`, `cpu-distinct-terms-v50-loo` y
  `cpu-stem-reuse-v56-loo` y `cpu-stem-reuse-v56b-loo`: las400 respuestas COMPLETAS son idénticas a42,
  SHA256 `e3ae62e0cc3aade1b26b4de094d11a1f72adb17acbd29c1cc8f7fe2fdbed7ca6`.
  La igualdad incluye score, orden, fragmentos y metadatos públicos; no sólo top1.
- EN169/240 (70,42%); ES108/160 (67,5%); implementación213/320 (66,56%);
  identidad44/48; tests20/32; macro por repositorio69,25%.
- Revisión43:123 fallos =110 de ordenamiento con owner elegible,8 de fragmento,
  5 de partición/delegación. CandidateRecall@100392/400 (98%) es disponibilidad,
  no acierto del primer resultado ni respuesta bajo presupuesto.

## Qué se probó y qué se descartó

Todos los controles numéricos de esta tabla mantienen400 consultas, referencias,
scorer estricto, presupuestos y16folds con exclusión completa del repositorio.
Son controles preparados, salvo las filas que nombran explícitamente API.

| Control | Top‑1 estricto | Decisión |
|---|---:|---|
| API contextual235 (42/46/50/56/56b) |277/400,69,25%| Mejor API válida; aún insuficiente |
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
| Índice completo extractor6 + propuestas nuevas58 |277/400,69,25%;291identidad| Mismo acierto estricto; control preparado, fuente aprobada |
| Ventanas entrenadas dentro de cada owner60b |269/400,67,25%;290identidad| Orden de owners fijo; descartar selector |

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

La última comparación pública COMPLETA sigue siendo Ken21 macroNDCG@10
**0,8189553482** frente a Semble **0,8543853796**, en las mismas1251 consultas y
63pins, sin errores ni exclusiones. Top1 público857/1251 frente a935/1251.
Estas referencias de archivo/solapamiento no equivalen al top1 estricto anterior.
48 prepara todos los100235 owners públicos antes de ejecutar la API contextual
sobre las1251 consultas. Aún no hay score nuevo de esa corrida.

58 completó los16 índices con index_project real y extractor6. Auditoría
independiente: mismos6314ci_files/hashes/lenguajes,6139 archivos con pasajes,
50967owners y124839pasajes con cuerpos/geometría/roles intactos. Cambian2535docs:
2527 recuperaciones47c y8 correcciones adicionales de trailing ajeno verificadas
en fuente.48384 vectores reutilizados para bytes/hash/modelo/política idénticos,
2523 nuevos;32 recodificaciones independientes exactas. Generaciones reales y
las6314 filas retrieval son correctas. No hubo relabel de proyecciones viejas.

Las400 propuestas nuevas y167374 filas235features dieron277strict/291identidad
con16folds excluidos y scorer original: ningún acierto estricto adicional.
37singletons exactos usan placeholders explícitos en8 columnas fuera del modelo
de ranking de producción. El primer harness falló al exigirles cosenos; conserva
21 registros parciales no evaluados y0 agregados. El58b completó400 sin exclusión
y con solicitudes idénticas. Ese worker sí calcula las227features con Potion;
el bypass sin CodeRank/ranking describe la API, no el worker completo.

60b entrenó43features de ventana dentro de cada owner, conservando el orden235.
Reprodujo primero277/290, después obtuvo269/290: descartado. La corrección de
una aserción de métricas dict/float conservó el intento60 original y exigió los
587346scores idénticos entre ambos intentos. No se corrigió el resultado cambiando
referencias ni seleccionando ventanas desde anchors.

59 prepara dos vistas propias por owner, contrato e implementación.61 prueba
interacción por tokens contextuales usando el MISMO137Mgraph, sin otro modelo:
proyección fija128dim/int8, fuente en disco/mmap y consultas codificadas una vez.
No se transfieren resultados de ColBERT a este encoder no entrenado para MaxSim.
Ambos completan todos los16repos fuente antes de consultas; aún sin score.
Las7 ayudas experimentales suman44tests aprobados y mypy7. Son investigación,
no funcionalidades incorporadas por el solo hecho de tener tests.

Faltan90% estricto y sus estratos, superar Semble en su métrica original, la
aceptación ciega, el perfil final CLI/MCP y la validación aislada de CPU/RAM.
Ninguno se declara resuelto por estas pruebas de desarrollo.
