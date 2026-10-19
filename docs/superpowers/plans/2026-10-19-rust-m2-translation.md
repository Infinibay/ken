# Native Spanish Query Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, task-by-task. Preserve the selected native method. Steps use checkbox syntax; one final fresh reviewer, no implementer agents.

**Goal:** Prepare the registered CT2 data and expand Spanish queries entirely natively.
**Architecture:** Translation registration/preparation, per-query lexical policy
and lazy C++ runtime ownership have separate responsibilities. Reuse verified
artifact ownership and shared identity escaping; keep retrieval/model selection
outside this profile.
**Tech Stack:** Rust1.95; ct2rs0.10.1/staticCT24.8.2; sentencepiece/sys0.13.2,
SPM0.2.1; onig6.5.3; existing serde/sha2/tempfile; macOS Accelerate and Linux
OpenBLAS0.3.26/static/OpenMP COMP, CMake3.31.10 build tooling.
**Spec:** docs/superpowers/specs/2026-10-19-rust-translation-design.md.

## Global Constraints

- Whole migration authorization includes this plan, no renewed confirmation pause.
- Original1066hashes, dirty/untracked work, installed entrypoint/userindexes preserved.
- Source ad91ad1697ea1761111ff4c179400796d085b347; derived c96e2c5399ebfae4fc43d9669556b9afa74bb69d; all5original artifact hashes exact.
- Recipe1af342f7677e9f51477171000e5aa6e6527590a715f064bd64679c1aa491a9f0; config-only newline; insertion order and ASCII/indent2 exact.
- CPU/int8,2intra/1inter,beam1,maxdecode256,maxinput1024; actual1replica.
- Exact Unicode15word/decimal/space/casefold and protected identifier semantics.
- Exact IDs/pieces/hypotheses/text/failure boundaries; no output whitelist/tolerance.
- Native offline runtime/preparation, no Python/subprocess/implicit model download.
- Both registered ARM platforms; no unobserved deployment or whole-M2 acceptance.

## Review Focus

1. Unicode casefold/boundaries and regex greediness around dollar signs, combining marks, digits and empty backticks must preserve the decision and exact matches.
2. Placeholder collisions, multi-digit indices, unusual whitespace and model-damaged placeholders must preserve original restoration without leaked cross-call state.
3. Corrupt/replaced sources or caches and simultaneous preparation/loading must never load unchecked bytes, publish partial data, deadlock or turn failure into text.
4. Degenerate long inputs and platform numeric backends must retain translations and512/1024boundaries; a working short example cannot certify parity.
5. Wrong/stale executables, foreign-platform native libraries, Python-only preparation or missing prerequisite propagation must fail acceptance, including nested prior gates.

### Task 1: Frozen original oracles and fixtures

**Files:** create tools/rust_migration/{translation_reference,translation_fixtures,translation_unicode}.py,
tests/rust_migration/test_translation_reference.py,
crates/ken-models/tests/fixtures/translation/,
docs/validation/rust-migration-2026-10-19/m2-translation/{cases,reference}.json.
**Interfaces:** translation_cases()->list[dict] defines stable named histories;
capture(reference:Reference,source:Path,output:Path,*,cases=None,definition=None)->dict;
generate_policy(reference:Reference,output:Path)->dict records fixed/generated
query decisions/matches and whole-scalar Unicode digest; generate_preparation
explicitly adapts the frozen original translation_files fixture with sourcehash.
- [x] Write RED tests for missing oracle/fixture modules. Assert native-independent
  original tiny config/vocabulary exact bytes, recipe SHA, distinct-word/lazy
  behavior, 2438policy histories including indices above9, and Unicode15source.
- [x] Implement frozen child capture with reference_env/verify_reference;
  record original module/helper hashes, actual CT2/SPM versions/device/compute,
  protected/prepared input, sourceIDs/pieces+EOS, raw hypotheses/decoded/restored
  output, errors/readiness, timing/peak and source/prepared sizes/SHA.
  Label policy-only doubles; actual neural outputs always use real CT2/SPM.
- [x] Freeze English/missing-data/empty, repeated-one/two-distinct/question,
  Spanish/code/Unicode/emoji/NUL/newline, repeated/many identifiers, literal
  placeholder, repeated/error-then-English histories. Derive translated queries
  with exactly511/512/513/1023/1024/1025source pieces INCLUDING EOS from original
  SentencePiece; assert measured counts instead of guessing BPE overhead.
