# M1: proyecto y estado nativos

**M0 y M1 aceptados en Linux aarch64 y macOS arm64.** La [matriz conjunta](matrix.json)
pasó con las mismas huellas de fuentes nativas, referencia Python, casos, tooling
y Rust 1.95.0. La aplicación completa sigue en migración: M2–M8 no están acreditados.

Rama `codex/rust-migration`. Referencia congelada:
`e95cc533cc8a603d46481c5310f4b870ffbaaced6fa24fd8a1d85cbd04123222`.
Los 1.066 originales y la referencia ampliada se verificaron sin deriva antes y
al cerrar. Ninguna fuente original se eliminó o modificó; el comando instalado
sigue activo. El binario nativo temporal es `target/release/ken-rs`.

## Alcance verificado

- Descubrimiento y confinamiento con override, Unicode, usuarios, symlinks,
  destinos inexistentes, `..`, ciclos y destinos compartidos.
- Estado SQLite readonly en un snapshot: quince contadores, referencias inline
  y por slot, frescura, cobertura, señales y recomendaciones; WAL visible.
- Health loopback autenticado, sin proxy ni redirect y deadline global de un segundo.
- `status [PATH] [--json]`, argumentos, defaults, JSON/texto y errores de proceso.
- Autonomía fuera del checkout, PATH sin Python, sentinelas y dependencias nativas;
  [strace Linux](linux/native-exec.trace) registra sólo el exec inicial.

`ken-core` posee proyectos, lectura/reglas de estado y health; `ken-cli`, argumentos
y presentación. Las responsabilidades de tooling se separan en referencia,
inventario, fixtures, comparación, aceptación de recibos y medición.

## Pruebas y aceptación

Cada plataforma pasó los 16 gates, 15.606 pruebas Python con los mismos 10 xfail
históricos, 28 pruebas de integración Rust, 66 pruebas de integración de paridad
y el contraste independiente de los 62 casos públicos. No hubo fallos, omisiones
ni skips nuevos. Los 58 casos originales permanecen, con cuatro regresiones añadidas.

El tipado no introduce errores: Linux pasó sobre los 409 fuentes; macOS conserva
los dos errores previos por `transformers` ausente, identificados por archivo,
línea, mensaje y código. Por ello no se presenta el baseline general como libre
de incidencias históricas. Los fallos de arranque KQL registrados en M0 siguen
visibles por ID y pasaron en estas ejecuciones.

Recibos locales: [macOS](macos/summary.json), [Linux](linux/summary.json),
[paridad macOS](parity.json), [paridad Linux](linux/parity.json).
Cada recibo local mantiene `M1_matrix_accepted=false`: sólo el agregador acredita
la matriz completa. Los logs y JUnit crudos se conservan sin alterar bajo
`.ken/rust-migration/m0-m1/validation/` y
`.ken/rust-migration/m0-m1/linux-receipts/validation-corrected/`.

La [revisión independiente](REVIEW.md) encontró un Important en expansión de
symlinks compartidos. Se corrigió en una única pasada TDD; el triage agregó la
semántica de existencia de enlaces cíclicos y paths no codificables. Se observaron
FAIL→PASS antes de regenerar ambos cierres completos. Los dos Minor del reviewer
se mantienen diferidos y están descritos en REVIEW. No hubo segunda revisión.

Se conservaron los intentos previos: `validation-attempt-1` detectó un problema
del parser de identidad rustc y deriva del propio tooling; `validation-before-review`
identifica las fuentes anteriores a la corrección. Sus resultados no se mezclan
con la aceptación actual.

## Mediciones y reproducción

Se retienen 30 procesos por programa y escenario (180 muestras por plataforma),
con orden alternado, preparación separada y ninguna muestra descartada. Para
el caso poblado, proceso completo incluyendo arranque:

| Plataforma | Rust mediana | Rust p95 | Python mediana |
| --- | --- | --- | --- |
| macos | 5.168 ms | 7.866 ms | 201.079 ms |
| linux | 1.279 ms | 1.460 ms | 229.962 ms |

[Todas las muestras macOS](macos/benchmark.json) y [Linux](linux/benchmark.json)
incluyen máximo y RSS kernel por hijo. En Linux ese RSS incorpora memoria heredada
antes de exec: la [calibración](linux/rss-calibration.json) demuestra el suelo del
harness. No se interpreta como RSS exclusivo del binario ni se atribuye mejora de
memoria. No se inventó un SLA para `status` ni se midieron modelos en este gate.

