# Native Ettin Preparation and Reranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, task-by-task. Preserve the already selected native method. Steps use checkbox syntax; one final fresh reviewer, no implementer agents.

**Goal:** Prepare the registered Ettin graph and score bounded paired text in Rust.
**Architecture:** Model registration/provenance, small head compiler, atomic cache
publication, and paired reranker are independent responsibilities. Reuse native
ORT owner and verified ModelAssets; retrieval remains the consumer/fusion owner.
**Tech Stack:** existing pinned Rust1.95,ort2rc14/API25,tokenizers0.22.2,
safetensors0.8,sha2/serde/tempfile; no new product dependency initially.
**Spec:** docs/superpowers/specs/2026-10-19-rust-ettin-design.md.

## Global Constraints

- Whole migration authorization includes this plan, no renewed confirmation pause.
- Original1066hashes, dirty/untracked work, installed entrypoint/userindexes preserved.
- Source d166fa88ddde3c42bc3ee92f7df476d941c8204a; derived274035078B/SHA8e22c1a014dbb6bf803824b531943ee067de4e9c6dea72f8c178348732db38bf.
- CPU4/1,arenaenabled,batch1,max_tokens1024,top10,only_second,rightpad50283.
- Exact tokens/metadata/bytes; raw F32 logits atol1e-5/rtol1e-5, finite/zeroexact.
- Native runtime/preparation, no Python/subprocess/implicit network in product.
- Both registered ARM platforms; no unobserved deployment or whole-M2 acceptance.

## Review Focus

1. Source/protobuf/config damage or explicit default-valued fields: preparation must preserve valid graph bytes and reject malformed input without panic or partial publication.
2. Concurrent cache preparation, corrupt existing cache or replaced source: every returned graph must match verified registration and remain owned after paths change.
3. Oversized queries, special tokens and only-second truncation at capacity: preserve query, padding/masks, pair counts and original error/lazy-load ordering.
4. Empty/top11/custom batch/concurrent histories: no unwanted core/data load, reordered logits, shared mutable results or lock cycle.
5. A stale executable, Python-built-only cache, wrong platform/core or incomplete receipt: all must fail native preparation/profile acceptance.

### Task 1: Independent oracle, preparation bytes and fixtures

**Files:** create tools/rust_migration/{ettin_reference,ettin_fixtures}.py,
tests/rust_migration/test_ettin_reference.py,crates/ken-models/tests/fixtures/ettin/,
docs/validation/rust-migration-2026-10-19/m2-ettin/{cases,reference}.json.
**Interfaces:** ettin_cases()->list[dict]; capture(reference,source,out,*,cases=None)
accepts optional definition/prepared overrides for independent tiny graph fixtures;
records original preparation bytes/hashes, runtime, options, token/mask/pair_fits,
logits/details/state/timing; fixture generation explicitly adapts frozen original
published_head/registered_head/registered_reranker helpers and records sourcehash.
- [x] Write RED tests missing modules; assert tiny head scalar expected within4e-6,
  exact original assembled bytes, pair scores29/30/28/31,pad7,empty no load,
  config/graph failures, raw boundary counts and original imports confined.
- [x] Implement frozen child capture/generator, dynamicbatch tiny graph adapter,
  malformed protobuf/head/weights/output/config fixtures. Preserve failures.
- [x] Fix all23real histories from spec and record raw1023/1024/1025pair lengths;
  capture bothOS before native scorer. Expected all exact policies/graphhash match.
- [x] Run .venv/bin/python -m pytest tests/rust_migration/test_ettin_reference.py tests/retrieval/test_reranker_head.py tests/retrieval/test_neural_reranker.py -q;
  Expected allpass. Verify originals, inspect/commit ownfiles; task-done samecommand.

### Task 2: Native graph preparation and cache ownership

**Files:** create crates/ken-models/src/{reranker_model,published_head,onnx_wire,reranker_preparation}.rs,
tests/{published_head,reranker_preparation}.rs; reexport via read lib.rs;
modify assets.rs only to factor crate-private verify_artifacts(root), preserving
public verify revision guard and existing asset tests.
**Interfaces:** RerankerModel::from_json(&str)->Result<Self>; source_assets()->&ModelAssets;
prepared_assets()->ModelAssets; verify_prepared(&Path)->Result<PreparedReranker>;
recipe_key()->String; compile_head(&VerifiedSnapshot)->Result<Vec<u8>>;
prepare(&self,source:Option<&Path>,destination:&Path)->Result<PreparedReranker>;
PreparedReranker owns Arc<VerifiedSnapshot> and model association, private constructors.
- [x] RED public tests exact tiny assembled bytes, every head operator/transpose,
  malformed varints/lengths/duplicate graph/output/opset/collision/nonfinite F32,
  arbitrarily named prepared cache without upstream, changed cache and failed
  derivedhash no publication; stage an inner ordinary-mode directory, preserving
  umask-readable files/directories instead of publishing TempDir0700.
- [x] Implement bounded wire fields, preserved upstream data and exact scalar/
  tensor/node/valueinfo presence/order. Validate head with safetensors, no generic
  graph interpreter. Verify source provenance and derived four-artifact bytes.
