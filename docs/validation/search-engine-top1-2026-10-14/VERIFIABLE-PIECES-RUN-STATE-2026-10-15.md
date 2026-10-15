# Verifiable pieces CPU comparison — running state

Updated18:55UTC. The user authorizes the new benchmark and17/32/68M comparison.
Latest steering: Ken's initial top10 should cover the correct piece in≥95% of
queries; a small reranker discards clearly irrelevant candidates and orders the
remaining candidates; final≥90% requires correct piece plus sufficient evidence.
Both positive ranking and negative rejection are useful. Uncertain is distinct
from irrelevant, and abstaining never counts as success in the full denominator.

No new quality percentage exists yet. Historical71.5% strict and the Semble NDCG
comparison keep their old definitions and are not this utility metric.

## Closed preparation

- Own branch codex/search-engine-top1, scaffold commit b9d9ddb. All work lives in
  output/search-engine-2026-10-14/workspace; no edits to the original dirty tree.
- Protocol experiments/search-engine/cpu-verifiable-pieces-v98.md;200cases,
  50eachclass/module/symbol/file,120EN80ES,160behavior40qualified_lookup.
  Cards≤64literal source lines,4excerpts,12000canonical JSON characters.
- Existing69repo-excluded numeric ranking + source7 context views is common.
  Baseline+Ettin17/32/68 share identical top10 cards;20stored for diagnostics.
  No model fit, HPO, Gold injection or production default change.
- All-source8metadata sealed at
  /private/tmp/ken-verifiable-pieces-benchmark-20261015/source-metadata/manifest.json
  SHA8e0dacf95cf71156f85e711ad6e16088c1172a0a478dcd7ffbe1b4b24ee16e37.
  SourceCatalog receipt output/analysis/verifiable-pieces-catalog-v98/receipt.json
  SHA0f4d8dae05d226bd593d9fdd3610919af8a4f2db70d49fc05915cc5823ea02b2.
  39810owners,4760tracked blobs; no queries/Gold read by root before closure.
- Canonical comparison33965/33967 source parser identities exact; two same-line
  Ajv methods do not survive source7 passage grouping. No divergent source hash.
  This is an index limitation, not a reason to remove queries.
- Three published Apache2 ARM64 INT8 encoders plus their matching published
  CLS/Dense/GELU/LayerNorm/Dense heads assembled locally. Registrations/graphs at
  output/models/ettin-all-onnx-v98/{17m,32m,68m}/assembly.json. AllCPU, noTorch.
  Reference head deltas<2e-5;32/68independently audited. Not FP32 backbone parity.
- Producer/policy snapshot output/frozen/verifiable-pieces-v98/CONTROL-MANIFEST.json
  SHA26b4189b322e541373e5fead6892f14685b42ce69ba093ca35a2534e65c06375.
  Real comparison must run its immutable scripts, with existing core snapshot
  cpu-rank-consensus-v97b receipt bec2c778…7fc3.14boundary tests pass in own tree;
  frozen primary snapshot includes11tests (filter add-on followed the freeze).
- Public-only full CPU worker recomputes retrieval for each arm, checks exact
  pool/card/expansion digest, records complete prepared pipeline latency and RSS.
  Gold/scoring cannot enter it. Guards authenticate ALL8before queries open.

## Curation and review still running

Two already authorized agents, only curation/review: independent_retrieval_corpus
does50class+50symbol and10calibrationfamilies; development_reference_review does
50module+50file and10families. Each later judges only the other strata without
that Gold. Class/symbol latest count50drafts, module/file not final yet.
Each type30EN20ES and40behavior10lookup. IDs vp-cs-/vp-mf-, cal-cs-/cal-mf-.
Eight previously transferred module drafts are excluded from final and calibration
because their Gold was already known to the intended consumer. Calibration uses
20families/60cards and is globally file-disjoint from principal via opaque HMAC
intersection checks between curators; root gets only receipt/counts.

Root has not read any new public query, new Gold or old private reserve contents.
Earlier broad tmp filename discovery traversed unrelated temporary trees; no
private content was intentionally read or used. Further discovery is restricted
to explicit roots/assets. Never recurse the old reserve.

Blind output: per-public-facet supported/contradicted/unobservable with literal
citations, R0–2/S0–2, abstention. Positive requiresR2/S2/allfacets supported and
authenticated source. Calibration gate≥90%pass/fail agreement,≤5%falseaccept on
40negativecards; otherwise no calibrated utility success claim. Root Gold access
only after all principal blind judgments close. Persistent contexts/familiarity
are disclosed. Gold is identity/source audit, not exact-snippet/ALL-anchor score.

## Resource preflights, not quality measurements

