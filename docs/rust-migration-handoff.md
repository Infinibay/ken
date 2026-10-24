# Continuar y terminar la migración a Rust

Actualización del 24/10: los directorios de evidencia se retiraron del seguimiento
de Git por pedido del usuario; sus archivos locales se conservaron. Para un clon
nuevo, [recuperar los artefactos necesarios](validation-artifacts.md) antes de
ejecutar la reconstrucción siguiente. La cápsula ya no viaja en el árbol actual.
El usuario autorizó continuar la migración y agregar Linux x86_64; los recibos
ARM históricos conservan su alcance y no certifican esta nueva arquitectura.

Traspaso del 23 de octubre de 2026. Rama: `codex/rust-migration`.
Punto histórico del traspaso: `5d9dc6f927098f47942d5c0dd5ee72ca22853c4a`.
Cierre M4c2 del 24/10: `3e4a4e4ccd6762f437af43f618e8631984e67b39`;
ver el recibo y la identidad de archivo al final de este documento.
**La migración completa todavía no está terminada.** La aplicación instalada sigue
siendo Python; `ken-rs` no sustituye todavía todos sus comandos.

La parada solicitada el 23/10 quedó superada por la orden de continuar del 24/10.
El usuario autorizó los push a esta rama y el soporte Linux x86_64. Continuar
por M4d, sin reiniciar M0/M1 ni repetir originales aceptados. Conservar fuentes,
recibos y archivos locales; comprobar cada bloque y subir commits periódicos.
Esta autorización no incluye merge, release, tags ni reemplazar el Ken instalado.

## 1. Autoridad y lectura inicial

1. Este documento fija el punto exacto de reanudación y los problemas conocidos.
2. [Contrato global aprobado](superpowers/specs/2026-10-18-rust-migration-design.md):
   capacidades, persistencia, calidad, retirada de originales y condiciones M0–M8.
   Sus párrafos históricos de estado no sustituyen los recibos posteriores.
3. [Especificación M4c2](superpowers/specs/2026-10-23-rust-source-pieces-design.md)
   y [plan ejecutable M4c2](superpowers/plans/2026-10-23-rust-source-pieces.md).
4. [Ledger preservado](validation/rust-migration-2026-10-23/handoff/LEDGER.md)
   y `progress.md` dentro de la cápsula: tareas realmente ejecutadas, RED/GREEN,
   decisiones, intentos inválidos y límites. Las casillas del plan no son recibos.
5. [Guía de construcción y perfiles](rust-migration.md), `AGENTS.md` y
   `CONSTRAINTS.md`. Diseñar desde el uso público, conceptos y responsabilidades.

Los enlaces de este documento son relativos al repositorio para funcionar al
cambiar de máquina. No dependen del historial del chat ni de memoria local de Ken.

## 2. Qué está terminado y qué falta

| Bloque | Estado real | Evidencia / próximo resultado requerido |
| --- | --- | --- |
| M0/M1 | Aceptados | Referencia, contratos, proyecto, paths y `status`; matriz Linux/macOS en `docs/validation/rust-migration-2026-10-18/m1/` |
| M2 | Aceptado | Datos, modelos, backends opcionales e integración; recibo `m2-integration-review` del 23/10 |
| M3 | Aceptado | Fuentes, 19 parsers / 20 gramáticas / 44 extensiones, imports, modelo común e indexación incremental; recibo `m3-index-review` |
| M4a | Aceptado | BM25F/SQL, búsqueda densa y fusión; `m4-kernels-review` |
| M4b | Aceptado | Intención, selección, propietarios, vistas contextuales y ranking de entidades/pasajes; `m4-selection-review` |
| M4c1 | Aceptado | Bosques, stemming, alineamiento, features y ranking numérico de propietarios; `m4-numeric-owner` |
| M4c2 | Aceptado tras una revisión y una pasada de corrección | Catálogo, piezas, ranking, cards, evidencia y presentación; 446 observaciones por ARM, 126/125 raíces Rust y 174 de tooling; recibo `m4-source-pieces` |
| Gramáticas Linux x86_64 | Aceptadas; requisito local de M4d | 33 raíces Rust/doc, 87 de tooling y 249 comparaciones en tres hosts; no equivale a aceptación completa de indexación/modelos x86 |
| M4d | En curso: fusión ordinal migrada; composición completa pendiente | Requisitos y observaciones de fuente/símbolos, composición de piezas, canales restantes, pools preparados, modelos y aceptación CLI/MCP |
| M5a/M5b/M5c | Pendientes | Productor/almacén estructural CFG/IR, KQL1/2 y sesiones, flujo y completitud |
| M6 | Pendiente | Conocimiento, memoria justificada, anchors, vigencia, entrega, razonamiento, checks, inspection y responsabilidad |
| M7 | Pendiente | Daemon, colas, watcher, lifecycle, concurrencia, CLI restante, MCP completo, hooks e integración con hosts |
| M8 | Pendiente | Distribución, matriz global, upgrade/rollback y promoción nativa sin Python |

No hay un porcentaje funcional global acreditado. M3 incluye el modelo común,
pero **no** acredita el productor completo de IR ni la ejecución KQL de M5.
Ningún bloque numérico o probe interno acredita por sí solo la búsqueda pública.

Los recibos siguientes están bajo `docs/validation/rust-migration-2026-10-23/`:

| Recibo | SHA-256 de `FILES.json` |
| --- | --- |
| `m2-integration-review` | `293f1de6f3865a8f5c6c4ab489e804b77adaa18863599ef0d044741594ee76bb` |
| `m3-source-review` | `3a9448aa7489e9c9a99bbf80b6e70e0ed61f1beaf063208f4944443b0340caa9` |
| `m3-parsers-review` | `c1541177be2a0716ff52276d7cfe042ae4ff5acea75d3f4c90d4a3452ab48ff8` |
| `m3-imports-review` | `3779ac933aacc766c9372b8e623c4314bd5b65a31bb65735177ba2fa7aa6db6f` |
| `m3-program-review` | `20737c5dced1e23df625b2a1c1220536c0f9b9bdb38354b51094daf6bdc0f461` |
| `m3-index-review` | `5216c937b4537dd940f3d43c71181e7ce44c4b2987b53d6e6d2699877f7414a9` |
| `m4-kernels-review` | `b7143128a6959650bb4bc28d0b94c21e3a12d061627ecdfc40d81745762f644e` |
| `m4-selection-review` | `502522eb0af6e3136be30114c5509314593785e94604ff1c70303f721a33a10b` |
| `m4-numeric-owner` | `9058d60199da6ef080991203bf0b6351361a5c27c2d5e6358bf31c3f3e4d1a6e` |

