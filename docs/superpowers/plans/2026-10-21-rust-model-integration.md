# Native model acquisition and integration implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:executing-plans inline. The user authorized continuous native execution with no confirmation pauses. Checkboxes describe verifiable steps.

**Goal:** Resolve pinned public data and existing compatible profiles into the correct lazy native model, then close the remaining M2 integration gate.

**Architecture:** `ArtifactCache` owns verified atomic publication, `PublicModelTransport` owns HTTPS, profile types own compatible identity, and `ModelFactory` composes existing backends. No inference math moves into the factory.

**Tech Stack:** Rust1.95, existing locked serde/sha2/ring/tempfile and ureq3.4.2 with rustls; current verified ONNX/Torch/MLX/CT2 backends.

**Spec:** [Native model integration](../specs/2026-10-21-rust-model-integration-design.md), under the approved general migration and M2 runtime contracts.

## Global Constraints

- Begin implementation only after the transformer plan's final review and repair pass close. Documentation may overlap its immutable final gates.
- Preserve all originals, user changes, frozen references and historical proofs; no entrypoint replacement, push or merge.
- Public pinned data only; no credentials, remote code or Python product runtime. Offline performs no network operation.
- Streaming buffer64KiB; redirects10; connect15s/read-inactivity60s/total3600s per artifact. Exact registered sizes/hashes; no tolerance or inference-budget changes.
- Atomic publication on one filesystem; staging0700; interruption/corruption never publishes a ready cache. Remove only owned temporary directories.
- Preserve compatible profile hashes separately from actual native runtime identity. Do not rewrite an existing project pin.
- Meaningful RED→GREEN per change, scoped commits, one final fresh review and one Important/Critical repair pass. No per-task reviewer loops.
- Run focused tests during implementation; run the full regression suite once on the final coherent candidate. Reuse unchanged neural proofs only with exact relevant source/module/host bindings and fresh semantic replay.

## Review Focus

1. A model ID with `.` or `..`, a cache symlink or a concurrent publication cannot escape the cache root or overwrite unrelated files; Task2 tests actual files and races.
2. Truncated/chunked/overlong HTTP responses and redirects never publish partial data or leak authorization; Task3 tests a real local server and bounded streams.
3. Compatible configuration hashes must include every nested optional profile/runtime field without inventing an installed Python package; Task1 compares independently captured original values.
4. Concurrent cold calls and failed preparation cannot publish a partial encoder or select a different family; Task4 exercises real native initialization, repair and explicit device policy.
5. A factory can appear numerically correct while using the wrong source revision, role or projection identity; Task5 binds the factory's actual model/runtime and stored space to the original and rejects mutations.

## Interfaces and file responsibilities

| Files | Owner |
| --- | --- |
| `crates/ken-models/src/profile.rs`, `profile_identity.rs` | Original profile validation, serialization and compatible hashes |
| `crates/ken-models/src/artifact_cache.rs` | Private staging, verification, publication, offline resolution |
| `crates/ken-models/src/model_transport.rs` | Public HTTPS and transport limits |
| `crates/ken-models/src/model_catalog.rs` | Registered model/role selection |
| `crates/ken-models/src/model_factory.rs`, `managed_encoder.rs` | Explicit resources, lazy construction and public encoder use |
| `crates/ken-models/tests/{profile_identity,artifact_cache,model_transport,model_factory}.rs` | Public behavioral contracts |
| `tools/rust_migration/integration_{reference,compare,validate}.py` | Original capture, external native calls and integration evidence |
| `crates/ken-models/examples/model_integration_probe.rs` | Actual product factory consumer, no expected-output input |
| `tests/rust_migration/test_integration_{reference,compare,validate}.py` | Malformed/stale/resealed evidence rejection |
| `integration_migration_tests/test_models.py`, CI and `docs/rust-migration.md` | Complete integration gate and usage |

### Task 1: Compatible profile identities

