# Estado actual — piezas verificables

Candidato nuevo v126:175/200=87,5% de identidad top1,197/200=98,5% top10;
CV excluyendo el repositorio evaluado. Siete ganancias y cero pérdidas frente al
nativo168. No es default publicado ni aceptación privada; falta integración y
medición completa. Tipos:clase47/50,módulo45/50,símbolo43/50,archivo40/50.
La investigación, todos los valores y los pasos para retomar están en
[scoring-internals/README.md](scoring-internals/README.md) y RESUME.md.

Actualización explícita del usuario,2026-10-15: el objetivo principal es>=90%
top1 con la pieza correcta; la suficiencia de evidencia retornada queda como
métrica separada. Identidad nativa actual168/200=84%,Recall10197/200=98,5%.
Los protocolos históricos sellados conservan su definición conjunta. Ver
RANKING-CAUSES-V121.md para las causas observadas y el control de una sola señal:
igualarrrf_rank gana4/pierde15 y baja a157/200; no se adopta.

ActualizadoUTC: 2026-10-16T00:05:00+00:00.

Último resultado conjunto cerrado: v116102/200=51%, identidad168/200=84%,
Recall10197/200=98,5%. v11193/200=46,5%;v10989/200=44,5%;v10580/200=40%;v10276/200=38%.
Control de identidad, NO conjunto:68M FP32 v110RRF50 175/200=87,5%; v112prefijo3
raw175/200=87,5%,RRF50 174/200=87%, conservando todos los10candidatos.
CPU completa v116 mediana1,219s/p952,363s/pico1,531GB; sin reranker neuronal.
CPU v112 sólo reranker mediana0,962s/p950,991s/pico0,724GB; no total Ken.

Checkpoint de implementación0435c55c5f255cfa68eb5a2b875e22cc07529250 verificado
en GitHubmain; incluye8fcd2d0(v114),bb1f36cf(trazas),4d11b631(composiciónv116)
y respaldo683archivos/593gzip/104968967bytes, todos descomprimidos y hashverificados.
v116gana2/pierde0 respecto av114;22tarjetas nuevas revisadas independientemente,
178opiniones reutilizadas sólo con entrada visible idéntica. Ver VERIFIABLE-SCOPE-COMPOSITION-V116.md.
Diagnóstico nativo v120:200trazas cerradas y101764scores+orden reproducidos;
29/32errores top1 tienen la pieza correcta en top10. Exportación limpia de Git más
cambios propios; los8archivos de trazas coinciden byte a byte con v118.267tests
retrieval+36enfocados pasan y mypy337fuentes limpio. Ver NATIVE-RANKING-DIAGNOSTICS-V120.md.
Control LateOn-Code-edge17M FP32 v115 cerrado:raw149/200=74,5%,RRF50 168/200=84%,
RRF25 169/200=84,5% (4ganancias/3pérdidas,intervalocluster[-.018519,.035299]).
Sólo reranker:mediana1,688s/p955,670s/pico0,345GB. No mejora confirmada.
Nuevos ensayos neuronales pausados por pedido del usuario.150M preparado sin ejecutar.
No release, tags ni cambios de default. Original checkout sucio sigue intacto.
Privada v104:200casos curados, nunca abiertos por implementador; no ejecutar hasta
congelar una nueva versión. El objetivo90% conjunto sigue pendiente.

## Notas históricas de preparación (superadas por el estado de arriba)

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


## User clarification 2026-10-15T19:53:19.812942+00:00 — optional automatic acceleration

CPU is the mandatory usable fallback and the platform on which latency must meet
the user budget. GPU is allowed and should be used when available AND faster.
Normal runtime should detect usable providers/devices, compare representative
whole scoring latency including transfers/initialization separately, cache the
choice per model/runtime/device, and fall back safely to CPU. Do not assume
accelerator availability implies lower latency for ten small pairs. Preserve
explicit device overrides. The active comparison remains CPU-only by design to
verify the minimum requirement; it does not prohibit optional production GPU.
The user reference remains roughly1s per100repository files, earlier3–5s response
expectation, modest RAM; no new hard numerical cap is invented from the letterX.
Quality gates Recall10>=95% and jointtop1>=90% stay unchanged.


