# Native Import Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with native inline execution.

**Goal:** Resolve native parsed imports with exact original target/classification and config precedence.

**Architecture:** ImportCatalog owns ordered indexed paths and delegates to ModulePath, AliasResolver and language policies. Config acquisition produces byte inputs; the pure resolver never reads filesystem or SQLite. Incremental writes consume the resulting edges in a later plan.

**Tech Stack:** Rust1.95, existing ken-core serde/serde_json/regex, Python validation only.

**Spec:** `docs/superpowers/specs/2026-10-23-rust-import-resolution-design.md`

## Global Constraints

- Begin implementation after M3b final review and verified repair; preserve original1066files/user dirt.
- Native inline implementation, no confirmation pauses, one fresh whole-plan final reviewer.
- Exact request/result/config ordering, language priorities and original error boundaries.
- No third-party upgrades or global serde_json feature changes; no production writer/CLI promotion.
- Actual Macarm64/Linuxaarch64 acceptance, unchanged model/parser/source histories reused.
- SDK preparation may use Python; native import consumers never use Python/processes/network.

## Review Focus

1. Two aliases or workspace prefixes can match; preserve original ordered first success and stable duplicate-key positions. Task2 tests exact targets.
2. A generic structural match can precede a language rule; do not apply preferred language semantics out of order. Task3 tests collisions.
3. Malformed config shape differs from missing/invalid JSON; preserve actual original failure versus tolerance. Tasks1,2,4 observe and test both.
4. Nearest config/module with no target may or may not fall through according to its owner; Task2/3 tests missing-target ancestor/nested cases.
5. A native proof must retain every target/classification and every original error, including no-root and Unicode inputs. Task5 rejects resealed omissions and false summaries.

---

### Task 1: Independent original resolution reference and structural targets

**Files:** Create `tools/rust_migration/import_reference.py`, `tests/rust_migration/test_import_reference.py`, `crates/ken-core/src/imports/{mod.rs,paths.rs}`, `crates/ken-core/tests/import_resolution.rs`, `crates/ken-core/tests/fixtures/import-reference.json`; export imports from lib.rs.

**Interfaces:** Original capture records ordered files, config bytes, pending module/source/language requests and observed final target/resolution. Public ImportRequest{module:String,source_path:String,language:Option<String>}, ImportResolution{target:Option<String>,resolution:Resolution}, Resolution::{Internal,Unresolved,External}, ImportError. Internal structural_target(module:&str,source:Option<&str>,files:&[String],suffixes:&BTreeMap<String,Vec<String>>)->Option<String>. `ImportCatalog::from_inputs(files:Vec<String>,configs:Option<BTreeMap<String,Vec<u8>>>)->Result<Self,ImportError>` constructs native catalogs; specialized resolve remains explicitly pending until Tasks2/3.

- [ ] Capture actual original tests/test_indexer.py resolution calls with owners and124parser/model histories reused. Record all test IDs/states, real raw requests/output and supplemental direct original ambiguity/no-root/Unicode cases; reference tests reject changed owners, missing cases and stale captures.
- [ ] Add Rust public-usage tests for generic dotted/suffix uniqueness, relative joins, exact/non-code path priority, all seven extension/index fallbacks and ESM rewrite. Run affected test: expect missing imports module/API RED.
- [ ] Implement data contracts, path normalization, JS matcher and precomputed Python suffix lookup; preserve bytes/whitespace/ambiguity rules from original. No DB access or generic guessed external success for pending languages.
- [ ] Run structural subset, focused capture tests, ken-core existing tests and fmt/clippy on both native systems. Expect complete captured structural results and original1066guard GREEN.
- [ ] Commit scoped changes as `feat(imports): preserve structural module resolution`.

### Task 2: Ordered config and JS/TS aliases

**Files:** Create `crates/ken-core/src/imports/{config.rs,aliases.rs}`; extend imports tests/reference fixtures.

**Interfaces:** ConfigValue owns ordered object values, UTF8 replacement/strict parsing policies and original JSONC cleanup. AliasResolver::from_inputs(files:&[String],configs:&BTreeMap<String,Vec<u8>>)->Result<Self,ImportError>; resolve(module:&str,source:&str)->Option<String>; is_internal_shape(module:&str,source:&str)->bool. Reads only supplied bytes and indexed config paths.

- [ ] Add original full-target tests for ordered overlapping aliases/workspaces, duplicate keys, nearest config ties and fallthrough, depth<3 extends cycles, parent baseUrl inheritance, malformed/invalid JSON and wrong shapes.
- [ ] Run JS/TS subset expecting explicit pending/missing aliases RED.
- [ ] Implement ordered JSON via serde visitor and string-aware original JSONC cleanup. Preserve first-position/last-value duplicate semantics, paths insertion order and stable nearest-first configs/packages.
- [ ] Run all current imports tests, focused tooling, existing ken-core regressions and fmt/clippy on both systems. Expect exact original target/classification/error boundaries and unchanged model dependencies.
- [ ] Commit as `feat(imports): resolve ordered JS and TS project aliases`.