Usar sus snapshots `native-sources`/validation para reproducir recibos históricos:
no atribuir resultados viejos a fuentes nuevas. Revisar sus `MINORS`, `RULINGS`,
`FIXES` y `REVIEW`; los menores diferidos siguen siendo límites, no correcciones
implícitas. M4c1 pasó por host 80 raíces Rust, 92 de tooling, 35 raíces originales,
861 observaciones nuevas y 758 observaciones de selección reejecutadas en Rust.
Sus tres Important fueron reparados; M4/global siguen falsos en ese recibo.

## 3. Trasladar el trabajo sin depender de esta máquina

```sh
git clone --branch codex/rust-migration https://github.com/Infinibay/ken.git
cd ken
git status --short --branch
```

Usar un clon completo; los objetos del commit inicial
`96a9d2d5ed5b7a6dc51b13c8e97e290cae7c9908` reconstruyen la parte inalterada
de la referencia. En un clon superficial, obtener antes ese historial.

### Cápsula local recuperable del historial

En `docs/validation/rust-migration-2026-10-23/handoff/`:

- `PORTABLE.json`: inventario de los 1.066 originales, objetos Git reutilizables,
  hashes, 102 archivos de progreso y tamaños/hashes de los dos archivos comprimidos.
- `original-overrides.tar.gz`: 75 contenidos originales que no se reconstruyen
  desde aquel commit inicial. Son un **fixture aislado del oráculo**, necesario
  porque el punto de partida incluía cambios previos y archivos sin commit.
  No se añadieron esos cambios al código Python de la rama ni se incluyeron otros
  directorios privados, bases, credenciales, entornos o cachés del usuario.
- `m4c2-progress.tar.gz`: capturas originales, JUnit, stdout/stderr, salidas RED/
  GREEN, gates, generadores y ledger; incluye intentos fallidos para auditoría.
- `oracle-environment.json`: versiones observadas del entorno de desarrollo.
  No es una instrucción de instalar todos los backends ni una dependencia runtime.

Hashes de los comprimidos:

```text
original-overrides.tar.gz  61d0c66498e731b66f0600f97f9a54a2c404a694867a4be1eed6597182ca6788
m4c2-progress.tar.gz       9148bec5dffb12d4809c31e3b457aa385ecbb57dc0cee5aea44112b08b66a328
```

### Reconstruir oráculo y progreso

Ejecutar desde la raíz del clon, con Python 3.12.9 disponible. El siguiente código
usa sólo la biblioteca estándar y Git. No modifica los originales del worktree.
Se niega a sobrescribir un destino ya existente. Los paths absolutos de capturas
históricas se conservan como evidencia; no hay que editarlos ni volver a sellarlos.

```sh
python3.12 - <<'PY'
from pathlib import Path
import hashlib, io, json, subprocess, sys, tarfile

root = Path.cwd()
capsule = root / 'docs/validation/rust-migration-2026-10-23/handoff'
manifest = json.loads((capsule / 'PORTABLE.json').read_bytes())
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
assert sha((root / manifest['baseline']['path']).read_bytes()) == manifest['baseline']['sha256']
archives = {}
for name, expected in manifest['archives'].items():
    raw = (capsule / name).read_bytes()
    assert len(raw) == expected['bytes'] and sha(raw) == expected['sha256'], name
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        entries = archive.getmembers()
        assert all(e.isfile() and not Path(e.name).is_absolute() and '..' not in Path(e.name).parts for e in entries)
        assert len({e.name for e in entries}) == len(entries)
        archives[name] = {e.name: archive.extractfile(e).read() for e in entries}
overrides = archives['original-overrides.tar.gz']
assert set(overrides) == set(manifest['override_files'])
reference = root / '.ken/rust-migration/portable-reference'
progress = root / manifest['sdd_root']
assert not reference.exists() and not progress.exists(), 'Use new destinations; preserve existing evidence'
records = []
for row in manifest['reference_files']:
    name = row['path']
    raw = (subprocess.check_output(['git', 'cat-file', 'blob', row['git_blob']], cwd=root)
           if row['git_blob'] else overrides[name])
    assert len(raw) == row['bytes'] and sha(raw) == row['sha256'], name
    target = reference / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    records.append({'path': name, 'sha256': row['sha256']})
fingerprint = sha(json.dumps(records, sort_keys=True).encode())
assert fingerprint == manifest['portable_reference_fingerprint']
reference_manifest = dict(format='ken-rust-oracle/1', scope=['src/ken/**'],
                          fingerprint=fingerprint, python=str(Path(sys.executable).absolute()), files=records)
(reference / 'reference-manifest.json').write_text(json.dumps(reference_manifest, indent=2) + '\n')
saved = archives['m4c2-progress.tar.gz']
assert set(saved) == {r['path'] for r in manifest['sdd_files']}
for row in manifest['sdd_files']:
    raw = saved[row['path']]
    assert len(raw) == row['bytes'] and sha(raw) == row['sha256'], row['path']
    target = progress / row['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
print('Restored', len(records), 'originals and', len(saved), 'progress files')
print('Reference:', reference)
PY
```

La referencia portátil contiene exactamente los originales del baseline; omite
antiguos archivos Rust e informes adicionales del freeze local de 616 MiB. Por eso
su fingerprint `5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038`
es distinto del freeze histórico `4077b9be320c25375e7716221298ee85d984bcff5064cca68a2ae3af0e8cda3d`.
Cada uno de los 1.066 contenidos y todos los owners usados por el observador
mantienen su hash. No modificar fingerprints de recibos históricos para ocultar
esta distinción. Las capturas nuevas deben declarar la referencia portátil.

### Recuperar el baseline en un clon nuevo para los gates futuros

Los gates actuales comprueban los 1.066 originales también en el worktree del
candidato. El clon Git, por sí solo, carece de los cambios previos del baseline.
**Sólo en un clon recién creado y limpio**, ejecutar esta restauración explícita:

```sh
python3.12 - <<'PY'
from pathlib import Path
import hashlib, json, subprocess
root = Path.cwd()
assert not subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal']), 'Requires a fresh clean clone'
reference = root / '.ken/rust-migration/portable-reference'
manifest = json.loads((reference / 'reference-manifest.json').read_bytes())
for row in manifest['files']:
    raw = (reference / row['path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == row['sha256']
    target = root / row['path']
    if not target.exists() or target.read_bytes() != raw:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
print('Original baseline restored; keep these prior changes out of migration commits')
PY
```

