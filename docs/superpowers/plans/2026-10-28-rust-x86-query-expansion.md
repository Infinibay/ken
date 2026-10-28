# Linux x86 Query Expansion Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. No implementer agents; one final fresh read-only reviewer for this slice and one Important repair pass.

**Goal:** Enable native registered Spanish query expansion and warming on Linux x86_64 with independent original parity.
**Architecture:** Keep LocalQueryExpansion/model preparation; shared observer gains optional immediate journaling. A profile-specific frozen fixture supplies expectations; a host owner authenticates native-only evidence without recapturing originals.
**Tech Stack:** Rust1.95/Python3.12.9, authenticated CT2core4.8.2 with an owned C ABI on x86, SentencePiece0.13.2/source0.2.1; legacy ARM retains CT2RS0.10.1/Ruy/OpenBLAS0.3.26.
**Spec:** docs/superpowers/specs/2026-10-28-rust-x86-query-expansion-design.md

## Global Constraints
- Linux x86_64 active; retain ARM code/fixtures. No installed-app replacement, merge or release.
- Frozen1066fingerprint5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038 and all accepted originals/models/tolerances immutable.
- Only new x86 original histories, journal immediately; never original pytest roots or accepted observation repeats.
- Preserve CPU int8/two intra threads/one replica/beam1/input1024/output256. On x86 use the registered CT2 CPU core and report its actual DNNL/MKL backend; ARM retains Ruy and existing BLAS policy.
- No new external versions/private reserve; raw receipts/workspaces local and untracked; branch push authorized.
- BestSearch SkylakeX discrepancy and all unrelated global gates remain explicit pending work.

## Review Focus
- Wrong-architecture or foreign-runtime fixtures must fail before comparison, not silently select Linux ARM.
- Journal failures/timeouts must preserve completed original rows and prevent accidental overwrite/re-observation.
- Failed first load/inference must leave English lazy and allow a valid retry without crossing call diagnostics.
- Token boundary/max-input policy and placeholder restoration must preserve original discrete results and errors.
- The x86 C ABI must authenticate the pinned CPU dependency closure, report its actual backend, and retain code/buffers/sessions in the correct destruction order. Legacy ARM backend identities remain unchanged.

### Task 1: Independent original x86 translation histories
Files: tools/rust_migration/translation_reference.py; new tools/rust_migration/x86_translation_reference.py; tests/rust_migration/test_translation_reference.py and test_x86_translation_reference.py; crates/ken-models/tests/fixtures/translation-linux-x86_64.json.gz.
Interfaces: existing capture(reference,source,output,*,cases=None,definition=None,journal=None) retains default behavior; new capture(reference,source,out), validate(value), load(repo). Frozen29cases and raw per-call traces, explicit x86 runtime/source/model/inventory checks.
- [x] RED optional journal propagation/refuse overwrite, missing/crossed/altered x86 fixture and source/trace integrity.
- [x] Implement optional immediate observer journaling and x86 capture/authentication without repeating existing observations. Store original stdout/stderr/inputs/journal/script identities before compressing.
- [x] Observe29distinct histories once on x86 before native behavior changes; scoped tests pass and commit the immutable fixture.
Expected: authenticated complete x86 histories, partial failure records retained, ARM references unchanged.

### Task 2: Native x86 owner and public model consumers
Files: crates/ken-models/src/query_expansion.rs; tests/query_expansion.rs; examples/translation_probe.rs; model_catalog tests as needed; crates/ken-search/tests/best_search.rs for registered warming.
Interfaces: preserve LocalQueryExpansion construction and ARM serialized identity; add explicit NativeTranslationRuntime and its actual x86 binding/backend identity; oracle selectors add Linux/x86_64 and reject other targets; raw-core x86 parity consumes Task1's prepared traces.
- [x] RED public Spanish translation/full29histories/native raw-core/registered resource warming on x86, preserving cold English behavior.
- [x] Enable the existing native policy for Linux x86; select Task1 expectations by architecture in tests/probe, preserving ARM branches and actual backend declarations.
- [x] Run full model unit/integration and affected search suites, including the two previously ARM-only unit failures. Run fmt/strict Clippy/build; commit.
Expected: native translations/tokens/hypotheses/errors match the independent x86 original; no Python fallback.

Task2 amendment after the independent Ruy/oneDNN counterexample:
- [x] SDK: new `tools/rust_migration/translation_cpu_prepare.py` and pinned data registry. Reuse a public generic verified-source archive helper, preserving native_core_prepare compatibility. RED hash/target/overwrite/member tampering; prepare exact CT2wheel/core/OpenMP and CT2RS headers without importing Python model runtimes.
- [x] ABI: `native/ken-ct2-backend` C++ CPU module with version/size checked C ABI, explicit Rust-owned policy, length-aware token spans and owned buffers; actual core backend reporting. Build with pinned CMake, record source/compiler/core proofs.
- [x] Owner: `NativeTranslationRuntime` verifies all declared bytes before private loading, retains module/files through session destruction and shares lazy owners across clones. Reuse artifact validation and existing ownership conventions; test foreign/duplicate/altered declarations, failed load retry, NUL/Unicode and returned-buffer ownership.
- [x] Wiring: add explicit `with_native_runtime` and PreparedModelResources.translation; probe accepts physical runtime declaration, never expectations. Preserve cold English and ARM static behavior; x86 reports its actual native binding/core/backend. Full29histories/raw-core/model consumers must become green before qualification.

### Task 3: Native-only source-bound x86 host qualification
Files: tools/rust_migration/x86_translation_host.py; tests/rust_migration/test_x86_translation_host.py; targeted .github/workflows/rust-x86-translation.yml; minimal shared comparer/probe platform selection.
Interfaces: run_host(repo,out,source), verify_host(out,repo), using Task1 load and existing compare_output; actual command discovery/build proof, owned resource closure and confined input-only native capture.
- [ ] RED missing/partial/resealed input/output/source/recipe/runtime/build-proof tampering; no repeated original calls in run/verify.
- [ ] Implement confined native histories, same-inode ownership, actual registered CT2 module/compiler/SDK build proof and complete roots/fmt/Clippy. Preflight complete29histories before full host qualification.
- [ ] Run complete local and two independent x86 CI hosts on exact committed sources; verify downloaded ZIP digests and each packet. Preserve failed epochs.
Expected: source-bound native parity and runtime preparation without attribution from old/partial executions.

### Task 4: Review and portable closure
Files: migration/handoff docs, local sealed receipt/archive and Git proofs for code/design/support/frozen1066inputs.
- [ ] One fresh read-only reviewer with Review Focus/spec/plan/rulings; regrade, one Important TDD repair pass, no re-review.
- [ ] Verify final three hosts, original journals and source/build proofs; replay extracted archive outside checkout with archived validators and recorded metadata.
- [ ] Update actual x86 expansion/registered-warming scope and remaining BestSearch/global gates; commit/push, clean Git and zero tracked generated validation evidence.
Expected: bounded x86 CT2 capability accepted independently; overall migration continues to its remaining milestones.
