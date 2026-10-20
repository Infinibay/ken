# FastEmbed T4: sesiones ONNX reales

Base74148519. Propietario de sesión/datos y selección de proveedores; aún no acredita el encoder completo ni M2.

- Pruebas de14ejecuciones, cuatrosecciones, cero fallos/ignorados: cinco unidades, tres casos públicos de sesión, cuatro de runtime y dos de proveedores. Nueve grafos pequeños reales cubren inputs I64, máscara, tipos cero, task1 escalar, tipos/formas/NaN inválidos, operador inválido, fuentes retiradas, resultados propios y limpieza al destruir.
- El ensayo privado obliga planes CUDA/ROCm contra el core CPU acreditado: falla el CAPI real, se descarta el constructor y una nueva sesión CPU devuelve `[3,4]`. La disponibilidad de GPU no se fabrica ni se acredita ejecución numérica GPU.
- Cinco modelos reales (BGE, MiniLM, MiniLM multilingüe, CLIP y Jina v3), dos llamadas mixtas cada uno:80filas con inputs/formas exactos y vectores finitos dentro de1e-6absoluto+1e-6relativo contra el original de macOS. Política real: ORT_ENABLE_ALL,0/0hilos y arenaCPU habilitada como en Python. Los pesos reales no se incorporan a Git; los archivos privados se eliminan al terminar y sus fuentes conservan los hashes anteriores.
- PATH sin ejecutables en cada proceso nativo; sin resultados esperados en las solicitudes. Los logs y entradas/salidas son gzip sin pérdida. Clippy estricto/fmt correctos;1066originales intactos. CUDA/ROCm son las únicas features agregadas; ninguna versión de dependencia cambia.

El primer controlador comparó erróneamente macOS nativo con ambos oráculos: el propio original macOS difiere del original Linux hasta0.0001079589 en ese caso. Se conserva la excepción y el diagnóstico independiente; aquel intento no conservó el stdout antes de abortar. El controlador corregido guarda las trazas antes de comparar y usa cada original de su misma plataforma. La tolerancia no cambia. La prueba completa de30modelos/300casos en ambas plataformas queda enT6/T7.

El primer candidato usaba Level3 y el default de arena del binding (false); la lectura de fuentes primarias detectó ambos y se corrigieron ANTES de los resultados aceptados. Las opciones efectivas y sus diagnósticos comparten ahora una sola definición. No se atribuye a la arena la diferencia entre sistemas. Los errores de compilación intermedios/RED quedan conservados.

`provenance.json` enlaza fuentes/fixtures/lock actuales. El Cargo.toml del reproductor conserva el path absoluto del proyecto (ajustarlo si se mueve). `compare.py` es una medición macOS de cinco familias, no el comparador final de T6. Desde la raíz:

```sh
CARGO_INCREMENTAL=0 .ken/rust-migration/m2/prepared-macos-env cargo build --locked --offline --release --manifest-path docs/validation/rust-migration-2026-10-20/m2-fastembed-sessions/reproducer/Cargo.toml
.venv/bin/python docs/validation/rust-migration-2026-10-20/m2-fastembed-sessions/reproducer/compare.py --repo . --probe .ken/rust-migration/m2-translation/source-t4a/target/release/ken-fastembed-session-measurement --out /tmp/ken-fastembed-session-replay
```

Los grafos pequeños se regeneran con `crates/ken-models/tests/fixtures/fastembed/generate.py`, que verifica igualdad de bytes de los existentes y registra la versión ONNX. Los modelos reales y runtime son los artefactos preparados/acreditados de la migración.