Ese paso deja cambios previos y archivos originales sin commit, deliberadamente.
No usar `git add .`, reset, stash global ni clean sobre ellos. En esta máquina
esos originales ya estaban presentes y **no** se ejecutó dicha restauración.
Otros cambios del usuario ajenos al baseline no forman parte de esta cápsula:
si se necesitan fuera de la migración, trasladarlos por separado.

## 4. Preparar la máquina de desarrollo

Plataformas acreditadas: **macOS arm64 y Linux aarch64**. Otra arquitectura necesita
su propia preparación y evidencia; no hereda la aceptación numérica/ABI.

```sh
rustup toolchain install 1.95.0 --profile minimal --component rustfmt --component clippy
uv python install 3.12.9 --no-bin
uv sync --locked --dev --python 3.12.9 --managed-python
export CARGO_INCREMENTAL=0
export CARGO_BUILD_JOBS=2
export CMAKE_PARALLEL=2
export CARGO_PROFILE_DEV_DEBUG=0
export CARGO_PROFILE_TEST_DEBUG=0
export RUST_TEST_THREADS=1
export KEN_RUST_REFERENCE="$PWD/.ken/rust-migration/portable-reference"
```

Actualizar sólo el campo `python` de la referencia portátil a la ruta absoluta de
`.venv/bin/python`; ese campo es un ejecutable de desarrollo, no un contenido
original:

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
import json, sys
assert sys.version_info[:3] == (3, 12, 9), sys.version
path = Path('.ken/rust-migration/portable-reference/reference-manifest.json')
value = json.loads(path.read_bytes())
value['python'] = str(Path(sys.executable).absolute())
path.write_text(json.dumps(value, indent=2) + '\n')
PY
```

Comprobar Python 3.12.9, Unicode 15.0.0, SQLite 3.47.1, NumPy 2.4.4,
tree-sitter 0.25.2, tree-sitter-language-pack 1.8.1 y snowballstemmer 3.0.1.
Si el entorno resuelto difiere, usar las versiones registradas y conservar la
diferencia; no regenerar los oráculos para acomodar una actualización.

La preparación reproducible extensa está escrita en
`.github/actions/prepare-native-validation/action.yml`,
`tools/rust_migration/{preparation,transformer_prepare,grammar_prepare}.py`
y la [guía de perfiles](rust-migration.md). Adaptar `GITHUB_ENV` a exports locales
al ejecutar los bloques de la acción fuera de CI. Preparar herramientas/recursos
no obliga a repetir la inferencia de todos los modelos aceptados.

- C/C++/CMake 3.31.10; en Linux build-essential, pkg-config, zstd y strace.
  La compilación de dependencias de `ken-models` puede necesitar CT2/OpenBLAS
  aunque sólo se ejecute `ken-retrieval`. Seguir la preparación registrada;
  `--offline` funciona **después** de `cargo fetch --locked` y de preparar assets.
- Gramáticas: `crates/ken-syntax/grammars.lock.json` fija archivos, licencias,
  bundles por plataforma y hashes. `prepare_grammars(lock, cache, destination)`
  prepara el SDK. Para los observadores existentes el destino es
  `.ken/rust-migration/m3-parsers/sdk-macos` o `sdk-linux` con `manifest.json`.
  El original de ensamblado necesita configurar explícitamente el CPP de ese
  SDK: el HOME aislado no dispone del caché global del language-pack.
- macOS usa Accelerate para los kernels de alineamiento; Linux usa los sidecars
  exactos del registro de BLAS de recuperación, con `KEN_DENSE_BLAS_DIR` absoluto.
  Ver `crates/ken-retrieval/src/dense_math.rs` y
  `tools/rust_migration/retrieval_validate.py::prepare_runtime`.
  Ese OpenBLAS ILP64 de NumPy **no** es el OpenBLAS LP64 de CT2.
- Los pesos/catálogos/cores de M2 se adquieren con revisiones y hashes registrados.
  Configurar los `KEN_*` de la guía antes de la suite workspace completa. No
  descargar todos los modelos para empezar la Task 3: usa el NPZ y los bosques
  ya versionados; ejecutar sólo las suites afectadas hasta necesitar más perfiles.
- No hay que trasladar `target`, `.venv`, todo `.ken`, Cargo cache ni Docker.
  Son reconstruibles; los binarios/librerías son específicos del host. Mantener
  los recibos y originales; limpiar sólo scratch propio ya archivado y targets
  regenerables cuando no haya compilaciones activas.

Las rutas locales antiguas sirven para localizar recursos si esta máquina sigue
disponible, pero **no son requisito de reanudación**:

```text
macOS wrapper: .ken/rust-migration/m2-optional/review-repair/prepared-macos-env
macOS target:  .ken/rust-migration/m2-fastembed/target-final-ci
macOS Cargo:   .ken/rust-migration/m2-translation/cargo-home
Docker:        codex-ken-rust-m2, Linux aarch64, 2 CPU / 6 GiB
Docker source: /app/.ken/rust-migration/m2-optional/source-transformers-review-work
Docker wrapper:/app/.ken/rust-migration/m2-optional/review-repair/prepared-linux-env
Docker Python: /app/.venv/bin/python
```

Los wrappers antiguos contienen paths absolutos de `/Users/andres` o `/app`:
recrearlos con las rutas nuevas, no ejecutarlos ciegamente. No editar Rust mientras
algún host ejecuta cargo/clippy. Para sincronizar fuentes, copiar sólo contenidos
cambiados; usar `tarfile` de Python, evitando archivos AppleDouble de tar macOS.

## 5. Punto exacto de reanudación: gates ARM de Task 3, luego Task 4

### Actualización del 24 de octubre

Se implementaron `piece_features.rs`, `piece_ranking.rs` y `tests/piece_ranking.rs`.
En x86_64 se capturaron una vez los 84 inputs originales y sus nueve raíces de
ranking, y 14 inputs adicionales disjuntos reutilizaron esas raíces: límites de
términos, deduplicación, ocho declaraciones, cutoff de cancelación y declaración
ausente con expansión de espacios. El último conserva el error original
`'declaration_identity_stem'` como error retornado; nunca debe abortar con panic.
También hay una regresión de sufijos: `.json` no es un archivo con extensión
`.json`, mientras que `.config.json` sí la tiene.

`PieceMatch.proposal_index: usize` está implementado: conserva la identidad de
propuestas duplicadas aunque el resultado posea una copia de la pieza.
Se comparan las 262 columnas, llamadas, scores y caminos/hojas de los 1.280
árboles reales. Sólo las features de composición estática usan el bound F32 ya
aprobado; scores, caminos, llamadas e identidades siguen siendo exactos.

Los nuevos originales y logs están en el workspace local del plan, con prefijos
`original-linux-ranking*` y `original-x86-alignment*`. Los fixtures de Linux
nuevos de ranking declaran `machine=x86_64`: **no constituyen una captura ARM**.
Se conserva aparte `numeric-reference-alignment-linux-x86_64.json.gz`; los 22 casos
de alineamiento adicional coinciden con ARM y no duplican el fixture versionado.
El [registro y preparación de x86_64](rust-migration.md) preserva los registros ARM.

Próximo gate: ejecutar Task 3 con sus originales y suites nativas en macOS arm64
y Linux aarch64. Mantener las nuevas capturas ARM separadas de las x86_64 y no
sobrescribir recibos aceptados. Después seguir Task 4 (cards) del plan. No repetir
las tareas 1–2 ni capturas aceptadas. M4c2/M4/global aún no están aceptados.

La sección histórica siguiente describe el checkpoint portátil del 23/10;
sus pasos 2–5 ya se realizaron en x86_64, no en ARM.

### Lo conservado

- Task 1: `source_snapshot.rs`, `source_catalog.rs`, prueba `source_catalog.rs`;
  38 observaciones / 4 raíces originales por host; suites core/retrieval completas
  con 115 raíces Rust. Tres observaciones son guardas de admisión más estrictas
  que el original, conservadas como tales.
- Task 2: `piece_candidates.rs`, prueba `piece_candidates.rs`; 45 observaciones /
  3 raíces originales por host; 68 raíces Rust afectadas y 2 de tooling.
  Catálogo inmutable, caché privado de descripciones por generación, validación
  de identidad/hash/evidencia antes de codificar. Tres guardas explícitas más.
- Task 3 preparatoria: `tools/rust_migration/piece_ranking_reference.py`, ampliación
  de `piece_reference.py`, `piece-inputs-ranking.json` y
  `piece-reference-ranking.json` en `crates/ken-retrieval/tests/fixtures/`.
  En aquel checkpoint: **84 observaciones macOS y 9 raíces originales aprobadas;
  sin Rust nuevo**. La actualización anterior registra la implementación posterior.
- Generador correcto: `make-ranking-inputs.py` en el progreso restaurado.
  Captura válida: `original-macos-ranking/`. Captura previa con entradas aliased:
  `original-macos-ranking-aliased-inputs/`, retenida sólo para auditar el error
  del generador y reutilizar sus nueve raíces originales.

La primera captura compartía prototipos mutables y unas puntuaciones de overflow
contaminaron otros casos. Se corrigió con deep-copy; **no fue un fallo de Ken**.
La captura válida reutiliza las nueve pruebas originales previas sin repetirlas.
Su `reused_suite.sha256` apunta a
`1cd20ae9b42a085f25ef72edb0075e4e618b36e62d997cb566f51a8b788581fc`.
El path histórico es absoluto: resolverlo por el sufijo relativo al directorio de
progreso al verificar en otra máquina. El JUnit está en la cápsula previa; no
inventar uno para la captura nueva ni contar los 84 casos inválidos como aceptados.
El verificador completo de esta cadena todavía corresponde a Task 7.

### Pasos del checkpoint del 23/10 (referencia histórica)

1. Verificar hashes y restaurar el progreso. Leer el ledger y confirmar que no
   existen cambios nuevos de otro agente. Las tareas 1–2 no se reinician.
2. Capturar **Linux** para los mismos 84 inputs y sus nueve raíces una vez, usando
   el oráculo aislado. Guardar `original-linux-ranking/` y fixture
   `piece-reference-ranking-linux.json`. La función actual es:

   ```python
   from pathlib import Path
   from tools.rust_migration.reference import Reference
   from tools.rust_migration.piece_reference import capture
   root = Path.cwd()
   capture(Reference.load(root / '.ken/rust-migration/portable-reference'),
           root / '.superpowers/sdd/2026-10-23-rust-source-pieces/original-linux-ranking',
           repo=root, family='ranking')
   ```

3. Completar sólo observaciones adicionales disjuntas que falten al contrato:
   límites 4095/4096/4097 términos, deduplicación de campos completos, ocho kinds
   de declaración y cancelación pequeña con cutoff 0. `ranking-edges` es una
   propuesta **todavía no implementada**. Extender el observador/reuso de suite
   sin recapturar los 84 casos ni reejecutar nueve raíces aprobadas.
4. Escribir el uso público y `tests/piece_ranking.rs`; observar missing-API RED.
   Comparar las 262 columnas, secuencias de llamadas, orden, scores y digest de
   caminos/hojas de los 1.280 árboles reales. Nunca introducir respuestas
   esperadas en el probe nativo.
5. Implementar `piece_features` y `PieceReranker` según el plan, usando cobertura,
   stemming, encoder y `NumericRanker` aceptados. Proponer `proposal_index: usize`
   en `PieceMatch` para conservar identidad de propuestas duplicadas tras clonar;
   es una decisión pendiente que debe registrarse, no una API implementada.
6. Pasar las suites completas afectadas, tooling, fmt y clippy en ambos hosts;
   verificar originales y hacer commit/push del resultado. Después Task 4.

Comandos base, con los recursos nativos preparados y las variables del host:

```sh
cargo test --locked --offline -p ken-retrieval --test piece_ranking
cargo test --locked --offline -p ken-retrieval --all-targets
.venv/bin/python -m pytest -o addopts= -q tests/rust_migration/test_piece_reference.py
cargo fmt --all --check
cargo clippy --locked --offline -p ken-retrieval --all-targets -- -D warnings
.venv/bin/python -m tools.rust_migration.reference verify --repo . --manifest docs/validation/rust-migration-2026-10-18/baseline.json
```

En el checkpoint del 23/10 el primer comando fallaba por target ausente.
Actualmente la prueba existe e incluye ranking; ver la actualización del 24/10.
Si la sandbox deniega bind loopback en tests health de core, repetir la misma
suite con permiso local de sockets, conservar el fallo y no filtrar tests.

### Semántica que debe preservar Task 3

- Esquema: 262 nombres = 18 escalares + 4 kinds de petición + 8 de declaración +
  8 campos × 9 estadísticas originales + 8 × 10 expandidas completas + 8 × 10
  expandidas de declaración. Campos en orden explícito:
  `identity, signature, documentation, executable, calls, returns, path, all`.
- Documento: deduplicar textos completos por campo conservando orden de miembros;
  anteponer identidad y newline a identity. `all` une en el orden original;
  `code_terms` limita a 4096. No reemplazar por un conjunto ordenado arbitrario.
- Tres pases: consulta original sin stems, expandida completa con stems y
  expandida de declaración con stems. Cadena vacía cae a fallback; espacios son
  truthy. `best_score` viene de la primera propuesta, no del máximo global.
- `member_score_mean3` usa **sum de Python 3.12 con compensación Neumaier**:
  `sum([1e16, 1., -1e16]) == 1.`; dividir entre 3 da `1/3`.
  No usar fold secuencial ni `math.fsum`, ni cambiar el reductor NumPy pairwise
  de `reductions.rs` o la suma secuencial de los bosques. Referencia del algoritmo:
  `https://raw.githubusercontent.com/python/cpython/v3.12.9/Python/bltinmodule.c`
  (acumulador/corrección y guardas de cero/no finitos). Ya hay casos de cancelación,
  negativos, priors sin ordenar y overflow; falta cutoff 0 del caso pequeño.
