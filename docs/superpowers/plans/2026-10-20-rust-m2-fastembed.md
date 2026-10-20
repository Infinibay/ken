# Native FastEmbed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The user selected native inline execution and continuous work without confirmations. Steps use checkbox (`- [ ]`) syntax for tracking. No implementer/reviewer per task; one fresh whole-plan review at the end.

**Goal:** Execute the original 30-model FastEmbed catalogue natively with equivalent CPU vectors, exact tokenization, safe ownership of large model files and reproducible both-platform proof.

**Architecture:** `ModelAssets` remains the artifact authority and gains a streamed private-file owner without changing memory snapshots. A registered model composes tokenization, output pooling and an ONNX session; the encoder owns lazy serialized coordination. Validation freezes real original behavior before product code, then composes the accepted storage31 chain with three new gates.

**Tech Stack:** Rust1.95.0/edition2024, existing tokenizers0.22.2, ORT2.0.0-rc.14/API25 and native ORT1.25.1, serde/sha2/tempfile/libc already pinned. Add only CUDA/ROCm binding features to the existing ort dependency when implementing providers; retain API25. Python3.12.9/FastEmbed0.8.0/NumPy2.4.4/tokenizers0.22.2/ORT1.25.1 are the original validation runtime.

**Spec:** `docs/superpowers/specs/2026-10-20-rust-fastembed-design.md` (initial commit7da059ea).

## Global Constraints

- Preserve all1066original hashes, user dirt, installed entrypoints and persistent data; no source deletion, hidden Python runtime or reembedding/relabeling.
- Existing identity/profile/pin contracts remain unchanged; actual Rust/runtime identity is separate from compatible original producer metadata.
- All30catalogue entries and five original implementation families count. CPU required on macOS arm64 and Linux aarch64. GPU numerical proof only where hardware/provider actually exists; availability/failure/CPU fallback paths are still implemented and tested.
- T1 established one precise existing CPU initialization failure on BOTH: `jinaai/jina-embeddings-v2-base-de`/revision`3f9eede875721714945b6a99a3198299243cf2be`, graph`onnx/model_fp16.onnx` SHA`e039ce538df36cb7ecee6bb88aacf0699227277be769a8e9adb5da719d23c571`, ORT Fail/GetIndexFromName/InsertedPrecisionFreeCast/SimplifiedLayerNormFusion. All300cases still execute. Only this bound failure may have error/traceback/attempt/state receipts in place of nonexistent vectors; other failures reject. Native requests contain no expected-error switch; the real runtime must independently fail and remain retryable. See spec's observed-baseline section. Successful cases retain all numerical/token checks; no gate or test is skipped.
- Exact IDs/masks/types/shapes/order/prompts/valid metadata; finite F32 vectors satisfy `abs(error)<=1e-6+1e-6*abs(reference)`. Do not widen this after a failure.
- Original batch256 and remainder order; chunk text before tokenization. Truncate right/longest-first/stride0 using actual config bounds77/128/256/512/8192/8194; preserve existing padding and special-token insertion order.
- CLS/2D+L2 uses F32; masked mean uses F64 after F32*I64 promotion, optional F64 L2, then final F32. Raw CLIP stays raw; Jina task_id is scalarI64=1 for both sides.
- Product session defaults match original threadsNone/ORT0/0 and ORT_ENABLE_ALL. Prototype2/1 is not the product policy. Reject nonfinite intermediates instead of false-zero overflow.
- Construction/empty batch do not load weights/runtime; failed preparation is retryable; serialize the complete batch request and return owned results.
- Model source files can be HF blob symlinks but opened inodes must be regular. Owned copies are new files, source-independent, with private0700directories/read-only data; keep them alive through session destruction. Audit external ONNX paths/ranges before session creation.
- Preserve all31old gates/deadlines/baselines, no new skips/ignored tests/typing errors. Precompile before unchanged runtime gates; CARGO_INCREMENTAL=0. Do not assume a source tree/installed library is verified from its version string alone.
- User continuous/no-confirmation instruction supersedes approval handoffs; still write/review spec and plan, use TDD, record rulings/costs and verify before advancing. No push/merge/deployment is implied.

