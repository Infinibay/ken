# Diagnóstico de ranking y controles 181–184

El motor instalado sigue en **159/200 top‑1 y 195/200 top‑10** en las consultas nuevas, que buscan símbolos. El mejor control nuevo llegó a **170/200 (85%)**; no alcanza el objetivo y no se incorporó. Las 200 originales conservan **191/197** como última medición MCP. La última aceptación independiente fue **177/198 con frozen145**: es histórica, no una medición del código actual. La reserva nueva continúa **cerrada**. Sin release.

## Qué muestran los errores

[El diagnóstico de las 200 consultas](new200-errors.json) conserva preguntas, identidades y posiciones de la respuesta correcta. Los 41 errores finales se agrupan en 17 operaciones distintas del mismo archivo, 14 resultados de otro archivo, 5 confusiones entre entrada de prueba y otra responsabilidad, y 5 respuestas ausentes del top‑10. La categoría de prueba tiene prioridad sobre las de archivo; son grupos descriptivos, no una explicación causal del modelo.

La fusión pierde 18 respuestas que el reranker había puesto primero y recupera otras 8: saldo −10. El reranker solo acierta 169/200. De sus 31 errores, 26 tienen la pieza correcta entre los diez y 5 no. Incluso un selector perfecto entre los primeros resultados de ambos órdenes sólo obtendría 177/200. Ese oráculo no se utiliza en ejecución.

## Cambios aislados, con las 400 consultas

| Control | Cambio | Top‑1 original / 200 | Top‑1 nuevo / 200 |
|---|---|---:|---:|
| MCP172 actual | Configuración instalada | 191 | 159 |
| S1 previo | Reranker crudo sólo para símbolos | 189 | 169 |
| T1 | Mínima similitud CLS de condiciones con implementación | 165 | 90 |
| T2 | Residuo lineal de 12 medidas CLS, excluyendo cada repo | 189 | 161 |
| U1 | Media de scores del mismo 68M por condición | 186 | 156 |
| U2 | Residuo lineal de 4 medidas de esos scores | 190 | 166 |
| V1 | Prioridad rígida de responsabilidad solicitada | 190 | 164 |
| W1 | Mismo 68M sobre código propio sin documentación | 188 | 164 |
| W2 | Media fija de W1 y la tarjeta original | 190 | 170 |

Todos conservan **197/200 y 195/200 top‑10**, respectivamente, con los mismos conjuntos de candidatos de MCP172. Se mantienen los bypass exactos y el orden de las 150 consultas originales que no buscan símbolos. Los 40 locators explícitos nuevos conservan su respuesta exacta. No se usan los pools antiguos de 193 aciertos.

Una verificación posterior reconstruyó los 3.200 resultados, comprobó los 3.200 conjuntos de candidatos y las 16 exclusiones de repositorio de T/U: [recibo](verification.json). Son resultados de desarrollo expuesto, no aceptación independiente.

T reutiliza los vectores de fuente ya preparados y prohíbe nuevas codificaciones de código. U compara las condiciones con las tarjetas habituales y reproduce sus scores originales. El separador de condiciones respeta literales y paréntesis, pero elimina conectores: puede perder relaciones. No equivale a un parser semántico.

V recupera 8 errores y pierde 13 aciertos frente al reranker. Una prioridad rígida puede perjudicar helpers dentro de tests y preguntas que no piden una prueba de forma explícita. W cambia sólo el texto que lee el modelo; no modifica las salidas compactas del usuario. W2 gana un acierto neto frente al reranker solo, con otra pasada. Ningún control se activa.

## Coste de los observadores

| Observador, 250 consultas simbólicas | p50 ms | p95 ms | Pico RSS, bytes |
|---|---:|---:|---:|
| T: codificar pregunta y comparar diez fuentes | 59,18 | 86,51 | 878182400 |
| U: pregunta completa y condiciones, 68M | 3057,55 | 5480,01 | 1003896832 |
| W: pasada adicional del 68M sobre código | 772,18 | 1367,90 | 1010925568 |

[Datos](observer-costs.json). No incluyen el recorrido API completo. Son ejecuciones separadas y no prueban una reducción de RAM ni una mejora de latencia de producción. U añade coste y empeora frente al reranker; W2 tampoco justifica incorporar otra pasada.

Las capturas cerraron sus observaciones antes de acceder a referencias expuestas y registraron los imports contemporáneos. Los graders originales se lanzaron con `PYTHONPATH=frozen172/src`, pero no registraron `__file__` durante esa ejecución. La verificación posterior tiene sus propios imports; no reescribe esa limitación histórica. Se conserva el criterio de identidad estricta, sin eliminar preguntas ni añadir suficiencia de evidencia como condición del acierto.

## Reanudar el trabajo

Archivo reproducible: `output/checkpoints/clause-and-purpose-controls-v181-v184`, con 172 gzip y 2.007.291 bytes. SHA‑256 del manifiesto:

`a637dcfe23ce48ec624a6bcdb0c86c431ba13ac25c5b05cc212954df02d06cdd`

Incluye protocolos previos, productores, características, scores, órdenes, resultados y tests rojos/verdes. No contiene reservas ni referencias privadas de aceptación.

La siguiente prueba adapta **el mismo modelo de 68.408.321 parámetros** con datos externos de [CodeSearchNet](https://huggingface.co/datasets/code-search-net/code_search_net), revisión `bd0cf261e357a3eb5c8fba490d23ec1a1cd59555`. El corpus corregido tiene 12.000 consultas de entrenamiento y 3.000 de validación. Los repositorios están separados también para todos los candidatos: 829 en entrenamiento y 199 en validación, sin intersección.

Se excluyen los ocho proyectos evaluados y forks con igual nombre final, además de clones por tokens. Esto no demuestra ausencia de toda versión modificada del código. El guard registra los hashes de 2.593 archivos de código de los snapshots públicos; 26 usan texto original cuando la limpieza dejaría un bloque vacío. Esos snapshots no tienen `.git`.

La revisión independiente encontró dos fragmentos Python que quedaban inválidos, tres con documentación residual y 386 negativos fáciles que incumplían la regla de nombre terminal distinto. El corpus `curated-c` corrige esos defectos. Se revisaron 24 pares sin confirmar negativos también correctos; persisten límites de contexto y de las etiquetas documentales. SHA del suplemento:

`5dbd9d498f44905fbc99b9f8b504bb4c9956f7488c0e15c7cf0bfa74ce961193`

La receta está fijada en `research/output/analysis/code-domain-adaptation-v186-protocol.md`: una época, últimos dos bloques y cabeza entrenables —4.722.177 parámetros existentes—, resto congelado; pérdida softmax por consulta y AdamW 5e‑5, sin elegir parámetros o checkpoint con las 400 consultas. Se mantienen los 3.000 casos externos de validación. Sólo entrenamiento filtra positivos que no caben completos en 512 tokens: quedan 10.968 grupos. Las 400 consultas de desarrollo conservan su denominador.

La prueba sintética confirmó paridad Torch CPU/ONNX y funcionamiento de MPS; el mapeo de los doce tensores finales al ONNX original es inequívoco. En este checkpoint la adaptación 186 está **en curso, sin resultado público**. Antes de incorporarla hacen falta la evaluación completa y un replay MCP en CPU con RAM/latencia. La reserva seguirá cerrada incluso si se alcanza el objetivo público. Sin release.