- [x] Atomic sibling-stage sync/publish/reverify winning cache; actual concurrent
  callers and source replacement use owned authenticated bytes. Real graph must
  equal declared274035078/SHA8e22 exactly on bothOS, never copy Python output.
- [x] Run cargo test --locked -p ken-models --test published_head --test reranker_preparation;
  Expected allpass with explicit KEN_ETTIN_SOURCE. Run prepared workspace/fmt/clippy
  and original preparation tests, verify originals, commit; task-done targetedcommand.

### Task 3: Native paired tokenizer and lazy CPU scorer

**Files:** create crates/ken-models/src/onnx_reranker.rs,tests/onnx_reranker.rs;
reexport via lib.rs. Existing ContextEncoder/runtime interfaces remain compatible.
**Interfaces:** RerankOptions{batch_size,intra_threads,max_tokens},validated new;
OnnxReranker::new(model,prepared:Option<Arc<PreparedReranker>>,source:Option<PathBuf>,
cache:PathBuf,runtime,options)->Result<Self>; prepare(),is_prepared(),pair_fits(&str,&str),
tokenize_pairs(&str,&[&str])->Result<Vec<PairTokens>>,score(&str,&[&str])->Result<ScoredPool>;
ScoredPool{scores:Vec<f32>,details:RerankDetails}; details token_ms/inference_ms,
truncated_documents,pair_tokens,pad_id Option omittedwhenempty. Lazy missing data
errors on actual use, empty/top11/invalidoptions ordering pinned to original.
- [x] RED tiny and mandatory actual23histories; invalid options/config padding/
  limits/dtype/output/count/NaN/Inf, query65536/65537 and token capacity, custom512/
  2048, batch3remainder, same/different concurrent queries and independent results.
- [x] Implement tokenizer policy and CPU4/1 arenaenabled with error_on_failure,
  runtime/session initialization before tensors, exact original outputfirstname,
  raw owned logits/details; no context/Potion normalization or prefix.
- [x] Run cargo test --locked -p ken-models --test onnx_reranker and original
  tests/retrieval/test_neural_reranker.py. Expected allpass on bothOS before closure;
  prepared workspace/fmt/clippy,1066hashes; commit/task-done targetedRustcommand.

### Task 4: Actual native preparation/process and complete platform proof

**Files:** create examples/ettin_probe.rs,tools/rust_migration/{ettin_compare,ettin_validate}.py,
tests/rust_migration/test_ettin_{compare,validate}.py,migration_tests/test_ettin_parity.py;
update own prerequisite owner,CI,guide and public evidence.
**Interfaces:** probe receives registration/source/cache/core/options/cases, noexpecteds;
returns actual preparedbytes/tokens/logits/details/runtime/state/phase peaks.
Comparator creates fresh native destination from source (not original cache), verifies
actual derivation, then outsidecheckout actual scoring. Matrix composes all20prior
gates plus ettin_release/ettin_preparation/ettin_parity=23, current fingerprints.
PreparedNativeEttin{source:Path,probe:Path}.environment()->dict and
ettin_environment(prepared=None) require absolute explicit paths; add optional
keyword ettin to validate_context/validate_tables/validate_models and the shared
_validation_environment. Typed inputs override ambient prepared vars; old CLI
callers forward only explicit KEN_ETTIN_SOURCE/KEN_ETTIN_PROBE. Frozen original
reference_env still strips everyKEN variable. No global os.environ mutation.
- [x] RED incorrect tokens/logits/config/state/core/assembledhash/stalebinary,
  cached-Python-only shortcut, wrongOS/stderr/missing cases/baseproof/currenthash.
- [x] Implement real probe, independent original/native destinations, fresh-source
  native preparation and existing-cache-without-source history; Linux actual1exec,
  copied binary/core audits, retained calibrated stderr policy and allmeasurements.
- [x] Prepared full tooling/process/original tests, then immutable-source complete
  bothOS23gates: fullPython exactbaselineIDs/mypy/Rust/fmt/clippy/allpriorparity+
  benchmark/integrity/current-sourcebinding; retain every attempt, no fake speedup.
- [x] Publish receipts/matrix, task-done printed matrix, one fresh whole-plan
  gpt-6-astra reviewer with all5ReviewFocus verbatim/rulings. Regrade C/I oneTDDfix
  pass, no rereview; deferMinors; acceptonlythisprofile then continue remainingM2.

## Preflight/self-review

T1 original bytes/fixtures feed T2; T2 prepared ownership feeds T3; T3 exact public
outputs feed T4. Optional prepared/source allows empty no-I/O without unchecked
snapshot constructors. Context owner/APIs stay unchanged; new shared validation
prerequisites require explicit forwarding and CI preparation, originals stripped
of all KEN env. CPU arena difference from prior context deferredMinor is not
silently copied into new profile. All5ReviewFocus have owningtask tests. Global
whole-program/selection/storage/optionalruntime obligations stay open.

Execution status: all four tasks complete; both-platform 23-gate matrix and the
one fresh whole-plan review passed. One Minor is deferred. See
[the execution record](../../validation/rust-migration-2026-10-19/m2-ettin/EXECUTION.md).
Global M2 remains open; the same migration branch continues.