## Review Focus

1. A real external initializer hidden in attributes/functions/sparse tensors or an overflowed range must not read outside the privately owned declared files (Task2).
2. A changed source after preparation, a failed large copy, FIFO/device or premature file-owner drop must not alter vectors, hang or leak a ready state (Tasks2/5/6).
3. Serialized padding/special order, shorter config bounds, mixed batch257 with a long final item, and F64 promotion/cast timing must preserve actual tokens/vectors (Tasks1/3/5).
4. First use, concurrent requests, GPU availability without usable construction and failed CPU retry must not cross results or misreport readiness/device (Tasks4/5/6).
5. Wrong dimensions/extra rows/nonfinite output, stale model/source/binary fingerprints or re-sealed altered compressed proof must not certify compatibility (Tasks3/5/7).

## File map and interfaces

| Owner | Files | Responsibility |
| --- | --- | --- |
| Original corpus | `tools/rust_migration/fastembed_{catalog,reference,reference_child}.py` | Actual catalogue, immutable source validation and original-process observations |
| File ownership | `crates/ken-models/src/file_assets.rs` | `ModelFileSource` and `VerifiedModelFiles`, streamed private copies |
| ONNX dependencies | `crates/ken-models/src/onnx_dependencies.rs`, existing `onnx_wire.rs` | Bounded wire traversal and declared external-file closure |
| Model/token/pooling | `fastembed_model.rs`, `fastembed_tokens.rs`, `embedding_pool.rs` | Independent declarations, lexical policy, arithmetic |
| Provider/session | `onnx_providers.rs`, `fastembed_session.rs` | Real provider construction/fallback and one owned session/batch |
| Encoder | `fastembed_encoder.rs`, `lib.rs` | Lazy serialized public use/reexports |
| Process proof | `examples/fastembed_probe.rs`, `tools/rust_migration/fastembed_{compare,ownership}.py` | Real text-to-vectors and external source-mutation controller |
| Acceptance | `fastembed_{validate,evidence}.py`, existing preparation/validator chain | Complete current34gate and33fingerprint proof |

Public Rust contracts to implement:

```rust,ignore
ModelFileSource::new(snapshot: &Path, private_parent: &Path) -> Result<Self, ModelError>;
ModelAssets::verify_files(&self, source: &ModelFileSource) -> Result<VerifiedModelFiles, ModelError>;
VerifiedModelFiles::fingerprint(&self) -> &str;
VerifiedModelFiles::read(&self, name: &str) -> Result<Vec<u8>, ModelError>;
// Its registered artifact path accessor stays crate-private for native loading.
FastEmbedModel::from_json(json: &str) -> Result<Self, ModelError>;
FastEmbedModel::dim(&self) -> usize;
FastEmbedModel::assets(&self) -> &ModelAssets;
FastEmbedModel::source_id(&self) -> &str;
FastEmbedModel::source_revision(&self) -> &str;
FastEmbedCatalog::from_json(json: &str) -> Result<Self, ModelError>;
FastEmbedCatalog::model(&self, name: &str) -> Result<&FastEmbedModel, ModelError>;
FastEmbedDeviceRequest::from_inputs(preference: Option<&str>, raw_ids: Option<&str>) -> Self;
FastEmbedEncoder::new(model: FastEmbedModel, source: ModelFileSource,
    runtime: NativeOnnxRuntime, device: FastEmbedDeviceRequest) -> Result<Self, ModelError>;
FastEmbedEncoder::prepare(&self) -> Result<(), ModelError>;
FastEmbedEncoder::is_prepared(&self) -> Result<bool, ModelError>;
FastEmbedEncoder::dim(&self) -> usize;
FastEmbedEncoder::device(&self) -> Result<FastEmbedDevice, ModelError>;
FastEmbedEncoder::tokenize(&self, texts: &[&str], kind: FastEmbedInput)
    -> Result<Vec<FastEmbedTokens>, ModelError>;
FastEmbedEncoder::embed_queries(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, ModelError>;
FastEmbedEncoder::embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>, ModelError>;
FastEmbedEncoder::embed_details(&self, texts: &[&str], kind: FastEmbedInput)
    -> Result<FastEmbedRun, ModelError>;
```

