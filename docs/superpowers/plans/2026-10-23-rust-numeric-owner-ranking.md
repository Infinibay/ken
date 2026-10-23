# Native numeric owner ranking implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Native inline execution is user-selected. Steps use checkbox syntax; no implementation delegation or task-by-task reviews.

**Goal:** Reproduce full numeric owner relevance, feature inputs and diagnostic observations with native code.

**Architecture:** Extend ken-retrieval with immutable matrices/forests, explicit word-model/stemmer collaborators and request-local features/traces. Keep projection, arithmetic, model execution and orchestration separate; reuse accepted models, source identity and numerical runtime. Reuse generic capture/receipt infrastructure, adding disjoint families rather than recapturing older behavior.

**Tech Stack:** Rust1.95, existing pinned serde/serde_json/sha2/Unicode/onig/model/runtime dependencies, already-locked flate2=1.1.10, official Snowball3.0.1 generated Rust at e4b3efb449ccb994d39230eb6e8440d267471f4a.

**Spec:** docs/superpowers/specs/2026-10-23-rust-numeric-owner-ranking-design.md

## Global Constraints

- Preserve all1066original files, user dirt and accepted receipts. Continue codex/rust-migration; commit and push validated blocks without merge/PR menus.
- M4b predecessor FILES SHA502522eb0af6e3136be30114c5509314593785e94604ff1c70303f721a33a10b; full M4/global remain false.
- Rust1.95; source extractor8/parser10, lexical256/code-lexical-v1, representation3, description1. No new external version except the pinned Snowball source; flate2=1.1.10 already exists in Cargo.lock.
- Numeric schema1; features1–512 unique/nonempty; trees1–4096; depth64; sequential tree addition. Original F32/F64 arithmetic and exact owner/evidence/call order.
- Query terms128; field terms4096; vocabulary block4096; stem cache32768entries with128codepoint eligibility. Existing model cache8MiB/8192entries unchanged without measured cause.
- Feature/evidence versions1–3; original stable proposal ties and exact priority; production native2560/piece1280trees and fingerprints from the spec.
- Capture each new original family once before implementation, exact discovery/JUnit; reuse old captures/models. No weakened/skipped tests, new lint suppressions, placeholder bodies or source deletion.
- Actual macOSarm64/Linuxaarch64 acceptance, input-only isolated process, source/binary/runtime/raw authentication, fixed bounds, one final review/fix pass, cleanup owned scratch.

## Review Focus

1. Mixed F32/F64 reductions, one-row/one-column BLAS, quartiles and values at0.5/0.7 must retain the same coverage and forest branch/owner cutoff.
2. Equal-spec different stemmer/encoder owners, concurrent cache misses and Unicode words near128codepoints must not share mutable buffers or another provider's results.
3. Vocabulary/field membership at4096boundaries, repeated terms and shared raw/source fields must preserve limits, projection order, memory bounds and actual encoder calls.
4. Forest0/1/32/128/129rows, depth64, cancellation and Python float/string coercions must preserve to_dict/fingerprint, sequential leaf sums and stable winner order.
5. Trace export/replay and reused descriptions must reject mismatched source/model/order, retain immutable observations and exact-bypass behavior, and account for margins using the actual tree paths.

### Task 1: Numeric forest, rectangular values and canonical identity

**Files:** Create ken-retrieval/src/matrix.rs,numeric_ranker.rs,rank_json.rs; tests/numeric_ranker.rs; tools/rust_migration/numeric_reference.py and input-only fixtures. Export through lib.rs.

**Interfaces:** Matrix<T>::new(rows,columns,values)->Result<Self>, rows/columns/values immutable access; NumericRanker::from_json(&str)->Result<Self>, features()->&[PythonText], to_json()->Result<String>, fingerprint()->Result<String>, predict(&Matrix<f64>)->Result<Vec<f64>>, explain_pair(left:&[f64],right:&[f64])->Result<PairExplanation>. Named explanation structs serialize original fields.

- [ ] Capture actual original numeric_ranker observations and its complete scoped suite once: schemas/extra keys/coercions, bounds/depth64/65, Unicode names, signed zero/exponent formatting, cancellation, mixed-depth independent paths,0/1/32/128/129rows, nonfinite input/output/explanation errors and margins. Capture nonfinite values explicitly; never turn them into null.
- [ ] Add complete native model/dict/fingerprint/prediction/explanation comparisons. Run `$MAC cargo test --locked --offline -p ken-retrieval --test numeric_ranker`; Expected missing API RED.
- [ ] Implement bounded immutable tree parsing, original canonical compact JSON/float spelling, checked matrix shape, sequential prediction and accurate pair-path/fsum accounting. Avoid modifying the accepted M2 serializer, whose spacing/escaping differs.
- [ ] Run new and directly affected complete suites plus fmt/clippy; Expected PASS. Commit/push `feat(retrieval): execute pinned numeric forests and explain margins`.