- Petición incompatible falla antes de embeddings. Vacío produce 0×262 sin calls.
  Símbolos omiten features/forest opcionales y conservan propuesta/score inicial.
  Otras piezas priorizan path nombrado, soporte exacto, bosque y estabilidad.
- Reutilizar `tests/feature_support/mod.rs` para encoder/stems/log de llamadas y
  el adaptador de tabla real de `tests/rank_models.rs` para composición estática.
  Pasar JSON por `json_transport::python_strings` antes de `PythonText`, también
  en Linux: conserva surrogates aislados y une pares válidos escapados.
- Comparador exacto por defecto, incluido signed zero. Sólo rutas de features
  previamente declaradas toleran F64 a 1e-12 o composición F32 a 1e-6; caminos,
  hojas, scores, llamadas, orden y evidencia son exactos. Transportar NaN/Inf
  con categoría IEEE explícita; no convertir silenciosamente en null.

## 6. M4c2 cerrado; continuar M4d

Todas las tareas M4c2 cerraron con el recibo del 24/10. Esta tabla conserva
sus responsabilidades y contratos; el siguiente bloque pendiente es M4d:

| Tarea cerrada | Responsabilidad | Criterio de aceptación esencial |
| --- | --- | --- |
| 4: `piece_cards.rs` | Proyección fija de piezas con evidencia física | Cards/card_text/canónico iguales; roles y gaps correctos, sin líneas fabricadas o repetidas; límites 64 líneas / 4 excerpts / 12.000 caracteres; fuente stale o fuera del root rechazada |
| 5: `evidence.rs`, `source_evidence.rs` | Ventanas y refinamiento dentro del owner | Judge recibe documentos/purpose reales; ramas distantes conservadas en fragmentos; ≤40 líneas totales; sin votos duplicados ni texto de hijos; >64 cues; scores finitos por bundle; bypasses sin calls |
| 6: `presentation.rs` | Respuesta pública con fuente actual | Diccionarios originales, identidad archivo/owner, warnings/truncated/omitted, orden, round(score,8), líneas completas y presupuestos Python; cambios físicos retiran evidencia stale |
| 7: `source_piece_probe`, `piece_validate`, `piece_evidence` | Aceptación aislada y autenticada | Entradas sin expectativas, raw originals + suites/calls/sources/modelos fijados, tamper tests, ejecución fuera de checkout sin Python, strace Linux/loader, medidas delimitadas, matriz y una revisión final |

