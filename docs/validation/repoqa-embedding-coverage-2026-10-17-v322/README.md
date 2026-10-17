# Contextual embedding comparison: public RepoQA C++ / Rust

Neither tested replacement improves the complete frozen Ken engine on these
200 exposed English queries. Keep the existing CodeRank contextual encoder.
This experiment changes no product preset, source, dependency or default.
The private acceptance reserve remains **CLOSED**. No release was made.

These are **100 C++ and 100 Rust queries on shipped source snapshots**, using
Ken's unchanged strict file/callable/span matcher. They are different from the
earlier 240-query English development benchmark and are not official RepoQA
LLM-based SNF scores. Every original case stays in the denominator.

| Contextual encoder | C++ top-1 / top-10 | Rust top-1 / top-10 | Combined top-1 / top-10 |
| --- | ---: | ---: | ---: |
| CodeRank INT8, control | 69% / 88% | 59% / 90% | **64% / 89%** |
| Jina v2 base code INT8 | 63% / 83% | 58% / 87% | 60.5% / 85% |
| Muninn-small FP32 | 60% / 73% | 58% / 85% | 59% / 79% |

All 600 normal public API calls completed. The engine is the same 431 source
file hashes at commit `c4c86543ded281bb74620f460e63487bd9a00f6c`.
Static Potion, native/piece forests and Ettin-68M at 1024 tokens are unchanged.
Every API profile fingerprint matches its injected runtime, with three distinct
contextual models and identical non-contextual configuration.

## Findings

- **Published C++/Rust coverage did not yield a better replacement here.**
  Jina lost seven existing API top-1 hits and gained none; Muninn lost eleven
  and gained one. Their raw full-owner retrieval also fell: CodeRank 66.5% /
  91% top-1/top-10, Jina 58% / 89.5%, Muninn 47.5% / 82.5%.
  This measures each fixed artifact under Ken's current source representation
  and frozen ranking, not the isolated causal effect of language coverage or
  overall model quality on other tasks. Native Muninn prompts and official CLS
  pooling were verified before capture.
- **8k is not an observed gold-target window shortage in this sample.**
  All 200 original reference spans fit 1024 tokens for each tokenizer; their
  maxima are 821/669/779 for CodeRank/Jina/Muninn. All 197 indexed gold
  full-owner views also fit 1024, with maxima 851/699/813. For CodeRank,
  66 of 69 indexed top-1 failures already have a complete input view fitting
  512. All original and expanded queries fit 512. These counts concern gold
  targets, not every source owner, and are not a window-size quality ablation.
  Missing context outside an owner is a separate representation question.
- **Selection/ranking needs attention even when semantic retrieval succeeds.**
  CodeRank's raw first result is correct but the complete API displaces it in
  24 cases (6 C++, 18 Rust). The API also fixes 19 raw top-1 failures, so
  blindly preferring the embedding only gains five net hits. At top-10 the
  pipeline loses seven and gains three. The 24 cases, target/input lengths,
  cosine values, wrong first choices and ranks under all models are saved in
  [bottleneck-cases.json](receipts/bottleneck-cases.json). This observation does
  not identify a particular forest, feature or reranker as the cause. The nineteen
  repaired counterexamples are saved in [repaired-cases.json](receipts/repaired-cases.json).
- **Rust has useful complementary candidates, without an API improvement.**
  Jina raises raw Rust top-10 from 93% to 96% while lowering top-1 from 67% to
  62%. Predeclared raw RRF with CodeRank reaches 97% Rust top-10, but 89% C++
  and 93% overall; it lowers overall raw top-1 from 66.5% to 62.5%. This is a
  diagnostic fusion returning ten items, not a production API result. No
  ensemble latency was measured. A union with twenty or thirty slots is an
  oracle bound, never top-10 recall.
- **The requested 90% top-1 is not reached on this population.** Current API
  top-10 is 89%, already below the desired top-1 target. CodeRank's contextual
  top-100 contains 197/200 targets, showing room to improve candidate selection;
  that 98.5% is top-100, not top-10. Next work should trace the saved stage
  disagreements and losses before choosing a new encoder or fitting anything.

## Local CPU cost

Apple M1 Pro, ten CPU cores, 32 GiB system RAM. Single query at a time, warmed
index, CPUExecutionProvider, no Torch/Transformers in query workers.

| Encoder | API wall p50 | API wall p95 | Peak process RSS including preparation |
| --- | ---: | ---: | ---: |
| CodeRank INT8 | 3.164 s | 4.610 s | 1.327 GiB |
| Jina INT8 | 3.092 s | 4.695 s | 1.664 GiB |
| Muninn FP32 | 3.119 s | 4.598 s | 1.536 GiB |

These measurements do not establish a speedup between encoders. RSS includes
four concurrent source-encoding calls during preparation. Muninn's native 384
values are zero-padded to 768 for frozen-interface compatibility, so this is not
its optimal production vector-storage footprint. Pure contextual replay p95 is
about 0.107–0.117 s; that replay is a separate measurement, not component-level
profiling of the complete API.

The approximate goal of one second per 100 files is **not met** when normalized
by these supplied snapshots: control median 4.113 s and p95 13.834 s per 100
supplied files. Supplied-file counts are not complete upstream repository sizes
and this normalization is not a size-only scaling law. Direct per-repository
measurements are retained in `runtime-profile-verification.json`.

Preparation is not a cold-index comparison: control reuses 83,338/83,711 source
vectors; Jina reuses 7,579; Muninn reuses none. No cold-index speedup is claimed.

## Evidence and reproduction

[RESULTS.md](RESULTS.md) contains all language/stage tables, NDCG@10, exploratory
fusion, original-span budgets and paired repository-bootstrap intervals.
[METHOD.md](METHOD.md) records controls, exact scope, integrity gates and limits.
[SCORING-FINDINGS.md](SCORING-FINDINGS.md) records source-representation ownership
and concrete follow-up cases. `receipts/` contains model/input/source pins,
per-query metric rows, audits and independent reviews. `COPY-MANIFEST.json`
protects copied artifacts with SHA-256.

Scripts are archived as `.py.txt` in `reproduce/v320` and `reproduce/v322` to keep
research copies out of Ken's source index. Restore their `.py` filenames into
the original research workspace layout to rerun; the archive does not package
weights, vector caches, supplied source snapshots or the earlier workspace
inputs referenced by these scripts. It is an audit archive, not a standalone
benchmark installer. The fixed criterion is
`experiments/search-engine/public_benchmarks_v222.py` at the engine commit.

Independent review corrected a queued Muninn mean-pooling exporter to the
native artifact's CLS **before any candidate export, capture or quality grade**.
Actual SentenceTransformer 5.5.1 output, raw tokenizer IDs and CPU ONNX output
then passed label-free parity. All originals and correction receipts are kept.
Review also recomputed the final tables and 600 API profile fingerprints.

Primary model documentation: [Jina v2 base code](https://huggingface.co/jinaai/jina-embeddings-v2-base-code),
[Muninn-small](https://huggingface.co/brokkai/Muninn-small). Jina describes
512-token training with ALiBi extrapolation to 8192; maximum supported length
alone does not demonstrate a retrieval improvement.
