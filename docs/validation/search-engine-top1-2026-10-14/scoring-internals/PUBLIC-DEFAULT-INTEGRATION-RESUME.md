# Public default integration handoff —2026-10-16

## Goal and authority

User explicitly authorizes best complete search configuration by default in CLI
and MCP, compact output, CPU/RAM optimization, more independent tests, commit
and push main. No release/tags. Correct requested piece is the acceptance target;
excerpt sufficiency is not required. Preserve original200 at180top1/197top10.
Additional200Gold stays closed until complete public production arm is frozen
and closed. The current public global recommendation/profile is STILL OLD: do
not claim best defaults are integrated yet.

## Workspaces and published state

Own clean native worktree: /Users/andres/.codex/worktrees/compact-default-output/ken
(branch codex/compact-default-output). Published main is
a047e09e656c0417ecc72cd05d34cacb406db097. Includes af041c7compact public UI,
fcb9de7independent scorer/public protocol, a047e09portable static backend.
Original checkout and research workspace contain foreign dirty edits, especially
cli.py/server.py/code_reasoning. Never reset/stash/addall/copyover those files.
Research: /Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace.
Its origin is LOCAL; push only explicit https://github.com/Infinibay/ken.git
HEAD:refs/heads/main with push.followTags=false, then ls-remote verify.
Clean worktree edits/git writes need sandbox escalation (native managed path).

## Verified controls and scripts

Original200typed cases:837a88a2c995a58257142ab763b8ac0035abc35b9d5f06759778f7ac3074305e,
in research/output/development/verifiable-pieces-v98-public/cases.jsonl.
Static extraction136source93c08ae1ffa5f312b44f57b5f89a98714fabd88fc7f04bb9c8de740dd88f90ee
closed all200, exact cards/units/pool hashes/orders equal134:180top1/197top10.
P502435.639ms,p953713.356ms,peak2106949632B descriptive, small background
tests/metadata I/O; not an isolated further performance gain. Gzip checkpoint
production-static-v136 is committed.45source/synthetic embedding vectors also
bit-identical to frozen134, identical model/profile identity.

Frozen contextual137source100bbfcca104c3ddb9578de0db3d81db7bc1cae515a2382047694c49b4ec3cf4
closed all200, exact observable outputs/orders equal136. Source-free8actual
pretrained vectors bit equal, context specaed8c3a8ed338b26f9fd61c5cb6798687d5700dae60fe71dfc2be4e6356512ed.
Frozen translation138source37075978f3419c3eb4a2d95c69e7a2374bb5a6892d1b56f9680a268dfa7aa0be
closed all200, same exact parity. All prepared CT2 files byte equal;4actual
source-free translations equal, revision7a0253108f179d21a47310b4a25e77942e36e79b113b5aa826362481337b533b.
Details: research/output/development/backend-extractions-v137-v138, each
piece-production-context-v137/piece-production-translation-v138 directory.
Closed evidence is archived in output/checkpoints/portable-backends-v137-v139.

Frozen neural139sourcec3fa8f40c86c29a691c558d5357729ee1b67d799d9c4718bc9001abf01425b92.
Supervisor output/analysis/run-neural-extraction-v139.py waits137/138, then checks
portable graph8e22c1a014dbb6bf803824b531943ee067de4e9c6dea72f8c178348732db38bf and
actual scores against oldCPU4/batch1, then fresh original200. CLOSED with exact200answer/order parity and6bit-equal real neural scores; exec9708complete;
log /private/tmp/ken-neural-extraction-v139.log. Probe/replay logs under
output/development/neural-extraction-v139-protocol. Check closure/errors first.
Do not edit frozen trees. Freeze scripts live output/analysis/freeze-*-v137/138/139.py.

