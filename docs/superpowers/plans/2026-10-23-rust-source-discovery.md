# Rust Source Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port project exclusions and confined source traversal without changing original source files.

**Architecture:** `SourceFilter` owns rule composition; `ProjectSources` owns traversal and path identity. A small external probe and frozen original capture prove parity, with explicitly separate integrity corrections.

**Tech Stack:** Existing Rust1.95 workspace, `ignore = 0.4.33`, serde JSON for test transport; Python only in the independent test oracle.

**Spec:** `docs/superpowers/specs/2026-10-23-rust-source-discovery-design.md`

## Global Constraints

- Original files remain untouched; no installed entrypoint replacement or production indexing yet.
- M2 source/evidence must be frozen before native M3 edits; unchanged neural histories are reused at their exact identities.
- All 16 built-in patterns match the original literally. No global Git rules, hidden-file default or shell Git lookup.
- Native walk performs no writes; scopes preserve root-relative identities and inherited exclusions.
- Symlink escapes/cycles and access errors are explicit errors, never confirmed absence.
- Actual native macOS arm64 and Linux aarch64 validation required; no fabricated platform receipts.
- This completes only M3a, not parsers or all M3.

## Review Focus

1. Nested negations cannot reopen a pruned ancestor or bypass `.kenignore`/built-ins; test actual scoped and complete trees.
2. Internal aliases preserve expected identity while external links and cycles cannot escape or hang; test real symlinks, including scoped aliases.
3. Directory enumeration must not touch ignored large subtrees or scoped siblings; test traversal with inaccessible excluded fixtures and visited-directory instrumentation owned by traversal tests.
4. Escapes, Unicode, invalid bytes in ignore files and special pattern syntax must not silently change source membership; compare independent original outputs.
5. Reusing `ProjectSources` after ignore-file changes cannot reuse stale matchers; test a second walk with changed rules.

---

### Task 1: Compatible source exclusions

**Files:** Create `crates/ken-core/src/source_filter.rs`, `crates/ken-core/tests/source_filter.rs`, `tools/rust_migration/source_reference.py`, `tests/rust_migration/test_source_reference.py`, `crates/ken-core/tests/fixtures/source-discovery/reference.json`; modify `Cargo.toml`, `Cargo.lock`, `crates/ken-core/Cargo.toml`, `crates/ken-core/src/lib.rs`.

**Interfaces:**
- Consumes: `ProjectPaths::root() -> &Path` and frozen `Reference`/`reference_env`.
- Produces: `SourceFilter::new(root: &Path) -> Result<SourceFilter, SourceError>` and `is_ignored(&mut self, relative: &Path, is_dir: bool) -> Result<bool, SourceError>`; `SourceError` identifies rule/read/path failures.
- Original fixture transport contains relative files/rules, matcher queries and exact original decisions, plus source/package identity. Never expected native results supplied to native code.

- [ ] **Step 1:** Capture original matcher and walk outputs on real temporary trees, using the existing frozen original interpreter. Include root/nested rules, last matching negations, directory/file distinctions, anchored patterns, double stars, escaped spaces/hash/bang, classes, CR/LF/Unicode line separators, invalid UTF-8 rule bytes, hidden files and all16built-ins. Assert capture missing/altered original ownership hashes fails. Save raw captures with fixture definitions and exact original module/package identities.
- [ ] **Step 2:** Write public `SourceFilter` integration tests consuming those original decisions. Assert `.kenignore` negation cannot revive `secret.env` excluded by Git nor `.ken/cache.py`; nested Git negation can revive a non-pruned file. Run `cargo test --locked -p ken-core --test source_filter`; Expected: compile failure for missing public source API.
- [ ] **Step 3:** Add the pinned matcher dependency and implement composition in `source_filter.rs`. Cache one spec per ancestor within the filter; preserve tri-state no-match vs negation. Use only matcher calls with explicit scope. Exact signature above; errors must name the relative path/rule source. Read memory before editing existing files.
- [ ] **Step 4:** Run `cargo test --locked -p ken-core --test source_filter` and `.venv/bin/python -m pytest tests/rust_migration/test_source_reference.py -q`; Expected: all tests pass, all captured decisions exact. Run fmt and clippy for `ken-core`; Expected: no warnings. Record any original/crate syntax difference as a tested ruling, not reduced coverage.
- [ ] **Step 5:** Commit only Task1 paths: `feat(core): preserve project source exclusion rules`. Completion verifier runs both focused targets and original-source guard.

