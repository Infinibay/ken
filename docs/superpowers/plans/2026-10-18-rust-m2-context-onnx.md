# Native contextual ONNX implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. The user selected native inline execution and continuing the whole migration.

**Goal:** Execute the pinned contextual CodeRank model natively while preserving exact lexical inputs and raw768-dimensional outputs.

**Architecture:** Verified model bytes + authenticated process runtime → contextual tokenizer/session → actual native probe → independent frozen comparison. Retrieval owns scoring and L2.

**Tech stack:** Rust1.95,ort2.0.0-rc.14(no defaults,std/alternative-backend/api-25),libloading0.9.0,tokenizers0.22.2. Python/ONNX packages are oracle preparation only.

**Spec:** `docs/superpowers/specs/2026-10-18-rust-context-onnx-design.md`.

## Global Constraints

- Branch codex/rust-migration; preserve all original dirty/untracked files and1066hashes.
- Independent platform oracles before native encoder implementation; no tolerance increase.
- Exact IDs/masks; F32 atol2e-6/rtol1e-5/cos0.999999, zero exact; raw output, no L2.
- CPU2/1, batch1, special tokens, no padding, truncation512 after query prefix.
- Native core1.25.1/API25; actual byte identity, no implicit search/fallback/Python link.
- Linux/macOS observed and source-bound; only this context profile accepted, not M2.
- Each task: RED→GREEN, required tests, own commit, task-done; no intermediate approval pause.

## Review Focus

1. Another ORT user preinitializes globals or two different libraries race; reported identity must name the actually executing authenticated library.
2. Verification sees a FIFO/device, oversized declaration, changing symlink or replaced native path; no blocking read or unchecked executable reopening.
3. Prefix plus special tokens crosses512 or tokenizer serializes padding and a different truncation; same IDs/masks as original with no Potion/table policy.
4. Graph yields wrong name, dtype, shape, extra row, NaN or Inf; no plausible success vector escapes. Output remains raw, not accidentally normalized.
5. A stale external probe, platform oracle from the other OS, unrecognized stderr or missing runtime hash is offered as acceptance; every one must fail.
6. Empty/repeated/mixed/concurrent histories; no lazy-load side effect on empty, leaked mutable outputs, deadlock or hidden native/Python subprocess.

### Task 1: Frozen oracle, independent graph fixtures and runtime declarations

**Files:** Create tools/rust_migration/{context_reference,context_fixtures}.py, tests/rust_migration/test_context_reference.py, crates/ken-models/tests/fixtures/context/, docs/validation/rust-migration-2026-10-18/m2-context/{cases,reference,runtime-libraries}.json.

**Interfaces:** Consume Reference/root/python/reference_env/verify_reference and frozen original ContextEncoder. Produce context_cases()->list[dict], capture(reference,snapshot,out,*,definition=None,cases=None)->dict. Oracle records platform, original runtime/import proof, exact registered assets/spec/key/tokenizer_revision, IDs/masks, raw vectors, separate preparation/load/inference/RSS. Merge the two independently captured platform results into one fixed oracle before Task3.

1. Write `test_frozen_context_capture_preserves_prefix_raw_vectors_and_lazy_empty`: missing module RED. Use the frozen original tiny graph fixture, explicit helper path/hash; assert raw query/passage difference, exact special/mask IDs, empty history without session load, and corruption rejection. Add test for registration/spec identity and drift.
2. Implement sanitized frozen child capture. Reuse frozen tests/test_context_encoder.py::contextual_model through an explicit generator adapter, then vary private tokenizer copies with CLS/SEP, padding64 and truncation3. Original files unchanged. Generate valid graph and wrong name/dim/dtype/extra row/NaN/Inf/corrupt variants and independent expected outputs.
3. Fix20histories: empty-passages, empty-query, whitespace-query, empty-passage, spanish-query, code-query, unicode-canonical, emoji-and-nul, query-versus-passage, serialized-special-literals, mixed-passages, repeated-history, unicode-whitespace, passage-boundary511/512/513, query-boundary511/512/513, long4097. For raw511/512/513, alpha repeats are509/510/511 for passages and501/502/503 for queries; verify with original tokenizer before truncation. Calls tokens(kind,text),query(text),passages(texts); prepare flag false only for empty-passages.
4. Capture registered histories independently on bothOS with graph/tokenizer hashes fixed. Preserve platform numerical variation and exact known Linux warning. Record core byte pins in a shared runtime manifest, including architecture. No Rust expectation generation.
5. Run `.venv/bin/python -m pytest tests/rust_migration/test_context_reference.py tests/test_context_encoder.py tests/retrieval/test_context_preparation.py -q`; Expected all pass. Verify originals, inspect own diff and commit. task-done uses this command.

### Task 2: Bounded verification and owned native runtime

**Files:** Create crates/ken-models/src/{verified_file,native_onnx}.rs, tests/native_onnx.rs; modify assets.rs, lib.rs and own Cargo manifests/lock; extend tests/assets.rs.

**Interfaces:** Existing ModelAssets::verify stays compatible. Shared regular/bounded reader validates opened regular file, exact declared size/hash, returning owned bytes. `NativeOnnxRuntime::from_json(registration:&str,library:&Path)->Result<Self,ModelError>` declares the current platform entry without loading; clone shares lazy authenticated state. `load()->Result<RuntimeIdentity,ModelError>` exposes actual core identity; internal environment access returns a shared process owner. Different declarations verify their requested files before reusing an equal authenticated identity. No raw native handles escape.