Both frozen new200controls have CLOSED WITHOUT GOLD:
output/development/unseen-cpu-validation-v135/closed-baseline-v136 (engine132),
closed-optimized-v136 (engine134). No scores were computed/read. Supervisor
run-static-and-unseen-controls-v136.py finished (exec54394); queue-v136.json
records closure/pins. Actual generic caller was previously parity-proved on old200.
New200 has50/type,120EN/80ES,8same repos. Disjoint175opaque source exclusions;
no new-repo/population90claim; oldv104 remains unopened/overlap unverified.
Curatorv135c scorer review15tests+8probes approved, zero Gold reads in rejects.
Scorer7af4b21da6d6ac7ba0207271c00969a81886e18576cc73d1dd74ca1f03ce62dc,
lock-v135c eb3368a1a0b4a897bc52c6a6b5019596ad9a2746c0fc3f59a0a864c3f43cb3c1.
Scorer currently accepts exactly baseline/optimized; third actual public arm
needs prospective registration/scorer extension and independent curator review
before newGold grading. Curators authorized only curation/review, not engine work.

## Own pending production files

contextual_onnx.py (ContextModel/ContextEncoder): lazy, CPU2, raw768CLS/no padding/512,
exact old registered spec; no Torch. code-context-int8.json pins upstream.
translation_preparation.py + query_expansion.py optional prepare_artifacts hook:
CPU2/INT8/beam1 expansion unchanged. Public Prukario CT2 model.bin44c5adc... is
identical to measured weights, same SPM. HFrevad91ad1697ea1761111ff4c179400796d085b347.
Only config/vocab JSON formatting differs: indent2,ensure_asciiTrue; config
trailing newline, vocabulary no newline reproduce measured hashes exactly.
No Torch conversion or new hosted weights needed. es-en-ct2-int8.json records
public source+derived pins. Cache seeded with identical registered bytes in
research/output/models/portable-hub-v138, compiled target portable-prepared-v138.

neural_reranker.py: lazy ONNXReranker, immutable RerankerAssets, batch1/CPU4/512,
published padding, finite one-score/document validation, max10, no load for empty
pool, explicit error for overlong query. Graph/tokenizer/config digests checked
before parsing. default_reranker in neural_assets.py lazily prepares FP32 graph
from public backbone+all head weights, no Torch/SciPy runtime. Validates exact
CLS/Dense/exactGELU/LayerNorm(eps1e-5)/Dense. CurrentCPU only; optional GPU fast
provider selection still needs implementation/parity/cost check.
Model source cross-encoder/ettin-reranker-68m-v1@d166fa88ddde3c42bc3ee92f7df476d941c8204a,
FP32 upstream onnx/model.onnx95505bbc6a95f9bdfad71e55998fec30c5cc0be490e921cbd796d2dbf0243f2f.
Full graph expected8e22...274035078B. HF cache portable-hub-v139 seeded from
identical registered bytes, prepared cache portable-prepared-v139.

Uncommitted pyproject adds onnx==1.20.1,ctranslate2==4.8.3,sentencepiece==0.2.1.
Static committed dependencies model2vec0.9.0,tokenizers0.22.2,HF>=0.36.2<1.
Important runtime .pth trap: .venv-model-runtime inherits research .venv and
original .venv sitepackages. Installing tests briefly changed tokenizers to0.23.3;
restored main and explicitly installed0.22.2 in model runtime before all136+
replays. Both control identities/parity remain exact. Do not mutate benchmark
runtime while runs active. Actualnumpy2.4.4,onnxruntime1.25.1,safetensors0.8.0.

Tests: full static slice14859passed/10existingxfail504.29s; follow-up57embedding
checks pinned tokenizer. Most recent focused backend29tests pass (context,
translation,rawscores,complete head/cache,existing expansion). Mypy348source
files clean in /private/tmp/ken-backends-mypy-final3.log. Latest NNfocused12pass
after annotations, tests include real ONNX+native Model2Vec, no prediction mocks.
Two-dimensional LayerNorm fixture magnified FP32 cancellation1.5e-5 at logit30;
confirmed identical with ORT optimizations disabled. Replaced it with a meaningful
3Dfixture that distinguishes wrongGELU and kept original4e-6tolerance; no metric
or acceptance threshold changed. All default-public-format14kcompatibility
tests passed earlier; no release/version changes.