### Task 2: Confined source traversal

**Files:** Create `crates/ken-core/src/source_walk.rs`, `crates/ken-core/tests/source_walk.rs`; modify `crates/ken-core/src/lib.rs`; extend `SourceError` in its owning module only if necessary.

**Interfaces:**
- Consumes: Task1 filter API and M1 `ProjectPaths::resolve_inside(path, context)`.
- Produces: `SourceEntry { path: PathBuf, is_dir: bool }`; `ProjectSources::new(paths: ProjectPaths, context: DiscoveryContext) -> Self`; `walk(&self, scope: &Path) -> Result<SourceWalk, SourceError>`; `SourceWalk: Iterator<Item=Result<SourceEntry, SourceError>>`.

- [ ] **Step 1:** Write outside-in walk tests for original exact ordered entries/files, scopes retaining ancestor rules, excluded ancestors, all16built-ins, nonexistent/file scopes, Unicode, repeated walks after rule changes. Test real internal alias with exact canonical scoped identity; external symlink and ancestor cycle each emit a named error and terminate, unrelated valid entries remain discoverable. Test unavailable directory surfaces an error; ignored directories never get enumerated.
- [ ] **Step 2:** Run `cargo test --locked -p ken-core --test source_walk`; Expected: missing API compile failure.
- [ ] **Step 3:** Implement `source_walk.rs`: resolve scope through M1; check ancestors before enumeration; sorted entries plus LIFO directories. Fresh filter each walk. Track canonical ancestry per pending directory to reject cycles without suppressing a valid independent alias. Verify every followed target remains under root. Keep pattern decisions in `SourceFilter`.
- [ ] **Step 4:** Run both source targets plus existing `ken-core` tests, fmt and clippy. Expected: all green; exact original order in compatible cases and explicit integrity errors in corrected cases. Exercise unreadable-directory test as ordinary user on both platforms; never skip merely because the controller is root.
- [ ] **Step 5:** Commit only Task2 paths: `feat(core): traverse project sources within confined scopes`. Completion verifier includes both source targets and original-source guard.

### Task 3: Native differential acceptance and handoff

**Files:** Create `crates/ken-core/examples/source_probe.rs`, `tools/rust_migration/source_validate.py`, `tests/rust_migration/test_source_validate.py`, `docs/validation/rust-migration-2026-10-23/m3-source-discovery/`; update `docs/rust-migration.md` with precise completed scope.

**Interfaces:**
- Consumes: `ProjectSources` and Task1 fixture/capture schema.
- Produces: bounded JSON external probe, independent semantic comparator and complete authenticated platform evidence. Receipt states `M3a_accepted` only; `M3_accepted` and whole migration remain false.

- [ ] **Step 1:** Write comparator tests: membership, directory flag, ordering, dropped case, altered rule, wrong source hash and unsupported correction each reject. Write real process tests rejecting expected-output injection, relative project root and unknown request fields. Run focused pytest; Expected: missing module/API failure.
- [ ] **Step 2:** Implement strict probe request `{root,scope}` with absolute root, public traversal only and one bounded JSON response. Implement original capture/replay and source/binary/fixture binding. Integrity-correction cases must identify exact errors rather than feed altered goldens back to the original.
- [ ] **Step 3:** Build release probe and run native original differential once per platform on real independent temporary trees outside checkout with sentinel PATH. Linux records actual exec trace. Preserve raw request/output, environment, hashes, correction cases, tests and command exits. Run all `ken-core` tests and new tooling tests, fmt/clippy; do not rerun unchanged neural models. Verify1066original files before/after.
- [ ] **Step 4:** Independently replay saved artifacts and reject resealed mutations of path/type/order/source/case inventory. Expected: exact parity for compatible cases, all declared integrity corrections pass, both platforms authenticate. Mark only M3a accepted.
- [ ] **Step 5:** Commit scoped source acceptance evidence; task-done runs replay and scoped tests. Perform the one fresh whole-plan final review required by inline Superpowers, one TDD repair pass for Important/Critical findings, archive complete ledger/rulings/review, remove only owned obsolete temporaries. Continue to native grammars/parsers and index write orchestration without confirmation pause.

## Plan self-review

Spec contract maps to Tasks1(patterns),2(identity/pruning/errors),3(actual platform proof).
Shared APIs are produced before consumers; all five review risks have concrete tests.
No task changes original files, model math, stored schema or active command. Later
parser selection consumes relative paths and source bytes independently of traversal.
Execution method is the user's previously selected native inline execution.
