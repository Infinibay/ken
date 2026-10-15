# Revisión independiente 92: PRE-FIT APTO

El controlador y todos los artefactos preparados son aptos para ejecutar exclusivamente el control fijo 92. Observé cero modelos, resultados y marcador al finalizar. No ejecuté entrenamiento, importé LightGBM/optimizador/NLP, modifiqué implementación/referencias/modelos ni abrí la reserva.

Revalidé el freeze, controlador archivado, 6.314 archivos físicos, 64 artefactos fuente, 51 bindings del padre y todos los inputs. Las 251 columnas originales de 69, sus qids, orden, posiciones y targets quedan ligados a las mismas fuentes. El scorer conserva los bytes originales de 74b. No se usan las columnas POS de 90 ni un encoder adicional.

Reconstruí independientemente la matriz 167.360×251 mediante agrupación ordenada de scores y conteo de mayores/iguales, sin usar etiquetas o scores entrenados para la transformación. Los hashes coinciden con el registro. Se modifican únicamente las nueve columnas base de rango y seis de contexto/vistas previstas; las otras 236 son idénticas byte a byte en cada consulta. Los 37 bypass exactos conservan las 251 columnas originales completas.

Los 6.000 registros diagnósticos coinciden exactamente, y los 6.000 canales verifican la equivariancia del helper al permutarlos. Hay 555 canales pertenecientes a bypass exactos, 83 canales constantes no exactos neutralizados y 1.064.412 celdas de rango cambiadas. Son descripciones de la transformación fija, sin selección por calidad. La regla de canal constante y el promedio de empates permanecen las dos decisiones explícitas del ensayo; la política ordinal legacy sigue siendo una definición válida.

Los 16 archivos training-rows reproducen grupos, filas, features, labels y hashes de los otros 15 repositorios: 375 consultas por fold, conservando exactas y sin positivo como en 69. Envenenar features y labels de las 25 consultas retenidas no altera los datos de entrenamiento. La exclusión sucede antes de crear bins o ajustar. Los parámetros coinciden exactamente con 69 y el registro v18 fijado. El baseline entrenado de 69 se usa sólo en el replay posterior, no para elegir la transformación ni entrenar esta variante.

El gate posterior sigue requiriendo 16 exports nativos/numéricos válidos, replay de las 400 consultas, baseline 286/298, scorer/anclas/presupuestos originales y cinco aciertos estrictos adicionales. Esta aptitud no anticipa resultado, integración API/default o aceptación privada. La propiedad de permutación es local a los canales transformados; no se prueba invariancia de todo el pipeline. Una integración futura debe ligar explícitamente esta semántica al perfil de features aunque conserve los mismos 251 nombres.

Bindings que root debe revalidar para su marcador:

```json
{
  "engine_receipt": "dc63117ba6e8ab49e53db5781ccc7b96ab8253e0a70817ab56b1bbab47573d8c",
  "controller_sha256": "2d79e009c5e0b54beb4bebd82cee0d160ba45826320c963e2f1dc643d4e98c0f",
  "pre_fit_registration_sha256": "f385c8ddfe3e367e631ebd6abe7849102fa7d1638ff8ed24aec1036dc2c12bd6"
}
```

Recibo de aptitud exacta, columnas, 400 consultas y 16 manifiestos: `evidence-ties-v92-prefit-review.json`. La revisión matemática previa queda en `evidence-ties-v92-helper-review.json`.
