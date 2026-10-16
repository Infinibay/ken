# Default neural token budget: 1024

The reranker client accepts a configurable token budget and defaults to1024,
as requested. The published Ettin68M weights, CPU batch1/thread4 settings,
source-card selection, embeddings and final ranking policy remain fixed.
The client rejects budgets above a declared model/tokenizer limit before
creating an ONNX session.2048 is supported when the pinned model allows it.

This changes capacity, not search accuracy. Actual complete MCP runs on the
same400 exposed development queries preserve every512-budget top1 identity and every candidate pool (30lower orders change):

| Cohort | All queries top1/top10 | English top1/top10 |
| --- | --- | --- |
| Original |191/197 of200 |113/118 of120 |
| New symbols |159/195 of200 |93/119 of120 |

The current English objective is at least108/120 strict correct pieces in
EACH cohort. The new cohort does not meet it. The independent reserve remains
closed; these exposed development numbers are not independent acceptance.

Actual complete MCP English240 prepared-index latency: median1886.48ms,
p953120.45ms, maximum4004.57ms. All400: median2107.30ms, p953545.92ms,
maximum4597.67ms. Explicit model warmup is recorded separately. All calls and
outliers are retained. CPUExecutionProvider is verified for context and neural
models in all16 processes; no torch/transformers/sentence_transformers imports.
Peak server RSS across both full cohorts was2160279552bytes (2.16GB decimal),
including index and resident models. Per-process timings, file counts and RSS
are in costs.json. This is a measurement of1024, not a controlled CPU speedup
claim versus512. Both1024 and2048 previously had identical effective inputs on
these short cards; retaining2048 would not expose more source in this set.

Verification:20actual miniatureONNX runtime tests; full suite14967passed,
10existingxfail; mypy357source files clean. All loaded Ken modules came from
the clean worktree. The old512-capacity test remains with explicit512 config.
Source snapshot422files is bound by receipt in manifest.json; the patch and
normal MCP producers/outputs are preserved in compressed payloads. Each payload
is independently checked against its original SHA256 after decompression.

Review: token capacity belongs to ONNXReranker, and default_reranker only forwards
configuration. No dependency or model-weight change, no scoring-rule change,
no reference/acceptance edits. Lazy preparation and empty-pool behavior are
preserved. Real long-query/document tests cover1024 and2048 capacity and errors.
No release, tag, version bump or PyPI publication is part of this change.