- [x] Retain BOTH platform OpenBLAS/Accelerate viability and capture real original
  histories before native product runtime. Run .venv/bin/python -m pytest
  tests/rust_migration/test_translation_reference.py tests/retrieval/test_local_query_expansion.py
  tests/retrieval/test_translation_preparation.py -q; Expected allpass.
  Verify originals, inspect/commit ownfiles; task-done same command.

### Task 2: Native policy, registration and atomic preparation

**Files:** create crates/ken-models/src/{translation_model,translation_preparation,translation_json,query_policy,python_unicode}.rs,
src/data/python-unicode15.json inside that crate;
tests/{translation_preparation,query_policy}.rs; modify read lib.rs/assets.rs;
add pinned onig dependency in workspace/crate manifests and lock.
**Interfaces:** TranslationModel::from_json(&str)->Result<Self>,source_assets()->&ModelAssets,
prepared_assets()->ModelAssets,recipe_key()->&str,cache_path(&Path)->PathBuf,
verify_prepared(&Path)->Result<PreparedTranslation>,prepare(Option<&Path>,&Path)->Result<PreparedTranslation>;
PreparedTranslation::artifact(&str)->Result<&[u8]>;
FrozenTranslationRuntime::{MacOS483,Linux482}; model.compatible_identity(profile)->Value
returns the original identity object; compatible_revision(profile)->String returns its hash.
plan_query(&str)->Result<QueryExpansionPlan>; QueryExpansionPlan::{Passthrough(String),Translate(ProtectedQuery)};
ProtectedQuery::text()->&str,protected_values()->&[String],restore(&str)->Result<String>.
- [x] RED integration tests for original fixture bytes, full recipe and both
  compatibility revisions; recursive-array ASCII identity regression; exact
  whole-scalar digest and original2438policy cases. Pin repeat/alias/long-s/
  dotted-I classification; match priority, dollar/end boundaries, Unicode digits,
  backticks/newlines/repeats; restore indices0/9/10/23 with001C..001F whitespace,
  mixed case, literal collision, damaged key, regex replacement punctuation and
  empty/whitespace rejection.
- [x] Implement explicit Unicode15 data/predicate/fold owner and onig explicit
  classes/boundaries; per-query ordered placeholders. Extend shared python_json
  arrays only; ordered JSON normalizer delegates the same string escaping and
  rejects unsupported float/duplicates/surrogates/invalid/bounded-number input.
  Preserve all existing model identities and global serde ordering.
- [x] RED missing/extra/wrong-revision/size/hash/recipe/cache/JSON damage,
  existing-cache-without-source, concurrent publishers, source path replacement,
  failed derived hash and nonregular-source tests. Implement via authenticated
  owned snapshots, staged sync/atomic publish/reverify; real derived bytes must
  match all5pins. No network/weight conversion.
- [x] Run cargo test --locked -p ken-models --test query_policy --test translation_preparation
  with explicit KEN_TRANSLATION_SOURCE; Expected allpass. Run existing assets/
  context/reranker identity tests and prepared workspace/fmt/clippy; verify
  originals, inspect/commit ownfiles; task-done targeted Rust command.

### Task 3: Lazy native CTranslate2/SentencePiece runtime

**Files:** create crates/ken-models/src/query_expansion.rs,tests/query_expansion.rs;
reexport via lib.rs; add fixed target-aware ct2rs/sentencepiece/OpenBLAS dependencies
and lock. Private build prerequisites become explicit inputs, no user venv edits.
**Interfaces:** LocalQueryExpansion::new(model:TranslationModel,source:Option<PathBuf>,cache:PathBuf)->Result<Self>;
expand(&self,&str)->Result<String>,is_loaded()->bool,load(&self)->Result<()>,
tokenize_prepared(&self,&str)->Result<TranslationTokens>,runtime_identity()->Result<Option<TranslationRuntimeIdentity>>;
expand_detailed(&self,&str)->Result<ExpandedQuery> returns per-call owned text and
optional TranslationTrace{prepared,tokens,hypotheses,decoded}; expand forwards its
text. The private native session's real translate operation is also exercised by
the independent24raw-core oracle, including English/raw-empty and degenerate inputs.
TranslationTokens{ids:Vec<u32>,pieces_with_eos:Vec<String>}; runtime identity
distinguishes compiled versions/configured backends from observed replica count.
- [x] RED original real histories and negative constructor/load tests: English
  with absent/bad source/cache stays untouched; translated failures retry;
  source/cache replacement cannot replace owned data; same/different concurrent
  queries match serial originals and returned strings remain independent.