`FastEmbedInput={Query,Passage}`; `FastEmbedDevice={Unknown,Cpu,Gpu}`.
`FastEmbedTokens` owns `shape:[usize;2]`, flat `ids:Vec<i64>` and `attention_mask:Vec<i64>`.
`FastEmbedRun` owns vectors, actual per-batch input tensors/output shapes/dtype,
provider/preparation report and artifact/model fingerprints; it never retains or
clones the full hidden tensor solely for diagnostics. `embed_*` extracts vectors
from the same internal operation. Source/definition/compatible identity and
actual native execution are separate fields.

Detailed result fields: `FastEmbedRun { vectors:Vec<Vec<f32>>,
batches:Vec<FastEmbedBatchTrace>, preparation:FastEmbedPreparation }`;
`FastEmbedBatchTrace { inputs:BTreeMap<String,FastEmbedTensorI64>,
output_shape:Vec<usize>, output_dtype:String }`;
`FastEmbedTensorI64 { shape:Vec<usize>, values:Vec<i64> }`.
`FastEmbedPreparation` contains `device`, `configured_providers:Vec<String>`,
`attempts:Vec<FastEmbedProviderAttempt>`, `runtime:Option<RuntimeIdentity>`,
`model_fingerprint:String`, `declared_artifacts_fingerprint:String`,
`verified_artifacts_fingerprint:Option<String>` and `notices:Vec<FastEmbedNotice>`.
An attempt has `providers:Vec<String>`/`error:Option<String>`; a notice has
`kind:String`/`message:String`. Do not label declared bytes verified before copying.
`EmbeddingBatch` is `{ vectors:Vec<Vec<f32>>, trace:FastEmbedBatchTrace }`.
Model/catalog definition fingerprints are native declarations, not replacements
for compatible original identity keys.

The catalogue JSON is `{"format":"ken-fastembed-catalog/1","models":[...]}`.
Each model has exactly `format="ken-fastembed-model/1"`, `name` (public model
name), `assets` (existing ModelAssets declaration), `graph`, `dimension`,
`pooling`, `task_id` and `advisories`. Advisory records have `kind` and exact
`message`; they preserve original model-update/mean-pooling notices separately
from actual runtime diagnostics. All nested artifact duplicate checks still run
on original raw JSON. Registry lookup follows original case-insensitive names;
source/cache layout belongs to callers, not the model declaration.

Python contracts: `capture_fastembed(reference:Reference,sources:Path,registry:Path,out:Path)->dict`,
`compare_fastembed(reference,prepared,out)->dict`, `verify_fastembed_ownership(reference,prepared,out)->dict`,
`PreparedNativeFastEmbed(probe:Path,sources:Path,registry:Path)`,
`fastembed_environment(prepared=None)->dict`, `aggregate_fastembed(directory,expected_fingerprints=None)->dict`.
`capture_fastembed` has a CLI with `capture --reference PATH --sources PATH
--registry PATH --out PATH`. `fastembed_validate` uses `--scope local|matrix`
and the same explicit prepared/base arguments as storage, adding
`--fastembed-probe/--fastembed-sources/--fastembed-registry`; matrix uses
`--platform-receipts PATH --out PATH`.

### Task 1: Freeze the real original catalogue and CPU corpus

**Files:** create original-corpus files above, `tests/rust_migration/test_fastembed_reference.py`,
`crates/ken-models/resources/fastembed-catalog.json`,
`docs/validation/rust-migration-2026-10-20/m2-fastembed/{cases.json,reference-index.json,reference-{macos,linux}/...}`.
**Interfaces:** produces30versioned definitions and300ordered original case IDs with per-model compressed raw records; no product Rust code.

