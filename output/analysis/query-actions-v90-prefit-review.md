# Revisión independiente 90: PRE-FIT APTO

La fuente, features y manifiestos reales son aptos para ejecutar únicamente el control fijo 90. Reproduje las 33 columnas adicionales de las 400 consultas con el encoder estático registrado, bit a bit en las 167.360 filas. El gate seguía cerrado y había cero modelos al finalizar la revisión. No importé LightGBM, ejecuté fits, creé marcadores, modifiqué reglas/fuentes/referencias ni abrí la reserva.

Revalidé 6.314 archivos físicos y los 50.967 owners de los 16 índices fuente 7. Cada identidad, hash y lista `executable/calls/returns/all` coincide con OwnerDescription y code_terms4096 de sus pasajes originales. La unión `all` mantiene el mismo orden y límite independiente de la base. El controlador completa todas esas bases antes de leer consultas o registros POS. No depende de etiquetas o consultas para seleccionar código ni amplía ownership.

Los 80 artefactos fuente —64 originales y 16 bases de términos—, 51 bindings del padre y todos los inputs conservan sus hashes. Las 251 columnas originales se referencian sin copiar/modificar y coinciden sus qids, posiciones y hashes por repo. El orden global qid/repo también es el original de 66c/69. Las 33 extras son finitas y reproducibles con el POS, texto expandido, corpus de palabras y encoder registrados. Las 35 consultas sin acciones y 37 bypass exactos mantienen extras neutrales; ninguna consulta se omite.

Cada uno de los 16 archivos training-rows reproduce exactamente filas, grupos, features, labels y pertenencia de los otros 15 repositorios. Hay 375 consultas por fold, incluyendo exactas y sin positivo como en 69: este control usa LambdaRank y no el selector CE de 358 grupos de 88b/89. Envenenar todos los valores y etiquetas de las 25 consultas retenidas no cambia sus hashes de entrenamiento. Los parámetros son idénticos a 69 y al registro v18 fijado; no hay otro encoder, selección por scores entrenados, validación retenida o early stopping.

El callback reutiliza `_coverage`; no duplica ni cambia la fórmula. Su IDF es relativo al pool de candidatos y a sus palabras `all`. Preparar 50.967 owners no convierte ese DF en corpus-global. POS y campos fuente siguen siendo evidencia léxica/gramatical, sin certificar acciones ejecutadas, negación, condiciones, llamadas resueltas o runtime. El análisis anterior `query-actions-v90-review` conserva ejemplos y límites; no se ajustaron reglas a esos ejemplos.

El futuro fitter debe seguir sus guards de exportación nativa/numérica, 160 árboles, autoridad exacta, desempate original, evidencia 3, respuestas completas y scorer original. El gate sigue siendo cinco aciertos adicionales sobre 286/298 en las 400 consultas. Este informe no anticipa calidad, API/default ni aceptación privada. El pico registrado del productor es del harness de preparación y las llamadas nuevas de coverage quedan fuera del diagnóstico query-only de 0,425 ms; no es un certificado de recursos API.

Bindings que root debe revalidar para su marcador:

```json
{
  "engine_receipt": "d0fa6e6e3b80eb432d19b73449211e7cee26df235b976e59f91f7594c43f6259",
  "controller_sha256": "94b242dc2c5878713c83797b1c4a410e9d191f9e87beffafff09e414c38dbdf9",
  "pre_fit_registration_sha256": "9bdfcef4747b1d261fd2335182b83005d12659c49f35ab2cb18b18bc2a8de436"
}
```

Pruebas, hashes y los 400 reencodes/16 manifiestos: `query-actions-v90-prefit-review.json`. La revisión posterior tendrá que comprobar los modelos y replays efectivamente producidos; no ejecuté ninguno en esta auditoría.