**Consumes:** Original `src/ken/retrieval/profile.py`, its tests, frozen reference and `assets::python_json`; no SDK is needed.
**Produces:** `EncoderSpec`, `JointRanking`, `EvidenceRanking`, `ContextualRetrieval`, `RetrievalProfile`, `LegacyRuntimeIdentity`, and original-only immutable identity fixtures.

- [ ] Capture original `to_dict`, `key`, `tokenizer_revision`, `vector_revision("identity"/"behavior")` and `fingerprint` for static, Potion, Torch, MLX, provided, joint, evidence versions1/2/3, contextual and source-view profiles. Include Unicode identifiers and absent optional keys. Record actual package versions and source hashes in each capture; input options never contain expected digests.
- [ ] Write `profile_identity.rs` public tests comparing those literal captures; add wrong revision/backend/dtype, zero budgets, inconsistent contextual/view versions, joint+evidence conflict and representation2 upgrade cases. Run `cargo test --locked -p ken-models --test profile_identity`; expected RED before exports/types exist.
- [ ] Implement `EncoderSpec::from_json(&str)->Result<Self,ModelError>`, `RetrievalProfile::from_json(&str)->Result<Self,ModelError>`, `RetrievalProfile::from_json_with_upgrade(&str,bool)->Result<Self,ModelError>` and `to_json()->Result<String,ModelError>`. Port the observed original defaults and validations exactly.
- [ ] Implement `LegacyRuntimeIdentity::from_json(&str)->Result<Self,ModelError>` for `ken-legacy-runtime/1`: ordered backend version pairs plus ordered evidence/contextual pairs. Reject missing/duplicate package declarations; a literal original `unavailable` remains an explicit version value. It describes a compatibility input, not actual native linkage.
- [ ] Implement `EncoderSpec::{key,tokenizer_revision}(&LegacyRuntimeIdentity)->Result<String,ModelError>` and `RetrievalProfile::{fingerprint,vector_revision}(...)->Result<String,ModelError>` (`vector_revision` also takes `view:&str`). Use the existing Python JSON codec; assert exact captured bytes/digests and changes on runtime/dtype/budget mutations.
- [ ] Run the complete profile identity test target and focused capture-tool tests GREEN; commit only Task1 paths with `feat(models): preserve compatible retrieval profile identities`.

### Task 2: Verified atomic artifact cache

**Consumes:** Existing `ModelAssets`, bounded `verified_file` operations and Task1 identities only for caller context.
**Produces:** `ArtifactRequest { model_id, revision, name }`, `ArtifactTransport::open(&self,&ArtifactRequest)->Result<Box<dyn Read+Send>,ModelError>`, `AcquisitionPolicy::{Offline,Public}`, `ArtifactCache::new(root:&Path)->Result<Self,ModelError>` and `resolve(&self,assets:&ModelAssets,policy:AcquisitionPolicy,transport:&dyn ArtifactTransport)->Result<PathBuf,ModelError>`.

- [ ] Write `artifact_cache.rs` tests with real files/Read implementations: complete publication, zero-byte registered artifact, nested path, missing offline data without calling transport, wrong size/hash, overlong first extra byte, interrupted stream/write, corruption on reuse, two concurrent successful publishers and failed loser preserving the winner. Assert no partial ready directory and no leftover owned stage.
- [ ] Add model IDs with `.`/`..` components and an unrelated sentinel; the digest-based cache path must stay confined. Reject cache-root/final/staging directory substitutions with symlinks; borrowed HF blob symlinks remain accepted by the existing verifier. Run target RED.
- [ ] Implement only cache coordination. Use `models/<assets.fingerprint()>/<assets.revision()>`, create-exclusive files,64KiB streaming hashes, fsync and atomic rename. Reverify a race winner. Return an existing corruption error without deleting that snapshot. Offline exits before transport invocation.
- [ ] Keep `ModelAssets` authoritative for declarations and `VerifiedModelFiles` authoritative for private inference copies. Add a focused internal streaming writer helper only if the current copy primitive cannot consume a network `Read`; use the same verification owner rather than a second hash rule.
- [ ] Run `cargo test --locked -p ken-models --test artifact_cache` and existing asset/file ownership targets GREEN; commit `feat(models): acquire verified model snapshots atomically`.

