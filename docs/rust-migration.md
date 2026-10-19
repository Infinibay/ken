# Migración Rust

La rama `codex/rust-migration` añade un ejecutable temporal, `ken-rs`.
La implementación Python, sus datos y sus integraciones siguen activos.
La primera entrega implementa exclusivamente `status`; las siguientes etapas
están descritas en [el contrato aprobado](superpowers/specs/2026-10-18-rust-migration-design.md).

```sh
cargo build --release --locked -p ken-cli
./target/release/ken-rs status . --json
./target/release/ken-rs status /ruta/al/proyecto
```

Rust 1.95.0 y los componentes rustfmt/clippy quedan fijados en
`rust-toolchain.toml`. Cargo fija las dependencias directas y transitivas.
No se instala ni reemplaza el comando `ken` para ensayar esta entrega.

## Referencia y pruebas

M0 conserva una copia del worktree original, incluyendo fuentes untracked,
en `.ken/rust-migration/m0-m1/reference`. Sus manifiestos detectan alteraciones.
Los 1.066 hashes iniciales corresponden al worktree con cambios previos;
un clon limpio de HEAD no reconstruye esos contenidos sin la copia.

```sh
.venv/bin/python -m tools.rust_migration.reference verify --repo . --manifest docs/validation/rust-migration-2026-10-18/baseline.json
# Prepare primero todas las variables de modelos indicadas más abajo.
cargo test --locked --workspace
KEN_RUST_BIN="$PWD/target/release/ken-rs" .venv/bin/python -m pytest migration_tests -q
.venv/bin/python -m tools.rust_migration.validate \
  --reference .ken/rust-migration/m0-m1/reference \
  --native target/release/ken-rs \
  --out .ken/rust-migration/m0-m1/validation --scope local
```

En Linux se añade `--trace-exec` y se requiere `strace`. La prueba sigue los
execve/execveat y exige únicamente el exec inicial del binario. En macOS se
comprueban ejecución fuera del checkout, PATH sin Python, sentinelas y librerías;
el recibo local no certifica por sí solo la matriz de plataformas.

El gate ejecuta contratos, suite Python completa, mypy, formato/clippy/tests
Rust, build release, paridad, autonomía e integridad. Compara fallos originales
por ID, omisiones por ID y errores de mypy por archivo/línea/código/mensaje.
Un número igual de fallos no basta. Un reporte ausente, caso omitido, proceso
sin ejecutar, cambio de fuentes durante la validación o error nuevo impide aceptar.

Los errores preexistentes siguen presentes en los recibos aunque el último
intento pase. `summary.json` distingue `M0_accepted`, `M1_local_accepted` y
`M1_matrix_accepted`. Sólo el agregador de plataformas puede aceptar este último:

```sh
.venv/bin/python -m tools.rust_migration.validate --scope matrix \
  --platform-receipts /ruta/a/recibos-linux-y-macos \
  --out .ken/rust-migration/matrix
```

## Medición e integridad

Se miden 30 procesos por programa y escenario: metadatos sin DB, índice vacío y
poblado. El orden Python/Rust alterna; cada muestra incluye el proceso completo.
Se informa mediana, p95 nearest rank, máximo y máximo RSS del proceso mediante
wait4 (unidades normalizadas a bytes). No se descartan muestras fallidas/lentas
ni se usa el high-water acumulado de hijos. La preparación se mide aparte.
Los resultados describen esta máquina; no establecen un SLA nuevo ni miden modelos.
En Linux el pico por hijo incluye memoria heredada antes de exec; la
[calibración](validation/rust-migration-2026-10-18/m1/linux/rss-calibration.json)
impide interpretarlo como memoria exclusiva del binario. M0/M1 pasaron la
[matriz Linux/macOS](validation/rust-migration-2026-10-18/m1/matrix.json).

SQLite se abre readonly, con busy timeout de 5 segundos y un único snapshot para
contadores/paths. Se observan commits WAL publicados sin checkpoint ni migraciones.
La integridad se comprueba sobre datos y metadatos; WAL/SHM son coordinación de
SQLite y no se presentan como datos de dominio modificados.

Health sólo consulta loopback con bearer local, timeout global de un segundo,
sin proxy, redirect ni spawn. Los cuerpos inválidos/vacíos degradan a detenido.
Los datos corruptos producen error explícito y no un informe con contadores falsos.

## CI y límites de la evidencia

