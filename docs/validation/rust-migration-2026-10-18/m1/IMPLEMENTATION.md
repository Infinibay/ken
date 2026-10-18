# M1: proyecto y estado nativos

Rama: `codex/rust-migration`. Referencia Python congelada:
`e95cc533cc8a603d46481c5310f4b870ffbaaced6fa24fd8a1d85cbd04123222`.
Toolchain: Rust 1.95.0. Esta entrega conserva los originales y el comando `ken`
instalado; el binario de ensayo es `target/release/ken-rs`.

## Alcance implementado

- Descubrimiento y confinamiento de proyectos, con override, Unicode, usuarios,
  destinos inexistentes, symlinks y ciclos.
- Lectura SQLite readonly en un snapshot: quince contadores, referencias inline
  y por slot, frescura, cobertura, señales y recomendaciones.
- Health HTTP local autenticado, sin proxy ni redirect y con deadline global.
- `status [PATH] [--json]`, defaults y errores de proceso reales.
- Comparación diferencial de 58 casos, ejecución fuera del checkout, shims que
  detectan auxiliares, auditoría de dependencias y medición por proceso.
- Gate reproducible y workflow Linux/macOS separado de la CI Python original.

`ken-core` posee proyectos, lectura y reglas de estado y transporte health;
`ken-cli` posee argumentos y presentación. Los módulos nuevos de tooling separan
fixtures, comparación de procesos, aceptación de recibos y medición.

## Evidencia y estado del cierre

Tareas 1–8 completadas. El primer cierre local ejecutó 15.604 pruebas Python
aprobadas, 10 xfail históricos, 24 pruebas de integración Rust y 62 pruebas de
integración de paridad, además del contraste separado de los 58 casos.
No aparecieron fallos Python nuevos. Los dos errores de mypy por `transformers`
ya estaban en M0 y se comparan por archivo/línea/mensaje/código.

Ese primer cierre **no se acepta como resultado final**: detectó que los avisos
de rustup precedían a la identidad del compilador en su log. Se añadió una prueba
RED→GREEN que exige una única línea de identidad y conserva los avisos. El cambio
de tooling durante el ensayo también invalidó correctamente su gate de higiene.
Los recibos de ese intento están en `.ken/rust-migration/m0-m1/validation-attempt-1`.

La validación final macOS pasó sus 16 gates: 15.605 pruebas Python aprobadas y
10 xfail históricos, sin fallos ni omisiones nuevas; los dos errores previos de
mypy permanecen identificados. Los [recibos macOS](macos/summary.json) y la
[medición completa](macos/benchmark.json) conservan sus huellas y todas las muestras.
La ejecución Linux sigue en curso. La matriz M1 sólo se
cierra cuando ambos recibos completos tienen las mismas huellas de fuentes,
casos, tooling y toolchain, y Linux aporta su traza exec. La revisión independiente
del conjunto también es necesaria. No se acredita ninguna etapa M2–M8 aquí.

Los resultados completos locales se guardan bajo `.ken/rust-migration/m0-m1/`;
los recibos públicos finales se incorporan al cerrar el gate. El manifiesto de
1.066 originales y el manifiesto ampliado de la referencia se verifican antes y
después. El inventario M0 conserva 60 rutas CLI, 15 herramientas MCP y 475 recursos
de fuente: `status` constituye sólo el primer corte de esa superficie.

## Reproducción

Los comandos y límites del gate están en [la guía](../../../rust-migration.md)
y en [el plan aprobado](../../../superpowers/plans/2026-10-18-rust-m0-m1.md).
El workflow está preparado, pero ninguna ejecución remota se presenta como
realizada. La comprobación Linux local usa una copia aislada en Docker Desktop,
con Rust/Python fijados y strace, sin montar los fuentes originales para escritura.

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
