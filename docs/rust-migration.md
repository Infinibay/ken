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
Tras tres hallazgos importantes de la revisión, la tabla está repitiendo la
validación completa. M2 sigue abierto para los demás modelos y datos.