- [ ] RED `test_catalog_captures_all_original_families_and_revisions`: assert30unique case-insensitive names, family counts13/1/9/6/1, immutable40hex revisions, actual verified sizes/SHA for every graph/additional/config file. `test_original_cases_have_no_native_expected_payload` rejects native-expected/source-setup flags.
- [ ] Run `.venv/bin/python -m pytest tests/rust_migration/test_fastembed_reference.py -q`; expected missing module/functions before implementation.
- [ ] Implement source preparation/capture. Reuse the already verified six representative files/config data where bytes match; acquire remaining registered public data inside `.ken/rust-migration/m2-fastembed`, verifying every byte. Current metadata alone cannot certify downloaded weights. Frozen Ken imports and complete installed FastEmbed Python-source provenance are checked before/after; retain exact Python/NumPy/tokenizers/ORT/FastEmbed versions.
- [ ] Execute the unchanged frozen `OnnxEmbedder` in a fresh original child per model. Cold empty observation precedes importing FastEmbed/ORT for instrumentation. Constructor adapter adds only verified local asset location/offline mode; it does not change threads, providers, math or implementation classes. Observe real ORT feeds/options/output shapes and final F32 vectors, `_model`, `device`, `_dim`, warnings and errors. Capture all source paths/hashes; no mock inference.
- [ ] Ten cases per model: `empty_cold_passages`, `mixed_queries`, `mixed_passages` (empty/space/ASCII/español/combining/emoji/Japanese/literal specials), `repeat_queries`, `length511`, `length512`, `length513`, `batch256`, `batch257`, `empty_warm_queries`. Batch257 is256short passages followed by one513-word passage, exposing chunk-before-padding behavior. Capture all29tokenizers additionally at their context bounds without loading full networks for each lexical boundary.
- [ ] RED/GREEN `test_dimension_correction_is_narrow_and_vector_preserving`: actual CLIP512/Jina1024 vectors while original API stays384; record this as declared correction, not a relaxed comparator. Require actual raw graph dtype F32 for the registered corpus; resolve a contrary observation in the spec before product code. Preserve source update/mean-pooling advisories as notices, not omitted stderr.
- [ ] Freeze BOTH actual original captures only after strict schema/source/case validation; no Rust expected values are in future requests. Store F32 LE hex, lossless deterministic gzip chunks with raw/compressed hash+size, max16MiB uncompressed per model. Synthetic unit receipts are explicitly synthetic and cannot publish acceptance. Run the focused tests GREEN and original1066verification; commit only these owned files.
- [ ] Include the observed bound FP16 baseline: capture all eight failing nonempty attempts per platform, cold/warm-empty laziness and unchanged retryable state; preserve complete messages/tracebacks/options. Reproduce twice per platform without session/inference hooks. Reject a different model/revision/hash/error signature. Later native parity exercises exactly the same texts and real runtime failure, with no numeric waiver for successful outputs.

### Task 2: Own large verified files and validate ONNX dependency closure

**Files:** create `src/file_assets.rs`, `src/onnx_dependencies.rs`, tests `file_assets.rs`/`onnx_dependencies.rs`; modify `assets.rs`, `verified_file.rs`, `onnx_wire.rs`, `lib.rs` only as required.
**Interfaces:** public file-owner contracts above; crate-private `verify_dependencies(graph:&Path,files:&VerifiedModelFiles)->Result<(),ModelError>`. Preserve `verify()->VerifiedSnapshot`, its fingerprint and all current callers.