Tras Task 7: **una** revisión fresca del plan completo; regraduar hallazgos y
registrar rulings/minors. Una pasada de correcciones Important/Critical con TDD,
suites afectadas completas y replay desde fuentes archivadas; no bucles de
revisión ni recapturas generales sin una causa nueva. Aceptar M4c2 separado de
M4/global; archivar y limpiar su scratch sólo después de commit/push verificados.

M4d debe fijar antes de implementar el contrato de composición y aceptación:

- Conectar recuperación, reranking numérico, piezas, evidencia y presentación
  con datos reales y selección de modelos aceptada; cubrir búsquedas preparadas
  de símbolos/archivos y canales históricos del inventario.
- Preparar/reutilizar vistas y propietarios con lifetimes explícitos. No trasladar
  al adaptador reglas de scoring, ownership o fuente física.
- Probar CLI por procesos y MCP stdio con cliente real, incluyendo errores,
  freshness, límites y esquemas originales. La prueba neural de PieceSearch
  diferida de M4c2 Task 6 pertenece aquí.
- Verificar el contrato de calidad vigente: top1 ≥90%, Recall10 ≥95%, pertenencia
  top10 de los 197/200 casos aplicables, sin usar reserva privada para diseñar.
  Medir arranque, request completo, preparación/indexación y RSS por separado.
- Publicar recibo M4 completo sólo cuando todos sus canales y accesos públicos
  estén acreditados; ningún wrapper Python, stub o fallback silencioso cuenta.

## 7. Etapas restantes después de búsqueda

Antes de cada bloque nuevo, escribir su especificación y plan Superpowers con
llamada representativa, propietarios, archivos, pruebas y salida verificable.
La orden de continuar del 24/10 ya está vigente; no volver a pedir aprobación
de etapa por rutina.

1. **M5a, representación/persistencia estructural:** producir CFG/IR desde los
   parsers/modelo común; identidades, relaciones, valores, evidencia/versionado,
   lectura de formatos previos y snapshots reproducibles del corpus existente.
   M3d no reemplaza este productor. Dividirlo en capacidades completas probables.
2. **M5b, consulta:** conservar KQL1 y KQL2, parser/compilador/operadores,
   bibliotecas, registro, consultas guardadas, sesiones/preparación y frontends.
   Probar positivos, negativos, budgets, cache invalidation y estados desconocido/
   incompleto; un timeout nunca acredita ausencia. Preservar APIs Python públicas
   sólo mediante bindings finos del motor nativo si su auditoría exige mantenerlas.
