# FastEmbed T5: encoder público perezoso

Basebf36496. `FastEmbedEncoder` coordina modelo, archivos verificados, tokenizer y sesión con una exclusión que abarca cada petición completa. `embed_queries`/`embed_passages` consumen la misma operación que `embed_details`; los resultados y trazas pertenecen al solicitante.

Cinco pruebas públicas ejecutan grafos ONNX reales: constructor/vacíos con pesos y core ausentes; diagnóstico léxico sin pesos/core; dos fallos y reparación real de grafo y biblioteca con reintento; seis primeras llamadas concurrentes y resultados independientes; lote257 con padding separado; error nativo no finito en el segundo lote que rechaza toda la petición y conserva la recuperación posterior. La dimensión512/1024 está disponible sin cargar el modelo. Los archivos temporales se limpian al fallar preparación y al destruir el encoder.

Verificación:219ejecuciones Rust/50secciones sin fallos ni ignorados, Clippy workspace/all-targets sin advertencias, fmt correcto, todos los ejemplos release compilados,1066originales sin cambios. Se conserva el RED de API ausente y el primer error de coerción del guard; la corrección no relaja ninguna prueba.

La metadata declarada/propia tiene una autoridad común (`FastEmbedPreparation::unprepared`); el estado listo sólo se publica después de construir tokenizer y sesión. El fixture añadido provoca un fallo mediante división por cero en el grafo real; no hay interruptores de fallo ni resultados esperados en el producto. Su generador verifica los bytes de los diez grafos existentes antes de registrar el inventario; una omisión inicial de attention_mask fue detectada por esa comprobación y corregida.

`provenance.json` y los logs gzip sin pérdida acreditan este corte. Para reproducir la suite con el entorno ya preparado:

```sh
CARGO_INCREMENTAL=0 .ken/rust-migration/m2/prepared-macos-env cargo test --locked --workspace --all-targets
CARGO_INCREMENTAL=0 .ken/rust-migration/m2/prepared-macos-env cargo clippy --locked --workspace --all-targets -- -D warnings
CARGO_INCREMENTAL=0 .ken/rust-migration/m2/prepared-macos-env cargo build --locked --release --workspace --examples
```

Las pruebas de salud necesitan sockets loopback locales. Este corte no acredita todavía los30modelos/300casos en ambas plataformas ni marca FastEmbed/M2 aceptado: eso corresponde aT6/T7.