- [ ] RED `private_copy_survives_source_replacement_and_drops_its_files`: fixture revision40ones/`weights.bin=b"abc"`, source changes to`abd` after verification; owned read remains`abc`, fingerprints equal, source change cannot affect it; private0700/read-only copies and lifetime cleanup asserted. Add symlink/device/FIFO/size/hash/failed-copy tests; retain existing `assets` assertions.
- [ ] Run prepared native `cargo test --locked -p ken-models --test file_assets --test onnx_dependencies`; expected missing public types/modules.
- [ ] Implement streamed copying through the same opened-regular-file guard. Factor `verified_file::open_regular` and checked hash/copy helpers so FIFO/device and size rules have one home; do not duplicate or weaken the current guard. Constructor paths are explicit absolute locations, lazy/no weight read. Unknown artifact access rejects. Do not use hardlinks to source, Rust file mappings or unsafe static lifetimes.
- [ ] Exercise mid-copy source truncation through a private generic Write barrier around a real destination file, then require size/hash failure and cleanup. This is ordinary I/O instrumentation in tests, not a product failure switch. Snapshot/data source identity remains the original ModelAssets fingerprint.
- [ ] Add bounded Read+Seek protobuf traversal, reusing wire-varint validation. Skip tensor payloads without allocating their length. Traverse Model graph7/training20/functions25; Graph node1/initializer5/sparse15; Node attr5; Attr tensor5/graph6/tensors10/graphs11/sparse22/23; Sparse values1/indices2; Training graphs1/2; Function nodes7/attrs11; Tensor external13/data_location14. Schema source is installed ONNX1.20.1.
- [ ] RED/GREEN `nested_external_references_cannot_escape_owned_artifacts`: graph/attribute/function/sparse/training references with absolute/`..` paths, unknown location, duplicate keys, unsupported basepath, negative/overflow/out-of-file ranges, malformed/truncated wire, depth>64 and >1,000,000fields reject before session creation. Registered files/names/offsets remain valid. Reuse one varint decoder; assert existing byte-backed field/rewrite outputs unchanged.
- [ ] Run existing `--test assets`, new tests, reranker-preparation tests and strict Clippy. Measure a real multi-GiB copy with bounded buffers, source unchanged, cleanup after failure; commit the independently testable file owner.

### Task 3: Register models and implement exact lexical/arithmetic policy

**Files:** `fastembed_model.rs`, `fastembed_tokens.rs`, `embedding_pool.rs`, `lib.rs`; tests `fastembed_model.rs`, `fastembed_tokens.rs`, `embedding_pool.rs`.
**Interfaces:** model/catalog contracts above. Four pooling modes: `cls_or_sentence_l2`, `mean`, `mean_l2`, `raw`; `task_id:Option<i64>` is absent or scalar1. Token batch owns IDs/mask; type IDs are generated as zeros only for session inputs that require them. Reuse `model_policy::prompts_for`.

- [ ] RED model/schema tests:30entries, case-insensitive lookup/order, source HF ID distinct from public name, graph declared, positive integer dim, strict enum/task/unknown/duplicate fields and nested artifact duplicate rejection. Native definition fingerprint must not replace a legacy EncoderSpec/profile identity.
- [ ] Run the new focused Rust tests; expected absent APIs.
- [ ] Implement declarations retaining raw nested artifact JSON until `ModelAssets::from_json` validates it, avoiding duplicate-key loss through `Value`. Implement config tokenization from verified4JSON without loading weights/runtime: preserve special-map order, string vs AddedToken default flags, ignored other value types, serialized padding, right/longest-first/stride0 truncation. Select minimum numeric bound before checked conversion; load only registered config files through the artifact authority.
- [ ] RED/GREEN exact original token comparisons for all29tokenizers, context77/128/256/512/8192/8194, unequal config bounds, fixed/longest padding, string/dict/list specials, literal tokens, Unicode and malicious JSON. Chunk text first, then tokenize each256; assert batch257 short-prefix input shape is not padded to the last long item's length.
- [ ] RED/GREEN arithmetic tests: CLS `[3,4]→[0.6,0.8]`; raw `[3,4]` unchanged; masked/zero-mask cases; F32`[1e10,1,-1e10]` masked mean retains F64`1/3` before F32; original frozen late-cast normalized bits; shapes/extra rows/NaN/Inf/overflow norm reject. No premature F32 mean or added normalization.
- [ ] Run all new tests plus existing lexical/static/context/translation-policy tests and strict Clippy. Commit these model/token/pool components; no inference acceptance yet.

### Task 4: Prepare real ONNX sessions with provider fallback

**Files:** `onnx_providers.rs`, `fastembed_session.rs`, exports; Cargo ort CUDA/ROCm features only; tests `onnx_providers.rs`, `fastembed_session.rs`.
**Interfaces:** `EmbeddingSession::prepare(model:&FastEmbedModel,files:Arc<VerifiedModelFiles>,runtime:NativeOnnxRuntime,request:&FastEmbedDeviceRequest)->Result<Self,ModelError>`; `run(&mut self,batch:&FastEmbedTokens)->Result<EmbeddingBatch,ModelError>`. `EmbeddingBatch` owns vectors and actual input/output/provider metadata, not the full hidden output.