1. Write public-usage RED tests for regular/HFsymlink, wrong size/hash, device/FIFO/nonregular and maximal size; bounded child proves old FIFO block and kills only that child on deadline. Write missing runtime API RED tests, real core mandatory, wrong version/hash/symbol, exact identity reuse, incompatible descriptor, preinitialized API in child and concurrent loads. No skipped native prerequisites.
2. Add pinned dependencies after RED. Use Unix nonblocking open plus opened metadata and bounded exact-size reads; keep this rule with its asset owner. Native core uses verified private copy, dlopen, exact version/GetApi25 and supported set_api. One synchronized owner rejects prior unowned registration/conflicting identity, retains handle even if environment creation fails and unlinks its private copy after dlopen. All unsafe ABI/lifetime obligations documented locally.
3. GREEN: prepared `cargo test --locked -p ken-models --test native_onnx --test assets`, then full prepared `cargo test --locked --workspace`, `cargo fmt --all -- --check`, `cargo clippy --locked --workspace --all-targets -- -D warnings`, original `tests/test_model2vec_backend.py tests/test_context_encoder.py`. Expected no failures/ignores/new diagnostics. Verify originals and commit. task-done runs prepared workspace.

### Task 3: Context model identity, lexical policy and lazy CPU session

**Files:** Create crates/ken-models/src/{context_model,context_encoder}.rs, tests/context_encoder.rs; export real concepts from lib.rs.

**Interfaces:** `ContextModel::from_json(&str)->Result<Self,ModelError>`, read-only assets and compatible identity/spec/key. `ContextEncoder::new(model,owned_snapshot,runtime)->Result<Self,ModelError>`, dim768, `prepare()->Result<(),ModelError>`, `tokenize(text:&str,kind:ContextInput)->Result<ContextTokens,ModelError>`, embed_query/ embed_passages with the existing owned vector shapes. ContextInput Query/Passage and ContextTokens IDs/attention_mask are explicit. Empty passages never loads a session; missing runtime in this call must still succeed.

1. Write all fixture and mandatory registered-model RED tests through these callers. Cover exact identity, prefix/special/Unicode/serialized-policy override, all six boundaries, long text, raw non-unit outputs, ordering, independent vectors, repeats/concurrency and all graph/input/output errors. Missing assets must fail, never skip.
2. Implement tokenizer-owned policy and one lazy Mutex session. Consume only owned verified graph/tokenizer bytes, CPU2/1, I64[1,L], exact sentence_embedding[1,768]F32finite. Query prefix has one authoritative home. No L2, term cache or inherited provider selection. Report compatible original identity separately from actual Rust/core.
3. GREEN targeted fixture/real tests, all original contextual tests, full prepared workspace, fmt/clippy. Verify originals; commit. task-done runs prepared workspace.

### Task 4: Source-bound native process and complete platform proof

**Files:** Create examples/context_probe.rs, tools/rust_migration/{context_compare,context_validate}.py, tests/rust_migration/test_context_{compare,validate}.py, migration_tests/test_context_parity.py; update own CI, guide and public m2-context evidence.

**Interfaces:** Stdin explicitly names model registration/snapshot, runtime declaration/library and cases. Probe returns actual asset/core hashes, compatible identity, tokens/masks, raw vectors and separate preparation/load/inference/peak data. Comparator executes owned copies outside checkout; matrix validates current source/cases/oracle/runtime manifest/registration plus platform-specific exact core hash. Compose table18gates and context_release/context_parity=20. Migration process tests require explicit KEN_CONTEXT_PROBE and prepared model/core paths.

1. RED comparator/binding/matrix tests: wrong platform golden, IDs/mask/vector/NaN/zero/shape/type/runtime/core hash, stale/missing executable, unknown stderr and missing cases all rejected. Real process integration plus false executable/corrupt requests. Observe failure before implementation.
2. Implement actual probe, outside-checkout comparison and release binding after fresh build; selected executable, built release and parity hash must match. No child from Rust. Audit executable and core libraries/Cargo; actual Linux strace exactly1exec. Preserve stderr, allowing only the calibrated exact Linux CPU-vendor line/count. Other profiles retain strict silence.
3. Run new tooling/process tests plus all required original tests and prepared workspace. Then freeze sources during complete bothOS gates: full Python exact-ID baseline, full Rust/fmt/clippy, all prior parity/benchmarks, original1066/frozen hashes,20context histories and phase measurements. Never reuse old-source acceptance. Retain every attempt and every measurement; no invented speedup/SLA.
4. Publish matching platform receipts and matrix. One fresh whole-plan review per executing-plans with all6ReviewFocus lines; regrade by effect; one TDD pass for Important/Critical, no re-review. Defer Minors. Commit own results; task-done runs printed complete matrix assertion. Accept context only, continue remaining M2 models/data.

## Preflight and self-review

T1 fixed fixtures/runtime/cases/oracle feed T2–T4; T2 lazy runtime/verified bytes feed
T3 without public unchecked handles; T3 public inputs/outputs feed T4. Platform
core hashes differ but their shared manifest/oracle/case fingerprints do not.
Compatible original metadata does not claim Rust runs NumPy. Extra-row rejection
is the explicit corruption guard declared in the spec. The user authorized the
full migration; this is the next scoped plan, not a request to stop after M1/M2.
