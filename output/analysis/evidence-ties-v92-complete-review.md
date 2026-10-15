# Revisión independiente final de 92

Control negativo verificado: baseline **286/400 estricto y 298/400 identidad**; empates **282/400 estricto y 294/400 identidad**. No hay faltantes ni exclusiones y no alcanza el gate fijo de cinco adicionales. No entrené, importé LightGBM/optimizadores, modifiqué código/datos/modelos/referencias/marcador ni abrí la reserva.

Revalidé el freeze, controlador y marcador abierto por root contra los bindings exactos del informe pre-fit, los 6.314 archivos físicos, 64 artefactos fuente, 51 bindings del padre y diagnósticos conservados. Reconstruí otra vez la matriz 167.360×251 y sus targets: coinciden exactamente. Las 15 columnas usan la regla registrada y las otras 236 y los 37 bypass exactos permanecen byteidénticos al padre.

Los 16 conjuntos de entrenamiento conservan 375 grupos y sólo filas/etiquetas de los otros 15 repositorios. Los parámetros coinciden con 69. Cada forest tiene 160 árboles y hasta 15 hojas por árbol; su estructura exportada es idéntica al dump nativo y los conteos de hojas corresponden a sus filas de entrenamiento. La suma independiente de hojas reproduce todos los scores retenidos bit a bit, igual que NumericRanker.

Reproduje los 800 objetos completos de respuesta, con scores, perfiles, autoridad exacta, desempate original y evidencia 3. Los 7.016 hits visibles conservan fuente física/hash y hasta 40 líneas. Todas las respuestas cumplen hasta 10 resultados y 12.000 caracteres JSON. En 57 consultas cambia la cantidad final por presupuesto tras cambiar el orden; ninguna consulta se elimina. El baseline coincide completo con el de 89. Los dos informes se recalculan exactamente con el scorer original, idéntico a 74b, sin cambiar owners, anclas, alternativas ni denominadores.

El resultado pertenece al único ensayo registrado de rango promedio más neutralidad de canales constantes. No demuestra un error universal de la política ordinal ni una garantía de la variante. No se adopta en API/default ni cambia el gate privado. El pico de 2.873.999.360 B es del proceso completo de matrices, fit, exportación, replay y scoring; no es un certificado de memoria o latencia API.

Hashes, 16 modelos y verificaciones: `evidence-ties-v92-complete-review.json`. El estado exacto antes de ajustar queda preservado en `evidence-ties-v92-prefit-review.json`.