3. **M5c, flujo/completitud:** cuerpos, valores/efectos, excepciones/finally,
   recursos, generadores y continuaciones con sus límites actuales; regresiones y
   oráculos runtime independientes. Repetir comparación Django aislada con
   resultados y cobertura explícitos. KQL2 preparado mantiene el objetivo vigente
   de gran mayoría de consultas simples dentro de 10 ms, con cold/warm separados.
4. **M6, conocimiento/contratos:** notas y findings, justificaciones/dependencias/
   hashes, anchors, vigencia, entrega, deduplicación por sesión/generación,
   razonamiento, checks y límites de evidencia. Migrar consumidores y persistencia
   con pruebas de comportamiento; conservar incógnitas y presupuesto de checks.
5. **M7, servicio/integración:** autenticación/protocolo local, snapshots/sesiones,
   orden y cierre de cola, watcher, reinicio, lifecycle, concurrencia y lectores,
   CLI/MCP restantes, hooks tolerantes a fallos, skills y hosts. Ejecutar transporte
   y procesos reales, recuperación/interrupciones e instalación/desinstalación
   sobre fixtures; no tocar configuración instalada para aparentar promoción.
6. **M8, entrega:** paquetes binarios con recursos/gramáticas/licencias/modelos y
   sidecars autenticados; CI nativa en cada plataforma/perfil prometido. Matriz
   global sin pendientes, autonomía fuera del checkout con Python ausente, datos
   compatibles, upgrade y rollback ensayados con copias verificadas. Sólo aquí
   puede promoverse la sustitución. Conservar los originales sigue siendo válido;
   no borrarlos como parte de este traspaso ni para adelantar el cierre.

## 8. Riesgos conocidos que no deben redescubrirse

- **Lectores y slots legacy:** COW protege propietario comprometido, rollback y
  reciclaje; no fija indefinidamente slots mmap para lectores entre commits.
  Antes de exponer búsquedas legacy en M4d/M7, materializar filas/vectores propios
  bajo exclusión del escritor o coordinar explícitamente la vida del lector.
  MVCC SQLite por sí solo no fija `vec_slots` del mmap.
- **Freshness del root (hipótesis aún no reproducida):** SourceAuthority confina
  con descriptor de raíz. Probar renombrar/reemplazar la raíz completa después
  de crear catálogo y antes de citar, además de reemplazo de archivo/symlink.
  Un descriptor antiguo puede ver bytes viejos mientras la ruta visible cambió.
  Añadir control mínimo de identidad sólo si el experimento lo exige.
- **Presupuesto de surrogates Task 6:** Python `json.dumps('\ud800', ensure_ascii=False)`
  mide 3 caracteres con comillas; su transporte UTF-8 seguro escapado mide 8.
  Contar caracteres semánticos Python, no bytes ni longitud del escape. También
  difieren escapes de control (`\n` frente a `\u000a`). No cambiar el codec
  compartido aceptado para arreglar el presenter; añadir caso original específico.
- **Floats canónicos ya corregidos M4c1:** Rust Debug puede elegir `.3` para
  `601174747868153.25` y Python `.2`. `rank_json::float` usa serde_json/zmij fijados
  para desempate y formato de exponentes Python. Mantener `float_roundtrip` en
  lectura: sin él un threshold F64 cambió un ULP. Ragged trace ahora valida ancho
  por owner antes de flatten; comparador exacto salvo rutas toleradas explícitas.
- **Coste de fingerprints ya resuelto:** bosque de 2.560 árboles memoiza identidad
  en `OnceLock`; veinte llamadas warm bajaron de 4.578 s a 2.083 ns totales en
  aquel debug. No reimplementar ni repetir ese perfil sin cambios relevantes.
- **Menores M4c1:** coerción/diagnósticos de entradas numéricas Python extremas
  (whitespace vertical-tab, int `10**400`, repr U+0080/U+00AD) siguen delimitados
  en MINORS; no ampliar tolerancias de inferencia por esos diagnósticos.
- **Coste de desarrollo:** capturar originales y catálogos grandes una vez,
  reutilizar recibos con fuentes fijadas, validar sólo el blast radius nuevo;
  ampliar suites cuando un cambio/fallo lo justifique. No regenerar todas las
  expectativas ni reconstruir targets después de cada lectura de documentación.

## 9. Identidades de recursos y criterio final

Los bosques originales están en `crates/ken-retrieval/resources/ranking/` con
manifest/licencias. No entrenar ni sustituir modelos durante el port:

| Recurso | Identidad |
| --- | --- |
| Forest native: 2.560 árboles / 251 features | fingerprint/JSON SHA `6b563fed14ed276e1b310beba84006078ef65ab5d7d3cb5622d759f6a671e3a0` |
| Forest piece: 1.280 árboles / 262 features | fingerprint/JSON SHA `62846d51f58e5da1cf27ad444073d14341bdc6368f8552a7bb1c30e8d6e7d9b9` |
| NPZ `src/ken/embedder/data/ken__static-qwen3-r512-v2.npz` | SHA `e6ab79ad2462d447d367ac4c9735e1062cb752ba6ed50901773ec2bd427a1ff0` |
| Linux dense `libscipy_openblas64_-7220728c.so` | 28.699.769 bytes; SHA `c938cf8481a5858e8d5efea804106275d7d5e7878a161a5d90f05b6121ef4583` |
| Linux dense `libgfortran-daac5196-038a5e3c.so.5.0.0` | 1.671.529 bytes; SHA `8c13f44b44e4dd0005632ea4173f5f5014d2829d50aa12b2054034297c07f233` |

M7/M8 deben distribuir/adquirir explícitamente esos sidecars por plataforma;
no confiar en que estén casualmente junto al ejecutable o instalados con NumPy.
Los manifests/versiones de dependencias son la autoridad, no el nombre del archivo.

La migración sólo termina cuando la matriz de **todas** las capacidades públicas,
perfiles y plataformas prometidas está verificada, CLI/MCP/integraciones usan Rust
de verdad sin intérprete, datos y rollback están probados y calidad/recursos
cumplen los contratos. Hasta entonces mantener `M4_accepted`/aceptación global
falsos donde corresponda y documentar el próximo corte exacto.

### Continuación del 24/10: runners ARM y preparación de cards