### Task 2: Exact English stemming and provider-owned reuse

**Files:** Create src/stemming.rs, private snowball/{mod.rs,english.rs,runtime.rs}; license/provenance manifest; tests/stemming.rs; extend original-reference families.

**Interfaces:** WordStemmer:Send+Sync::stem(&PythonText)->Result<PythonText>; EnglishStems::shared()->Arc<Self>, stem_words(&[PythonText])->Result<Vec<PythonText>>. A supplied provider owns its cache; default English shares one bounded provider cache.

- [ ] Capture original stem output and scoped test_stem_reuse once, including long/Unicode/lone-marker words, order, duplicate/mutated outputs,32768bound,128/129codepoints, concurrent independent state and factory replacement. Write public native tests; run `cargo test --locked --offline -p ken-retrieval --test stemming`; Expected absent API RED.
- [ ] Acquire only official commit e4b3efb449ccb994d39230eb6e8440d267471f4a into owned scratch, record source/license hashes and native compiler/generator command, generate English Rust and vendor only required runtime/algorithm. No runtime compiler or Python; preserve algorithm/source provenance. Integrate without new lint suppressions. Implement bounded provider-owned reuse and proven lossless text handling.
- [ ] Run stem differentials, concurrent/cache boundary roots and affected complete native/tooling/fmt/clippy checks; Expected PASS. Commit/push `feat(retrieval): preserve Snowball English stemming with bounded native reuse`.

### Task 3: Dtype-aware term alignment and original numerical dispatch

**Files:** Create src/alignment.rs; extend private dense_math.rs only for required F64 dot/norm and F32/F64 matrix products/reductions; tests/alignment.rs.

**Interfaces:** FloatMatrix{F32(Matrix<f32>),F64(Matrix<f64>)}, FloatVector{F32(Vec<f32>),F64(Vec<f64>)}; TermAlignment::new(FloatMatrix,FloatVector)->Result<Self>, similarities(&FloatMatrix)->Result<FloatMatrix>, coverage(&FloatMatrix)->Result<TermCoverage>, summarize(&FloatMatrix)->Result<TermCoverage>, summarize_maxima(&FloatMatrix,present:&[bool])->Result<Vec<TermCoverage>>; TermCoverage{mean,minimum,quartile,above50,above70,weighted}:f64.

- [ ] Capture original alignment/maximum-summary observations and scoped tests once, including empty rows/columns, mixed dtypes, invalid dimensions/weights/presence, inactive nonfinite maxima, scalar/GEMV/GEMM shapes, threshold/quartile/weighted cancellation and block-shaped products. Add numerical and ordered cutoff regressions before changing shared math; run alignment tests, Expected missing API RED.
- [ ] Implement original dtype promotion, finite checks, row-wise reductions and one-row weighted dot. Extend the already pinned platform BLAS with exact original dispatch; retain all accepted F32 storage/dense paths unchanged. Check dimensions/lengths before every FFI call; reuse existing pairwise reduction where appropriate.
- [ ] Run alignment plus all affected M4b storage/dense/context/index regressions on both platforms after a shared arithmetic change; Expected PASS, original fixed bounds/order, fmt/clippy. Commit/push `feat(retrieval): align query terms with dtype-correct bounded arithmetic`.

### Task 4: Full owner feature projection and bounded vocabulary

**Files:** Create src/feature_matrix.rs,word_encoder.rs,coverage.rs,evidence_features.rs,contextual_features.rs; extend vocabulary.rs with lossless code_terms_python; tests/coverage.rs,evidence_features.rs,contextual_features.rs.

**Interfaces:** FeatureMatrix{names:Vec<PythonText>,values:Matrix<f64>}; WordEncoder::{spec()->&EncoderSpec,embed_query(&PythonText)->Result<Vec<f32>>,embed_passages(&[PythonText])->Result<Vec<Vec<f32>>>}; ManagedWordEncoder adapter consumes Arc<ManagedEncoder> plus pinned spec. coverage(query,documents,fields,encoder,optional_stemmer)->Result<Vec<BTreeMap<String,f64>>>; base_features(request,candidate), evidence_features(request,candidates,descriptions,encoder,stemmer,expanded), contextual_features(candidates,source_views)->Result<FeatureMatrix>.

