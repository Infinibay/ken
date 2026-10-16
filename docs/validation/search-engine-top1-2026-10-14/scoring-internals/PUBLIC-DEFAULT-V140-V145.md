# Public default integration checkpoint — 16 October 2026

The user requested the best complete configuration by default, not only a new
embedding. Implementation now routes normal CLI semantic search and MCP
ken_find(files/symbols) through the portable complete pipeline. Explicit legacy
and prepared-profile evidence APIs remain available. No release or version bump.

## Quality and interpretation

A prospectively documented generic model portfolio replaced validation-only
repository-excluded folds. Native is an equal-weight mean of16 complete forests
(2560trees,251features), piece is a mean of8(1280trees,262features). No runtime
repository/query routing, label lookup, new labels, HPO or per-repository weights.
The model package is approximately1MB compressed; inference is plain NumPy.

Original exposed development200, each change separately:
- Native generic mean only:182/200top1,197/200top10.
- Add generic piece mean:191/200top1,197/200top10.
- Actual production default through real MCP stdio:191/200top1,197/200top10.
  class49/50,module48/50,symbol46/50,file48/50. Known-correct identity is the
  criterion; no snippet/facet/sufficiency gate was added.

The191/200result is development evidence and may reuse training data. It does
not establish95.5%unseen accuracy. The independently curated additional200 remains
ungraded and its Gold closed at this checkpoint. CPU132/134captures are already
closed. Production policy was locked before new queries; its capture began only
after actual public original200 cleared180/197. No result from new Gold selected
models or execution policy. Same8repos; no new-repository generalization claim.

Actual MCP original200 wall latency: p502448.979ms,p953632.497ms,max4346.855ms.
Server process peak RSS2119303168bytes in JUnit5(2446indexed files/21521owners),
1152778240–1401487360bytes in the smaller repositories. General tests overlapped
part of this run; timings are descriptive. Child per-query CPU is unavailable via
MCP: record null, report process-total CPU separately including setup/warmup and
sample compact checks; never compare it as per-query CPU.

## Responsibilities and production changes

- SourceCatalog authenticates physical source and canonical ownership. Its
  inventory matches all39810owners in the8source controls.
- piece_cards preserves measuredv102neural inputs:64physical lines/4excerpts/12k.
  3928existing cards across200queries have identical model input text. Presentation
  independently shows at most16physical lines per result, numbering each line;
  contiguous fragments merge only for display. No fabricated ellipses/ranges.
- assemble_pieces consumes actual ranked owners instead of exporting/parsing a
  1200x251diagnostic trace. Complete declaration/member descriptions remain the
  same. PieceSearch owns the piece forest, fixed RRF60/.5, named-path priority and
  top10permutation invariant. Display limits apply after reranking.
- ContextVectorCache reuses model+text-bound normalized vectors; prepare_context
  builds complete/full plus contract/implementation mmap snapshots with artifact
  hashes. Source-only migration into normal project stores reproduced all full
  and view vectors bit-for-bit. Context owner proposal ties retain the measured
  ASCII-escaped canonical SQLite order, even for Unicode identifiers.
- SearchResources shares lazy CPU context, local ES→EN expansion and Ettin68MFP32
  sessions across roots. BestSearch prepares a separate Potion passage profile,
  never mixes Qwen or other legacy vectors, caches project source by generation.
- MCP reuses bounded, serialized project connections, giving generation caches a
  persistent lifetime while still reading fresh WAL commits. Exact unique
  class/callable lookup and empty repositories require no downloaded models.
  An old symbol-only index can backfill source passages without loading models.
- New project recommendation is PotionCode16Mv2; user overrides and existing CI
  vector pins remain intact. ken retrieval prepare explicitly separates complete
  model/index setup from prepared query latency. Default semantic queries also
  prepare when necessary; no silent legacy fallback is called the best engine.
- piece_kind=auto/class/module/symbol/file is carried through CLI and MCP. Auto
  exact class lookup returns the class. --json/output_format=json retains the
  actual default engine and requested primary unit, rather than switching rankers.

## Validation and receipts

Focused real tiny Model2Vec/ONNX, source integrity, stale inputs, lexical nesting,
member evidence, complete source snapshots, exact/empty/old indexes, CLI and real
persistent MCP tests passed. Full suite14901passed/10preexisting xfail; two later
connection/setup tests passed in their focused runs. Mypy356source files clean.
Final full-suite rerun is still required after all final changes/review.

Generic/source checkpoint output/checkpoints/generic-production-models-v140-v145
has47compressed receipts/captures (1374992bytes); manifestSHA
c65e9cbdf2dd39eda0e0df1d2b5338f9420c6f80704991aa2cf5276312d3039b.
Production frozen145SOURCE-MANIFEST receipt:
d95c87a9c3d35cf2191c029b4d61186a040bc34dc96fd286d7c8b69e30fe8fbc.
Original200MCP lockSHA2074e8d3143d6a8ef853258ff308aa2b80fbcb3692f73eb6861371f3a74afac7.
Additional200production lockSHAc01904ab0feeb6df76499345dfac8324c0544300352365a54858f45af987fc16.