## Generic production forests

Current full90%engine uses validation-only repo-excluded models; never choose
a fold by repository name in production. Predeclared portfolio in
docs/design/best-default-search-2026-10-16.md: fixed pooled refit of original
training recipe OR equal-weight mean of all registered folds, selection on
original development only before any newGold. Native registry actually16folds,
piece8; corrected before generation based solely on metadata, not new feedback.
Experimental production_forests.py + test_production_forests.py in CLEANworktree
(ignored, untracked; not in git status unless --ignored).3tests pass, including
unequal tree counts to ensure equal MODEL weights. Builder captures input bytes
once for truthful SHA receipts. Generated prospectively in RESEARCH:
output/models/production-forest-mean-v140/native/model.json,251features,2560trees,
FP6b563fed14ed276e1b310beba84006078ef65ab5d7d3cb5622d759f6a671e3a0;
piece/model.json,262features,1280trees,
FP62846d51f58e5da1cf27ad444073d14341bdc6368f8552a7bb1c30e8d6e7d9b9.
All source model fingerprints/exclusion/byte receipts checked against69/126.
NOT evaluated or selected yet. No public best-default90claim for these models.
Need fresh old200 separately for native/piece changes, then actual public arm.
Existing piece_complete_run hard-asserts historical native pool/piece order:
do NOT silently bypass guards and call it parity; use a prospectively declared
generic-model runner with identity grading on old exposed Gold and retain
>=180/197. If mean is too slow, profile NumericRanker.predict before optimizing;
a compiled/vectorized exact-order accumulate is an idea, NOT implemented.

## Remaining implementation

Portable production preparation/indexing and shared BestSearchRuntime still
missing. No production imports of ken.bench or experiments. Use core passage/
owner descriptions, source context and two mmap views with generation/source
receipts. Extract SourceCatalog/piece assembly/input-v102 separately; reuse
existing evidence ranker/piece262/weightedRRF60/.5. Preserve neural input separate
from compact UI. Share model sessions across roots; per-project source caches
are generation-bound. Lazy models should let unique exact lookups bypass context
and neural loads.

Connect actual normal CLI search and MCP ken_find auto routes, expose piece_kind
auto/class/module/symbol/file. Test bare exact class lookup with auto: experimental
SourceCatalog.symbol only accepts callable/constant, so auto bareClass must adopt
actual unique entity type instead of dropping it. Explicit corpus target_kind
is public request metadata; test its transmission through real CLI/MCP.
If using identity/behavior=potion_profile(model2vec backend), ranker's word_model
can separately be RegisteredStaticEncoder.spec(provided) with identical values;
normal ProjectionIndexer.load_encoder then works incrementally. Avoid a stored
provided encoder that cannot be loaded without experiment injection. Respect
old stored CI-vector pins; do not silently mix1024Qwen with256Potion.

Implement automatic portable preparation/status, generic packaged models, optional
fast usableGPU provider with CPU fallback; no heavy GPU requirement. Actual
public default pipeline must pass old200 and independent new200, then curator
score after ALL3arms closed. More dev tuning after private feedback exposes
that cohort: need another untouched acceptance set, do not recycle it silently.
Regenerate all12MCP/CLI examples after full integration. Current committed
examples document presentation-only oldstatic default. User wants examples of
every output, final concise examples plus catalog link. Commit/push main, no
release/tags, keep foreign original work. Do not end with partial completion.


## Resume override after v140–v145 integration

Read PUBLIC-DEFAULT-V140-V145.md first. Main published5307f83; current clean
worktree now has a complete portable public pipeline (not yet checkpoint pushed
at time of this paragraph). Generic model means selected only on old200gave
182/197then191/197; actual default realMCP original200confirmed191/197. Additional
production200is now capturing with its predeclared lock; Gold still closed.
Both old controls remain closed/ungraded. See current journal for source/code
receipts, resource figures, tests and remaining tasks. Never infer95.5%unseen
accuracy from development191/200.

