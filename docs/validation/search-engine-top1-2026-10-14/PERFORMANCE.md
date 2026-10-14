# Rendimiento del motor experimental

La condición vigente es CPU, RAM contenida y aproximadamente un segundo por
cada 100 archivos indexables para devolver la respuesta completa. No se acordó
un límite numérico de RAM. No hay todavía una certificación del perfil final.

## API preparada en CPU

Mismas 400 consultas, pasajes y modelo Potion de 16M parámetros. Procesos
separados en orden anterior → optimizado → optimizado → anterior, sin otros
ensayos de modelos concurrentes. Incluye API y serialización JSON; excluye
transporte CLI/MCP, preparación del índice e inicialización del proceso.

| Ejecución | p50 ms | p95 ms | Pico RSS MiB |
|---|---:|---:|---:|
| Anterior A | 39.44 | 426.62 | 694.50 |
| Optimizado A | 20.11 | 156.08 | 610.59 |
| Optimizado B | 20.33 | 144.93 | 622.88 |
| Anterior B | 39.62 | 441.45 | 694.72 |

Las cuatro salidas completas son idénticas byte por byte, SHA-256
`6eeda66d35bc18236904174c51d1361a4fbbc9c14d4f5c117fd192f10b04b3b6`.
Conservan 137/400 aciertos estrictos y 145 identidades correctas: la mejora
demostrada es de coste, sin aumento de precisión. El cambio evita agrupar todos
los vectores en Python por consulta y calcula BM25F sobre los postings
coincidentes con NumPy, conservando saturación, frecuencias y orden.

JUnit tiene 2446 archivos indexados; su p95 baja de 982/992 ms a 429/414 ms.
Los otros repositorios tienen entre 54 y 726 archivos indexados. El denominador
usa la política de exclusiones existente, sin contar archivos ignorados.
Recibo con las 16 cantidades y rutas de los cuatro ensayos:
`output/development/cpu-speed-comparison.json`. Fuentes congeladas v5 y v8.

## Ensayo histórico del backend MLX

Este backend usa GPU y no es elegible para la condición actual del usuario.
Se conserva el ensayo como diagnóstico de memoria y para reproducibilidad.

Comparación local sobre 1024 pasajes públicos de JUnit, sin queries ni etiquetas. Modelo Qwen3-Embedding-0.6B, revisión97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3, MLX0.32.3, FP16, batch16 y secuencia512. Mismos textos y orden, warmup16, caché libre vaciado antes de medir. Controles en procesos separados: original A → límite512MiB → original B → implementación → implementación sin tests concurrentes.

| Variante | Segundos | Activa + libre al terminar |
|---|---:|---:|
| Original A | 30.546 | 25,455,396,840 bytes |
| Original B | 30.688 | 25,453,103,080 bytes |
| Implementación, ejecución limpia | 26.539 | 1,736,687,624 bytes |

La memoria retenida bajó 93.2%; el tiempo de esta ejecución bajó 13.3% frente a la media de los originales. Los1024 vectores son idénticos byte por byte en las cinco ejecuciones. El pico de memoria activa fue2.128GB en todas: el problema era retención de buffers libres. El límite de512MiB respeta un límite menor fijado por el host y no restringe pesos vivos.

El límite de caché se aplica a buffers libres en asignaciones posteriores, según [MLX](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.set_cache_limit.html); el contador de [caché](https://ml-explore.github.io/mlx/build/html/python/_autosummary/mlx.core.get_cache_memory.html) excluye los arrays activos. Puede exceder ligeramente el límite inmediatamente después de liberar el último batch.

Recibos crudos, protocolo, vectores y comparación en output/development/mlx-memory/. La primera ejecución de implementación coincidió con tests durante warmup y se repitió limpia. Estos números no certifican calidad de búsqueda ni latencia global. El intento400 se interrumpió con200 resultados preservados para diagnosticar la memoria; los ensayos posteriores con GPU también se detuvieron al adoptar la condición de CPU. Sus costes se separan por episodio en resource-events.jsonl. La reserva no se usó.