### Task 3: Language module rules and unresolved classification

**Files:** Create `crates/ken-core/src/imports/{languages.rs,classification.rs}`; extend mod.rs/tests.

**Interfaces:** `ImportCatalog::resolve(&self,request:&ImportRequest)->Result<ImportResolution,ImportError>` becomes complete. Language policies consume catalog inventory/config-derived Go/PSR4 data; targets are existing paths only. Generic structural match always precedes specialized lookup.

- [ ] Add complete original edge tests for Java static/wildcard, Rust crate/self/super/glob/module precedence, nested Go modules and representative non-test files, Ruby relative loads, quoted C++ subtree ambiguity, Kotlin unique package files, PHP ordered PSR4/unique tail and all language-specific unresolved/external shapes. Include deliberate generic-vs-specialized collisions.
- [ ] Run affected language/classification tests: expect pending branches RED.
- [ ] Implement language decisions in their owners, stable ordering and exact original early-return/fallthrough rules. Remove all pending resolve branches; unknown languages retain original generic resolution/classification.
- [ ] Run complete native import corpus, original-owner guard, affected tooling, ken-core regressions and fmt/clippy on both systems; expect complete ordered results/errors GREEN.
- [ ] Commit as `feat(imports): complete native language resolution policies`.

### Task 4: Real project config acquisition

**Files:** Create `crates/ken-core/src/imports/project_inputs.rs`; extend imports public API and tests.

**Interfaces:** `ImportCatalog::from_project(root:Option<&Path>,files:Vec<String>)->Result<Self,ImportError>` reads only indexed config paths, with original UTF8/error tolerance, then delegates pure construction. None means no project configs. The filesystem adapter never chooses import targets.

- [ ] Write real temporary-project tests for indexed/unindexed configs, missing/unreadable files, JSONC UTF8 replacement versus PHP strict decoding, wrong shapes, optional root and config changes between separately constructed catalogs.
- [ ] Run new public caller tests: expect missing from_project RED.
- [ ] Implement config acquisition and contextual errors; keep resolution/persistence outside this owner.
- [ ] Run imports suite and relevant existing ken-core tests on Mac/Linux, fmt/clippy and1066guard. Expect same results as explicit-input catalogs and no hidden cache/fallback.
- [ ] Commit as `feat(imports): prepare resolution from indexed project configs`.

### Task 5: Native differential acceptance and review

**Files:** Create `crates/ken-core/examples/import_probe.rs`, `tools/rust_migration/{import_validate.py,import_evidence.py}`, `tests/rust_migration/{test_import_validate.py,test_import_evidence.py}`, `docs/validation/rust-migration-2026-10-23/m3-imports/`; update migration progress docs.

**Interfaces:** Strict bounded input-only probe accepts ordered file/config bytes and import requests, returns complete ordered ImportResolution or contextual errors. Native acquisition mode reads actual temporary project config files. Authentication pins the final closed M3b FILES manifest at execution time, validates immutable predecessor bytes and snapshots every consumed source/config/test input.

- [ ] Add RED comparator/protocol/receipt tests for missing/duplicate/reordered inputs, changed target/resolution, config order or bytes, lost original failures, injected expectations, missing platforms and resealed false passing gates.
- [ ] Implement native probe, isolated copied-binary process driver and semantic receipt replay. Record actual stdout/stderr/exit, sentinelPATH/loader evidence and Linux exec/connect audit; no expected values accepted by native requests.
- [ ] Run full affected native/tooling gates and one complete differential per actual platform, with actual config acquisition fixtures. Reuse unchanged earlier parser/source/model histories; verify1066originals intact.
- [ ] Replay authenticated evidence independently; expect all resealed mutations rejected and M3c-only acceptance. Compress raw histories, retain small source snapshots and exact gate inventories.
- [ ] Commit evidence, run one fresh whole-plan review and one TDD Important/Critical repair pass, archive complete ledger/rulings/minors/review before deleting own completed workspace. Continue common model and incremental indexing without confirmation pauses.

## Self-review

The catalog and ordered config boundary are fixed before specialized consumers;
all five Review Focus inputs have explicit task tests. No task conflates native
resolution with SQLite writes or claims global migration completion. Canonical
common-AST normalization remains its own producer/consumer boundary after import
resolution and before M3 indexing acceptance. The final M3b predecessor identity
is resolved only after that plan's required review repair closes, avoiding a pin
to provisional evidence. Existing no-confirmation/native authorization applies.

Closed M3b predecessor: `docs/validation/rust-migration-2026-10-23/m3-parsers-review`; FILES.json SHA256 `c1541177be2a0716ff52276d7cfe042ae4ff5acea75d3f4c90d4a3452ab48ff8`, repaired commit03400e2b. Its immutable proof is reused; no124parser-suite/model recapture.
