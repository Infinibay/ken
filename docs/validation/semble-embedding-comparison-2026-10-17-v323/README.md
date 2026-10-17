# Current Ken: Semble public1251 with three contextual encoders — V323

**CodeRank remains the strongest tested default for Top1/NDCG in the frozen
current engine.** Jina gains three Hit10 queries but loses 25 Top1 queries;
Muninn loses 22 Top1 and four Hit10 queries. Neither replacement reaches 90%
Top1. The UTF-8 repair eliminates the former Zig preparation failure. Most of
the measured historical improvement is recovery of that repository.

## Retrieval quality

All original 1,251 queries / 63 repositories remain in every denominator. Native
rank slots, original annotations and Semble's original evaluator are preserved.
The new capture has zero errors and zero missing responses.

| Engine / contextual embedding | Top1 count | Top1 | Hit10 count | Hit10 | NDCG@10 macro-repo | NDCG@10 micro-query |
|---|---:|---:|---:|---:|---:|---:|
| Ken: CodeRankEmbed 137M INT8 | 923/1251 | 73.78% | 1221/1251 | 97.60% | 0.847971 | 0.848550 |
| Ken: Jina code 161M INT8 | 898/1251 | 71.78% | 1224/1251 | 97.84% | 0.843813 | 0.843864 |
| Ken: Muninn-small 47M CLS FP32 | 901/1251 | 72.02% | 1217/1251 | 97.28% | 0.841007 | 0.841904 |
| Semble 0.7.0, historical V219 | 926/1251 | 74.02% | 1234/1251 | 98.64% | 0.851223 | 0.851428 |

Semble is a recomputed quality reference from the closed V219 capture, using
commit `8ee6463efbb1ff755c339e965c7298b7afd7db5b`. It is not a fresh matched-cost
arm. Its old timings must not be used for a speedup ratio. Macro-repo NDCG gives
each repository equal weight; micro-query NDCG gives each query equal weight.

**Correctness scope:** of 1,496 annotation targets, 1,462 specify only a path and
34 include a line span. There are 1,217 queries with file-only targets and 34
queries with a span target. This primarily measures target-file retrieval. It
does not establish correct-function accuracy, sufficient displayed evidence or
the strict-function 90% acceptance goal. This public benchmark has been evaluated
before; it is development evidence, not blind acceptance.

## CPU latency and RAM

Apple M1 Pro, 10 CPU cores, 32 GiB physical RAM; CPUExecutionProvider only. One
worker at a time; no competing test/model jobs during query measurements. Each
worker runs one generic unscored warm query before the original queries. Wall
time includes normal public find_best, compact rendering and canonical JSON
serialization. Ready-index measurements exclude initial preparation/model load.
Process CPU seconds sum thread work and can exceed elapsed wall seconds.

| Contextual encoder | Wall p50 / p95 / max (s) | Process CPU p50 / p95 / max (s) | Worker peak RSS p50 / p95 / max (GiB) |
|---|---:|---:|---:|
| CodeRank INT8 | 1.970 / 4.222 / 14.706 | 6.023 / 10.460 / 22.107 | 1.141 / 1.448 / 1.759 |
| Jina code INT8 | 1.991 / 3.841 / 14.016 | 6.065 / 10.409 / 21.390 | 1.399 / 1.709 / 2.105 |
| Muninn CLS FP32 | 2.015 / 4.006 / 14.303 | 6.134 / 10.614 / 21.765 | 1.313 / 1.613 / 1.883 |

Every arm has 1,251 successful timed queries, zero timed errors and zero untimed
failures. RSS is the whole-worker high-water mark including source preparation,
model load and warmup. Its distribution has 63 worker samples per arm, not 1,251
per-query memory samples. The separate shared source-index setup process peaks
at 0.311 GiB. Muninn uses native 384-dimensional vectors zero-padded to 768 for
the frozen storage interface; this preserves cosine geometry, but the observed
memory is not a native-384 storage claim.

The longest wall query in every arm is in Zig: 14.706 s (CodeRank), 14.016 s
(Jina), 14.303 s (Muninn). A p95 near four seconds does not guarantee that every
query completes within five seconds. This run measures cost; it does not
implement a latency optimization.

## Preparation and cache coverage

The source index is rebuilt once per repo using extractor8 and shared across all
three arms. There are 12,074 original admitted file records and 269,149 contextual
source views. Source prefill uses four concurrent batch1 CPU calls, bitwise
serial/parallel probes on five actual source views per worker, and a full join
before query timing. Query calls are serial.

| Contextual encoder | New / reused source vectors | Source-prefill wall total | Preparation + warmup p50 / p95 / max per repo (s) |
|---|---:|---:|---:|
| CodeRank INT8 | 34,998 / 234,151 | 16.03 min | 5.64 / 40.29 / 675.04 |
| Jina code INT8 | 269,149 / 0 | 107.73 min | 40.80 / 548.45 / 883.26 |
| Muninn CLS FP32 | 269,149 / 0 | 99.66 min | 37.23 / 509.21 / 842.58 |

CodeRank reuses exact model/text vectors from its pre-existing source cache; the
other arms start without matching vectors. These are observed warm-source-cache
setup costs, not a cold full-index encoder speed comparison. Shared static
indexing is additional: p50 7.92 s, p95 117.34 s, max 245.35 s per repo. Source-only
caches are retained outside Git; owned scratch projects are removed after each
repository.

## What actually improved

As a separately dated, posthoc comparison, V219 Ken8ce6b00 scored 912/1251 Top1
(72.90%), 1202/1251 Hit10 (96.08%) and macro NDCG0.836516. All 20 Zig queries failed
during preparation. Current CodeRank has 923 Top1 and 1,221 Hit10 matches:
+11 Top1 and +19 Hit10.
Zig contributes +9 Top1 and +19 Hit10; other repos contribute net +2 Top1 and
+0 Hit10. Multiple engine changes separate these revisions, so the historical
comparison is not an isolated UTF-8 ablation or a latency comparison.