## Independent validation result — final override, 16 October 2026

All three arms closed before any private labels were opened. The independent
curator graded once after a second scorer review and final closure preflight.
This supersedes every earlier statement that the additional200 is ungraded.

| Arm | Top1 /200 | Recall@10 /200 |
| --- | ---: | ---: |
| Frozen CPU132 baseline | 170 (85%) | 197 (98.5%) |
| Frozen CPU134 optimized | 170 (85%) | 197 (98.5%) |
| Actual public default145 | **177 (88.5%)** | **198 (99%)** |

The public default **fails the requested90%** on this independent cohort.
Original exposed development remains191/200(95.5%),197/200(98.5%); it must not be
reported as unseen accuracy. Production macro-repository top1 is89.6143%.
Type top1/top10, denominator50 each: class45/50, symbol38/48,
module46/50, file48/50. EN109/120, ES68/80; behavior140/160, lookup37/40.
Query-level Wilson95% interval for177/200: [.833352831,.922136268]; no population
or unseen-repository guarantee. All cohorts use the same8repositories.

CPU production p502536.035ms,p953736.551ms,max4528.116ms; process peak
1941946368bytes(1.809GiB). Per-query child CPU is unavailable; process-total CPU
1411229.685ms includes setup,warmup and sampled compact calls. Do not compare it
as per-query CPU. CPU134 p502491.546ms,p953788.345ms,peak1930936320bytes.

Receipts in research/output/development/public-default-v145-additional:
- scoring-lock.json SHA c155b4bfbe7cf6cc9ab2d5243ba8700f68c92286946f5d5ea554f75995724cc6
- independent-grade/summary.json SHA 274ae2aaf4d3b8ef2aed17fc22244f1eae77d5c500336d76617d196d9cc98997
- independent-grade/EXECUTION-RECEIPT.json SHA ff825d91350e045729537f923b16e486c7477b0f2f974989725c8f76690f1d04
Corrected scorer review fd73e4e31ec345ffc438f829990f07b67c1cd2f81e2c0f0ab6583d62b3878536;
final preflight review b4a2ee8343ec0938501b5404ad2496d54f6f468bbe4f00ddd0ca4bcb7cdb2be5.
The implementer received aggregates only, not per-case labels or failure IDs.
The cohort is consumed feedback from this point; do not tune and call it fresh.

Next controlled work: diagnose symbol ranking on exposed development, curate
200 new exposed symbol questions, and independently curate a fresh balanced200
acceptance set. Before curation, source-file partition was fixed as first byte
of SHA256(UTF8(repo_id+'\\0'+relative_POSIX_path)): development<128, reserve>=128.
Both exclude175original primary files and200consumed primary files using the
same opaque HMAC inventory (union375, no overlap), SHA
eb3620928d327514091dccbb07699c7ad33775bcd46ba7a0bad6b467d0667724.
No acceptance threshold, reference or denominator has been reduced.

Published main ef7f0ef9562a7e7b31ddf451d17b27866acc1621 contains the complete
portable default. Own remaining label cleanup does not alter model values.
Actual all12MCP plus7CLI examples were regenerated in
../compact-output-2026-10-16-best-default/EXAMPLES.md (from validation root).
Original checkout still contains foreign uncommitted work and is not updated;
read-only three-way merge candidates and full dirty backups are in
/Users/andres/Projects/ken/output/local-main-update-2026-10-16. Never reset/stash.

A source-free CoreML probe with the measured dynamic Ettin graph failed even
outside the filesystem sandbox: unbounded dimensions/shape compilation error.
The measured default remains CPU-only. Provider availability does not establish
usable acceleration. No optional-GPU speedup or automatic selection is claimed.
