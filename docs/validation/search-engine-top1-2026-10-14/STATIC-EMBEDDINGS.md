# Comparación de embeddings estáticos en CPU

Mismas 400 consultas públicas y pasajes fuente; parser 8 / extractor 5, 100 candidatos, 40 líneas visibles y 12000 caracteres JSON. Revisión de modelos, pesos, tokenizer, runtime y política de inferencia fijados. Reserva privada sin abrir. Ningún perfil se promueve por estos resultados.

| Modelo | Pesos MiB | API estricta | Control de rol estricto | EN | ES | Anclas en 100 | API p95 ms | RSS pico MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| [minishlab/potion-code-16M-v2](https://huggingface.co/minishlab/potion-code-16M-v2) | 31.0 | 137/400 (34.25%) | 156/400 (39.00%) | 106/240 | 50/160 | 361/400 | 168.3 | 555.1 |
| [minishlab/potion-retrieval-32M](https://huggingface.co/minishlab/potion-retrieval-32M) | 123.2 | 93/400 (23.25%) | 106/400 (26.50%) | 70/240 | 36/160 | 336/400 | 187.5 | 854.4 |
| [minishlab/potion-base-32M](https://huggingface.co/minishlab/potion-base-32M) | 123.2 | 93/400 (23.25%) | 111/400 (27.75%) | 80/240 | 31/160 | 325/400 | 180.5 | 846.0 |
| [minishlab/potion-multilingual-128M](https://huggingface.co/minishlab/potion-multilingual-128M) | 488.6 | 87/400 (21.75%) | 100/400 (25.00%) | 60/240 | 40/160 | 357/400 | 197.8 | 1824.6 |
| [sentence-transformers/static-retrieval-mrl-en-v1](https://huggingface.co/sentence-transformers/static-retrieval-mrl-en-v1) | 119.2 | 91/400 (22.75%) | 104/400 (26.00%) | 71/240 | 33/160 | 331/400 | 201.5 | 1566.2 |
| [sentence-transformers/static-similarity-mrl-multilingual-v1](https://huggingface.co/sentence-transformers/static-similarity-mrl-multilingual-v1) | 413.6 | 106/400 (26.50%) | 119/400 (29.75%) | 73/240 | 46/160 | 355/400 | 201.2 | 1891.2 |
| [amgix/static-retrieval-multilingual-69m-v1](https://huggingface.co/amgix/static-retrieval-multilingual-69m-v1) | 263.6 | 104/400 (26.00%) | 113/400 (28.25%) | 77/240 | 36/160 | 346/400 | 198.9 | 1196.2 |

La columna de rol es un control experimental adicional al servicio público con perfil explícito; todavía no es el ranking predeterminado. EN/ES corresponden a ese control; la cobertura exige todas las anclas dentro de los 100 candidatos, no sólo el archivo. El objetivo mínimo del 90% y el checkpoint de cobertura 98% no cambian. Véanse los resultados por implementación y repositorio en los recibos JSON.

La latencia incluye búsqueda API+serialización JSON con índice preparado; excluye proceso frío, carga inicial, indexado fuente y transporte CLI/MCP. El RSS es el pico del proceso de medición, durante la secuencia de 16 repositorios, incluido el modelo y las cachés; no es sólo el tamaño del modelo. No se importaron torch, MLX ni ONNX. El presupuesto aproximado de 1 s/100 archivos se contrasta con COUNT(*) de ci_files, separado del inventario usado para verificar la fuente.

Se corrigió un defecto del control anterior: el tokenizer Potion serializado activaba padding por lote y truncado oculto a 512. Model2Vec incluía PAD al promediar. La política actual los desactiva antes del conteo/pooling; el encode explícito conserva 512. El perfil tiene nueva revisión y los vectores antiguos permanecen históricos. Los dos modelos 32M sin padding/truncado reutilizan vectores sólo después de comprobar que la nueva política es un no-op exacto y validar todas las vistas sin permitir nuevas codificaciones; cada uno vuelve a medir sus 400 consultas. Los demás se codifican desde cero.

La preparación de vectores parte de los mismos pasajes ya extraídos: no debe presentarse su tiempo como indexado completo del repositorio. El ranking, las referencias y los presupuestos no cambian entre modelos. No se ejecutó la reserva de aceptación.

Mejor top‑1 estricto de los controles de rol: 39.00%. Esto no equivale a demostrar el 90% en aceptación.


La comparación de modelos anterior está congelada en v14. Una corrección
posterior de búsqueda literal, con el mismo Potion y los mismos vectores,
obtiene 138/400 con RRF y 157/400 (39,25%) en el control de rol v15. La regresión
separada de nombres cualificados únicos pasa 48/48 sin embeddings. Esa mejora
es de resolución de identidad; no se atribuye a un cambio de modelo ni altera
las siete mediciones originales de esta tabla.

Recibos y puntuaciones por consulta en `output/development/static-models-v14/`;
`summary.json` contiene revisiones, pesos, licencias, números de archivos
indexados y latencia por repositorio. Fuente congelada y protocolo v2 en
`output/frozen/cpu-static-models-v14/`. El control posterior está en
`output/development/potion-cpu-exact-case-v15/`, con su propia fuente congelada.
