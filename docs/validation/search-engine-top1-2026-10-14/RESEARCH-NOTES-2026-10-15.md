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
