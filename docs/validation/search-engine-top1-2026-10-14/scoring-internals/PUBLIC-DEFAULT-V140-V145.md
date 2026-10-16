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
