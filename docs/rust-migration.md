# Migración Rust

**Para retomar en otra máquina:** leer el [traspaso actualizado](rust-migration-handoff.md).
Incluye estado actualizado, pendientes hasta M8, comandos de reconstrucción del
oráculo original, progreso M4c2 y riesgos conocidos. M0–M3 y M4a/M4b/M4c1 están
aceptados. M4c2 también cerró su revisión, reparación y recibo de ambos ARM: catálogo,
ensamblado, ranking, tarjetas, selección de evidencia y presentación nativos.
La aplicación completa todavía no está migrada. Los recibos y capturas se
[conservan localmente y se recuperan del historial](validation-artifacts.md).

Actualización del 28/10: `BestSearch` y preparación contextual están implementados
como biblioteca x86_64. La cadena local y una réplica CI Haswell pasan, pero el
score de la réplica SkylakeX sigue bajo diagnóstico; este bloque no está aceptado.
Ver el [estado actual](rust-migration-handoff.md#bestsearch-implementado-diagnóstico-skylakex-pendiente).

La rama `codex/rust-migration` añade un ejecutable temporal, `ken-rs`.
La implementación Python, sus datos y sus integraciones siguen activos.
La entrega inicial implementó `status`. Ahora también están implementadas la
búsqueda por defecto y la navegación del índice descrita abajo; las etapas
restantes están en [el contrato aprobado](superpowers/specs/2026-10-18-rust-migration-design.md).

```sh
cargo build --release --locked -p ken-cli
./target/release/ken-rs status . --json
./target/release/ken-rs status /ruta/al/proyecto
```

Rust 1.95.0 y los componentes rustfmt/clippy quedan fijados en
`rust-toolchain.toml`. Cargo fija las dependencias directas y transitivas.
No se instala ni reemplaza el comando `ken` para ensayar esta entrega.

## Navegación nativa del índice

Con una base `.ken/ken.db` ya indexada, estos comandos leen símbolos, imports,
documentación, código fuente y relaciones sin configurar recursos de modelos:

```sh
./target/release/ken-rs tools --path . read src/ken/search.py
./target/release/ken-rs tools --path . --json read src/ken/search.py --include symbols imports docstrings
./target/release/ken-rs tools --path . read src/ken/search.py --qualname module_graph --include symbols source
./target/release/ken-rs tools --path . read src/ken/search.py --include profile
./target/release/ken-rs tools --path . related src/ken/search.py imports --depth 2 --limit 20
./target/release/ken-rs tools --path . related src/ken/search.py neighbors
./target/release/ken-rs tools --path . find src/ken/search.py --scope tests
./target/release/ken-rs tools --list
```

La salida predeterminada es texto compacto; `--json` devuelve los datos y
`--compact` produce JSON en una línea. También se admiten los nombres completos
`ken_read`, `ken_related` y `ken_find` después de `tools`.

El mismo bloque está disponible por MCP mediante `ken-rs mcp PROYECTO`:
`ken_read` admite `symbols`, `imports`, `docstrings`, `source` y `profile`; `ken_related`
admite `neighbors` e `imports`; `ken_find` incorpora `scope="tests"`.
Cada llamada abre una vista de solo lectura del índice actual. Una instancia de
biblioteca `IndexNavigation` conserva su snapshot hasta cerrarse. Los snippets
leen la fuente actual con rutas confinadas al proyecto y presupuesto de caracteres.
El resumen del proyecto también está migrado como API de biblioteca.

Este bloque pasó 23 pruebas nativas locales de navegación, CLI/MCP, búsqueda y
status, junto con Clippy estricto. Compara estructuralmente JSON y exactamente
texto compacto de 49 casos de dominio y 19 respuestas públicas nuevas del
original. Otras relaciones y la matriz global de CPU
siguen pendientes; estas pruebas no acreditan la migración completa.

El bloque posterior de perfiles completa todos los valores originales de
`ken_read.include`. Describe la responsabilidad mediante términos reales de los
símbolos y la documentación, contrastados con el resto del índice. La biblioteca
`IndexNavigation.profile(path, granularity, top_terms)` también admite paquetes
con `granularity="dir"`; el tool público solicita perfiles de archivo. Informa
evidencia `none`/`thin`/`moderate`/`strong`, sin resumir con modelos. No escribe en
la base. Conserva los scores y ordena lexicográficamente los empates exactos, que
Python dejaba al orden variable de sus conjuntos.

Se compararon 16 perfiles originales y cinco respuestas públicas JSON/texto,
con pruebas reales CLI/MCP sin instalación de modelos. Sólo el par demostrado
`client`/`explanation` (frecuencias idénticas) difiere en orden en un perfil de
directorio; la referencia original permanece intacta. Pasaron las nueve pruebas
nativas del alcance de perfiles/navegación/texto y Clippy estricto.

## Exploración nativa del código vivo

CLI y MCP implementan `ken_related` con `callers`, `callees`, `subtypes` y
`supertypes`, además de `ken_find(scope="wiring")` para rutas, comandos,
decoradores y variables de entorno. Releen los archivos actuales y usan el
índice para enlazar símbolos y imports. No escriben en la base ni cargan modelos.
La resolución conserva T1 (mismo archivo/nombre único), T2 (un único importado)
y los callsites sin resolver cuando el nombre es ambiguo.

```sh
./target/release/ken-rs --resources grammar-only.json tools --path . related run callees
./target/release/ken-rs --resources grammar-only.json tools --path . related helper callers
./target/release/ken-rs --resources grammar-only.json tools --path . find ENV --scope wiring
```

Estas operaciones aceptan el manifest completo de búsqueda o uno mínimo:

```json
{"format":"ken-search-installation/1","grammar_manifest":"/ruta/grammars/manifest.json"}
```

Las rutas relativas parten del directorio del manifest. La carga de gramáticas
es diferida y compartida entre los tools; una configuración fallida puede
repararse y reintentarse en la misma sesión MCP. La biblioteca ofrece
`signals::extract`, `IndexNavigation.callgraph`, `type_hierarchy` y `wiring`.

Se conservan dos inconsistencias del original para separarlas de la migración:
el `min_confidence` numérico del tool se devuelve sin cambiar y selecciona T2;
los dos nombres públicos `subtypes`/`supertypes` producen descendientes sin
overrides porque el adaptador original pasa `down`/`up`. La API de biblioteca
admite `sub`/`super` y overrides, así como los umbrales de llamadas `T1`/`T2`.
La jerarquía es una heurística por nombres, incluso entre lenguajes.

Coinciden 19 observaciones de señales, 26 de dominio y 10 respuestas públicas
JSON/texto del original. Pasaron 33 raíces nativas del alcance afectado y Clippy
estricto, incluyendo reparaciones de configuración y cambios de fuente durante
una sesión MCP. No se añadieron versiones externas ni se cerraron M5/KQL o M7.

## Orientación nativa del proyecto

`ken_rank` añade tres scopes nativos, sin instalación de modelos:

```sh
./target/release/ken-rs tools --path . rank --scope project
./target/release/ken-rs tools --path . --json rank --scope architecture --verbose 2
./target/release/ken-rs tools --path . rank --scope changes
```

`project` resume lenguajes, directorios y archivos principales. `architecture`
informa ciclos de imports, capas, comunidades y nodos centrales. Expone la
cobertura de resolución, el tamaño completo de cada grupo, muestras acotadas,
la calidad de las comunidades y si PageRank convergió. Los algoritmos son
iterativos, también para ciclos grandes. `changes` lee Git con un límite de
cinco segundos y añade símbolos/tests del índice a los cambios del worktree;
conserva símbolos de archivos borrados y la interpretación original de nombres
citados y renombres de porcelain v1. No escribe en la base.

CLI y MCP comparten el mismo servicio y formatos de salida. `tools rank` usa
`project` por defecto; MCP conserva el default original `session`, que todavía
se rechaza explícitamente: hay que elegir uno de los tres scopes implementados.
La biblioteca ofrece `IndexNavigation.architecture(depth, limit)` y
`changed_context()`, además de `project_overview`.

Se compararon 24 informes de arquitectura y 20 respuestas públicas originales
JSON/texto en seis grafos y un worktree real. También se validaron un ciclo de
12.000 archivos, grandes salidas de Git y el cierre de helpers al vencer el
plazo. Las 31 raíces nativas del alcance afectado y Clippy estricto pasaron;
la revisión final no encontró problemas pendientes. La matriz global sigue
abierta. Se aplicó la skill
[deprecation-and-migration](https://github.com/addyosmani/agent-skills/blob/main/skills/deprecation-and-migration/SKILL.md)
para completar consumidores por interfaz y conservar el original hasta el cutover.

## Búsqueda nativa de texto

`ken_find(scope="text")` está implementado en CLI y MCP para Linux x86_64,
sin instalación de modelos. El modo predeterminado usa BM25 de SQLite FTS5;
`literal=true` busca substrings exactos en los archivos actuales ya indexados.

```sh
./target/release/ken-rs tools --path . find 'SourceFileReader' --scope text --literal
./target/release/ken-rs tools --path . --json find 'source reader' --scope text --language rust --limit 10
```

La búsqueda literal sólo lee. BM25 actualiza atómicamente el espejo derivado
`fts_files`/`ci_fts_state`, sin modificar los hechos del índice. Conserva el
comportamiento original: un archivo indexado que ya no se puede leer o supera
1 MiB retiene su entrada FTS anterior hasta retirarse del índice. Las rutas de
fuente se confinan al proyecto. Los términos BM25 se escapan como texto, sin
interpretar operadores escritos por el usuario. Los empates conservan el orden
SQLite del espejo existente; la primera creación de filas empatadas puede
ordenarse de forma distinta al `set` de Python.

Las 29 observaciones originales nuevas coinciden en datos y texto compacto,
por biblioteca, procesos CLI y sesiones MCP. También se comprobaron el rollback
del espejo, el inicio sin caché, límites de tamaño y el rechazo de formatos
inválidos antes de ejecutar la consulta. `response_format="legacy"` devuelve
datos para este scope; las variantes semánticas de compatibilidad siguen
pendientes. Este bloque no cierra la matriz global ni M4–M8.

## Continuación del 24 de octubre: ranking y Linux x86_64

`piece_features` conserva el esquema de 262 columnas y sus tres pases de
cobertura; `PieceReranker` usa el bosque registrado de 1.280 árboles y conserva
la identidad de propuestas duplicadas mediante `PieceMatch.proposal_index`.
Las pruebas comparan 98 observaciones originales de x86_64, llamadas del encoder
y stemmer, scores, orden y caminos/hojas reales. Los casos adicionales reutilizan
las nueve raíces originales de ranking; no vuelven a ejecutarlas.

Linux x86_64 tiene su propio registro en
`crates/ken-retrieval/resources/dense-runtime-x86_64.json`: los tres sidecars de
NumPy 2.4.4 se autentican antes de cargar el BLAS ILP64. El registro ARM se
conserva. El BLAS LP64 de compilación de CT2 se prepara desde el mismo OpenBLAS
0.3.26, con `TARGET=CORE2` en x86_64 y `TARGET=ARMV8` en aarch64.
La referencia de alineamiento de x86_64 está separada: las reducciones de ARM
no se usan como expectativas de esta arquitectura ni se amplían tolerancias.
Los nuevos fixtures de referencia se guardan comprimidos con gzip; las capturas
crudas y los logs quedan sólo en el workspace local.

El entorno local usa Python 3.12.9, Unicode 15.0, NumPy 2.4.4, CMake 3.31.10 y
Rust 1.95.0. Las bibliotecas de ejecución se copian desde `numpy.libs` a un
directorio local y se configura `KEN_DENSE_BLAS_DIR` con su ruta absoluta.
`translation_build prepare-openblas` acepta ambas arquitecturas Linux y rechaza
recibos de compilación de otra arquitectura.

Validación local con Rust 1.95.0: `ken-retrieval --all-targets` pasó 71 pruebas,
`ken-core --all-targets` pasó 50, y las suites de tooling afectadas pasaron 92.
El corpus estructural reubicado conserva sus bytes y pasa 2.429 pruebas, con
el único `xfail` conocido de su ledger. `cargo fmt --all --check` y Clippy de
`ken-retrieval --all-targets` con `-D warnings` también pasan.

Esto habilita y prueba recuperación/ranking en x86_64; no acredita todos los
backends de modelos, CLI/MCP, distribución ni M4 completo en esta plataforma.
`piece_cards` conserva la proyección `requested-piece-card-v102`: 64 líneas,
4 extractos, 12.000 caracteres de JSON canónico, texto físico y procedencia por
propietario. Sus 60 observaciones originales pasan localmente, incluidas fuentes
cambiadas y reemplazo del directorio raíz. Las suites actuales pasan 72 pruebas
de retrieval, 51 de core y 108 de tooling, junto con fmt y Clippy estricto.
Ranking y tarjetas pasaron todos sus gates en ambos ARM en la ejecución
`40117742527`: 123 pruebas nativas en Linux, 122 en macOS y 109 de tooling por host, formato y Clippy
estricto. La selección de evidencia conserva 88 observaciones originales, máscaras
dinámicas para más de 64 pistas y un presupuesto total de 40 líneas; pasa
localmente 124 pruebas nativas y 110 de tooling. También pasó ambos ARM en
`40118877663` (124 raíces Linux, 123 macOS y 110 de tooling por host).
La presentación compara 117 observaciones originales, incluidos redondeo,
caracteres Unicode y avisos de fuentes cambiadas; pasa localmente 125 pruebas
nativas y 111 de tooling en ese checkpoint. Los gates ARM, Task 7 y la revisión
M4c2 cerraron después, en el recibo del 24/10 descrito a continuación. M4d–M8
continúan pendientes. El límite de gramáticas x86_64 de ese checkpoint se cerró
en la validación posterior descrita a continuación.

## Avance al 23 de octubre

M2 está cerrado con [la integración nativa](validation/rust-migration-2026-10-21/m2-integration/README.md)
y [su revisión y reparación](validation/rust-migration-2026-10-23/m2-integration-review/README.md):
modelos, adquisición, propietarios diferidos y almacenamiento tienen evidencia
en macOS arm64 y Linux aarch64. El cierre pasó318/308casos Rust y77tests de
integración afectados por plataforma. Las matrices neurales previas conservan
sus identidades y resultados; esas cifras no representan nuevas ejecuciones de
todos los modelos ni promoción de la aplicación completa.

M3a añade `SourceFilter` y `ProjectSources` para exclusiones y recorrido confinado.
La [revisión y reparación](validation/rust-migration-2026-10-23/m3-source-review/README.md)
cierra sus seis hallazgos con34pruebas Rust y24pruebas de herramientas por
plataforma. Se comparan702decisiones y134recorridos originales, preservando
patrones Unicode, prioridades, orden y scopes. Los directorios pendientes se
abren mediante un descriptor confinado. M3a está aceptado. M3b implementa los19analizadores con20gramáticas y44extensiones;
[su revisión y reparación](validation/rust-migration-2026-10-23/m3-parsers-review/README.md)
cierra dos diferencias con249entradas por plataforma,33pruebas Rust y38pruebas de
herramientas. M3b está aceptado tras una única revisión y pasada de reparación. Los originales permanecen intactos.

M3c (imports) y M3d (modelo común) también están aceptados tras sus revisiones.
M3e ya tiene [aceptación revisada](validation/rust-migration-2026-10-23/m3-index-review/README.md):
indexación incremental completa, publicación transaccional, vocabulario, pasajes y
dos vistas de recuperación. La única revisión encontró3fallos importantes, todos
corregidos con pruebas RED→GREEN. Cada plataforma pasa47pruebas Rust y43de
validación;12historias nativas completas coinciden con el original. Las suites
anteriores y la inferencia ya aceptada se reutilizan con sus identidades.

M0–M3 están aceptados para sus capacidades documentadas. Ahora sigue M4 (búsqueda),
y quedan M5 (IR/KQL), M6 (memoria/checks), M7 (daemon/integraciones) y M8 (entrega).
La coordinación de lectores de slots antiguos entre varios commits sigue siendo
una condición explícita de M4/M7 antes del cambio público. Los originales siguen
intactos y la aplicación instalada conserva Python. No se declara la migración
completa ni se calcula avance por líneas traducidas.

Los recibos históricos describen sus propias fuentes. Para reproducir el bloque
de fuentes después de cambios posteriores, el agregador usa la copia pequeña de
`native-sources` incluida en el recibo; no atribuye una ejecución vieja al código
nuevo ni obliga a repetir inferencia sin cambios.

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
# Traducción y compilación C++: preparación detallada al final de esta guía.
export KEN_TRANSLATION_SOURCE=/ruta/al/snapshot/ad91ad1697ea1761111ff4c179400796d085b347
export KEN_TRANSLATION_PROBE="$PWD/target/release/examples/translation_probe"
export KEN_POLICY_PROBE="$PWD/target/release/examples/model_policy_probe"
export CMAKE=/ruta/absoluta/al/ejecutable/cmake-3.31.10
# En Linux prepare también OpenBLAS y sus tres variables antes de compilar.
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
La matriz de 23 comprobaciones pasó en macOS arm64 y Linux aarch64; la
[revisión independiente](validation/rust-migration-2026-10-19/m2-ettin/REVIEW.md)
no encontró problemas críticos ni importantes. Quedó un detalle menor de
diagnóstico de opsets en grafos personalizados, documentado como pendiente.

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

Ettin conserva cada lectura cruda `reported_hwm_*_bytes` del contador del sistema.
Los campos `peak_*_bytes` son el máximo observado de esas lecturas, comprobado
exactamente por el comparador. Linux documenta `VmHWM` como aproximado y puede
devolver lecturas decrecientes; esta evidencia no mide un pico exacto de memoria
ni acredita un SLA.

Los validadores aceptan prerrequisitos tipados o variables preparadas explícitas.
No inventan rutas si faltan. El oráculo elimina las variables nativas heredadas y
conserva únicamente sus directorios aislados de configuración y caché.
La configuración CI exige este perfil; su edición local no acredita ejecución
remota ni sustituye las pruebas locales en ambas plataformas.

## Traducción española nativa

`TranslationModel` prepara los cinco archivos registrados sin convertir pesos.
`LocalQueryExpansion` conserva las reglas Unicode15, la protección de nombres de
código y la carga perezosa del original. Ejecuta CTranslate2 4.8.2 y SentencePiece
0.2.1 directamente; las consultas inglesas no necesitan datos ni cargar el motor.
`expand_attempt` conserva también la entrada realmente codificada cuando falla
la inferencia. Las salidas y trazas pertenecen a cada llamada.

Los29 historiales públicos y24 adicionales del motor coinciden exactamente con
los originales de cada plataforma. Los originales ya difieren en algunos textos
largos entre macOS y Linux; se conservan ambas expectativas. Las26 comprobaciones del perfil pasan en ambos sistemas, con134 pruebas Rust y
15671 pruebas Python por plataforma y los mismos10 xfail históricos. La revisión
final detectó dos fallos, corregidos con pruebas de regresión y una matriz nueva.
Los [dos detalles menores](validation/rust-migration-2026-10-19/m2-translation/REVIEW.md)
quedan registrados. Este perfil está aceptado; M2 y la migración completa siguen abiertos.

La compilación requiere CMake3.31.10 y un compilador C++. Puede preparar el
ejecutable CMake en el directorio privado, sin modificar el entorno instalado:

```sh
uv pip install --python .venv/bin/python --target .ken/rust-migration/native-build-tools --no-deps cmake==3.31.10
export CMAKE="$PWD/.ken/rust-migration/native-build-tools/cmake/data/bin/cmake"
.venv/bin/python -c 'import json; from pathlib import Path; from ken.model_assets import ModelAssets; d=json.loads(Path("src/ken/embedder/data/es-en-ct2-int8.json").read_text()); print(ModelAssets.from_dict(d["source"]).resolve(local_files_only=False))'
export KEN_TRANSLATION_SOURCE=/ruta/al/snapshot/ad91ad1697ea1761111ff4c179400796d085b347
export KEN_TRANSLATION_PROBE="$PWD/target/release/examples/translation_probe"
```

macOS usa Accelerate y Ruy. Linux requiere GNU make, pkg-config, libgomp y una
compilación privada y estática de OpenBLAS0.3.26. El preparador verifica los
24404912bytes y SHA-256 del archivo fuente antes de ejecutar herramientas,
conserva los registros y publica un prefijo completo con sus hashes:

```sh
# Sólo Linux aarch64; obtenga el archivo de la publicación oficial fijada.
mkdir -p .ken/rust-migration/translation-build
curl --fail --location https://github.com/OpenMathLib/OpenBLAS/releases/download/v0.3.26/OpenBLAS-0.3.26.tar.gz \
  --output .ken/rust-migration/translation-build/OpenBLAS-0.3.26.tar.gz
.venv/bin/python -m tools.rust_migration.translation_build prepare-openblas \
  --archive "$PWD/.ken/rust-migration/translation-build/OpenBLAS-0.3.26.tar.gz" \
  --destination "$PWD/.ken/rust-migration/translation-build/openblas"
export PKG_CONFIG_PATH="$PWD/.ken/rust-migration/translation-build/openblas/lib/pkgconfig"
export DEP_OPENBLAS_INCLUDE="$PWD/.ken/rust-migration/translation-build/openblas/include"
export DEP_OPENBLAS_LIBRARY="$PWD/.ken/rust-migration/translation-build/openblas/lib"
```

El núcleo C++ se compila en Release incluso durante las pruebas Rust ordinarias:
su build Debug alteraba una traducción larga. El override afecta sólo a ct2rs;
Rust conserva sus comprobaciones. La validación lee el directorio que Cargo
seleccionó realmente, sus opciones CMake y el compilador; rechaza un caché antiguo,
un backend distinto o prerrequisitos ausentes o cambiados.
Si cambia el prefijo OpenBLAS, regenere ct2rs en cada perfil: `cargo clean -p ct2rs`
limpia el perfil por defecto; `cargo clean -p ct2rs --release` renueva Release.
Precompile las pruebas antes de ejecutar el gate con su límite fijo.

```sh
cargo build --release --locked -p ken-cli -p ken-models --bins --examples
cargo test --locked --workspace --no-run
native_build_args=(--cmake "$CMAKE")
# En Linux añada: native_build_args+=(--openblas-prefix /ruta/absoluta/al/prefijo/openblas)
.venv/bin/python -m tools.rust_migration.translation_validate \
  --reference .ken/rust-migration/m0-m1/reference \
  --model-probe "$KEN_MODEL_PROBE" --potion-snapshot "$KEN_POTION_SNAPSHOT" \
  --table-probe "$KEN_TABLE_PROBE" \
  --artifact src/ken/embedder/data/ken__static-qwen3-r512-v2.npz \
  --context-probe "$KEN_CONTEXT_PROBE" --context-snapshot "$KEN_CONTEXT_SNAPSHOT" \
  --library "$KEN_ORT_LIBRARY" \
  --ettin-probe "$KEN_ETTIN_PROBE" --ettin-source "$KEN_ETTIN_SOURCE" \
  --native "$KEN_TRANSLATION_PROBE" --source "$KEN_TRANSLATION_SOURCE" \
  --baseline-dir .ken/rust-migration/m0-m1 \
  --original-manifest docs/validation/rust-migration-2026-10-18/baseline.json \
  --out .ken/rust-migration/m2-translation/validation "${native_build_args[@]}"
.venv/bin/python -m tools.rust_migration.translation_validate --scope matrix \
  --platform-receipts /ruta/a/recibos-linux-y-macos \
  --out .ken/rust-migration/m2-translation/matrix
```

Este gate incorpora las23 comprobaciones anteriores, la preparación nueva en
Rust, el release acreditado y el proceso de traducción. El proceso consume copias
independientes fuera del repositorio, con PATH de sentinelas; Linux registra un
único exec real. Los tiempos y picos crudos/observados se conservan sin atribuir
una mejora de rendimiento ni un SLA. Las fuentes y fixtures embebidas participan
en las huellas del candidato actual. El workflow usa los CT2 originales
4.8.3/macOS y4.8.2/Linux en entornos CI desechables; el runtime Rust declara su
propia versión. Los originales, el comando instalado y los índices se conservan.

## Política de selección de modelos en Rust

`ken_models::model_policy` decide la recomendación, el modelo del proyecto,
el modelo activo y los prompts desde valores explícitos. Mantiene separados el
modelo forzado del proceso y la resolución del proyecto. Conserva espacios,
NUL y nombres desconocidos; usa las reglas Unicode15 del original para validar
el default del usuario. Cada instancia y cada resultado poseen sus datos.

`ProjectModelFacts` exige hechos de almacenamiento ya establecidos. La presencia
de vectores incluye BLOB vacío y slots cero o negativos. Un lector que no puede
establecer esos hechos debe producir un error. Sólo ausencia probada de vectores
y de marcador permite devolver `InitialModelPin`; un marcador presente vacío
impide ese pin. El resultado es un valor. `ken-store` ya ofrece la publicación transaccional y
los hechos SQLite; la conexión con los consumidores de la aplicación y los
lectores de configuración se completa en sus etapas de integración.

Las [expectativas originales](validation/rust-migration-2026-10-19/m2-policy/reference.json)
se capturaron en ambas plataformas antes del código nativo: 1.292 historiales,
seis variantes de forzado por historial y 23 nombres para prompts. El comparador
repite el original, exige tipos JSON exactos y ejecuta una copia del probe fuera
del checkout con PATH de sentinelas y sin datos de modelos. Linux exige un exec
real. El manifiesto de la referencia actual se verifica antes y después; las
fuentes propietarias deben conservar sus hashes originales. Su identidad completa
puede cambiar por archivos ajenos a esa lógica; la huella de fuentes actual se
vincula a los recibos de ambas plataformas.

El replay admite parches estables de Python 3.12 conservando el parche real como
procedencia. Sigue exigiendo Unicode 15, hashes exactos de las fuentes y todos los
resultados, filas y prompts; otra versión menor o una diferencia de comportamiento
rechaza la comparación.

Prepare todos los modelos anteriores y añada el probe explícito antes de los
gates o de `migration_tests`; ninguna ruta se inventa cuando falta:

```sh
export KEN_POLICY_PROBE="$PWD/target/release/examples/model_policy_probe"
cargo build --release --locked -p ken-cli -p ken-models --bins --examples
cargo test --locked --workspace --all-targets --no-run
.venv/bin/python -m tools.rust_migration.policy_validate \
  --reference .ken/rust-migration/m0-m1/reference \
  --model-probe "$KEN_MODEL_PROBE" --potion-snapshot "$KEN_POTION_SNAPSHOT" \
  --table-probe "$KEN_TABLE_PROBE" \
  --artifact src/ken/embedder/data/ken__static-qwen3-r512-v2.npz \
  --context-probe "$KEN_CONTEXT_PROBE" --context-snapshot "$KEN_CONTEXT_SNAPSHOT" \
  --library "$KEN_ORT_LIBRARY" \
  --ettin-probe "$KEN_ETTIN_PROBE" --ettin-source "$KEN_ETTIN_SOURCE" \
  --native "$KEN_TRANSLATION_PROBE" --source "$KEN_TRANSLATION_SOURCE" \
  --policy-probe "$KEN_POLICY_PROBE" \
  --baseline-dir .ken/rust-migration/m0-m1 \
  --original-manifest docs/validation/rust-migration-2026-10-18/baseline.json \
  --out .ken/rust-migration/m2-policy/validation "${native_build_args[@]}"
.venv/bin/python -m tools.rust_migration.policy_validate --scope matrix \
  --platform-receipts /ruta/a/recibos-linux-y-macos \
  --out .ken/rust-migration/m2-policy/matrix
```

La aceptación exige las 26 comprobaciones previas más release y paridad de
política: 28 gates y 26 huellas actuales. `Policy_accepted` corresponde a este
tramo; `M2_accepted` permanece falso. Otros runtimes, adquisición, ciclo de vida
de cachés y etapas posteriores siguen pendientes. El almacenamiento tiene su
propio perfil de aceptación, descrito abajo.

Cada recibo local vincula `execution-artifacts.json` por SHA-256. La matriz exige
los archivos enumerados y sus hashes/tamaños, los recibos previos en su árbol real,
logs, resultados XML, benchmark y trazas Linux; vuelve a comparar la salida de
política autenticada con el oráculo original. Copie el árbol completo de evidencia
con sus rutas relativas. Los resúmenes sueltos no acreditan una ejecución. La
carpeta `environment` contiene cachés descartables de preparación y se excluye del
manifiesto de resultados.


## Almacenamiento nativo y recuperación

`ken-store` conserva SQLite y los segmentos formato1/F32 de65536filas. La SQL
original se incorpora como recurso compartido. `ProjectStore` recupera una
compactación pendiente antes de exponer la conexión; el asignador exige una
transacción `BEGIN IMMEDIATE`. Manifiestos y segmentos se publican completos;
los segmentos existentes no se redimensionan y las lecturas poseen sus buffers.
La [especificación](superpowers/specs/2026-10-19-rust-storage-design.md) y el
[plan](superpowers/plans/2026-10-19-rust-m2-storage.md) definen las garantías y
las correcciones de integridad. Los originales y el comando instalado se conservan.

Los [32 historiales originales](validation/rust-migration-2026-10-19/m2-storage/reference.json)
se congelaron antes del código nativo:23 de compatibilidad y9 defectos de
integridad separados. Normalización/scoring usa exactamente
`abs(actual-reference) <= 1e-6 + 1e-6*abs(reference)`; IDs, slots, BLOBs, orden y
tipos son exactos. El oráculo de datos exige Python3.12.9, SQLite3.47.1 y
NumPy2.4.4. La excepción de parches de Python del perfil de políticas no amplía
este registro. El runtime Rust usa el SQLite3.53.2 ya fijado por Cargo.

Prepare los datos y cores anteriores y añada el perfil explícito:

```sh
export KEN_STORAGE_PROBE="$PWD/target/release/examples/storage_probe"
cargo build --release --locked -p ken-cli -p ken-models -p ken-store --bins --examples
cargo test --locked --workspace --all-targets --no-run
.venv/bin/python -m tools.rust_migration.storage_validate \
  --reference .ken/rust-migration/m0-m1/reference \
  --model-probe "$KEN_MODEL_PROBE" --potion-snapshot "$KEN_POTION_SNAPSHOT" \
  --table-probe "$KEN_TABLE_PROBE" \
  --artifact src/ken/embedder/data/ken__static-qwen3-r512-v2.npz \
  --context-probe "$KEN_CONTEXT_PROBE" --context-snapshot "$KEN_CONTEXT_SNAPSHOT" \
  --library "$KEN_ORT_LIBRARY" \
  --ettin-probe "$KEN_ETTIN_PROBE" --ettin-source "$KEN_ETTIN_SOURCE" \
  --native "$KEN_TRANSLATION_PROBE" --source "$KEN_TRANSLATION_SOURCE" \
  --policy-probe "$KEN_POLICY_PROBE" --storage-probe "$KEN_STORAGE_PROBE" \
  --baseline-dir .ken/rust-migration/m0-m1 \
  --original-manifest docs/validation/rust-migration-2026-10-18/baseline.json \
  --out .ken/rust-migration/m2-storage/validation "${native_build_args[@]}"
.venv/bin/python -m tools.rust_migration.storage_validate --scope matrix \
  --platform-receipts /ruta/a/recibos-linux-y-macos \
  --out .ken/rust-migration/m2-storage/matrix
```

El directorio del probe debe contener también `storage_recovery_driver`, vinculado
al release recién compilado. El controlador prepara datos con el Python original,
ejecuta copias Rust fuera del checkout con PATH sin Python y termina su propio
grupo de procesos en cuatro fases de compactación y después del primer lote de
migración. El original lee las generaciones recuperadas y comprueba valores,
filas, contadores, listas libres y ausencia de marcadores internos estables.
Linux conserva las trazas reales de cada ejecución. La prueba acredita recuperación
ante terminación del proceso; la serialización de lectores y la pérdida eléctrica
mantienen los límites declarados en la especificación.

El probe informa tiempo del recorrido y pico acumulado de su proceso al terminar
las observaciones, antes de serializar el transporte JSON. Los tamaños aparentes,
bloques asignados y hashes físicos se distinguen de la comparación lógica; no se
presume una mejora de rendimiento por el cambio de lenguaje.

La matriz exige31gates y29huellas actuales: los28controles anteriores más release,
paridad y recuperación de almacenamiento. Autentica una sola lectura de los bytes
del árbol completo y reutiliza esos buffers al verificar el manifiesto de políticas
anidado. Repite las comparaciones semánticas aun cuando los archivos hayan sido
sellados de nuevo. Las fixtures sintéticas de las pruebas no pueden acreditar una
aceptación real. `Storage_accepted` corresponde sólo a este subsistema;
`M2_accepted` continúa falso hasta cubrir el resto de los modelos e integraciones.

Los dos workflows comparten `.github/actions/prepare-native-validation`, siguiendo
el mecanismo de [acciones compuestas de GitHub](https://docs.github.com/en/actions/tutorials/create-actions/create-a-composite-action).
La preparación usa Python administrado por uv dentro de `.ken`, sin crear un
comando global, y verifica las versiones registradas antes de descargar modelos;
la [gestión de Python de uv](https://docs.astral.sh/uv/guides/install-python/)
documenta ese mecanismo. La configuración de CI es revisable localmente; su
presencia no acredita que se haya ejecutado en GitHub.

### FastEmbed nativo: corpus completo y propiedad de archivos

El encoder Rust prepara el modelo al primer texto no vacío. La construcción y las
listas vacías no necesitan pesos ni runtime. El tokenizer conserva los prompts del
nombre solicitado, los inputs I64 y el batching de256 del original. La sesión
posee archivos privados verificados hasta después de destruir el runtime; una
preparación fallida permite corregir la fuente y volver a intentar.

El [plan FastEmbed](superpowers/plans/2026-10-20-rust-m2-fastembed.md) añade tres
controles a los31 anteriores: release recién compilado, paridad de30modelos/300casos
y propiedad con fallo real, reparación y retirada de fuentes copiadas en cinco
familias. Los vectores F32 finitos se comparan con el original de la misma
plataforma a1e-6absoluto+1e-6relativo. El error original del modelo alemán FP16 se
conserva como error observado y delimitado; no se fabrican vectores. No se afirma
paridad numérica GPU ni identidad de vectores entre sistemas operativos.

Prepare los tres parámetros explícitos, además de los anteriores. `SOURCES`
contiene `<model_id con / reemplazado por -->/<revision>/` para cada fuente del
catálogo registrado. Los archivos de origen pueden ser symlinks de una caché;
los archivos privados del encoder son independientes. Para CI, use una carpeta
temporal vacía y `--acquire-fastembed-sources`: cada modelo se descarga con su
revisión, tamaño y hash fijados, se valida y se retira al cerrar su propia sesión.
Las fuentes preparadas sin esa opción se conservan. Los30modelos y cinco familias
se recorren completos; no se necesita retener simultáneamente19GB de pesos.

CI comprueba espacio real antes y después de compilar, y antes de cada descarga.
Reserva dos copias para paridad y tres para propiedad, más512MiB para evidencia.
Los cinco modelos de las pruebas por procesos se preparan juntos antes de su
contador de600s y se retiran al cerrar la suite; sus procesos reciben el plazo
restante para poder terminar antes del corte. El máximo, incluyendo esa fase,
es8.14GB. La preparación añade3GiB de margen para compilar.
Las compilaciones dev/test de CI omiten símbolos de depuración y conservan
assertions y optimización. No se borran cachés ajenas ni se contratan runners.
El comando aislado de matriz instala explícitamente `numpy==2.4.4`.
El job completo dispone de180min para preparación, baseline y validación; los
plazos de600s por suite y1800s por modelo conservan sus valores anteriores.

```sh
export CARGO_INCREMENTAL=0
export KEN_FASTEMBED_PROBE="$PWD/target/release/examples/fastembed_probe"
export KEN_FASTEMBED_SOURCES=/ruta/absoluta/a/las/fuentes
export KEN_FASTEMBED_REGISTRY="$PWD/crates/ken-models/resources/fastembed-catalog.json"
cargo build --release --locked -p ken-cli -p ken-models -p ken-store --bins --examples
cargo test --locked --workspace --all-targets --no-run
.venv/bin/python -m tools.rust_migration.fastembed_validate \
  --reference .ken/rust-migration/m0-m1/reference \
  --model-probe "$KEN_MODEL_PROBE" --potion-snapshot "$KEN_POTION_SNAPSHOT" \
  --table-probe "$KEN_TABLE_PROBE" \
  --artifact src/ken/embedder/data/ken__static-qwen3-r512-v2.npz \
  --context-probe "$KEN_CONTEXT_PROBE" --context-snapshot "$KEN_CONTEXT_SNAPSHOT" \
  --library "$KEN_ORT_LIBRARY" \
  --ettin-probe "$KEN_ETTIN_PROBE" --ettin-source "$KEN_ETTIN_SOURCE" \
  --translation-probe "$KEN_TRANSLATION_PROBE" --translation-source "$KEN_TRANSLATION_SOURCE" \
  --policy-probe "$KEN_POLICY_PROBE" --storage-probe "$KEN_STORAGE_PROBE" \
  --fastembed-probe "$KEN_FASTEMBED_PROBE" --fastembed-sources "$KEN_FASTEMBED_SOURCES" \
  --fastembed-registry "$KEN_FASTEMBED_REGISTRY" \
  --baseline-dir .ken/rust-migration/m0-m1 \
  --original-manifest docs/validation/rust-migration-2026-10-18/baseline.json \
  --out .ken/rust-migration/m2-fastembed/validation "${native_build_args[@]}"
.venv/bin/python -m tools.rust_migration.fastembed_validate --scope matrix \
  --platform-receipts /ruta/a/recibos-linux-y-macos \
  --out .ken/rust-migration/m2-fastembed/matrix
```

La matriz exige34controles y33huellas actuales en Darwin arm64 y Linux aarch64.
Autentica una sola vez el árbol de ejecución completo y usa los mismos bytes
para verificar los manifiestos anidados, descomprimir registros limitados a16MiB
y repetir las comparaciones semánticas de vectores, inputs, fuentes y propiedad.
Los resúmenes guardan referencias y medidas; stdout y stderr completos permanecen
en registros gzip autenticados. Una fixture sintética no puede acreditar la matriz.
`FastEmbed_accepted` y `Storage_accepted` corresponden a esos subsistemas;
`M2_accepted` permanece falso hasta completar los modelos e integraciones restantes.

El controlador aplica el mismo plazo total a escribir solicitudes, completar
líneas y cerrar el proceso. Las tuberías no bloqueantes limitan cada frame a16MiB;
un timeout o frame inválido termina y recoge el grupo propio, incluido el trazador
de Linux. Las pruebas usan procesos nativos reales que dejan de leer, envían una
línea parcial o producen salida excesiva.

La [aceptación posterior a la revisión](validation/rust-migration-2026-10-20/m2-fastembed-final-acceptance/IMPLEMENTATION.md) conserva los recibos actuales de34controles/33huellas en ambos sistemas,30modelos y cinco familias de propiedad. Cada sistema pasó15.844tests Python y221ejecuciones Rust; las93pruebas por procesos terminaron en211,010s/macOS y449,871s/Linux, sin ampliar el plazo de600s. El comando de matriz aislado conNumPy2.4.4 también pasó. La [revisión original](validation/rust-migration-2026-10-20/m2-fastembed-final-acceptance/REVIEW.md), las [decisiones y el menor diferido](validation/rust-migration-2026-10-20/m2-fastembed-final-acceptance/DECISIONS.md) y las medidas de recursos permanecen junto a los registros completos. Los recibos anteriores permanecen intactos; M2 continúa abierto para los modelos e integraciones restantes.

Actualización2026-10-23: M2 cerró en la integración revisada (`m2-integration-review`).
M3a descubrimiento, M3b parsers y M3c imports tienen recibos revisados separados.
La [aceptación M3c](validation/rust-migration-2026-10-23/m3-imports-review/README.md)
verifica79pruebas Rust y33de tooling por plataforma,107entradas originales en
ambos modos de adquisición y249regresiones del parser después de compartir la
representación Unicode. Las2incidencias importantes de revisión están corregidas;
MINORS documenta límites de JSON profundo/enteros enormes. Modelo común e
indexación incremental siguen pendientes de M3; M4–M8 aún no están aceptadas.
Los originales y todos los recibos anteriores se conservan.

M3d también tiene [aceptación revisada](validation/rust-migration-2026-10-23/m3-program-review/README.md):
modelo common-ast/1, tipos, scopes, binding y consultas léxicas nativos. Ambos
sistemas pasan8pruebas Rust/28de tooling,348casos y1366lookups. La incidencia de
truthiness de annotations quedó corregida; MINORS/RULINGS documentan los límites
restantes. El siguiente bloque es indexación incremental; M3 completo y M4–M8
continúan pendientes. Los1066originales siguen intactos.

Actualización posterior2026-10-23: [M3 completo](validation/rust-migration-2026-10-23/m3-index-review/README.md)
está aceptado, incluida indexación incremental y las tres correcciones importantes
de su revisión. [M4a](validation/rust-migration-2026-10-23/m4-kernels-review/README.md)
también está aceptado: consultas, candidatos, BM25F/SQL, búsqueda densa y fusión.
Cada plataforma pasa44pruebas Rust afectadas/46de validación,292casos originales
y cuatro regresiones nuevas. Las dos incidencias importantes de M4a están
corregidas. M4 completo y M5–M8 siguen pendientes; los1066originales se conservan.

[M4b](validation/rust-migration-2026-10-23/m4-selection-review/README.md) está aceptado
tras una revisión y una pasada de corrección: intención/identidad de consultas,
selección SQL y vectorial, propietarios completos, vistas contextuales y ranking
de entidades/pasajes. Ambas plataformas coinciden con758observaciones originales
y conservan122pruebas originales ejecutadas una vez; pasan43pruebas Rust y38de
verificación por plataforma. Las dos entradas públicas de snapshots rechazan
ahora evidencia vacía, de otro propietario o de otra versión. Esta guarda cierra
un hueco heredado del original; las comparaciones válidas mantienen su paridad.
M4c conserva modelos numéricos/features, piezas y evidencia fresca/presentación;
M4d conserva canales y aceptación pública CLI/MCP. M4 completo y M5–M8 siguen
pendientes. Se conservaron los1066originales y se limpiaron221.5MiB/319.5MiB de
artefactos regenerables de ken-index en los targets macOS/Linux. Los commits
validados se suben periódicamente a `origin/codex/rust-migration` por petición
del usuario; el gate local no certifica una ejecución de CI remota.

## Cierre M4c2 del 24 de octubre

M4c2 está aceptado en ambos ARM tras una revisión y una pasada de reparación,
con fuentes `3e4a4e4c` y ejecución `40127406181`. Pasaron 126 raíces Rust Linux,
125 macOS y 174 de tooling por host, formato y Clippy estricto. Las 446
observaciones incluyen 433 comparaciones y 13 guardas más estrictas explícitas;
los originales, modelos y tolerancias se conservaron. El recibo anterior no
certifica búsqueda pública ni aceptación global.

Se corrigieron la escritura del probe a través de enlaces, admisión de soporte
stale en cards, identidad semántica del constructor y evidencia incompleta de
Clippy. Las cifras anteriores que sumaban resultados Rust incluían un hijo de
la prueba de salud; el recibo final verifica las raíces descubiertas.
El [traspaso](rust-migration-handoff.md#cierre-m4c2-del-2410-recibo-revisado-y-transportable)
fija los hashes del recibo y del archivo local transportable, con replay desde
fuentes archivadas. Nada de ese raw se vuelve a seguir en Git.

Siguen M4d (composición, pools, modelos reales, CLI/MCP y calidad/recursos) y
M5–M8. La próxima extensión local es el registro de gramáticas Linux x86_64;
el soporte BLAS ya probado no acreditaba todavía parsers ni indexación allí.


## Gramáticas x86_64 aceptadas el 24/10

El catálogo nativo admite Linux x86_64 con el mismo pack 1.8.1 y autenticación
por biblioteca. Los registros ARM permanecen iguales. La matriz
[40141705583](https://github.com/Infinibay/ken/actions/runs/40141705583)
pasó en Linux x86_64, Linux aarch64 y macOS arm64: 33 pruebas Rust/doc,
87 de tooling, 249 comparaciones por plataforma, formato y Clippy estricto.
El recibo se revisó, reparó y reprodujo con fuentes/tooling archivados; sus
identidades y transporte están en el [traspaso](rust-migration-handoff.md).
Esto elimina el requisito local de sintaxis para M4d. No acredita por sí mismo
indexación/modelos completos x86, búsqueda pública ni promoción del Ken instalado.


## Fusión ordinal de M4d

La política `reranker_fusion::fused_reranker_order` está migrada y revisada:
2.616 comparaciones exactas, incluyendo errores y conservación del pool. Pasó
la integración completa Linux ARM/macOS ARM y la regresión de sintaxis en tres
hosts. La revisión dejó un caso adicional de cobertura para el próximo corpus;
el código conserva el agrupamiento correcto. El detalle está en el traspaso.
La composición completa de búsqueda sigue pendiente. El siguiente objetivo
solicitado es validar el motor migrado también en Linux x86_64, incluyendo
modelos e indexación, además de gramáticas y BLAS ya habilitados.

## Runtimes CPU Linux x86_64 aceptados el 24/10

El candidato `ece7a0c67c5c7ad64e0cb72a1e2cd03fb099c458` añade selección exacta por OS y arquitectura,
ONNX 1.25.1/API25 y Torch 2.9.0 CPU para Linux x86_64. Las fuentes oficiales,
licencias, bytes y cierre de bibliotecas quedan autenticados antes de publicar
un SDK en un destino nuevo. Los registros ARM conservan sus identidades.

El CI [40149696864](https://github.com/Infinibay/ken/actions/runs/40149696864)
pasó en Linux x86_64, Linux aarch64 y macOS arm64: 6 raíces ONNX/protocolo por
host, 15 de Torch en Linux y 16 en macOS, 364 de tooling por host, formato y
Clippy estricto en ambos workspaces. La raíz adicional de macOS es la prueba
MPS existente. Linux registra exec/connect reales; esta capacidad nueva exige
en macOS un sandbox y un probe que demuestra el bloqueo de un hijo propio,
un ejecutable de ruta absoluta y una conexión. Se preservó el alcance de los
protocolos históricos. También pasaron las regresiones de gramáticas en tres
hosts (`40149696833`) y de fuentes/piezas en dos ARM (`40149696715`), con sus
fuentes y tooling contrastados contra Git y replay archivado independiente.

El recibo local está en
`docs/validation/rust-migration-2026-10-24/x86-runtime-cores`.
`FILES.json` contiene 3762 miembros y SHA-256
`150a0f88cacfe22c98d8d053411299bf5281eef30cc68a112a25aaa754c4ce12`.
Archivo local: `.ken/rust-migration/archives/x86-runtime-cores-ece7a0c6.tar.gz`, 108804290 bytes,
SHA-256 `19b7361473f7074712f4aa5f059c925d555e0095ba369af976a98363b90039bc`.
Pasó el replay desde los snapshots archivados y desde el transporte extraído.
El replay se aísla de `PYTHONPATH` para cargar el validador archivado. Los 1.066
originales congelados siguen intactos; SDKs, raw y archivos permanecen locales.

Sólo `NativeCPUCore_x86_64_accepted=true`. La aceptación completa de modelos e
índice x86, M4 y la migración global siguen pendientes. El Ken instalado sigue
siendo Python. Faltan los originales x86 y matrices completas de los restantes
modelos/perfiles, CT2, indexación con sus historiales y composición de búsqueda.
El executor antiguo de transformers rechaza x86 hasta contar con originales
ligados a arquitectura: no retirar esa guarda ni usar originales ARM como prueba.

El siguiente original contextual ya existe en `.ken/rust-migration/x86-context`:
20 historiales originales x86, 4 pruebas originales y 20 comparaciones nativas
pasaron con los límites existentes y un solo exec, sin conexiones. Es un
experimento pendiente de fixture permanente y cierre de su propia capacidad.
El original tiene 935725 bytes y SHA-256
`b1feb05a1abe09637450f55c6988f669884183df76f675e6696a7827ee0a5733`.
Transporte local: `.ken/rust-migration/archives/x86-context-preparation-9b9ff88b.tar.gz`,
4603583 bytes, SHA-256
`18417f23303f9a21aa32c20b7d2a861648afe211e004fc182616a66734f20869`.
Conservar sus labels `9b9ff88b` y reutilizarlo sin recapturar. Ese original ya se incorporó al test permanente; el estado posterior está al final
de este documento. Además pasaron
localmente 7 contratos de los encoders/juez con Torch real y 6 de `ken-rs status`.

Hubo una revisión final y una pasada TDD. El Important de aislamiento quedó
resuelto. El conteo se corrigió por plataforma tras observar las 16 pruebas
macOS: no se omitió ninguna. Menor diferido: una descarga fallida puede dejar
su temporal `.sdk-download-*`; la limpieza se hará por separado. Las decisiones,
los intentos y los límites están en `LEDGER.md` del recibo local.

## Estado contextual x86_64 y fallo ARM preexistente

El fixture contextual propio de Linux x86_64 ya está incorporado y el test dejó
de exigir aarch64. Se conserva el original de 935725 bytes y SHA-256
`b1feb05a1abe09637450f55c6988f669884183df76f675e6696a7827ee0a5733`.
No se volvió a capturar. El candidato de código es
`b9ea0578151c887c92984e3112734ffd81d94a77`.

En el [CI 40154476254](https://github.com/Infinibay/ken/actions/runs/40154476254),
Linux x86_64 y macOS pasaron sus 8 raíces contextuales Rust, 20 historiales
nativos auditados y 11 de tooling, además del padre CPU completo. Los tres
hosts pasaron el padre CPU (6 raíces ONNX/protocolo, 15/16 Torch, 364 de tooling,
formato y Clippy). También pasaron gramáticas y fuentes/piezas del candidato.
La única revisión final encontró un Important de vinculación del JUnit; quedó
reparado mediante RED→GREEN y comprobación del destino declarado, incluido el
transporte a otra carpeta. No hubo segunda revisión.

**La matriz contextual completa no está aceptada y el workflow global queda rojo.**
Linux ARM falla en `passage-boundary511`: esperado `0.21820393204689023`,
obtenido `0.181270033121109`. El diagnóstico ejecutó en el mismo runner tanto
la versión actual como el baseline intacto `26ec740d...`: ambos fallaron igual.
Los logs confirman que el baseline se compiló desde su worktree. El selector
x86 y la corrección del JUnit no introdujeron esa diferencia. Su causa exacta
sigue sin determinarse; no atribuirla todavía al hardware ni al backend.
No se cambiaron los originales, tolerancias ni criterios para convertirlo en verde.

El [estado local preservado](validation/rust-migration-2026-10-24/x86-context-status/README.md)
registra x86=true, macOS=true y ARM=false; no es un recibo de aceptación.
`FILES.json`: 3818 miembros, SHA-256
`72eb98dacf9590a18965b9cfd5dcfa734a218b05deea72912792a74f56eb56dc`.
Archivo local `.ken/rust-migration/archives/x86-context-status-b9ea0578.tar.gz`,
121742888 bytes, SHA-256
`f1ed4cd7ff7f5e195e237a8084512266700ce8acac8fe260579bb5e2ba1e9bba`.
Los verificadores archivados reproducen los estados observados. Los raw, SDK,
pesos y diagnósticos siguen fuera de Git. El recibo CPU aceptado de ece7a0c6
permanece intacto.

Quedan dos menores de este bloque: el audit contextual tiene un límite de 60 s
frente a los 600 s históricos, y el hash Rust del fixture se comprueba en una
raíz de test separada del consumo. El conjunto completo sí exige esa raíz y el
coordinador Python comprueba el hash antes de comparar. El resto de modelos,
CT2, indexación x86 y M4/global siguen pendientes. La siguiente investigación
es explicar la diferencia ARM conservando la evidencia del baseline; no recapturar
sus vectores para hacer coincidir la implementación.

## Actualización del 25 de octubre

El diagnóstico ARM confirmó igualdad exacta Python ONNX/Rust en tres casos y
doce combinaciones de carga/hilos; ambos reproducen la diferencia frente al
original histórico. La causa concreta del kernel/CPU sigue pendiente y no cambian
los originales ni las tolerancias. La matriz contextual completa sigue sin aceptar.

En `3da84508`, el test de Ettin usa su original propio Linux x86_64, autenticado
en el consumidor, sin tomar el de ARM. Pasaron 16 raíces nativas, 23 historiales
en una ejecución nativa auditada, 24 pruebas originales y formato/Clippy estricto.
La revisión final no encontró problemas. La referencia nueva de 667940 bytes y
SHA256 `ec1a7477107da440828fd0f46ab2c6d9be45a5d64c7c516306797aa2636e20ce`
ya está consumida: reutilizarla, nunca recapturarla.

El [handoff](rust-migration-handoff.md#continuación-del-25-de-octubre-diagnóstico-arm-y-ettin-x86_64)
registra evidencia, hashes, replay y alcance exacto. La evidencia permanece local
y fuera de Git. Esto verifica el test/experimento Ettin x86; no acepta todavía
la matriz completa de modelos, CT2, indexación x86, M4 ni la migración global.

## Foco actual: Linux x86_64

Por instrucción del usuario, el trabajo activo continúa sólo en x86_64. El
candidato `45ab4dc4` integra el ejecutor Ettin al flujo CPU → contexto → reranker
y pasó ambos CI de modelos/gramáticas en Linux x86_64. CPU pasó 6/15 raíces
ONNX/Torch y 364 de tooling; contexto 8/20/11 y Ettin 16/23/38
(raíces Rust/historiales/tooling), con formato/Clippy estricto.

La preparación nativa de Ettin autoriza sólo sus cuatro archivos de caché y
conserva las 15 entradas verificadas. El protocolo de auditoría anterior sigue
inmutable; la generación exige un contrato explícito con hashes y rechaza
salidas faltantes, extra, alteradas o cambios en las entradas. Se reutilizan los
originales existentes sin capturarlos de nuevo.

El [handoff](rust-migration-handoff.md#foco-x86_64-ejecutor-de-modelos-cerrado-el-25-de-octubre)
registra el recibo, revisión, hashes y replay aislado del transporte. Contexto y
Ettin x86 quedan aceptados en este alcance; ARM/macOS, los modelos restantes,
M2/M3 completos en x86_64, M4 y la migración global mantienen sus pendientes. La revisión
dejó un detalle menor de clase de error para el path inválido `"."`, que se
rechaza antes de ejecutar. Todo el raw permanece local y fuera de Git.


## Vistas de símbolos: siguiente componente nativo x86_64

`206f4861` completa las vistas neuronales de símbolos y su adaptador Ettin:
admite código completo con límites Python de 64 líneas/12000 codepoints,
deduplica la inferencia adicional, conserva fallback y orden estable mediante
la media original. La inferencia vacía sigue sin cargar recursos.

Pasaron los 134 roots nativos de core/retrieval, 61 observaciones de política,
5 frames reales y 27 tests de tooling, junto con CPU/contexto/Ettin, gramáticas,
formato y Clippy. CI x86: [modelos/búsqueda](https://github.com/Infinibay/ken/actions/runs/40225028046)
y [gramáticas](https://github.com/Infinibay/ken/actions/runs/40225028097).
La revisión independiente encontró un test dependiente de un archivo local;
quedó reparado con RED→GREEN y validación en checkout limpio. Queda un Minor
de cobertura directa del guard de scores adicionales no finitos.

El [handoff](rust-migration-handoff.md#vistas-neuronales-de-símbolos-en-rust-linux-x86_64)
contiene alcance, originales nuevos inmutables, hashes del recibo/transporte y
replay aislado con tooling archivado. Todo el raw continúa local y sin tracking.
Quedan las preferencias de operaciones/test/operadores, SymbolRanker y
PieceSearch completos, modelos restantes y M4/global. El foco activo sigue
siendo sólo Linux x86_64; el workflow histórico ARM de piezas pasa a manual.


## Requisitos y preferencias de símbolos en Rust

`2c0bf3ac` completa las preferencias explícitas de operaciones, tests y operadores
para Linux x86_64. Conserva las tres prioridades estables y la pertenencia de
candidatos; la identidad de test usa el catálogo inmutable. Componen con las
vistas neuronales sin modificar los scores. La observación de operaciones es
el siguiente componente pendiente, antes de cerrar SymbolRanker/PieceSearch.

Pasaron 141 pruebas nativas, 404 casos de política, 21 identidades y 24 tests de
tooling, con CPU/contexto/Ettin/vistas/gramáticas y formato/Clippy. CI:
[modelos/búsqueda](https://github.com/Infinibay/ken/actions/runs/40232431774) y
[gramáticas](https://github.com/Infinibay/ken/actions/runs/40232431765).
El recibo conserva también un fallo contextual anterior no reproducido en el
diagnóstico AMD; su causa sigue pendiente y no se cambiaron tolerancias. La revisión
encontró y corrigió mediante RED→GREEN un falso requisito de
invocación por diferencias entre espacios Python y Oniguruma. Queda como Minor
una mejora de consulta indexada al clasificar tests. El
[handoff](rust-migration-handoff.md#preferencias-explícitas-de-símbolos-linux-x86_64)
registra originales inmutables, decisiones, límites, recibo y replay archivado.
Los observadores, la búsqueda completa, M4/global y otras plataformas siguen pendientes.

## Observadores de operaciones Python y selector nativo x86_64

`d3a47eb3` implementa `PythonOperationWitnesses` y el selector completo
`OperationWitnesses`, sobre catálogos inmutables. Coinciden 218 casos originales
Python/230 entidades y los 120 casos CST anteriores. Una revisión independiente
identificó seis diferencias semánticas, reparadas en una pasada RED→GREEN;
las 182 pruebas nativas afectadas, formato y Clippy estricto pasaron.

La cadena local y las dos réplicas del
[CI final](https://github.com/Infinibay/ken/actions/runs/40611631533) pasaron
532 pruebas de herramientas y 198 nativas por host. El recibo sellado pasó
replay desde una extracción aislada, con fuentes y validadores archivados. El
[handoff](rust-migration-handoff.md#backend-python-ast-y-router-de-operaciones)
registra procedencia, parches reversibles del parser y alcance. Siguen pendientes
SymbolRanker/PieceSearch completos, otros modelos y M4/global; el foco permanece
en Linux x86_64 y los recibos quedan locales, fuera de Git.

## SymbolRanker completo en Rust para x86_64

`d78d8313` compone vistas neuronales, observaciones de operaciones y preferencias
estables, con una caché de descripciones compartida y vinculada al catálogo.
Coinciden 36 casos originales nuevos, incluidos tres con Ettin real, tanto en
frío como en caliente. La revisión encontró y corrigió un acceso a una caché de
otro catálogo; pasaron la regresión, las 153 pruebas nativas de core/búsqueda,
formato y Clippy estricto.

La cadena local y las dos réplicas del
[CI final](https://github.com/Infinibay/ken/actions/runs/40620639879) pasaron
557 pruebas de herramientas y 202 nativas por host. El recibo sellado pasó el
replay desde una extracción aislada, usando sus fuentes y validadores archivados. El
[handoff](rust-migration-handoff.md#symbolranker-completo-y-descripciones-compartidas-en-rust)
registra la procedencia de originales, decisiones y límites. Siguen pendientes
PieceSearch completo, otros modelos y M4/global. Los artefactos quedan locales
y fuera de Git; el foco sigue siendo Linux x86_64.


## PieceSearch completo sobre Linux x86_64

`PieceSearch` compone tarjetas, ensamblado, ranking de piezas y símbolos, fusión
ordinal y presentación. Conserva el top 10 antes de los límites de visualización,
el ranking numérico en modo exacto y la promoción final de rutas explícitas.
Las señales de explicación se agregan por identidad después del recorte, como
en el original; por eso `explain` puede superar `max_chars` al incluir diagnósticos.

Se comparan 45 casos nuevos del API Python congelado, incluidos 42 con modelos controlados
y tres con Ettin real, fríos y calientes. No se repitieron originales
aceptados ni se cambiaron modelos o tolerancias. El primer probe aislado omitía
los tres sidecars BLAS del ranking numérico; una regresión reprodujo el fallo y
pasó tras incorporar su preparación, autenticación y comprobación de carga real.

La versión `4d88c8379b61c3570ff1cea5bcc31ac924d84619` pasó la cadena completa
local y las dos réplicas del [CI final](https://github.com/Infinibay/ken/actions/runs/40628141649):
586 pruebas de herramientas y 206 nativas por host, formato y Clippy estricto.
El transporte sellado pasó el replay fuera del checkout con sus fuentes y
validadores archivados. El [traspaso](rust-migration-handoff.md#piecesearch-completo-en-rust-sobre-linux-x86_64)
registra las identidades, la revisión, la reparación y los límites de aceptación.

El próximo bloque es `BestSearch`: recursos, preparación y caché por generación,
búsqueda exacta y recuperación contextual. Continúan pendientes otros modelos,
M4/global y M5–M8. Los crudos y recibos quedan locales, fuera de Git; la aplicación
instalada sigue en Python.
