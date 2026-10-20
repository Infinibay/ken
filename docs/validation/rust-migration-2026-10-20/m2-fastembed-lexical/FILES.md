# FastEmbed T3: declaraciones, tokens y pooling

Base73941d0. Componentes nativos; todavía no acredita inferencia ni M2.

- 30declaraciones registradas, sin reemplazar la identidad de perfiles originales.
- 29tokenizadores reales, 116casos léxicos (límites77/128/256/512/8192/8194, Unicode y especiales): igualdad exacta con ambos oráculos.
- 300peticiones de los30modelos se tokenizan. En292casos originales correctos (60vacíos), los261lotes efectivos coinciden exactamente con macOS y Linux. Los8fallos FP16 originales previos a inferencia no tienen feeds; su tokenizer sí está entre los29 comprobados. La reproducción del error nativo queda en T4–T6.
- Los procesos nativos reciben únicamente nombre, textos y lado, sin resultados esperados. El controlador conserva los oráculos fuera del proceso.
- Media/promoción F64 y conversión final F32 contrastadas con funciones originales FastEmbed0.8.0/NumPy2.4.4. El fixture detecta dos bits distintos si se convierte antes.
- Suite completa actual: 208ejecuciones Rust, 47secciones, cero fallos/ignorados. Clippy estricto y fmt correctos. Originales1066 sin cambios.

La primera suite en sandbox falló al abrir sockets loopback: se conserva y la ejecución completa con acceso local pasó. Los RED previos a implementación y los fallos de la herramienta experimental se conservan. Todos los logs son gzip sin pérdida, con hashes originales y comprimidos.

`provenance.json` acredita52fuentes/contratos, las208dependencias exactas del lock y el alcance. `measurement/summary.json` identifica el binario real; no se entrega el binario ni pesos en Git. El Cargo.toml reproducido conserva el path absoluto de este proyecto; ajustar sólo ese path para reproducir en otra ubicación. La prueba usa las cuatro configuraciones registradas y no carga pesos/runtime.

Reproducción, desde la raíz y con el entorno de dependencias preparado:

```sh
CARGO_INCREMENTAL=0 .ken/rust-migration/m2/prepared-macos-env cargo build --locked --offline --release --manifest-path docs/validation/rust-migration-2026-10-20/m2-fastembed-lexical/reproducer/Cargo.toml
.venv/bin/python docs/validation/rust-migration-2026-10-20/m2-fastembed-lexical/reproducer/compare.py --repo . --probe .ken/rust-migration/m2-translation/source-t4a/target/release/ken-fastembed-token-measurement --out /tmp/ken-fastembed-lexical-replay
.venv/bin/python docs/validation/rust-migration-2026-10-20/m2-fastembed-lexical/reproducer/pooling_observation.py
```

El corpus original T1 está en el directorio hermano `m2-fastembed`; esta evidencia no modifica su inventario. Las evidencias históricas permanecen vinculadas a sus fuentes.
