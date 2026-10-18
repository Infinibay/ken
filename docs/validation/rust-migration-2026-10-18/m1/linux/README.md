# Recibos Linux M1

Linux aarch64 en contenedor local, Rust 1.95.0 y Python 3.12.9.
`summary.json` conserva los 16 gates; `benchmark.json`, las 180 muestras.
`parity.json` contiene los 62 casos y `native-exec.trace` registra el único exec inicial.
Los logs crudos y JUnit identificados por el manifiesto se conservan sin alterar
en `.ken/rust-migration/m0-m1/linux-receipts/validation-corrected/`.
La matriz conjunta está en `../matrix.json`. No se ejecutó CI remota.

El máximo RSS wait4 de Linux incluye memoria heredada del harness antes de exec.
La [calibración](rss-calibration.json) reproduce ese efecto incluso con /bin/true.
Los valores publicados son máximos de vida completa del hijo y tienen ese suelo;
no permiten atribuir una mejora de memoria al binario ni compararlos como RSS
posterior a exec. Los tiempos completos de proceso se informan por separado.