El workflow `Native source-piece gates` ejecuta ahora Rust 1.95 y el oráculo
portátil en runners reales `ubuntu-24.04-arm` y `macos-15`. El primer intento,
[40113265720](https://github.com/Infinibay/ken/actions/runs/40113265720), pasó
las 98 observaciones de ranking de piezas y sus dos raíces de pruebas en ambos
hosts. Las suites completas detectaron diferencias de alineamiento numérico
frente a los recibos históricos; ese intento **no acepta Task 3**.

El commit `41d324bd` conserva esos originales y prepara una comparación con
Python congelado en los mismos runners, sin ampliar tolerancias ni cambiar el
cálculo para ajustarlo a resultados esperados. Sus artefactos guardan originales,
resultados, descubrimiento y hashes; todavía requieren interpretación y cierre
de los gates. Los originales se guardan en caché antes de compilar para evitar
repetir las capturas cuando falla una prueba nativa.

Task 4 tiene 60 observaciones originales nuevas en Linux x86_64 y tres raíces de
pruebas, con tarjetas completas, texto canónico, límites de líneas/caracteres,
procedencia y cambios de archivos/directorios. El mismo workflow captura las
familias faltantes en ARM. `piece_cards` ya implementa unidades, extractos y
tarjetas tipadas, proyección canónica y validación física. Sus 60 observaciones
coinciden localmente; las suites completas pasaron 123 pruebas nativas y 108 de
tooling, junto con fmt/Clippy estricto. Sus gates ARM se cerraron en la ejecución
posterior indicada abajo; completar M4c2 sigue pendiente.

La prueba nueva del lector físico también detectó que reemplazar el directorio
raíz conservaba por error las lecturas del directorio anterior. Cada apertura
nueva adquiere ahora un descriptor confinado del directorio actual; los archivos
ya abiertos conservan su propio descriptor. La regresión pasó de RED a GREEN,
y las suites completas core/búsqueda pasaron localmente. El intento adicional de
indexación pasó publicación (7 raíces), pero sus 8 pruebas incrementales carecen
de `KEN_GRAMMAR_MANIFEST`; el catálogo de gramáticas aún no admite Linux x86_64.
Ese límite sigue pendiente y no debe confundirse con aceptación de indexación en
esta arquitectura.

La ejecución posterior [40117742527](https://github.com/Infinibay/ken/actions/runs/40117742527)
(commit `45dc4195`) pasó todos los gates en **ambos hosts ARM**: 123 pruebas
nativas en Linux y 122 en macOS (la prueba del sidecar BLAS es exclusiva de Linux),
109 de tooling, formato y Clippy estricto por host, además de las 98
observaciones de ranking y 60 de tarjetas. El ajuste de almacenamiento del
fixture (`Cow<str>`) resolvió el lint exclusivo de ARM; no cambió la aritmética.
Los originales de evidencia (86 observaciones/19 raíces) también se capturaron
antes de comenzar esa implementación nativa.

Task 5 ya implementa `evidence` y `source_evidence`: verificación de fuente,
completar regiones propias, ventanas y bundles juzgados, selección léxica con
máscaras dinámicas y un presupuesto común de 40 líneas. `result_selection` es la
autoridad compartida de deduplicación por archivo y slots para futura presentación.
La suma Python 3.12 existente se comparte desde `reductions`, sin duplicarla.
Las 88 observaciones locales coinciden (86 iniciales y dos adicionales de
stemming que reutilizan las 19 raíces originales). Pasaron 124 pruebas nativas
locales, 110 de tooling, formato y Clippy estricto. Falta ejecutar esa nueva
implementación en ambos ARM, Task 6, el probe/recibo y la revisión final de Task 7.
M4c2, M4 y la migración global siguen sin aceptación final.

La evidencia nativa de Task 5 cerró sus gates ARM en
[40118877663](https://github.com/Infinibay/ken/actions/runs/40118877663), commit
`b3b74726`: 124 pruebas nativas Linux, 123 macOS y 110 de tooling por host,
formato y Clippy estricto. Se verificaron por separado sus originales, salidas
crudas y los 757 hashes de fuentes contra ese commit.

Task 6 implementa `presentation`: respuestas tipadas de propietarios y piezas,
consulta sin pérdida, redondeo a ocho decimales, ventanas/rangos fieles y los dos
recortes originales por prioridad. El presupuesto usa el formato numérico y
escapado Python ya aceptado, contando los surrogates aislados como un carácter
semántico. Las 117 observaciones y nueve raíces originales pasaron también en
ambos ARM antes de escribir esa implementación, ejecución
[40119578070](https://github.com/Infinibay/ken/actions/runs/40119578070).
El oráculo necesita `onnx==1.20.1` para importar un fixture de la prueba acotada;
no se ejecuta la raíz neural ni se descargan modelos.

La comparación local de presentación pasó de API ausente RED a GREEN. Encontró
y corrigió el formato del aviso de archivo eliminado (errno y ruta), conservando
al lector confinado como única autoridad de bytes. Pasaron 125 pruebas nativas
locales, 111 de tooling, formato y Clippy estricto. Falta validar esa nueva
implementación en ARM y completar el probe/recibo/revisión de Task 7. No se ha
sustituido el comando Python instalado ni se acepta M4/global todavía.

## Cierre M4c2 del 24/10: recibo revisado y transportable

Fuentes aceptadas: `3e4a4e4ccd6762f437af43f618e8631984e67b39`.
La ejecución [40127406181](https://github.com/Infinibay/ken/actions/runs/40127406181)
pasó todos los gates en Linux aarch64 y macOS arm64: **126/125 raíces Rust**,
**174 de tooling por host**, formato y Clippy estricto. Son raíces descubiertas;
las cifras anteriores obtenidas sumando `passed` incluían además un subproceso
de la prueba de salud y no deben usarse como inventario de raíces.

Cada plataforma acredita **446 observaciones: 433 comparaciones y 13 guardas
más estrictas**. Siete casos originales sintéticos etiquetaban como clase una
declaración de otro tipo; se conservan sus resultados originales y se exige
ahora el error preciso sin llamadas de encoding. Las otras seis guardas de
admisión ya estaban declaradas. No se cambiaron modelos, tolerancias numéricas,
salidas válidas ni presupuestos para obtener el resultado.

La única revisión final encontró tres Important: escritura del probe por cadenas
de enlaces, soporte stale en cards y clase con entidad no clase. Una incidencia
de recibos Clippy se elevó de Minor a Important. Las cuatro se reprodujeron y
corrigieron en una pasada; los diez comportamientos apartados tienen resolución
explícita. No hubo segunda revisión ni recaptura de originales aceptados.

El [recibo local](validation/rust-migration-2026-10-23/m4-source-pieces/README.md)
contiene revisión, decisiones, reparaciones, binarios, originales, auditorías,
snapshots y replay. Sus 986 archivos de fuentes/tooling por plataforma se
contrastaron contra Git y la aceptación se repitió con el verificador archivado.
`FILES.json` tiene SHA-256
`92954a5df4ea37bf4820b50e695b023d84d305fab29e7c19c09b93ea7d781e20`.

Archivo local `.ken/rust-migration/archives/m4-source-pieces-3e4a4e4c.tar.gz`:
340.368.226 bytes; SHA-256
`feafc8ea7dfe9f81beaf729e5ba15766ff7ab70eb3d3c656a8dd9c447172f5d7`.
Se mantiene fuera de Git. Las capturas de plataforma también están en Actions
por 30 días: Linux `12572999379`, macOS `12573364847`. El recibo posrevisión
completo se transporta con el archivo local; no se reconstruye recapturando.

Los 1.066 originales conservan sus hashes. Los escenarios y runtimes temporales
se limpian al cerrar sus propietarios; se mantienen raw, SDKs y cachés compartidas.
**M4c2 está aceptado; M4 y la migración global siguen falsos.** La búsqueda pública,
CLI/MCP y el Ken instalado todavía no usan este motor completo. Continuar por
M4d: las gramáticas x86_64 quedaron registradas y validadas en el cierre siguiente;
continuar con composición, pools, modelos y gates públicos.


## Cierre de gramáticas Linux x86_64 del 24/10

Fuentes: `7048d3fb6f4505ca44dfa222cfdde80a9c3dea3e`.
La ejecución [40141705583](https://github.com/Infinibay/ken/actions/runs/40141705583)
pasó en Linux x86_64, Linux aarch64 y macOS arm64: **33 raíces Rust/doc,
87 de tooling y 249 comparaciones completas por host**, formato y Clippy estricto.
Son 20 gramáticas, 19 parsers y 44 extensiones; las 13 bibliotecas dinámicas x86
usan el pack 1.8.1 fijado y los dos registros ARM conservan sus bytes.

La referencia x86 se capturó una vez antes de habilitar el host: 215 casos,
217 llamadas y 124 raíces originales. Los originales ARM se reutilizaron;
los 1.066 archivos congelados siguen intactos. La única revisión final encontró
una falta de unión entre recibo, snapshot y tooling, además de filtros CI
incompletos. Ambos puntos se repararon en una pasada; ocho regresiones nuevas
pasaron de RED a GREEN. No hubo segunda revisión ni recaptura de originales.

El [recibo local](validation/rust-migration-2026-10-24/x86-grammars/README.md)
se reprodujo con el verificador archivado, ligado a las fuentes y al tooling
revisados. Se contrastaron 273 archivos de snapshot por host contra Git.
`FILES.json` contiene 942 miembros y tiene SHA-256
`7990e3edaf04a9b95f2ede40cb165298840d5f33094d397c1d749ee8beaf1350`.

Archivo local `.ken/rust-migration/archives/x86-grammars-7048d3fb.tar.gz`:
23.328.842 bytes; SHA-256
`479fd3e89717ae2130207b2859b8f83c854ddd4b61ed7adb126f90324da3535f`.
El replay también pasó tras extraer ese archivo en un destino independiente.
Los raw, SDKs y recibos siguen fuera de Git. Ver [transporte](validation-artifacts.md).

Sólo `Grammar_x86_64_accepted` es verdadero en este recibo. Las ocho pruebas
incrementales locales son smoke; falta aceptación completa de indexación y
perfiles de modelos x86. Los recibos ARM anteriores conservan su aceptación.
M4 completo, CLI/MCP y la migración global siguen pendientes; Ken instalado sigue
siendo Python. Continuar M4d sin volver a ejecutar originales ya aceptados.


## Avance M4d: fusión ordinal y siguiente objetivo x86_64

`reranker_fusion::fused_reranker_order` ya combina el orden existente y el neural
sin cambiar identidades ni limitar el pool. Fuentes `f239ea9b`, integración
`b2ea3b318280c393185600d49854de2ab29fd387`. Compara exactamente 2.616 observaciones
originales, incluidos errores, empates, subnormales y pools mayores que diez.
Sus doce raíces originales se ejecutaron una vez antes de escribir la API Rust.

La ejecución [40142505190](https://github.com/Infinibay/ken/actions/runs/40142505190)
pasó 127 raíces Rust en Linux ARM y 126 en macOS ARM, 174 de tooling y 446
observaciones de piezas por plataforma, formato y Clippy estricto. El aumento
respecto de M4c2 es exactamente la nueva raíz de fusión. Las fuentes y el tooling
se contrastaron contra Git y cada integración se reprodujo con su verificador
archivado. La regresión de sintaxis también pasó sus tres hosts en `40142505163`.
Localmente pasaron 127 raíces Rust, 174 de tooling y 363 comparaciones auditadas
x86, conservando intactos los recibos M4c2 y de gramáticas.

La única revisión final no encontró fallos de producción ni Critical/Important.
Queda un Minor de cobertura: añadir por separado el caso scores `[0,1]`, peso
`0.5`, offset `2^53`, que protege el agrupamiento aritmético ya correcto. La
siguiente captura M4d debe incluirlo sin reescribir el corpus de 2.616 casos ni
repetir sus doce raíces originales. Las ocho conductas apartadas tienen resolución.

El [recibo parcial local](validation/rust-migration-2026-10-24/reranker-fusion/README.md)
conserva original, fuentes, revisión y gates; `FILES.json` tiene 69 miembros y SHA
`27d87534b036bf336590d967eca242f931f0fae5ab14d8a1fd6f3cd91ca7b6d3`.
Los paquetes CI completos y sus verificadores permanecen fuera de Git en
`.ken/rust-migration/fusion-ci-40142505190/`; este recibo pequeño no afirma un
replay separado de esos paquetes externos. M4d/M4/global siguen pendientes.

El usuario reiteró que quiere soporte x86_64 para el motor. Continuar por
**Linux x86_64 como objetivo de validación completo**, ampliando modelos,
indexación y la matriz del motor ya migrado. Gramáticas y BLAS están habilitados;
los validadores antiguos aún fijan ARM en varios puntos y faltan runtimes x86
registrados. Conservar sus recibos y originales, registrar recursos CPU x86
propios y validar cada capacidad antes de declararla soportada. Después retomar
fuente/símbolos/PieceSearch y el resto de M4d. No cambiar el Ken instalado.