- [ ] Capture actual base/coverage/owner/contextual feature matrices, names and encoder/stemmer call traces with disjoint original suites. Pin all field/schema orders; include stale/foreign/empty evidence, missing signals, original/expanded equal/different queries, Unicode/negation/operations, duplicates and4095/4096/4097vocab/term boundaries. Add tests; Expected missing APIs RED.
- [ ] Implement complete projections and pool-relative ranks with one authoritative schema. Preserve query128/field4096limits, membership order, shared-field reuse, query/source coverage passes and original dtype/mean normalization. Stream vocabulary blocks4096, retaining field sums/maxima rather than full similarity history. Validate source identity before embedding with the accepted evidence guard.
- [ ] Run complete affected feature/alignment/vocabulary/owner-selection suites, deterministic call/memory bounds, fmt/clippy; Expected PASS. Commit/push `feat(retrieval): project complete source evidence into pinned ranking features`.

### Task 5: Owner reranking and immutable diagnostic traces

**Files:** Create src/owner_ranking.rs,ranking_trace.rs; tests/owner_ranking.rs,ranking_trace.rs.

**Interfaces:** EvidenceReranker::new(model,word_encoder,stemmer,optional_expansion)->Result<Self>, validate(&EvidenceRanking), prepare_query(&PythonText), rank(request,candidates,descriptions,optional_expanded,evidence_version,optional_trace)->Result<Vec<CodeMatch>>; RankingTrace::new(optional_request_id), record(...), from_json(...,&NumericRanker), to_json(include_query), compare(left,right). Expansion identity is explicit and pinned.

- [ ] Capture original owner ranking and trace behavior/suites once: feature/profile/expansion validation, unique exact no calls, versions1–3, complete evidence, stable proposal ties, repeated attempts, deep-copy exports, query hashes, replayed scores/rank permutations and actual divergent paths. Add tests; Expected absent APIs RED.
- [ ] Coordinate accepted components without duplicating projection/model rules; preserve exact priority, original evidence-version rules and immutable request-local traces. Invalid source/profile data must not reach encoding.
- [ ] Run owner/trace plus directly affected complete suites and fmt/clippy; Expected PASS. Commit/push `feat(retrieval): rerank source owners with reproducible request-local traces`.

### Task 6: Registered production forests and native model composition

**Files:** Create src/rank_models.rs; preserve exact copies of the two original gzip artifacts under resources/ranking with manifest/licenses; tests/rank_models.rs; associate already-locked flate2=1.1.10.

**Interfaces:** ProductionRankModels::open(resources)->Result<Self>, native()/piece()->Result<Arc<NumericRanker>>; compressed bytes and canonical fingerprint verified, lazy owned model lifetime.

- [ ] Capture actual original registered artifact fingerprints/predictions and scoped tests once. Add byte corruption, truncation, wrong decoded schema/fingerprint, lazy missing-resource and both2560/1280tree tests; Expected missing loader RED.
- [ ] Verify/preserve original artifacts and native lazy loading. Add new owner-feature/rank composition with the accepted static encoder on a small fixed source corpus, complete model/encoder/source provenance and call traces. Reuse M2 catalogs; do not refit models or reopen private search reserves.
- [ ] Run artifact/integration and directly affected suites/fmt/clippy; Expected PASS. Commit/push `feat(retrieval): load verified production ranking forests natively`.

### Task 7: Authenticated numeric-owner acceptance and one final review

**Files:** Extend/reuse strict native probe/capture infrastructure with new numeric families, tools/rust_migration/numeric_{validate,evidence}.py and test_selection-compatible tamper gates; docs/validation/rust-migration-2026-10-23/m4-numeric-owner/.

**Interfaces:** Bounded input-only numerical/feature/rank/trace operations plus explicit verified resource inputs; fixed dtype-aware comparisons retain complete names/rows/order/owner/evidence/traces/errors. Reuse generic NativeJsonCapture/receipt/source helpers and M4b predecessor rather than recapture old cases.

- [ ] Add actual-positive/tamper tests for omitted/reordered feature rows/names/calls, resealed results, stale resources/runtime/source/binary, skipped tests and altered raw originals. Run; Expected missing protocol/verifier RED.
- [ ] Execute both actual platforms once for new complete families and affected native/tooling gates, original preservation, isolated runtime, measured resources and independent source/tooling/raw replay. Expected full PASS. Archive before commit/push `test(retrieval): authenticate numeric owner features and ranking`.
- [ ] One fresh whole-plan reviewer with Review Focus verbatim and ledger rulings; regrade all findings/declined behaviors, one Critical/Important RED→GREEN fix pass with affected green suites; preserve exhaustive review/rulings/minors, final replay, clean only owned obsolete scratch and continue M4c2 without confirmation. M4/global stay false.
