# CPU verifiable pieces comparison v98

Authorized by the user's 2026-10-15 request to build the revised benchmark and
compare Ettin17/32/68. This is a new evaluation, not a relabeling of development400
or the original private reserve. No production defaults or old acceptance rules
are changed. The requested 90% remains a goal, not an assumed result.

## Fixed question and responsibilities

User steering before any real query/result was read: retrieval Recall@10≥95%
followed by final joint-utility top1≥90% (correct piece and sufficient verifiable
evidence). Identity-only top1 is reported separately and cannot satisfy the goal.
With95% coverage the reranker needs approximately
94.74% conditional success; identity coverage alone does not ensure usable cards.
The primary intervention reranks only ten; twenty remain a retrieval diagnostic.

Does the first answer identify the requested class, importable module, named
symbol or physical file, and let a consumer verify its requested responsibility
from that answer? SourceCatalog authenticates all source identities before any
new question is read. PieceProjection groups existing Ken owners at the requested
granularity. EvidenceCard presents literal, attributed source. FrozenPool fixes
the same candidate cards for all rankings. CPUReranker orders the first ten. BlindReview
judges only query requirements and visible cards; GoldAudit checks unit identities
and source-grounded alternatives after judgments are sealed.

Representative use: `prepare_catalog(all_eight_roots)`; then
`pool = ken_candidates(public_case, catalog).cards[:10]`;
`answers = {arm: order(pool, arm)[0] for arm in arms}`;
`review(public_case, anonymize(answer))`; finally `audit(gold, answers, reviews)`.
Missing candidates and abstentions remain in the original denominator.

## Corpus and granularity

200 independently curated positive questions,50 per kind. Each kind has30EN20ES
and40behavior10qualified_lookup. Eight pinned roots: packaging, pytest, boltons,
attrs, ajv, marked, junit5, commons-csv. Behavior questions do not identify their
target by name/path. Two or three public facets only restate the literal question.
Twenty separate calibration families each have sufficient, sparse and plausible
wrong cards. No old reserve or new acceptance reserve is used.

Class means an actual class declaration (not interface/enum/trait/struct).
Symbol means a named function, method or constant, excluding classes/modules/files.
Module means a file-backed Python import unit (including package __init__) or
JS/TS import unit; Java files/packages are not fabricated into modules. File
means a physical tracked artifact. Canonical entity tuples include kind,
qualname, owner and definition ordinal. Module/file identity is the relative path;
logical module name is supplementary. Supporting members retain their own owner.

## Frozen intervention

Baseline uses the existing repo-excluded69 numeric Ken ranking and source7
context views. The common projection groups classes using lexical source
containment, and modules/files by path, preserving best-member baseline order.
It never uses Gold. The first20 unique typed candidates form a diagnostic pool;
only its first10 enter the primary reranker comparison.
Symbol candidates are filtered by the public kinds above. All four arms use
exactly the same immutable card for each candidate. True unique exact-name
matches retain existing exact authority; other ties retain baseline order.
No training, query-specific rules, HPO, pool injection or cross-encoder ensembles.

Card schema: `{unit:{target_kind,path,entity|null,module_name|null},source_hash,
excerpts:[{role,path,start_line,end_line,source_hash,entity|null,content}],truncated}`.
All content is literal source, with real ownership and SHA256. No generated
responsibility summaries. At most64 quoted physical lines,4 excerpts and12000
canonical JSON characters per card. Signatures/docs establish declared contracts;
implementation claims need appropriate code. Evidence selection uses the query,
existing candidate evidence and source only, never facets/Gold/model scores.
Source-only catalogs and card policy are closed before public queries are read.
All pools/cards and outputs close before Gold is opened.

Models: pinned Apache2 cross-encoder/ettin-reranker-{17,32,68}m-v1, published
ARM64 INT8 encoder plus the matching published CLS/Dense/GELU/LayerNorm/Dense head.
Assembly parity is checked against a NumPy reference head on synthetic inputs;
this does not claim FP32-backbone parity. CPUExecutionProvider only, ORT2 intra/1
inter threads, batch4, max512 pair tokens, truncate only document, raw logits.
Queries use the identical existing local ES→EN expansion where applicable.
Record token truncation. No Torch/Transformers import or GPU/remote inference.

## Judging and metrics

