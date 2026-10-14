# Memoria del backend MLX

Comparación local sobre 1024 pasajes públicos de JUnit, sin queries ni etiquetas. Modelo Qwen3-Embedding-0.6B, revisión97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3, MLX0.32.3, FP16, batch16 y secuencia512. Mismos textos y orden, warmup16, caché libre vaciado antes de medir. Controles en procesos separados: original A → límite512MiB → original B → implementación → implementación sin tests concurrentes.

| Variante | Segundos | Activa + libre al terminar |
|---|---:|---:|
| Original A | 30.546 | 25,455,396,840 bytes |
| Original B | 30.688 | 25,453,103,080 bytes |
| Implementación, ejecución limpia | 26.539 | 1,736,687,624 bytes |

La memoria retenida bajó 93.2%; el tiempo de esta ejecución bajó 13.3% frente a la media de los originales. Los1024 vectores son idénticos byte por byte en las cinco ejecuciones. El pico de memoria activa fue2.128GB en todas: el problema era retención de buffers libres. El límite de512MiB respeta un límite menor fijado por el host y no restringe pesos vivos.

El límite de caché se aplica a buffers libres en asignaciones posteriores, según [MLX](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.set_cache_limit.html); el contador de [caché](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.get_cache_memory.html) excluye los arrays activos. Puede exceder ligeramente el límite inmediatamente después de liberar el último batch.

Recibos crudos, protocolo, vectores y comparación en output/development/mlx-memory/. La primera ejecución de implementación coincidió con tests durante warmup y se repitió limpia. Estos números no certifican calidad de búsqueda ni latencia global. El intento400 se interrumpió con200 resultados preservados para diagnosticar la memoria y se reanuda con la misma fuente/modelos; sus costes se separan por episodio en resource-events.jsonl. La reserva no se usó.