- [ ] RED provider tests pin CPU, auto/gpu/cuda/unknown preference normalization, CUDA→ROCm→CPU order, invalid IDs vs empty IDs and the original ignored explicit-provider IDs. Original helper facts are distinct from actual numerical GPU proof.
- [ ] Run focused tests to observe absent session/provider functions.
- [ ] Implement real API25 session creation after dependency audit, ORT_ENABLE_ALL/default0/0threads; use the existing runtime owner/environment. A GPU construction failure discards partial builder/session and retries CPU; CPU failure returns error. Use actual available targeted providers, no CoreML/TensorRT auto-selection, and report selection separately from hardware execution claims.
- [ ] Run a real CPU tiny graph after a controlled private provider-plan GPU attempt against a CPU core fails, proving actual CAPI fallback rather than a fake output. Assert provider/readiness report and CPU failure propagation. No product failure flags or fabricated available hardware.
- [ ] Construct only requested I64 graph inputs, optional zero types/scalar task1, use first output and validate batch/sequence/dim/type/finiteness before pooling. Pool borrowed runtime data while outputs live; return owned rows. Session destruction precedes private-file cleanup. Source path replacement and held output ownership tests pass.
- [ ] Run actual five representative graphs and all focused session tests/Clippy, preserving native identity and no Python children. Commit working session/provider owner.

### Task 5: Deliver the lazy serialized public encoder

**Files:** `fastembed_encoder.rs`, `lib.rs`, tests `fastembed_encoder.rs`.
**Interfaces:** complete public encoder contracts above; one mutex protects preparation/tokenization/session for a whole nonempty request. A tokenizer-only diagnostic can verify four configs without initializing model weights/runtime.

- [ ] RED public-use tests: cold constructor/empty inputs with absent model/library create no owned directory and leave deviceUnknown/preparedFalse; dim comes from registered model. First query prepares; CPU failures can retry after real source repair.
- [ ] Run focused tests to observe absent encoder APIs.
- [ ] Implement request coordination over existing model/token/session owners. Reuse the same operation for vectors-only/details; no duplicated tokenization rule or last-call global trace. Preserve complete batch256+remainder order and notices from actual preparation. Report corrected dim512/1024 explicitly without mutating stored metadata.
- [ ] RED/GREEN real concurrent first-use queries/passages and batch257-long-tail tests: independent owned results, one prepared session, no query mixing, no partial returned request on a later batch error. Repeated calls after source replacement keep identical prepared data; failed preparation leaves no ready device/session/tempfiles and can retry.
- [ ] Run focused tests, fresh whole Rust workspace, fmt/strict Clippy and release examples. Original1066 hashes stay unchanged. Commit the working Rust encoder.

### Task 6: Prove real text-to-vector parity and file ownership outside checkout

**Files:** `examples/fastembed_probe.rs`, `tools/rust_migration/fastembed_{compare,ownership}.py`, tests `test_fastembed_compare.py`, `migration_tests/test_fastembed_{parity,ownership}.py`.
**Interfaces:** strict NDJSON probe with explicit args `--registry/--sources/--work/--runtime-library/--model`; operations `status`, `prepare`, `tokenize`, `embed` (`side=query|passage`, `texts`), no expected results/source-setup/failure switches. One process per model avoids retaining30large sessions.

