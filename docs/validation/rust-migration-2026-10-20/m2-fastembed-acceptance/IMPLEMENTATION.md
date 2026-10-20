# FastEmbed: aceptación nativa M2

Este corte ejecuta los30modelos y300casos del catálogo original en macOS arm64 y Linux aarch64. Se conservan los originales, el comando instalado y los espacios persistentes. La revisión final del plan se registra junto a este recibo al terminar.

La matriz exige34controles y33huellas actuales: incluye los31controles anteriores y añade release, paridad y propiedad de archivos de FastEmbed. Los resúmenes de cada plataforma están en `macos/summary.json` y `linux/summary.json`; `summary.json` reúne la matriz. Cada archivo de ejecución está ligado a su manifiesto SHA-256 y tamaño. `FILES.json` inventaría la publicación completa. Los logs gzip conservan también el hash y tamaño de sus bytes originales.

En cada plataforma se aprobaron15819pruebas Python y se conservaron10xfail, sin nuevos fallos, skips ni IDs perdidos frente al baseline. Rust ejecutó221pruebas en51secciones, sin fallos ni ignoradas; las93pruebas de procesos nativos también pasaron. macOS mantiene los dos errores de tipado anteriores por Transformers ausente; Linux no tiene errores y ninguna plataforma añadió errores de tipado. La advertencia de HF Xet es una deprecación del entorno original.

Los vectores F32 finitos se comparan con el original de la misma plataforma a1e-6absoluto+1e-6relativo. Son15660filas válidas por plataforma. El modelo alemán FP16 conserva ocho errores reales de inicialización ya presentes en el original, delimitados por modelo, revisión, graph y diagnóstico; no se fabrican vectores ni se omiten casos. Sus dos lotes vacíos permanecen perezosos. Inputs, máscaras, shapes, dtypes, orden y prompts se verifican exactamente.

Cinco familias prueban corrupción real de la última configuración después de copiar pesos, limpieza de la preparación fallida, reparación de la fuente, archivos privados independientes y resultados idénticos después de retirar sólo las fuentes COPIADAS. La caché canónica conserva sus hashes. El proceso nativo se ejecuta fuera del checkout con PATH de sentinelas y, en Linux, exactamente un exec por rol. El binario, el core y el catálogo se verifican antes y después; el productor compilado acredita39fuentes/recursos. No hay fallback a Python en el runtime Rust ni afirmación de inferencia numérica GPU o aceleración.

La evidencia de ejecución se autentica una sola vez; los mismos buffers se reutilizan para manifiestos anidados, descompresión limitada a16MiB y comparaciones semánticas. Las pruebas rechazan datos alterados incluso si se recalculan los hashes: vectores falsos, propiedad falsa, revisiones incorrectas, salida anterior alterada y trazas de procesos adicionales. Las fixtures sintéticas no pueden acreditar la matriz.

`FastEmbed_accepted=true` y `Storage_accepted=true` corresponden a estos subsistemas. `M2_accepted=false`: aún faltan otros backends opcionales, adquisición/preparación e integración antes de avanzar a M3. La migración completa de la aplicación continúa hasta M8.

La versión candidata contiene6756archivos con la huella45686e6db539da18a2e0a7ad711f9ab2758c056dbbde8e51988bfaeaeceaa8e8 y fue verificada en ambos sistemas antes de medir. No se cambiaron fuentes durante la aceptación, ni plazos, baselines o límites de recursos. Linux mantiene2CPU/6GiB. Un primer lanzamiento macOS se interrumpió al comprobar que el sandbox impedía sockets locales; se repitió íntegramente con el acceso necesario. Ese intento no certifica aceptación.

Para comprobar la matriz contra las fuentes actuales desde la raíz del proyecto:

```sh
.venv/bin/python -m tools.rust_migration.fastembed_validate --scope matrix \
  --platform-receipts docs/validation/rust-migration-2026-10-20/m2-fastembed-acceptance \
  --out .ken/rust-migration/m2-fastembed/current-matrix
```