Parent producer and server both execute with frozen145/src on PYTHONPATH and
model-runtime Python; the launcher pins the server's environment. JSON answers
are from actual MCP calls. Native/compact parity is sampled once per repository,
not all-query format parity. The public identity capture covers every query.

Independent scorer review found missing old-arm closure hashes, extraneous empty
repos and invalid resource values. New wrapper now authenticates both files for
all3arms, requires exact repo/IDpartitions, finite nonnegative wall/CPU/RSS and
strict bytes/KiB units, and leaves immutablev135c unchanged. Regression probes
first reproduced6improper acceptances, then27combined scorer tests passed. No
Gold was read. Final three-arm scoring lock/review remains pending closure.

## Outstanding

1.Close and independently grade production additional200against both frozen CPU
controls, only after all three complete closures and pre-Gold guards. Report
cohorts/types separately. If feedback drives changes, it is now exposed and needs
fresh acceptance; do not silently reuse it as untouched.
2.Final review, current full-suite run, regenerate all output examples, portable
wheel check, reconcile original checkout's foreign changes without losing them,
commit and push main. No release/tags.
3.Optional accelerator selection still needs source-free parity/cost validation;
current measured path is CPU-only. This Mac advertises CoreML but availability
alone proves neither real acceleration nor a speedup. Official configuration:
https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html.
4.Fix stale CLI default-model --clear label/model listing comments to report the
actual recommended Potion; recommendation itself is already correct. Do not alter
ranking policy while the independent capture is running.

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

## Local integration and validation checkpoint v147

Main dea7035816c59ba976e5d495542ede63c215a06e was pushed and ls-remote verified,
without tags/releases. Original checkout advanced from6286d910 todea7035 via
guarded three-way update, retaining61foreign changed tracked files,754untracked
backups and all foreign source/features. Six conflicts reconciled and211merged
preview tests passed. Original now63dirty tracked paths (some former untracked
constraints/plans became tracked); staging remains empty. Raw backups, candidate
resolutions, per-file hashes and rollback snapshot are in
/Users/andres/Projects/ken/output/local-main-update-2026-10-16-v147. No foreign
working content was committed or uploaded. No reset/stash. Local .venv installed
missing declared CPU packages/model2vec0.9.0/onnx1.20.1/CT2 4.8.3/SPM0.2.1; HF
normalized from1.14.0 to required0.36.2. Frozen model runtime remains pinned.
Actual default-model/models now print Potion as default. Already running MCP
processes still require restart to load new modules; no restart was claimed.

Current complete clean suite:14902passed,10preexisting xfail,544.27sec;
/private/tmp/ken-best-default-suite-v147.log. Mypy356source files clean.
Additional12feature/training-boundary tests passed after first red runs.
The frozen145public observer closed all200old cases, preserving every actual MCP
unit order exactly; no exact bypass in that dataset. Source calibration schema
SHA4e6eb5dd419e5a234c9b5abac99020ed8522eb5c77ca35ad240aa15d5643ff3f.
Capture registration SHA677145fa81167a15fd24a3c22d76c5c338fb5107af8656ebc4169ecd1b965964
at research/output/development/score-calibration-v147/old200-capture.
No calibration models fitted yet; new exposed symbol200and fresh reserve200
are still independently curating. Prospective protocol is
docs/design/requested-piece-calibration-2026-10-16.md; fixed34or296features,
original fixed LambdaRank recipe, repo-excluded development; unchanged top10.
Independent88.5%result remains the latest unseen quality, and fails90%.

## New development and guard review — continuation v147

New exposed symbol200 curated independently:48source files/8repos,120EN80ES,
160behavior40qualified lookup,130runtime/API+70test/support; all<128partition,
zero375excluded-file overlap. v1andsealedsource receipts are preserved at
research/experiments/search-engine/datasets/symbol-development-20261016.
Independent review read all200queries/witnesses and14extra source contexts.
Gold primary identities/alternatives/ranges/hashes/quotas were valid;041strict
mode and060structural-ref wording needed precision. No ranking/quality was read.