## Update20:14UTC — ALL800 closed, blind345review running, no Gold/quality read

Actual comparison session9396closed0. Registration output/development/verifiable-pieces-v98/
registration.json SHA2ca7cfb34540543f17b8fa28619dc363e13c9c192f066b95473038836c92b482.
All200baseline and200each17/32/68 outputs closed, all exactsharedpool checks pass.
CPU primary p50/p95ms: baseline2501/11820(variablefirst3repos),17M1373/2459,
32M1650/2661,68M2497/3633. Rerankonlyp50/p95ms205/246,479/566,1370/1580.
MaximumwholeprocessRSSMiB1448baseline,1521/1587/1689neural; includesload/warmup.
Of1988neuralpairs permodel,470documents truncated to512tokens. Not quality evidence.

Performance-only repeat session37164closed0 at output/development/
verifiable-baseline-timing-repeat-v99. ALL200answers/pools byte-exact vsoriginal;
repeatp50/p95/max1152/2217/3662ms,peak1456MiB. Preserve original and repeat; cannot
attribute temporal common-stage change to a model speedup or subtract percentiles.

Publiccal60 sourcevalid via CSv2+MF; serialcalmodelscore session90686closed0 at
output/development/verifiable-calibration-scores-v99b. No labels used in scoring.
All60blind judgments sealed942dfc7a…79fe4. Eachcurator audited their owncalGold
AFTER bothjudgmentseals, rootreceivedaggregateonly. Gate file
output/development/verifiable-calibration-judgments-v99b/CALIBRATION-GATE.json
SHAdd9e03aed53c71d6e896109b875affa28639cbdcbb06d68bcf5aeb24f4563dc3:
60/60passagreement,0/40falseaccept,0falsereject. OrdinalR/S differences remain
limitation, no calibrationjudgment changed. Generalclarification frozenbeforemain
at output/frozen/verifiable-calibration-auth-v99/verifiable-judge-clarification-v99.md
SHAa4b0bf97785b41bb8f194366a1b4e7ba8f0a73bed98f0cef0700f487a55d09f1.

Primaryblindsourceauth finished: output/development/verifiable-main-blind-v98.
800answers deduplicate to345visiblequery/cardpairs: class-symbol163,
module-file182. Receiptfile pins CS3ecf751910abda90367ac32b6275cb3fdf15cd0b261c73c175a7af2d7cb76d6d,
MF69957cce241e9597fec8322522d8c036afb7ba2cc1628d4fc5190a62b52fd1d0.
ExistingreviewerB judgesCS; curatorA judgesMF, onlycurrentrow, no sources/Gold,
model/score/mapping. Outputs output/development/verifiable-main-judgments-v98/
{class-symbol,module-file}.jsonl. Lateststatus80CS/140MF, notsealedyet. Rootnever
reads mainoutcome summaries before closure and has opened NO newprincipalGold,
NO calibrationGold, NO oldprivate acceptance reserve. No new utility percentage.

After345initialjudgments close: verify exactIDs+cites, sealoriginalprincipalstatus
'ALL principal blind judgments closed before Gold' with original inputreceiptSHA,
judgmentfilepins andcalibration_gate_passedtrue. Onlythen open separatecalGold
(paths askcurators, no broadtmpsearch) to run frozenv99verifiable_shadow.py.
It compares reject→neural and reject→preserveKenorder, all200denominator.
Generate shadow extras with frozenv99verifiable_shadow_blind.py, de-dup against
345sealedvisibleinputs, crosscuratorsjudge NEWpairs only. Sealcombinedstatus
'ALL primary and shadow blind judgments closed before principal Gold' with all
judgmentfilepins, principal_input_receipt_sha256,shadow_input_receipt_sha256,
principal_judgment_seal_sha256. OnlyAFTERFINALseal openprincipalGold and run frozen
v98verifiable_report.py using ORIGINAL345judgmentseal (extraIDs forbidden there),
then frozenv99verifiable_shadow_report.py with finalcombinedseal andprimaryreport.
Preserveoriginalscores; anyunlistedsemantic alternative needs independentsource
audit uniformlyapplied toALLarms with the sameliteralquery/type/owner criteria.
No90claim unlesscorrectpiece+visibleR2S2/allfacets/source andRecall10>=95%gatespass.