Synthetic4query Python integration v98c closes all4arms and source-authenticated
anonymous inputs. No new corpus query used. Supplementary Java/TS stress v98 was
aborted after the controller detected that its own source pin had changed during
the run. That partial attempt is preserved; actual comparison uses immutable
snapshot to prevent this. Completed Java workers still provide diagnostic point
observations:2446indexed files, two synthetic queries perarm, baseline1.01/1.24s
peak1.286GB;17M1.19/1.27s1.375GB;32M1.34/1.43s1.424GB;68M1.89/1.67s1.497GB.
Not percentile estimates, quality evidence, causal memory increments or production
default API certification. No concurrent model benchmark is allowed.

## Remaining steps

1. Finish and seal both100case public/Gold corpora separately; merge only public.
2. Run frozen comparison on all200; no interim Gold or quality tuning.
3. Authenticate calibration cards and principal answers; blind cross-curator
   calibration, audit own labels via aggregate reports, then principal review.
4. Seal all principal judgments before opening Gold. Score identity,Recall10/20,
   blind verifiability and joint utility pertype/language/style/repo, plusCPU/RSS.
5. Optional scalar-filter shadow: after principal judgments close, calibration
   labels select minimum score among40faithful correct-unit cards, including
   sparse cards; apply unchanged to principal10scores. Same-score filtering can
   suppress all candidates but cannot promote a different top1. Report lost
   correct candidates/Recall10afterfilter and known-irrelevant rejection; do not
   call every non-Gold candidate irrelevant. Neither precision-on-answered nor
   abstention can replace the original denominator.
6. Report actual outcomes and limitations; no claim90% unless jointgate is met.

Historical96b/97b independent audits also closed this turn:268/292 and285/297 vs
baseline286/298, no adoption.1600responses/sourcecaps verified; source reports
remain output/analysis/{lexical-context-ranking-v96b,rank-consensus-v97b}-final-review.*.


## Update19:36UTC — public200 sealed, CPU comparison running, calibration blind started

Main public merge: output/development/verifiable-pieces-v98-public/cases.jsonl,
SHA837a88a2c995a58257142ab763b8ac0035abc35b9d5f06759778f7ac3074305e.
First public main parse by root program19:14:32UTC after producer freeze. Main
Gold remains closed. Actual serial comparison output/development/verifiable-pieces-v98,
exec session9396. All8baseline workers/200answers closed; NN17/32Ajv closed with
exact shared-pool/card/expansion digests. No quality scoring or engine adjustment.

A prospective additional shadow was frozen before the first public main parse:
filter survivors then preserve originalKen order versus filter then neuralorder.
PolicySHA8a01005d2f13c108f6eee0e5ed1d5b32cf76db70a31d0db0b2ee4a365e6409e6.
Implementation freeze output/frozen/verifiable-filter-native-v99, receipt
5fe6dea3b3082104754fecd103efa9691d4ec2e6340fbbf42e93c6c8dd672ed4.
After initial main judgments close, open ONLY calibrationGold for fixed thresholds;
blind-review any newly selected query/card pair, then seal ALL judgments before
any principalGold. Same-score filter alone cannot improve neuraltop1. Empty or
all-rejected selections remain failures on200, not dropped cases.

Source authenticity and renderer evidence selection are separate responsibilities.
An attributed caller+helper quote can be authentic even from anotherowner/file;
blind source evidence still must prove literal query responsibility, all facets,
and relevant delegation. The v98 renderer/validator remains unchanged and can
therefore fail sufficiency when it omits a needed helper. New calibration-only
sourceauth amendment freezes at output/frozen/verifiable-calibration-auth-v99,
manifest087a9816e8c4692ad3a262448f3d1063af18844954e96a625de859af57bf83bd.
Its manually entered19:30minute was a typo; TIMESTAMP-CORRECTION retains original
bytes and actual mtime19:29:03.907685UTC, before observed first public calvalidation
19:29:14UTC. No calibrationGold was opened.18existing+auth tests and2shadowtests
pass,20total; actual primary frozen tests unchanged.

CalibrationCS firstseal had one trailingLF in all55excerpts, causing30literal
mismatches. Curator preserved oldseal, repaired ONLY content terminalLF in a new
calibration-cs-v2, unchanged queries/ranges/identity/sourcehashes/criteria/labels.
CardsSHA7647c890c90dbd6c84b5c695b5b3cbfff370458e2dfeae080705878b22cab9c7.
All60public calibration cards now source-authenticated (source-v99b receipt).
Anonymous30CS+30MF at output/development/verifiable-calibration-blind-v99b.
Existing curators started cross-stratum review, no variant/engine/model/Gold or
source browsing. Expected output output/development/verifiable-calibration-judgments-v99b.
Both30must seal before feedback; only aggregate ownGold audits come to root.

Timing limitation: baseline first3repos median~7.1–7.8s, others~1–1.7s.
Ajv17/32 commonretrieval median~0.97s versus originalbaseline~7.3s, despite exact
sharedpool digests. This large temporal variation cannot be attributed to model
speedups; model inference itself is separately timed. Preserve original timings
and investigate measurement stability before claiming causal end-to-end overhead.
Originalbaseline RSS maxima~1.41GiB on2446fileJUnit; others~0.62–0.94GiB.
All numbers here are resource observations, never new utility percentages.