La [guía](../../../rust-migration.md) y el [plan aprobado](../../../superpowers/plans/2026-10-18-rust-m0-m1.md)
contienen los comandos. El workflow independiente está preparado; no se ejecutó
CI remota, no se hizo push/PR y no se promocionó `ken-rs` como comando instalado.
La comprobación Linux fue local, sobre copias aisladas en Docker Desktop.

El inventario M0 conserva 60 rutas CLI, 15 herramientas MCP y 475 recursos;
`status` es el primer corte. Se continúa con el [plan M2](../../../superpowers/plans/2026-10-18-rust-m2-static-encoder.md)
antes de portar consumidores, manteniendo originales y ejecución nativa.

## Decisiones de ejecución

Se conserva a continuación el registro completo de decisiones del ejecutor.
Las decisiones reemplazadas permanecen visibles junto con su corrección.

- Ruling: work in the approved branch/current checkout — an isolated worktree would omit the uncommitted oracle — wrong choice would compare against stale Python.

- Ruling: normalize task headings from T1 to 1 for Superpowers task-start compatibility — no task or contract changes — wrong choice would lose reliable progress extraction.

- Task 2: Ruling: baseline collection failed on missing snowballstemmer 3.0.1 already pinned in uv.lock — restore the declared hashed wheel in .venv, preserve failed attempt, then rerun baseline — risk if wrong: an environment-only repair could be mistaken for a product fix.

- Task 2: Ruling: raw SDK schemas add titles and nullable anyOf/defaults absent from the CLI registry — inventory compares names and retains both raw schemas plus their differences rather than demanding byte equality — risk if wrong: a real pre-existing interface difference must remain visible for M7, never be normalized away. Evidence: mcp-raw.json.

- Task 3: Ruling: prepare the independent M0 fixtures while the full original suite and T2 transport capture run — M1 remains gated on completed M0 receipts — risk if wrong: task ranges overlap, so commits and task completion are recorded separately.