## Optional accelerator investigation; CPU requirement clarified by human

NewDEVICE-REQUIREMENTS-2026-10-15.md and kenmemory
search-engine-device-requirements-20261015 recordCPUmandatoryfastfallback,
GPUoptionalautochoosefaster, not CPU-onlyproduct. Existingembedder alreadyhas
autoGPUpriority/fallbacktests; future reranker mustreusepolicy, add measuredchoice.
BenchmarkforcedCPU unchanged. ORT1.25.1availableCoreML/Azure/CPU onhost.

Source-freesynthetic provider probes only, nevercorpus/Gold. Frozen
output/frozen/verifiable-provider-probe-v99 control5b6378ed…569d; trials
output/development/verifiable-provider-probe-v99 first failed nativeTMPdir.
Secondv99b withTMPDIR=/private/tmp/ken-coreml-probe-v99 failed Library/Caches/python
sandbox. Single17escalatedv99c(auto-approved) gotpastcache butCoreML rejected
unbounded dimensions. Noauto-reviewrejection; no pendingpermission. Nativecache
outsideworkspace is incidentalCoreML requirement, userGPUrequestauthorizestrial.

Shape-only17MINT8probe frozen output/frozen/verifiable-fixed-provider-v100,
controlba1d9a400f53e5098aeeccb933c1cd356f38cb2c748fb12fd3f5fff01e97c8ab.
Executedwithescalation(auto-approved), session62811closed0. Derivedsameweight4x512
graphpadsfinalbatch withvalidduplicates andtrimsscores;2boundarytests pass.
Results output/development/verifiable-fixed-provider-v100/report.json:
CoreMLactuallyexecutes153events+357CPUevents. Short/longmicrotimes459/464ms vs
originaldynamicCPU12.4/226.9ms. StaticCPU247/257ms. PaddingCPUshortchangeslogits
max0.8369(long0.0), CoreMLvsdynamicCPUshort0.732/long0.245 andrankdiffers.
NoGPUdefaultpromotion. Causeofpaddingeffectnotyetisolated; dynamicquantization
is ahypothesis. Kenmemorysearch-ettin-padding-coreml-probe-20261015has evidence.
Do not claim APIlatency or200quality from thesesynthetics.

Currentadditionaldiagnosis: download samepublished17MFP32encoder (notlargermodel)
to output/models/ettin-17m-fp32-source-v101/encoder.onnx. DefaultDNSblocked before
filecreation; retryexecsession62661running withnetworkescalationautoapproved.
Publicrevision9e4aa35321a6dd1a43ca313f500c4b4f7cfb5cc6, SHA256
2a375ccea150a4df925a47884b510eeb4bd6227ca6fffdbbc62ca2284bfe6211;
o source/query sent. PurposeONLYsource-free precision/padding/provider diagnosis;
no additionalcorpusarmregistered/requiredyet. Attachsamepublishedhead and verify
NumPyheadparity before runtimeprobes; do notmutate frozenINT8assets ormaincontrol.
Officialdocs readCoreML EP and make-dynamic-shape-fixed helpers; linksincontrols.

Currentownedcommit0aac155 afterb9d9ddb/79834e8. Pendingownnewhelpers/reporting/docs
are ignored/untracked until explicitgitadd-f; neverstageall.26boundarytests pass
(20primary/auth/shadow+4devicechoice+2padding), no productioncoreedits. Foreigndirty
README/src/tests andolderrootdocs untouched. GPU/FP32research mustnot delay
sealingblindmain or leakGold. No newsubagent; existingtwo remaincuration/reviewonly.

## Correction20:35UTC — wrong padding ID discovered; controlled repeat v102

The experimental adapter used Tokenizer.enable_padding() default ID0 instead of
published [PAD]=50283. ALL3 pinned model configs/tokenizers agree on50283. This
is an adapter defect; the original neural ranking/calibration/device observations
are retained only as diagnostics, not valid model-comparison headlines. Common
baseline outputs do not call this adapter and remain valid. No main Gold or
quality aggregate was read before discovering or correcting this defect.