- [ ] RED comparator mutations: changed ID/order/prompt/token/mask/type/shape/byte, extra hidden row, wrong dim, nonfinite value, swapped model/revision, stale binary/source/producer and missing300case IDs reject. Only the exact original-reported384 vs registered non384 discrepancy is the declared dimension correction.
- [ ] Implement independently supplied text requests from cases, actual native diagnostics, F32 LE serialization and strict comparison against actual frozen originals. Compress raw chunks losslessly/deterministically, preserve original raw hash/size; bounded16MiB decompression authenticates owned compressed bytes before parsing. Never trim source warnings/logs or embed vectors into summary copies unnecessarily.
- [ ] Copy the probe outside checkout, sentinel PATH/no Python; Linux exec trace must show exactly one native exec per role. Audit linked libraries/cargo tree; no Python runtime/delegation. Capture actual RSS, full-process wall time and inference/preparation scope separately, without speedup claims.
- [ ] External ownership controller uses private copied model sources, real progress/status handshakes, then modifies/removes original paths after preparation; another embed stays identical. Drop/exit removes only owned temp files. Failed source/copy and later real repair produce retry, not empty vectors. Canonical source cache is never mutated.
- [ ] Run all300real cases for all30models on BOTH registered platforms and process ownership tests; expected exact lexical/policy data, finite vectors within fixed1e-6 rule, native states/provenance correct. GPU facts explicit; numerical GPU acceptance only on available hardware. Commit tooling/probe and reproducible receipts without marking whole M2 accepted.

### Task 7: Compose current both-platform34gate acceptance and retain proof

**Files:** `fastembed_{validate,evidence}.py`, `preparation.py`, existing validator/prepared-input chain and CI/guide; tests `test_fastembed_{validate,inputs,evidence}.py`; public `docs/validation/rust-migration-2026-10-20/m2-fastembed/`.
**Interfaces:** typed `PreparedNativeFastEmbed` above forwards only explicit absolute `KEN_FASTEMBED_PROBE/SOURCES/REGISTRY`; original environments strip them. New gates append `fastembed_release`, `fastembed_parity`, `fastembed_ownership` to storage31. New fingerprints append `fastembed_registry/cases/oracle/source_assets` to old29:33keys. Matrix requires exactly Darwin-arm64/Linux-aarch64, all34gates, current fingerprints and full authenticated nested raw proof; `FastEmbed_accepted=true`, `Storage_accepted=true`, `M2_accepted=false`.

- [ ] RED strict preparation/forwarding/current-key tests plus altered/unlisted/missing raw chunks, gzip bombs/trailing data, wrong raw hash/size, synthetic proof, re-sealed false native vectors/ownership/old base output and platform/source/toolchain drift. All must reject semantically after authentication, not merely by a stale hash.
- [ ] Implement fresh ken-models example release binding and forwarding through every earlier validator/test environment. Authenticate files once to owned bytes; reuse those buffers for nested authentication/decompression/recomparison. Summary stores refs/measures, not redundant full vector copies. Preserve previous source/proof and old baseline failures/xfails/deadlines.
- [ ] Run mandatory tooling and process tests, precompile all targets, freeze one immutable candidate after targeted GREEN and verify all source hashes BOTH. Fresh full34 on BOTH: no new Python failures/skips/missing baseline IDs/typing errors; no Rust failure/ignored test; original1066 unchanged. No source edits while acceptance runs.
- [ ] Publish complete verified raw trees and current33fingerprint matrix; rerun matrix against current Root. Commit only owned source/proof/docs. Complete task via printed matrix command.
- [ ] ONE fresh most-capable whole-plan reviewer reads spec/ledger/all7tasks and five ReviewFocus classes. Regrade by actual effects, ONE Critical/Important TDD fix pass with full fresh green acceptance; retain all reports, no rereview. Defer Minors and rule declined scope with costs. Archive only this completed SDD workspace, then continue remaining M2→M8 without a confirmation or partial final.

## Compatibility and self-review

`ModelAssets::verify`/`VerifiedSnapshot`, accepted runtime ownership, original
encoders, schema/vector format and model identity/pin decisions remain intact.
The file owner adds an explicit alternative, and shared regularity/wire helpers
keep their old behavioral tests. Graph/data policy lives with its owner;
coordination does not duplicate pooling, provider or artifact rules.

Dependency scan: T1→T3 supplies definitions/oracles; T2→T4 supplies durable owned
paths; T3→T4/5 supplies exact tokens/pooling; T4→T5 owns session lifetime/fallback;
T5→T6 is real text-to-vectors; T6→T7 supplies standalone/current authenticated
proof. All failures retain evidence and are resolved before the consuming task.
The spec's constraints and five review inputs map to named tests above. User
purpose/method are already explicit; routine design decisions are ledgered,
not converted into repeated approval prompts.