- [x] Implement private retained authenticated materialization, C++translator
  CPU/int8/2/1 and SPM0.2.1, sourcepieces+</s>, beam1/maxdecode256/defaults,
  firsthypothesis decode/restore. One mutex serializes loading/calls, no global
  env writes, Python bridge or fallback. Check empty/missing outputs and errors.
- [x] Require exact BOTH platform raw and restored results for511/512/513 and
  maxinput boundaries, including the previously differing degenerate histories.
  Pin platform float/int8/native-library provenance and actual1replica.
- [x] Run cargo test --locked -p ken-models --test query_expansion and original
  tests/retrieval/test_local_query_expansion.py; Expected allpass with explicit
  prepared inputs on bothOS. Prepared workspace/fmt/clippy,1066hashes;
  inspect/commit ownfiles; task-done targeted Rust command.

### Task 4: Native process proof and composed both-platform acceptance

**Files:** create examples/translation_probe.rs in ken-models,
tools/rust_migration/{translation_compare,translation_validate,translation_build}.py,
tests/rust_migration/test_translation_{compare,validate,inputs,build}.py,
migration_tests/test_translation_parity.py; update preparation.py, prior validators,
CI rust-models.yml, guide and public evidence.
**Interfaces:** PreparedNativeTranslation{source:Path,probe:Path}.environment()->dict;
translation_environment(prepared=None) validates absolute explicit paths.
The typed translation input also accepts optional PreparedTranslationBuild{cmake,
openblas_prefix}; explicit build inputs override ambient paths. ExpansionAttempt
owns the normal expansion Result and optional actual pre-inference TranslationInput.
Native build proof consumes Cargo JSON's selected ct2rs out_dir and actual CMake
compiler/backend flags. The private OpenBLAS preparator authenticates source and
publishes archive/header/pkg-config identities. Shared native_source fingerprints
also bind eligible crate src/data and tests/fixtures bytes.
Add optional keyword translation to validate_ettin/context/tables/models and
_validation_environment; typed inputs override ambient values. CLI only forwards
explicit KEN_TRANSLATION_SOURCE/KEN_TRANSLATION_PROBE; frozen originals strip all
KEN vars. validate_translation composes23prior+3translation gates=26; aggregate
requires both current-source receipts and exact registered platform/compiler.
- [x] RED wrong tokens/hypotheses/text/errors/state/recipe/derivedbytes/backends,
  missing/corrupt native prerequisites, stale binaries, Python-prepared-only
  shortcut, wrongOS/libs/stderr/caseIDs/baseproof/current-fingerprint damage.
- [x] Implement actual JSON probe with no expected outputs; original and native
  independent destinations, fresh native preparation then reuse without source.
  Execute copied binary outsidecheckout/sentinelPATH, audit system dependencies
  including explicit Linuxlibgomp, actual Linux1exec, retain raw/observed peaks
  and all measurements/attempts. No speedup/SLA claim.
- [x] Run targeted tooling/process tests, then immutable-source full BOTH OS26gates:
  exact fullPythonbaselineIDs/mypy/Rust/fmt/clippy/original1066hashes/allpriorparity/
  benchmark/integrity/current-sourcebinding. Missing prerequisites fail, no skips.
  Publish receipts/matrix and task-done printed matrix; Expected passed=true on
  both platforms, Translation_accepted=true,M2_accepted=false.
- [x] One fresh whole-plan gpt-6-astra reviewer with all5ReviewFocus verbatim and
  ledger rulings; regrade, one TDD correction pass for C/I, no rereview; defer
  Minors, record every declined scope and cost. Accept only this profile and
  continue remaining migration under the existing authorization.

## Preflight and self-review

T1 original oracles/data feed T2 policy/preparation and T3 runtime; T2 prepared
ownership/plan feeds T3; all three feed T4. Array formatting is shared with prior
asset/context/reranker identities: extend recursively without changing ordering
and rerun them. Task3 native toolchain is consumed by Task4 typed preparation/CI;
Linux OpenBLAS must be prepared and authenticated before compiling its profile;
enable openblas-src/system directly, never ct2rs/system (which skips CT2 compilation).
Explicit model/cache inputs keep English lazy and native runtime offline. All
five review focuses have owner tests. Other optional runtimes/storage/selection
and M3–M8 remain required work under the whole migration, outside this cut.