### Task 3: Bounded native public transport

**Consumes:** Task2 transport interface and the existing pinned ureq3.4.2 source/API.
**Produces:** `PublicModelTransport::new()->Result<Self,ModelError>` implementing `ArtifactTransport`; test transport endpoint configuration stays private to tests.

- [ ] Read the locked ureq configuration/streaming/TLS APIs. Write real local-server tests for successful streaming,404/500, Content-Length mismatch, chunked truncation, oversize, timeout, redirect limit and request headers. Assert public requests contain neither Authorization nor Cookie; native request URL contains the exact immutable revision and registered artifact name.
- [ ] Run `cargo test --locked -p ken-models --test model_transport` RED. Implement public HF URLs and HTTPS-only redirects with the spec's fixed limits. Disable credential sources and ambient authorization/proxy behavior. Do not buffer complete weights or auto-decompress registered bytes.
- [ ] Enable only existing locked ureq rustls dependencies in `ken-models/Cargo.toml`; preserve versions and lockfile semantics. Public invalid model/revision/name errors occur before any connection. Local HTTP is available only through the private test constructor.
- [ ] Run all transport/cache tests GREEN. Execute a Rust external probe downloading one small actual pinned public tokenizer/config artifact into a fresh project-local cache, then repeat offline with network-disabled transport and compare hashes. Record exact URL/revision/bytes/digest, process/dependency audit and cleanup; no credentials.
- [ ] Commit `feat(models): stream pinned public model data natively`.

### Task 4: Lazy factory and backend composition

**Consumes:** Task1 profile types, Tasks2/3 acquisition, `ModelPolicy`, all accepted native backend constructors and prepared resource paths.
**Produces:** `ModelCatalog::built_in()->Result<Self,ModelError>`, `ModelFactory::new(catalog:ModelCatalog,cache:ArtifactCache,resources:PreparedModelResources,policy:AcquisitionPolicy)->Self`, `encoder(&self,spec:&EncoderSpec,legacy:&LegacyRuntimeIdentity)->Result<Arc<ManagedEncoder>,ModelError>` and `legacy_encoder(&self,name:&str)->Result<Arc<ManagedEncoder>,ModelError>`.

`PreparedModelResources` contains explicit source overrides, bundled NPZ path, ONNX registration/library and optional Torch/MLX registration/module/core paths. It declares resources without opening them. `ManagedEncoder` exposes `is_prepared(&self)->Result<bool,ModelError>`, `dim(&self)->Result<usize,ModelError>`, `token_count(&self,text:&str)->Result<usize,ModelError>`, `embed_query(&self,text:&str)->Result<Vec<f32>,ModelError>` and `embed_passages(&self,texts:&[&str])->Result<Vec<Vec<f32>>,ModelError>`.

`ModelFactory::judge(&self,spec:&EncoderSpec,legacy:&LegacyRuntimeIdentity)->Result<Arc<RelevanceJudge>,ModelError>` creates the existing registered Torch/MLX judge. `context(&self)->Result<Arc<ContextEncoder>,ModelError>`, `reranker(&self)->Result<Arc<OnnxReranker>,ModelError>` and `expansion(&self)->Result<Arc<LocalQueryExpansion>,ModelError>` compose their existing prepare/constructor APIs using the exact current built-in registrations. These objects retain their separate public responsibilities; no common tensor executor is introduced.