The production fix is commit `1b07976d`, pushed to main before capture. Compressed
Zig `.input` fuzz fixtures contained invalid UTF-8 without NUL. Old extraction
replacement-decoded them into authenticated passages; faithful physical-source
loading then failed. Admission now requires valid UTF-8. Storage rejects obsolete
extractor metadata with the existing actionable preparation response; preparation
rebuilds v7 source projections even if their model profile matches. See
[UTF8-FINDINGS.md](UTF8-FINDINGS.md).

Four new regressions, 423 retrieval tests and the final full suite passed
(15,047 passes; 10 expected xfails). An isolated mutation of the migration guard
was killed. Production files were not mutated for that experiment.

## Where to focus next

CodeRank has 328 Top1 misses: **298 already contain a matching target inside the
returned Top10; 30 do not**. Ordering/selection is therefore the larger remaining
opportunity. This partition does not identify a specific scoring component or
prove a learned reranker alone can fix all 298 cases. Eight queries return no
results in every arm; all remain in the denominator. This run does not tune
ranking or fit models.

The broader-language encoder hypothesis also fails to improve these public
C++/Rust subsets under the fixed engine:

| Language | Queries | CodeRank Top1 / Hit10 | Jina Top1 / Hit10 | Muninn Top1 / Hit10 | Historical Semble Top1 / Hit10 |
|---|---:|---:|---:|---:|---:|
| C++ | 60 | 45 / 60 | 40 / 60 | 36 / 59 | 47 / 60 |
| Rust | 60 | 38 / 55 | 31 / 55 | 35 / 55 | 45 / 59 |

These are descriptive public subsets, not the separate 200-query RepoQA test.
The comparison tests drop-in contextual encoders in a fixed engine with its
existing learned ranking policy. It does not isolate pure embedding quality or
compare separately retrained systems. All arms use native prompts/pooling and
a common 512-token embedding budget. Jina's longer native context window is not
evaluated. Differences of a few queries are not a general superiority claim.

## Frozen recipe and evidence

- Engine: 431 production files from `1b07976d`, hashes in engine-source-manifest.json.
  Public find_best(scope=files, piece_kind=auto, purpose=auto, limit=10, max_chars=12000).
- Potion-code-16M-v2 static embeddings, both learned forests, query expansion and
  Ettin68M FP32 ONNX/1024 tokens fixed. No Torch/Transformers imports in API workers.
- Context: CodeRank137M INT8 nativeCLS/query instruction; Jina161M officialINT8
  maskedmean/no instruction; Muninn47M nativeCLS/nativeprompts/FP32 ONNX export.
  Context sessions use CPU2intra/1inter, batch1. Exact policies/assets are recorded.
- Same queries, IDs, revisions, index-admitted source paths and bytes. Original
  root basenames preserved. Original repos/caches read-only. Arm order rotates
  evenly: each arm occupies each position21times. The same87 exact-source query
  IDs take that fast path in all arms; they are retained in the full API metric.
- All3,753 outputs closed before label-free preflight and grading. All189 worker
  profiles/providers/source paths and IDs validated, zero failed workers. Each
  output is SHA-pinned. No query/target/scorer edits or model fitting during capture.
- Private reserve CLOSED. No release, tag, package-version or default-model change.

Registration SHA:
`6ed5f68acc9fbd5bcf14226680dd6fe0e306629e13a332a1f8653cc7dd7e52fa`.
Original requests SHA:
`c8ccb7efc678ccb97b5a03442047ee630b1e225d6009682584d0ffc6f14aca53`.

[summary.json](summary.json) contains primary aggregates/costs;
[report.json](report.json) contains per-query scores; [audit.json](audit.json)
contains explicitly posthoc paired/language/runtime/historical diagnostics.
Protocol, preflight, source/model/scorer/response hashes, verification receipts
and exact producer scripts are archived alongside this report. The local analysis
folder retains the raw 71MiB capture and 3.6GiB reusable source-only vectors outside
Git. Model weights and third-party source trees are excluded from Git.

Independent read-only review rechecked 8 producer pins, 66 scorer pins, 1,333
capture pins, the 431-file engine, all responses, original matching/scoring,
percentiles and cache totals. It found no numerical discrepancies or blockers
and did not access the private reserve or execute models.

## Reproduction

Scripts are exact .py.txt copies with their original absolute paths, not a portable
benchmark command. Restore the pinned Semble checkout and repository roots,
revisions, model assets and runtime before reproducing. Registration fixes all
source/scorer hashes and requests; capture verifies them on each worker. The
original scorer is benchmarks/metrics.py at the Semble commit above.

Execution order: run.py register; run.py run; preflight.py with frozen engine on
PYTHONPATH; grade.py using the pinned Semble environment. audit.py runs only after
primary grading and does not alter registered inputs. The exact registered scripts
are under scripts/ with .txt appended. The 63 foreign modified-file hashes and
117-entry original Git status were checked unchanged after capture.

The code-free gzip observation files preserve every effective native rank slot, returned location and error presence; current rows also retain exact wall/CPU timings. Historical projections contain no timing. worker-provenance.json and preparation-observations.json retain RAM and setup samples. These derived projections were made after primary grading; observation-projection.json records that boundary. To recompute all quality and cost aggregates without models or repository source:

    python scripts/recheck.py.txt . --tool-root /path/to/pinned/semble

This needs NumPy and the pinned Semble runtime/scorer. It verifies all archived hashes and registered producer/scorer pins before evaluating.
