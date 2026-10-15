# Información que falta distinguir en el ranking

El API74b tiene286/400aciertos estrictos;102fallos son de entidad y12 de
evidencia. El ranking69 ya contiene un owner elegible entre los2primeros en342
consultas, entre5 en373 y entre20 en391. Son disponibilidades de candidatos,
no aciertos ni una certificación del90%. Fuente: `ranked-coverage.json` bajo
`output/analysis/source7-context-views-ranking-v69/contract_body251/` y revisión
`output/analysis/complete-owned-api-v74b-review.json`.

La inspección de desarrollo muestra errores entre una operación y quien decide
cuándo ejecutarla, entre un constructor de validador y su implementación, entre
sobrecargas y entre funciones parecidas de módulos distintos. Por ejemplo,
rollback aislado frente a la transacción que elige rollback/commit según su
callback; undo aislado frente al contexto que siempre lo ejecuta al salir.
Esto motiva comparar relaciones completas y controlar el conjunto final de
candidatos. No permite afirmar que cualquier función con las palabras buscadas
implemente el comportamiento, ni cambiar los owners originales de aceptación.

Las fuentes consultadas aportan hipótesis, no porcentajes transferibles a Ken:

| Fuente primaria | Información útil | Aplicación y límite local |
|---|---|---|
| [R2PS/APSEC2024](https://arxiv.org/abs/2305.04508) | Comparación conjunta de consulta/código y negativos difíciles dentro de una cascada de recuperación y ranking |73/73b generales pequeños,75c adaptación4,4M enCPU con repo excluido y77 prefijo20: todos inferiores al control286. Se rechazan, aunque el enfoque del paper sea plausible. |
| [Fine-grained matching/COLING2025](https://aclanthology.org/2025.coling-main.482/) | La media de tokens puede perder el detalle que distingue candidatos; propone interacción entre consulta y código |70 probó una interacción entrenada de tokens y empeoró. No se incorporó por el mérito del paper. Las relaciones/negaciones siguen siendo información que una media no demuestra. |
| [CoRNStack/ICLR2025](https://proceedings.iclr.cc/paper_files/paper/2025/file/285b0e63256699c04dbf2c8d4163fba4-Paper-Conference.pdf) | Importan calidad de pares y negativos; el artículo separa recuperación de reranking |CodeRank137M ya es parte del control. Su reranker7B queda fuera del objetivo deCPU/RAM; sus métricas no equivalen a nuestro top1 estricto. |
| [Model2Vec, autores](https://github.com/MinishLab/model2vec) | Un modelo estático reduce el costo de representar términos/textos |Ya se probaron7modelos estáticos con política de tokenizer corregida. Cambiar sólo el embedding no ha demostrado90%; no trasladar MTEB a estas funciones. |

Una siguiente línea posible, todavía sin implementar aquí, es alinear la
condición y su efecto como una relación: conservar qué condición controla qué
operación, qué valor recibe y qué salida produce.51/57 ya probaron bolsas de
relaciones y máximos de cláusulas con resultados inferiores. Una variante nueva
debe aportar información distinta, mantener la propiedad sintáctica real y probar
que mejora; sumar más contadores o cosenos del mismo conjunto no basta. El grafo
de destinos54 rechazado no debe reaparecer como si fuera resolución válida.

Se mantienen los400originales, todas sus líneas decisivas, los estratos y la
reserva independiente sin abrir. Las corridas75c/73/76/77 se conservan aunque
sean negativas; un resultado preparado no sustituye la API real ni la medición
final de CPU/RAM.75c y77 tienen revisión independiente cerrada;73b y80 están
pendientes.80 logra sólo288/400 preparado, por debajo del gate de5nuevos aciertos
para API; no se incorpora.78 prueba sólo una proyección distinta de código propio
con el encoder existente y sigue en preparación.

## Comprobaciones de continuidad: representación y recursos

La revisión87 verifica397 proyecciones y4347 asignaciones de líneas de las400
referencias de desarrollo. En los90 errores de identidad con propósito
implementación,79 ya tienen todas sus anclas en el prefijo512 de la vista
implementation69;4 tienen anclas propias posteriores y7 no están completas en
el mapa del cuerpo. Este mapa excluye declaraciones/documentación: esas líneas
pueden estar ya en el header de la misma proyección o en contract/fullowner.
No se deduce ausencia del input, una cota de precisión ni causalidad. Se decide
no invertir por ahora en recodificar masivamente ventanas más largas sólo por
suponer que el límite512 explica los fallos. Los originales siguen inmutables.

La opción enable_cpu_mem_arena está documentada por ONNX como activada por
omisión. El control86 ABBA con todos545 textos de consulta y32fuentes conserva
raw/unidades/tokens idénticos, pero no muestra ahorro consistente y es más lento
con arena desactivada. No cambiar el runtime por esa hipótesis. Recursos de
encoder más arnés/imports, con concurrencia; no certificado del API.
Fuente: [API oficial de ONNX Runtime](https://onnxruntime.ai/docs/api/python/api_summary.html#onnxruntime.SessionOptions.enable_cpu_mem_arena).

La búsqueda adicional de modelos no aporta un reemplazo adoptable por ahora.
La [PR oficial de Potion16M](https://huggingface.co/minishlab/potion-code-16M-v2/discussions/1)
retira padding/truncation del tokenizer; nuestro adaptador registrado ya llama
no_padding/no_truncation desde14, así que no es una corrección nueva para este
motor. El [modelo LFM2-350M](https://huggingface.co/LiquidAI/LFM2-350M) anuncia CPU
como destino, pero sus autores desaconsejan tareas que requieren programación.
No se descargaron pesos ni se atribuye calidad de búsqueda a sus benchmarks.
El entrenamiento de un head pequeño sobre evidencia code/query conjunta85b
sigue separado de la hipótesis de incorporar otro generador.


88b aísla el ordenador matemático con las representaciones251 actuales. La
pérdida softmax de listas usa igual peso por consulta y masa uniforme entre sus
positivos originales; ridge1 garantiza solución única. Se excluye el repositorio
retenido ANTES de estadísticas y optimización. Un único dot251 exportado evita
otro encoder en ejecución. La convergencia y residuo se verifican además de la
bandera success de L-BFGS-B; no se aflojan tras ver resultados.
Documentación primaria: https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html
Los stubs scipy1.18.1.1 y sus tres dependencias de tipos se instalaron sin cambiar
NumPy2.4.4/SciPy1.18.1 ni pesos del motor. Los dos arreglos88b son genéricos y
preceden cualquier ajuste de datos reales; el freeze88 original se conserva.


El control92 cambia sólo la política de empates de15rangos, no mejora:282/400
estrictos y294identidad frente a286/298. No adoptar ni afirmar que la definición
ordinal era un bug. Revisión independiente final conservada.

La nueva hipótesis95 distingue propiedad exclusiva de contexto léxico. Ajv07,
Boltons01 y Marked18 contienen fuente decisiva en una declaración anidada; ampliar
owned_regions o rebautizar al hijo como padre falsificaría procedencia. La nueva
unidad conserva primary y propietarios reales de cada tramo, bytes y ancestry;
no demuestra llamadas, retorno resuelto ni ejecución. Una declaración con otro
initializer o un binding destructurado no autoriza fuente lateral sólo porque
comparta un extent canónico legado. Los contraejemplos independientes dieron
pruebas RED antes de los arreglos. El helper19tests/mypy limpio sigue source-only,
sin medición de calidad y pendiente de auditoríaALL16.

La supervisión auxiliar93/94 usa repositorios disjuntos y curación fuente-primero
sin rankings. El piloto96 ya está sellado; ALL8source se prepara antes de abrir
queries/labels. El protocolo94 precede cualquier resultado93 y prevé384casos más,
incluidos128tests; no puede rellenarse con paráfrasis ni sustituirALL400 o reserva.
La disjunción privada es una certificación opaca del curador, no una lectura de
identidades o preguntas privadas por root/revisor. Las guardas casos↔sello y
receipts reales deben cerrarse antes de ajustar, no después de ver calidad.


Actualización 15/10, fuente y públicos auxiliares completos/parciales:
-93source terminóALL8:3176ci_files,16790owners,49604passages; full/views y
 recodificaciones independientes bitexact. PRE-QUERY93cAPTO y públicos93c ya
 completosALL96/45095filas,0exclusiones. Registro1fb56478aa67e58ac824b7c249e0f347db5fbf0e6ee2b0274c24465727f07b6d.
- Piloto2 sellado384 y PRE-QUERY94APTO. Freeze94consumer65d758/source93
 separado4ebee; se están recomputandoALL480públicos. No labels ni fits aún.
- Revisión prospectiva detectó que fitters93c/94 sobrescribían el dict del
 índice padre con una rutaaux y fallarían antes de puntuar. Se retiran SIN
 ejecución; nuevas93d/94b sólo separan ese nombre. Prueba RED/GREEN y revisión
 independientes cerradasAPTOcódigo, antes de leer casos/ajustar. PRE-FIT pendiente.
-95catálogoALL16 cerradoAPTO independiente;96loader/proyección/helper cerrados
 APTOcódigo y39tests verdes. Proyección96source-only completa36194contextos,
 full/nested literales,611filesfrozen/receiptd0279cd002a743cc2f824aa78fbd44e326487b0e575a1fc53914588a388d3e99.
 Registrob7d283d924468a8d14833dc66dd94f9709ea1cda060d3e414fd180492f6cf285.
 Pico161595392B sólo productorfuente. Features96prospectivos276=251intactas+25
 preparados en código, sin ejecución/querymatrix/labels/fit/políticarespuesta.
- MejorresultadoAPI sigue286/400estricto71,5%; público76b0,841718 frente a
 Semble0,854385. No90%, ni nuevo perfilAPI, ni apertura de reserva privada.