- [ ] Write outside-in tests through the public factory before implementation: cold declaration works with absent optional SDKs; all registered names choose their actual family/role; unknown/provided-without-injection/wrong revision fail; Potion fingerprint64 and upstream revision40 remain distinct; static NPZ SHA must match. Run RED.
- [ ] Add actual tiny-model tests for concurrent first use, failed load then repair, borrowed-source removal after successful ownership, wrong native core and exact empty/dimension/count policies. Use existing real tiny archives and backend fixtures; no test-only failure method in a product class.
- [ ] Implement catalog selection and focused lazy adapter owners. The catalog binds compatible original version sets to the accepted backend proof; reject an arbitrary unaccredited legacy runtime before using its vectors in an existing space. Add a test changing one declared package version while keeping the model weights valid. Reuse each encoder's lexical/device/fallback policy. Add lazy Potion/NPZ wrappers preserving their original load behavior; do not change mathematical code. Cache at most4 profile owners keyed by the complete compatible spec/runtime plus prepared resource context; evict only the factory reference, allowing live callers to keep their owner.
- [ ] Route source acquisition before existing preparation, including native Ettin head compilation and translation normalization. Retain separate errors and roles. Avoid loading/downloading unused families; a failed backend never selects another family.
- [ ] Run all factory/cache/profile targets plus current relevant Rust backend tests GREEN. Record exact changes to legacy probe source identities when new modules are added and retain the current compiled-inventory regression. Commit `feat(models): compose lazy native model factories`.

### Task 5: Both-platform M2 integration acceptance

**Consumes:** All earlier task APIs and immutable accepted model/storage proofs.
**Produces:** Fresh source-bound macOS/Linux integration receipts and an independently replayable M2 matrix, with scope-specific previous proofs retained.

- [ ] Write corruption/reseal tests for missing family/role, wrong profile revision/runtime, false offline claim, changed source/native module and missing storage/core proof. Run `pytest tests/rust_migration/test_integration_*.py -q` RED; implement capture/compare/validation tooling without accepting flags in place of raw observations.
- [ ] Implement the external native probe using the actual `ModelFactory`. Inputs specify requested public calls and explicit resources, never expected outputs. Capture factory-selected family, compatible identity, actual runtime identity, source preparation and outputs/errors. Execute outside checkout with sentinel PATH and both `execve`/`execveat` audit on Linux.
- [ ] On each platform run representative public factory calls for every family, all registered profile dtype/device selections, concurrent lazy ownership and offline acquisition/preparation. Compare to the approved original and direct backend behavior. Reuse existing complete neural observations only for unchanged numerical dependency/module/host inputs; explain the reused scope in the receipt. New factory paths get actual executions.
- [ ] Freeze the final source candidate once. Run fmt/clippy/workspace/native tests, complete Python regression, original guards and storage recovery. Run current integration groups without skips; check raw log counts and exact failures. Do not repeat unchanged full neural matrices merely to change artifact paths or evidence tooling.
- [ ] Publish immutable source/model/runtime/command/hash/log/capacity evidence under `docs/validation/rust-migration-2026-10-21/m2-integration/`; replay the complete matrix normally and with isolated NumPy2.4.4. Every tamper control must reject. Mark M2 accepted only when the previous storage/model receipts and this integration all pass, then continue M3.
- [ ] Commit only owned paths and run task-done with the full integration matrix assertion. Request ONE fresh whole-plan review with the five Review Focus lines and ledger rulings. Re-grade by user effect, perform one TDD Important/Critical repair pass with a green suite, and record minors and decisions before cleaning only this plan's workspace.

## Preflight and self-review

Task1 owns compatibility types consumed by Task4; Task2 owns the transport request
and cache consumed by Tasks3/4; Task4 uses existing backend constructors rather
than changing their ABI. The profile/runtime identity is data, while runtime
observations remain separate evidence. Existing cache corruption never authorizes
deleting an unrelated cache. All five Review Focus conditions have explicit tests.
No implementation is authorized to change neural tolerance, delete originals or
call M3 complete from this M2 plan. Native execution and no confirmation pauses
were already selected by the user.
