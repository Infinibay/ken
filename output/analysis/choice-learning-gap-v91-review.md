# Revisión independiente del diagnóstico 91

El diagnóstico reproduce sus bindings, pertenencias y fórmulas. Los 5.728 registros por ocurrencia coinciden exactamente con un recálculo independiente de los scores ya guardados de 89, sin entrenamiento, lectura de textos de consultas/referencias ni acceso a la reserva.

| Lectura numérica condicional | Ocurrencias | Consultas únicas | Hits de owner top 1 crudo |
|---|---:|---:|---:|
| Entrenamiento | 5.370 | 358 | 5.370/5.370 |
| Repo retenido | 358 | 358 | 235/358 (65,6425%) |

Cada consulta aparece exactamente 15 veces en entrenamiento y una vez retenida. Las 5.370 observaciones están correlacionadas; no son 5.370 consultas independientes ni resultados de holdout. En los 16 folds, las filas NPZ son exactamente las listas esperadas de los otros 15 repositorios. Los qids, repos, y, fuentes de scores y hashes de modelo coinciden con el cierre independiente de 89.

Recalculé argmax por primer índice, probabilidad softmax del positivo, margen positivo menos mejor negativo y todos los percentiles. No hay empates de máximo en estos registros. La probabilidad mediana es 0,97810 en entrenamiento y 0,76814 retenida; el margen mediano es 4,48392 y 1,62757. Son valores internos de cada lista, sin calibración probabilística entre consultas o modelos.

Esta lectura excluye 37 exactas y cinco sin positivo únicamente para el diagnóstico de los 358 grupos entrenables. No aplica autoridad exacta, selección de fragmentos, límites de presentación ni verificación de anclas visibles. La aceptación original de 89 sigue siendo **265/400 estrictos**. El gap observado demuestra un contraste en estas listas fijas; no identifica por sí solo su causa, un mínimo global del optimizador o transferencia a repositorios arbitrarios/reserva.

El script comprueba hashes de dumps/exports; no realiza inferencia nativa nueva. La fidelidad de todos los scores y prefijos nativos/exportados ya quedó probada en `choice-trees-v89-complete-review` para el mismo registro. Datos completos, percentiles y recibos: `choice-learning-gap-v91-review.json`.
