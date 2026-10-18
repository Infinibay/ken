# Recibo Linux aarch64

Fuentes nativas en `6ef6aa08`, misma referencia fuente y contratos que macOS.
Los 16 gates pasaron en un contenedor propio aislado, con Rust1.95.0 y datos
públicos fijados. `native-exec.trace` conserva la traza real: sólo el exec inicial.

Logs, JUnit, outputs completos y entradas de medición se conservan sin alterar
en `.ken/rust-migration/m2/linux-receipts/validation/`. Linux usa VmHWM del
propio proceso después de cada fase, evitando el suelo heredado de wait4 de M1.
Los picos son acumulativos entre cargas y no describen una asignación aislada.

La suite Python pasó 15.613 pruebas y los mismos 10 xfail, con una advertencia
upstream de deprecación hf_xet. Mypy pasó sobre los 409 fuentes originales.
La aceptación de Potion no implica terminar M2 ni los demás backends.
