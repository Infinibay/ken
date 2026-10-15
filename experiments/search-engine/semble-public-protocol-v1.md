# Semble public benchmark: frozen comparison protocol

Registered before producing or scoring results on this dataset, 2026-10-14.

Use Semble 0.6.2 commit 0e5e02832ae0340c0feb637d2b7213fe065571fd,
all 63 entries of benchmarks/repos.json at their exact revisions and
benchmark_root scopes, all 1,251 unmodified queries in load_tasks order,
all primary and secondary targets. No private Ken acceptance data is read.
Each engine uses its native ignore/indexing policy, recorded independently.
No repo or language is excluded; missing queries and failures score zero.

Engine: unchanged Ken cpu-exact-case-v15 frozen source, verified against
SOURCE-MANIFEST.json, registered Potion-code-16M-v2 CPU encoder with fixed
no-padding/no-hidden-truncation policy. The public service search runs with
SearchRequest defaults (auto purpose, limit 10, 12,000 JSON characters),
separately target=symbol and target=file. The latter is a real API mode;
no scorer-side file deduplication is allowed. Two separately named bench-only
controls apply the previously fixed prefer_requested_role function to the
same candidate pool, then the same presentation for symbol and file modes.
No new ranker, parameter tuning, label hints, or model selection on this set.
This is the experimental engine; the original checkout's default is unchanged.

Native Semble is rerun with the same pinned Potion-code-16M-v2 weights,
unmodified tokenizer, alpha=None, rerank=True, top_k=10, five searches per
query as its runner does, using the final result list for grading. Ken uses
one search per mode/query: timing is descriptive, not a speed comparison
against Semble's five-run medians. Each repository runs in a fresh process
to bound accumulated RAM. All inference is CPU; no transformer reranker.

Scorer: import Semble benchmarks.metrics.target_rank and ndcg_at_k without
modification. For each query evaluate all task.all_relevant; preserve rank
slots and binary gain, including collisions when two targets map to one
result. Do not deduplicate repeated files or inflate the top ten with
flattened fragments. Match Semble's native chunk extent against Ken's
native returned entity_span, as the retrieved units. A separately reported
visible-prefix diagnostic instead maps Ken's first evidence fragment and
Semble's formatted visible prefix, never unions disjoint fragment gaps.
No span guessing or lookup in gold references is allowed in the adapter.
The entity-span score does not establish visible decisive implementation.

Primary aggregation: mean of the 63 per-repository mean NDCG@10 scores,
matching run_benchmark._save_results and its published 0.8544 artifact
(semble-hybrid-a772a37d558c.json). Also report query-weighted mean (the
README describes this), language and category breakdowns, top-1 target
match and Hit@10. These do not substitute for the unchanged Ken strict
90% owner+ALL-visible-anchors acceptance gate.

Retain dataset/scorer/model/source hashes, public-only request manifest,
source file manifests, native responses, errors, indices, per-repo stats,
timings, peak RSS and per-query scores. Resume completed repositories only
with identical input/profile/source receipts; do not overwrite raw runs.