Authenticate source, identity, ranges, literal bytes and budget without Gold.
Blind consumer receives one public query/facets and one anonymous card; no model,
score, expected target or source browsing. Cite visible evidence for every facet
before relevance R0–2 and sufficiency S0–2. Facet states: supported/contradicted/
unobservable. R2/S2 with all facets supported is a blind utility pass. A complete
wrong card can be S2/R0. A name or suggestive callee does not prove execution.
Unknown/ambiguous judgments count as failures pending explicit adjudication;
no case is silently removed. Persistent judge context/familiarity is disclosed,
and only current-card citations may justify a verdict. Calibration disagreements
are reported and general rubric clarifications frozen before principal judgments.
Calibration is a gate: at least90% agreement on pass/fail and at most5% false
accepts among the40 negative cards. If it fails, blind sufficiency remains an
uncalibrated diagnostic and cannot support a90% success claim. Both initial
judgments and disagreements are retained. Root never reads calibration Gold
before principal judgments close; each curator audits judgments of their own
calibration and reports aggregate errors/general rubric issues only.

Two existing independently authorized curation/review agents split class/symbol
and module/file. Each judges only the other curator's strata and never opens
that Gold before sealing all judgments. Eight previously transferred module
drafts are excluded from both final corpus and calibration because their Gold
was already known to the intended consumer. Source familiarity is not blindness
to repository semantics; only current-card visible citations support ratings.

After all blind judgments seal, objective top1 identity and candidateRecall20 are
scored against source-grounded acceptable units. Report Recall@10 as the primary
coverage gate (≥95%), Recall@20 as diagnosis, and conditional reranker accuracy
among queries whose correct piece was in the first10. Honest alternatives can enter a
separate documented audit; preserve original scores and denominator and apply the
same identity decision to every arm. No exact-snippet/ALL-anchor criterion.
Report identity, blind verifiability, and joint identity+R2/S2+source-valid utility
separately; per kind, language, query style and repo; paired gains/losses and
intervals (repo-cluster bootstrap for aggregate differences). This benchmark
does not estimate NDCG or certify general 90% acceptance.

## CPU resources

User steering on filtering: compare rank-only and discard-then-rank. One shared
forward produces continuous relevance scores, not calibrated probabilities.
An additional conservative scalar rejection threshold is calibrated only after
all principal judgments close, using separate calibration cards: choose the
minimum score among the40 faithful correct-unit cards (sufficient or sparse),
thereby retaining all40 on calibration. Apply it unchanged to the200 principal
queries and their first10 scores, keeping uncertain candidates. Report loss of
correct pieces/Recall@10 after filtering, known-irrelevant rejection on calibration
and blind-reviewed principal cards, answer coverage, false answers suppressed,
and joint top1 on the original denominator. Non-Gold is not automatically
irrelevant; it may be useful supporting context. Calibration families are small
and correlated; zero calibration false drops is not a general safety guarantee.
Using the same score means monotone filtering cannot promote a different top1;
it can clean lower results or abstain when all fall below threshold. This is an
offline shadow-policy comparison, not another model or production behavior.

Measure model processes separately and serially. Record cold asset/model load,
common prepared retrieval/card preparation, tokenization+reranking+serialization,
per-query p50/p95, process peak RSS, indexed files and machine/runtime. Replay of
frozen pools is labeled reranking latency/RAM, never full Ken API latency/RAM.
If complete pipeline runs are made, repeat common retrieval under the same arm
process and verify pool hashes before labeling end-to-end. Do not add separate
p95 measurements or infer full-pipeline peak by adding process peaks.

## Implementation / stop checklist

1. Freeze this protocol and curate public/Gold separately; build all-source catalog.
2. Boundary tests for canonical projection, literal cards/budgets, head math and
   invalid/stale sources; assemble and pin complete graphs.
3. Close all200 common candidate pools and all four outputs without reading Gold.
4. Calibrate then seal blind judgments; audit Gold and retain all failures.
5. Produce per-kind quality/resource comparison, explain limitations; do not promote
   a default or claim90% without measured evidence.

Scope note: an earlier broad tmp filename discovery traversed unrelated temporary
trees before this protocol. No old private reserve content was intentionally read
or used; this new corpus is independently curated and never uses that reserve.
All subsequent discovery is restricted to the eight named roots and exact assets.