- Task 1: Ruling: Git discovery inside an ignored nested oracle returned an empty file list — use Git only at its actual worktree root and scan the frozen tree otherwise; default frozen scope to src/ken/** — regression test nested_ignored_snapshot RED→GREEN — risk if wrong: added oracle source could evade drift detection.

- Task 3: Ruling: self-check excludes only the predeclared health-redirect difference, retained in all native runs — Python cannot certify Rust redirect rejection — risk if wrong: confusing harness validation with native parity. Actual negative CLI exited 1 on installed_empty-json.

- Task 3: Ruling: add exact mismatch paths and reject valid non-object JSON reports before M1 — generic field diagnostics obscured negative-control evidence — RED→GREEN test_failure_identifies_the_field_and_rejects_non_object_reports.

- Task 2: Ruling: capture acceptance serially after concurrent full-surface captures exceeded 30s/90s tooling deadlines — isolated phase diagnostics complete init/list/close and CLI help; retain failed attempts and original KQL timing/startup failures — risk if wrong: treating flaky/environment failures as successful compatibility; M1 remains blocked until the serial gate exits 0.

- Task 4: Ruling: soft-canonicalize 0.5.6 ordinary API loses a dangling symlink target before .. (observed root/new vs Python root/missing/new). Use its anchored resolver at filesystem / on Unix, NEVER project root; project containment still checked after resolution — preserves absolute targets and rejects escapes without a custom symlink implementation — risk if wrong: resolver semantics; all path tests plus differential Python checks required before promotion.

- Task 5: Ruling: box InstalledStatus inside StatusReport to satisfy clippy large_enum_variant without suppression — same semantic variants and serialized contract, one allocation — risk if wrong: new Rust callers need dereference when taking ownership. 13 library integration contracts passed, including read-only directory, plus fmt/clippy. SQLite bundled version observed/tested 3.53.2; libsqlite3-sys locked 0.38.2.

- Task 7: Ruling: add ken-cli/src/lib.rs exporting args/status so integration tests exercise the real parsing/rendering boundaries without including source files twice — main remains process coordination only — risk if wrong: these Rust exports might be mistaken for a stable external API; they are internal migration interfaces.

- Task 8: Ruling: verify per-engine project_root/db.path/error paths against their fixture BEFORE declared temporary-root normalization — a real fake process could otherwise hide an incorrect root — test_process_cannot_hide_an_incorrect_project_root observed RED then GREEN; no exception or field was removed — risk if wrong: over-normalization could falsely certify path parity.

- Task 9: Ruling: separate receipt acceptance/JUnit comparison (receipts.py) and per-process measurement (measure.py) from validation orchestration — these are independent responsibilities discovered outside-in — risk if wrong: extra module boundaries without useful isolation; covered through public acceptance tests.

- Task 8: Ruling: canonicalize fixture parent paths at creation — stricter per-engine checks exposed macOS /var -> /private/var aliases in independent expectations — test_fixture_paths_are_canonical_through_symlinks RED→GREEN; expected paths are constructed before either engine runs — risk if wrong: fixture expectations could disagree with the requested canonical project.

- Task 9: Ruling: expose optional --original-manifest/--baseline-dir for CI platform-specific baselines and skip loading a local reference in matrix scope — clean CI must not assert dirty local hashes or depend on an unavailable interpreter path — risk if wrong: a CI receipt might be mistaken for this local checkout; fingerprints are compared explicitly.

- Task 9: Ruling: parse the unique rustc version line, preserving rustup installation notices in the raw receipt — observed isolated HOME triggers installation notices before compiler output — test_rustup_notices_do_not_replace_the_compiler_identity RED→GREEN; missing/ambiguous identities fail — risk if wrong: accepting a different toolchain. The in-flight first validation is diagnostic; source fingerprints changed and a fresh final run is required.

### Decisiones del cierre y revisión

- Final: Ruling: M2–M8 behavior — remains pending and will be implemented under the user’s instruction to finish the full migration; this review only accepts M0/M1 — risk if wrong: a first slice could otherwise be mistaken for full migration.

- Final: Ruling: Windows compatibility — Linux/macOS are the approved minimum; no Windows certification is inferred — risk if wrong: unmeasured Windows behavior.

- Final: Ruling: preexisting dirty Python changes — preserve them exactly as the frozen oracle, outside migration commits — risk if wrong: accidental loss or attribution of user work.

- Final: Ruling: remote CI and Linux/platform acceptance — no remote CI was run; actual local Linux gate and matrix acceptance remain mandatory for M1 — risk if wrong: false platform certification.

- Final: Ruling: full independent suite reruns by reviewer — author ran complete suites; reviewer independently checked identities/integrity and reproduced the defect, without claiming to rerun every suite — risk if wrong: review depth must not be confused with a second full test execution.

- Final: Ruling: manual verification of every CLI/MCP inventory entry — dynamic capture mechanisms and completeness audit preserve the original interfaces for later stages; historical commands are not certified migrated by the M1 review — risk if wrong: inventory could be mistaken for functional parity of unmigrated commands.

- Final: Ruling: retain the two reviewer Minor findings as deferred — current snapshot implementation is transactional and resolver replacement is already explained in the guide; neither is a current user-visible product defect — risk if wrong: weaker regression proof and incomplete historical documentation.

- Final: Ruling: include one additional Important found during triage in the same correction pass — indexed file replaced by a symlink loop returns Python status exit 0 with stale_files=1, but native exit 1; reproduce against frozen process saved in stale-cycle-repro.json — preserve Python existence semantics for ELOOP without swallowing permission/other IO failures — risk if wrong: normal stale indexes could prevent status diagnostics.

- Final: Ruling: use pinned libc 0.2.191 (already transitive in Cargo.lock) as a direct Unix dependency for pathlib-compatible ELOOP/EBADF stat handling — std::io::ErrorKind::FilesystemLoop is still nightly-only; no hardcoded platform errno and no nightly feature — risk if wrong: platform-dependent existence classification.

- Final: Ruling: append shared_symlinks/stale_cycle JSON+text cases to the matrix before verifying corrected release — all previous 58 IDs remain, now 62; independent fixture expectations test RED→GREEN — risk if wrong: extending coverage must not erase prior cases or normalize a new difference.

- Final: Ruling: retain literal per-child kernel wait4 RSS with an explicit Linux pre-exec inheritance caveat — /bin/true calibration changed child peak20.6MB→104.2MB when parent allocated80MiB, so the65.2MB Linux status floor cannot establish binary-only memory usage or a memory speedup — no RSS SLA was invented; next model measurements must separate loading/inference — risk if wrong: misleading memory comparisons.