registered_padding now validates SHA-pinned upstream config/tokenizer_config,
checks token->ID and right-padding, and explicitly applies ID50283 in runtime
and assembly.2new tests reproduce default-ID/stale-pin failure and pass after
correction;28previous+padding boundary tests passed. Optional FP32 encoder
assembly override is recorded but inactive for all3 principal model records.
Frozen v102 CONTROL-MANIFEST SHA2f2a09ecfd6570274e353608da672727e9fe702d37bcb7e824acec40bafc28f4,
16files. Compared with v98,12producer files identical,2modified plus2additions.
Original v98/v99/v100 snapshots untouched. New serial ALL200x3 rerun started
20:23:21UTC, session66031, output/development/verifiable-pieces-v102. Reuses
unchanged baseline answers/pools/original timing explicitly; neural workers
recompute complete pipeline and assert byte-exact sharedpool/card/expansion.
This does not claim a new baseline timing measurement. Separate prior registered
baseline timing repeat remains valid and preserved.

Independent static technical review receipt
/private/tmp/ken-verifiable-pieces-benchmark-20261015/technical-review-v102/static-review-receipt.json
SHAaa8b159037a9e0b0d3a583b783b98af1d60bae4673d5ed2eb937897c45e890aa.
No blockers for active records;16freeze/24originalcontrol/24reusedworker pins
match. Review ran no inference or tests and did not inspect corpus outcomes/Gold.

ALL345original blind opinions closed and literal citations/schema checked:
CS163 SHA b38846b307d5eecfc74ebcf45e42423a4747a0c5c65775f5bb5de93d5e42f5be;
MF182 SHA11de23d4f76815c773b12459bd35f3118882a89ee3b1a6db82779d5aaf09c671.
Original principal seal ALL-PRINCIPAL-BLIND-CLOSED.json SHA
6659909b3d4f91c067728d3cd4b431ef2e964c22e7e980a51313aaf1ff9d2ea8.
No opinion changed from model feedback. Corrected outputs require new blindinput
anonymization; reuse only full canonical-byte-identical visible inputs. Newpairs
crossreviewed by same existing independent curators, then corrected rawseal.
Helper+3tests separately frozen at output/frozen/verifiable-blind-reuse-v102;
staticreview preceded an additional tested calibration-gate closure requirement.
No first-corpus Gold or quality summaries have been opened. Cal60 must also be
rescored with corrected padding after main CPU workers finish, before thresholds.
The earlier main/shadow/Gold gate sequence applies to CORRECTED raw judgments.

## Update 2026-10-15T20:55:47.463924+00:00

Corrected CPU serial repeat stillrunning session66031,20/24workers observedclosed;
no new Gold/quality opened. A public-only continuation waits in session31444
(/private/tmp/ken-post-padding-v102.py), then runs frozenv102blindinputs, frozen
identical-opinionreuse and calibrationrescorev99 with correctedv102runtime.
Outputs expected verifiable-main-blind-v102,verifiable-main-reuse-v102,
verifiable-calibration-scores-v102; receipt/logs verifiable-post-padding-v102.
No threshold or principalGold is read by this continuation.

Owncommits ae61ced(adapter/provenance/providerhelpers) and97fb5cf(blindclosure).
Newclosurehelper frozen verifiable-judgment-seal-v102 manifest
e59ccf994385dbce524edfd7bb3f91b8c2fd77cd23c7ceed237ac112e8bbfd68.
Independentreview found/rechecked facetpermutation and read/hashrace issues;
6tests nowpass including mutation aftervalidation. No criteria changed: exact
unique facetcoverage matches frozenblind_pass. All39helperboundarytests pass.

Source-free numericalstabilitydiagnosis registeredbeforemainquality/Gold at
output/frozen/verifiable-stability-correct-padding-v103, manifest
ea84773a2668ae9995a0c9cf0e1292680c2669946f622ee6a19890c6179abc20.
Same17Mpublishedrevision INT8vsFP32, correctpad50283, short/capped512,
batch1/4/permuted/fixed512;2identity/permutationtests pass. NO corpusarm or
production adoption. Do not execute until main AND publiccal scoring close.
HostCPUcontention observed during17MAjv and68MAttrs/Boltons; allrawtimes
preserved, no externalprocesschanged. Details /private/tmp/ken-benchmark-resource-context-v102.txt.
Do not infer model speedordering from temporallydrifting commonstage.