El workflow independiente `rust-migration.yml` usa Linux/macOS, una referencia
de su propio checkout y un baseline por plataforma. `--original-manifest` y
`--baseline-dir` permiten identificar ese alcance sin atribuirle los hashes del
worktree local. Se comparan fuentes nativas, fuentes del oráculo, casos, tooling
y toolchain antes de combinar recibos. El workflow Python original no se altera.

Subir un workflow no demuestra que se haya ejecutado. No se hace push, se abre
un PR ni se ejecuta CI remota como parte del gate local.
Los [recibos](validation/rust-migration-2026-10-18/m1/) identifican el alcance observado.

El diseño de paths usa un resolver de componentes con detección de ciclos.
Los ensayos demostraron diferencias con pathlib en la dependencia propuesta
`soft-canonicalize 0.5.6` (targets inexistentes y symlinks dentro de targets),
por lo que se retiró antes de entregar el workspace. Los tests conservan esos
casos y los escapes por symlink/prefijo. No se cambió el contrato para pasar.

Las versiones/inputs de artefactos CI se contrastaron con la documentación
de [upload-artifact](https://github.com/actions/upload-artifact) y
[download-artifact](https://github.com/actions/download-artifact).

## Modelos nativos: primer perfil M2

`ken-models` ejecuta Potion sin Python. Los [casos y salidas congelados](validation/rust-migration-2026-10-18/m2-static/)
se fijaron antes de implementar. El primer perfil pasó pruebas y revisión independiente; los demás
runtimes y el almacenamiento M2 siguen pendientes. No se habilita búsqueda ni
se escribe en índices existentes desde este probe.

La preparación de pruebas utiliza Python exclusivamente como oráculo y para
obtener los cuatro datos públicos fijados; el binario Rust consume sus propios
bytes verificados. Configure los pesos antes de ejecutar la suite workspace o
los gates de migración; la prueba real falla explícitamente si faltan:

```sh
# Una vez con acceso a red; después, local_files_only=True exige cache preparado.
.venv/bin/python -c 'from ken.embedder.model2vec_backend import potion_assets; print(potion_assets().resolve(local_files_only=False))'
export KEN_POTION_SNAPSHOT=/ruta/al/snapshot/e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b
export KEN_MODEL_PROBE="$PWD/target/release/examples/model_probe"
export KEN_TABLE_PROBE="$PWD/target/release/examples/table_probe"
# También obligatorias para la suite workspace y todos los gates:
export KEN_CONTEXT_SNAPSHOT=/ruta/al/snapshot/e74f446dc6e67e29fcee77213472c142f73a6bbb
export KEN_ORT_LIBRARY=/ruta/absoluta/al/core/nativo/registrado
export KEN_CONTEXT_PROBE="$PWD/target/release/examples/context_probe"
export KEN_ETTIN_SOURCE=/ruta/al/snapshot/d166fa88ddde3c42bc3ee92f7df476d941c8204a
export KEN_ETTIN_PROBE="$PWD/target/release/examples/ettin_probe"
cargo build --release --locked -p ken-models --examples
cargo test --locked --workspace
.venv/bin/python -m tools.rust_migration.model_compare \
  --reference .ken/rust-migration/m0-m1/reference \
  --native "$KEN_MODEL_PROBE" --snapshot "$KEN_POTION_SNAPSHOT" \
  --out .ken/rust-migration/m2/parity
.venv/bin/python -m tools.rust_migration.model_validate \
  --reference .ken/rust-migration/m0-m1/reference \
  --native "$KEN_MODEL_PROBE" --snapshot "$KEN_POTION_SNAPSHOT" \
  --baseline-dir .ken/rust-migration/m0-m1 \
  --original-manifest docs/validation/rust-migration-2026-10-18/baseline.json \
  --out .ken/rust-migration/m2/validation
```

Linux exige strace real. Ambos sistemas ejecutan una copia fuera del checkout
con sentinelas en PATH y auditan librerías/Cargo. `compatible_identity` conserva
metadatos del espacio Python acreditado; `runtime` declara las bibliotecas Rust
que ejecutaron el modelo. No se confunden ambas identidades.

La medición separa verificación de bytes, construcción e inferencia. Se retienen
30 cargas nuevas por workload y motor, dentro de un proceso por motor; los picos
post-exec se observan después de cada fase y son acumulativos dentro del proceso.
Linux usa VmHWM del proceso, evitando el suelo heredado de wait4 observado en M1;
macOS usa getrusage del propio proceso. No se atribuye ese pico exclusivamente a
pesos ni se establece un SLA. La construcción Python vuelve a verificar archivos;
Rust construye desde bytes ya verificados, diferencia declarada en los recibos.

`rust-models.yml` conserva una validación independiente de este perfil y sus
regresiones M1. Su presencia no acredita ejecución remota; no se hizo push.

## Tabla estática NPZ nativa

`StaticTableEncoder` consume los bytes del NPZ original, conserva su tokenizer,
desquantiza filas int8 y ejecuta gather→suma F32→proyección→L2. Las expectativas
del [modelo real y fixtures](validation/rust-migration-2026-10-18/m2-table/)
se capturaron antes de implementar. No usa Python ni BLAS del host.

```sh
cargo build --release --locked -p ken-models --examples
.venv/bin/python -m tools.rust_migration.table_compare \
  --reference .ken/rust-migration/m0-m1/reference \
  --native "$PWD/target/release/examples/table_probe" \
  --artifact src/ken/embedder/data/ken__static-qwen3-r512-v2.npz \
  --out .ken/rust-migration/m2-table/parity
.venv/bin/python -m tools.rust_migration.table_validate \
  --reference .ken/rust-migration/m0-m1/reference \
  --model-probe "$KEN_MODEL_PROBE" --snapshot "$KEN_POTION_SNAPSHOT" \
  --native "$PWD/target/release/examples/table_probe" \
  --artifact src/ken/embedder/data/ken__static-qwen3-r512-v2.npz \
  --baseline-dir .ken/rust-migration/m0-m1 \
  --original-manifest docs/validation/rust-migration-2026-10-18/baseline.json \
  --out .ken/rust-migration/m2-table/validation
```

El gate ejecuta las suites completas y regresiones de Potion/M1 junto a la tabla.
Exige que el ejecutable seleccionado explícitamente coincida por SHA-256 con
el release recién compilado y con el proceso de paridad. La matriz requiere
Linux y macOS con ocho huellas coincidentes, los18gates, casos completos y
strace Linux. Cabeceras NPY duplicadas y normas desbordadas producen un error;
esta última corrección evita el cero aparente que también devolvía Python.
Los tres hallazgos importantes de la revisión fueron corregidos con TDD y la
tabla pasó18/18gates en ambos sistemas. M2 sigue abierto para los demás modelos
y datos.

## Perfil ONNX contextual

`ContextEncoder` carga el core nativo ORT1.25.1/API25 declarado en
[runtime-libraries.json](validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json).
La ruta del core es explícita; su tamaño, hash, versión y API deben coincidir.
El snapshot de CodeRank contiene únicamente el tokenizer y grafo fijados por
`code-context-int8.json`. Una lista vacía de pasajes conserva la carga perezosa.
Los vectores son F32 crudos; la normalización pertenece a recuperación.

Para preparar datos con el oráculo de desarrollo:

```sh
.venv/bin/python -c 'from ken.embedder.contextual_onnx import code_context_model; print(code_context_model().assets.resolve(local_files_only=False))'
```

El core standalone puede copiarse del directorio `onnxruntime/capi` del wheel
fijado del entorno de validación. En macOS se llama
`libonnxruntime.1.25.1.dylib`; en Linux, `libonnxruntime.so.1.25.1`. Compruebe su
SHA-256 y tamaño contra la entrada de su plataforma antes de configurar
`KEN_ORT_LIBRARY`. Esta preparación de pruebas no establece el mecanismo de
distribución final de M8 ni requiere Python desde el ejecutable Rust.

```sh
cargo build --release --locked -p ken-cli -p ken-models --bins --examples
.venv/bin/python -m tools.rust_migration.context_validate \
  --reference .ken/rust-migration/m0-m1/reference \
  --model-probe "$KEN_MODEL_PROBE" --potion-snapshot "$KEN_POTION_SNAPSHOT" \
  --table-probe "$KEN_TABLE_PROBE" \
  --artifact src/ken/embedder/data/ken__static-qwen3-r512-v2.npz \
  --native "$KEN_CONTEXT_PROBE" --snapshot "$KEN_CONTEXT_SNAPSHOT" \
  --library "$KEN_ORT_LIBRARY" --baseline-dir .ken/rust-migration/m0-m1 \
  --original-manifest docs/validation/rust-migration-2026-10-18/baseline.json \
  --out .ken/rust-migration/m2-context/validation
.venv/bin/python -m tools.rust_migration.context_validate --scope matrix \
  --platform-receipts /ruta/a/recibos-linux-y-macos \
  --out .ken/rust-migration/m2-context/matrix
```

La matriz contextual exige20gates, las13huellas del candidato actual,20historias
completas por plataforma, el core autenticado y la correspondencia entre release
y proceso real. Rechaza incluso dos recibos coincidentes de fuentes antiguas.
Audita tanto el ejecutable como el core fuera del checkout; Linux exige un solo
exec trazado. Los recibos conservan stdout/stderr y tiempos de preparación,
carga e inferencia, junto al pico acumulativo de memoria del proceso.

Los oráculos anteriores a la implementación y los cores registrados cubren
Darwin/arm64 y Linux/aarch64. Los workflows nativos seleccionan `macos-15` y
`ubuntu-24.04-arm`, según los [runners oficiales de GitHub](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
No se acredita aquí otra arquitectura. El Python original ya presenta pequeñas
diferencias numéricas entre plataformas; cada nativo se compara estrictamente
contra su propio oráculo, sin ampliar tolerancias. Linux permite únicamente cero
o una aparición de la advertencia exacta de identificación de CPU calibrada;
cualquier otro stderr falla. Los perfiles Potion/NPZ mantienen stderr vacío.

## Preparación e inferencia Ettin nativas

`RerankerModel` compila en Rust la cabeza publicada sobre el backbone fijado.
Verifica los 15 archivos fuente, publica un caché completo de forma atómica y
permite reutilizarlo sin el snapshot original. `OnnxReranker` conserva los logits
crudos y el orden de documentos; usa truncado sólo del documento, padding derecho,
CPU con arena activa y cuatro hilos intra-op y uno inter-op por defecto.

Las expectativas se fijaron en ambos sistemas antes del port. Los
[casos y comprobaciones](validation/rust-migration-2026-10-19/m2-ettin/)
incluyen preparación exacta, límites de consulta, concurrencia y 23 historiales
reales. La aplicación original y sus índices se conservan. M2 continúa abierto.

Prepare los datos públicos desde el entorno de desarrollo; esta descarga no
forma parte del runtime Rust:

```sh
.venv/bin/python -c 'import json; from pathlib import Path; from ken.model_assets import ModelAssets; d=json.loads(Path("src/ken/embedder/data/ettin-68m-fp32.json").read_text()); print(ModelAssets.from_dict(d["source"]).resolve(local_files_only=False))'
export KEN_ETTIN_SOURCE=/ruta/al/snapshot/d166fa88ddde3c42bc3ee92f7df476d941c8204a
export KEN_ETTIN_PROBE="$PWD/target/release/examples/ettin_probe"
cargo build --release --locked -p ken-cli -p ken-models --bins --examples
.venv/bin/python -m tools.rust_migration.ettin_validate \
  --reference .ken/rust-migration/m0-m1/reference \
  --model-probe "$KEN_MODEL_PROBE" --potion-snapshot "$KEN_POTION_SNAPSHOT" \
  --table-probe "$KEN_TABLE_PROBE" \
  --artifact src/ken/embedder/data/ken__static-qwen3-r512-v2.npz \
  --context-probe "$KEN_CONTEXT_PROBE" --context-snapshot "$KEN_CONTEXT_SNAPSHOT" \
  --library "$KEN_ORT_LIBRARY" --native "$KEN_ETTIN_PROBE" --source "$KEN_ETTIN_SOURCE" \
  --baseline-dir .ken/rust-migration/m0-m1 \
  --original-manifest docs/validation/rust-migration-2026-10-18/baseline.json \
  --out .ken/rust-migration/m2-ettin/validation
.venv/bin/python -m tools.rust_migration.ettin_validate --scope matrix \
  --platform-receipts /ruta/a/recibos-linux-y-macos \
  --out .ken/rust-migration/m2-ettin/matrix
```

Este gate exige las 20 comprobaciones anteriores y tres nuevas: release Ettin
recién construido, preparación nativa desde un destino inicialmente inexistente
y paridad real. Une 18 huellas del código y datos actuales. Un caché construido
sólo por Python o un ejecutable antiguo impiden aceptar. Los procesos consumen
copias propias fuera del repositorio; Linux exige un único exec trazado.

Los validadores aceptan prerrequisitos tipados o variables preparadas explícitas.
No inventan rutas si faltan. El oráculo elimina las variables nativas heredadas y
conserva únicamente sus directorios aislados de configuración y caché.
La configuración CI exige este perfil; su edición local no acredita ejecución
remota ni sustituye las pruebas locales en ambas plataformas.
