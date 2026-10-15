# Revisión independiente final de 90

Control negativo verificado: baseline **286/400 estricto y 298/400 identidad**; acciones **283/400 estricto y 295/400 identidad**. Las 400 consultas están presentes en ambos controles. No alcanza el gate fijo de cinco adicionales; no implica integración API/default ni aceptación privada. No ejecuté fits, importé LightGBM, cambié reglas/datos/modelos/referencias/marcador ni abrí la reserva.

Revalidé el freeze `d0fa6e6e3b80eb432d19b73449211e7cee26df235b976e59f91f7594c43f6259`, controlador, marcador abierto por root y todos sus bindings. Los artefactos fuente conservan los mismos hashes del informe previo que verificó exhaustivamente 50.967 owners, 6.314 archivos y las 167.360×33 columnas recodificadas en CPU. La matriz final 167.360×284, sus etiquetas originales y orden qid/repo coinciden exactamente.

Los 16 manifiestos de entrenamiento reproducen los 375 grupos y filas crudas de los otros 15 repositorios, incluidos exactos y sin positivo como en 69. Los parámetros son los mismos; cada forest contiene 160 árboles y hasta 15 hojas por árbol. La estructura exportada conserva exactamente los dumps nativos; el conteo de entrenamiento de todas las hojas coincide con las filas de su fold. Recalculé por suma de hojas las predicciones de todas las filas retenidas: coinciden bit a bit con scores guardados y NumericRanker, sin repetir entrenamiento.

Reproduje completos los 800 objetos de respuesta con scores, perfiles, autoridad exacta, orden/desempate original y evidencia 3. Los 7.023 hits visibles mantienen texto/hash de fuente y hasta 40 líneas. Todas las respuestas cumplen 10 resultados y 12.000 caracteres JSON. En 56 consultas cambia la cantidad final postbudget al cambiar el orden; ninguna consulta se excluye. El baseline coincide por completo con el de 89. Recalculé ambos informes con el scorer original, idéntico a 74b, sin cambiar alternativas, owner, anclas ni denominadores. Las 35 consultas sin acciones y 37 exactas continúan en la evaluación.

El pico registrado de 3.023.306.752 B pertenece al proceso completo de matrices, fit, exportación, replay y scoring. No mide memoria de API, RAM incremental del POS ni latencia aislada. Las limitaciones léxicas/gramaticales documentadas antes del fit siguen vigentes; no se ajustaron reglas a los casos diagnosticados.

Recibo detallado, 16 modelos, hashes y respuestas: `query-actions-v90-complete-review.json`. Las pruebas exhaustivas de fuente/features y la aptitud previa quedan preservadas en `query-actions-v90-prefit-review.json`.