v2directory symbol-development-20261016-v2 changes exactly those2wordings and
corresponding facets/requests/rationales; every identity/alternative/range/hash
and ordering/quota remains unchanged. Seal28fb14ea30cd757d3fdbb73fbeea93ef435ed6bd36482da30d2cc4489cf1afe2;
public SHA b90ce15d819b1da2e38b5d11e79f21d2f3550c3582cfdc532a6df3c45bda80f5;
exposedGold SHA7f9293b9eb69da668ecd337f4902b0a00f99cddd22e9806b6334d5b1583c021d.
Independent v2review APPROVED receipt e6a2452f27641f8d3d81e9565a4f0a7d36a6c323d0ce4796297b4c755dcfb91c
at research/output/analysis/symbol-development-reference-review-20261016-v2.json.
The v1feature capture closed but is NOT fitted or graded. A complete fresh200
observation run of v2is running, same frozen145source. v2lock
7095562ff9d6ede4227c2781f53d1bb410e67866bc4d6c4c92305f87cbe2f64b.
Queue output/analysis/queue-calibration-fit-v147.py waits full closure then writes
fit-manifest.json and runs the fixed A34/B296 development LORO/pooled fit.
Logs /private/tmp/ken-calibration-observe-symbols200-v2-v147.log and
/private/tmp/ken-calibration-fit-queue-v147.log. Do not modify fit code while queued.
No reserve labels are inputs. Fresh private reserve200primary files uses>=128,
50/type,120EN80ES,160behavior40lookup and is still in cross-review. Parent has not
opened its payloads; only curator paths/seals. Draftseal5ce1b548cf60c2d078dbf1fa002fae6b9b7f5891658d83bc912675c21734b206.

Fresh single-arm scorer preserves immutable identity evaluator/denominators and
adds protected-reference boundary before ALLpreflight reads (resolve+dev/inode),
canonical DTO validation, per-type quotas, actual producer/launcher hashes,
strict default/source policy and closed public source/resources. Independent
review first found17defects; all reproduced red then26tests passed. Corrected
source200c9d19b6a0c139c17b454a49108f77f5082e79db540b8f8d17f85890459cb3.
Second independent review APPROVED:26tests+13probes,39instrumented preflights,
36rejects/3valid,0Goldopenattempts. Receipt
research/output/analysis/fresh-public-piece-score-review-20261016.json
SHA58c529cb49d9532d94999f3cec197c33e6be470613af8e88beb1052f2dcc5663.
Code approval does not waive actual freeze/closure/preflight or authorize scoring.

Local normal HFandKen model caches were populated from the same verified public
assets without uploads or index changes. Actual original .venv normal defaults
passed a synthetic source-free probe:256static dimensions,768context,neural score
5.957465648651123, CPUproviders both, noTorch/transformers imports. Receipt
research/output/analysis/normal-local-model-cache-v147.json. Installed package
compatibility check99packages passes. Wheel built locally only; packaged model
imports/fingerprints verified. No release/tag/version bump.


## Closed calibration and source diagnosis — v147/v148

Both400public observations closed before fitting. New-symbol v2 registration
SHA e0d6d94e93fb839148744e57c608a22e07923d1a468591914b8ff656215270b8.
Original observer200 has exact order parity with actual public MCP145200.
Fixed A34/B296 fitting completed in separate CPU training environment after an
initial missing-LightGBM import failure (both receipts retained). No runtime
LightGBM dependency was added. A LORO359/400:original194/200top1,197top10;
new symbols165/200top1,193top10. B357/400:original192,new165; same Recall.
A was selected by prospective overall rule but FAILS required180/200new-symbol
gate. Pooled388/400(original197,new191) is TRAINING REUSE, not validation;
model0d458f7e2878382dd1766d64c43ff3ff05e1c7eb8ffaaeee4c51aaa2b8a98fce
is NOT integrated. No private reserve evaluation is authorized by these results.
Exposed source/capture/models/labels/receipts are gzipped with manifest in
output/checkpoints/score-calibration-development-v147; private reserve excluded.

New exposed-symbol native/piece/neural/final:129/129/169/144top1; calibration165.
Original170/191/168/191; calibration194. This isolates ranking from7new and3old
missing-positive pools, which cannot be repaired by permuting existing top10.
Inspection of exposed failures found request_tests==0 even for explicit test
requests because piece_features compares unresolved request.purpose=='tests'
while public callers pass auto. interpret is the authoritative owner of purpose.
In addition regression/regresión and Localiza test requests are not recognized
by its requested-noun parser; many failing tests are therefore treated as runtime
implementation. Keep those fixes separate in controlled measurements. The new
suite intentionally has70test/support cases and130runtime/API, not equivalent
to the previous balanced private200. No query-specific paths or Gold rules may
enter the engine. Other remaining errors confuse adjacent functions, nested
helper versus owning test, negation and overloads; intent alone will not solve all.

Fresh reserve v2 source-only wording revision independently conforms:200units,
437ranges unchanged, three precisions, receipt c1c2886a75c96ec5d25a27ee71df1f5296f1d87cbf704281739c953ab9d28cd4.
Private Gold remains unopened by implementer. Scorer FG5/FG6 first reproduced
red3/3, then fixed canonical duplicates using immutable identity_hit and reject
resource aggregate overflow/nonfinite values. Corrected wrapper SHA
c7df72f16485aa3529b3c80c0558178ac3b90a07ad5c3fd4999032a3c63cd419;
independent re-audit e8bef006df1e573aaf7a71f7498a811ac2dde136a84920f2c67d7271a9986ca4,
56tests,23synthetic probes plus valid control, zero reference open attempts.
Actual final engine freeze/complete capture/preflight review still required.
