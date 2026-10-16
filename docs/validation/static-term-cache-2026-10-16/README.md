# Bounded immutable static-term reuse

RegisteredStaticEncoder now reuses short lexical vectors from the same immutable
model/runtime/pooling profile. Per-encoder LRU, no preallocation, max8192entries
and8MiB accounted vector/key/estimated object overhead. Return mutable independent
arrays; cache owns read-only copies. Sentences, empty inputs and identifiers over
128characters bypass. Eviction changes only recomputation. No scoring, weights,
retrieval profile, evidence, kind handling or runtime dependencies change.

Five tests written red first on actual tiny StaticModel; all18file tests green.
Return-by-reference mutation fails and exact source restored. Actual pinned
Potion native float16pooling→float32output:12000vocabulary inputs, forward/reverse/
random duplicates, empty/sentence/large inputs and eviction all BIT_EXACT. Warm
component samples101.17→68.64ms and35.30→23.97ms, cold122.52→132.43ms; these are
component timings, not search latency. Full suite14923passed,10preexisting xfail,
519.44s, exit0. Clean-path mypy356files passes; initial mixed-runtime internal
mypy crash is retained. Five-axis self-review: no blocking correctness, ownership,
architecture, dependency or concurrency issue; native encode outside cache lock,
strict output cardinality and bounded admission/eviction verified.

Frozen actual public MCP original200: all200ordered unit lists AND entire decoded
public DTOs equal baseline155. Original191/200top1,197/200Recall10 preserved by
exact response parity, without reopening reference labels. CPUExecutionProvider
for both model sessions; no Torch/transformers imported. Default compact matches
JSON pieces in every repository. No private reserve payload read.

| Complete public API | Previous155 | Cache169 |
|---|---:|---:|
| p50(ms) |2416.469|2355.978|
| p95(ms) |3696.396|3698.542|
| max(ms) |4323.960|4813.169|
| peak RSS(bytes) |1997455360|2012807168|
| total server CPU(ms) |1393453.827|1365250.165|

These are separate historical captures, not randomized paired causal evidence.
Do not claim2.5%speedup or exact RSS cost from this comparison. Per-repository
timings and RSS vary (including some larger RSS differences); see comparison.json.
The8MiB accounting bound is not an exact process-RSS bound. Small113–141file
repos still take median2.00–2.47s on this original mixed cohort, so1s/100files
is NOT demonstrated. Overall~2GB process peak remains a resource limitation.
Keep this small lossless optimization for measured repeated-term CPU savings;
do not market it as a ranking/latency breakthrough.

New symbol stress200 is not rerun in this capture; existing complete current
baseline remains150/195. Latest independent balanced200 remains177/198 on145,
below90%. Fresh independent reserve stays closed; no release/tag/version bump.

Archive output/checkpoints/static-cache-v168-v169:76gz files,506904compressed
bytes, manifest7603ad80031f7645469940c7d37b78d883d78f25a95075caaec5b8fbad4b93d6.
Preserves capture lock, producer bytes, source receipt/patch, raw answers/resources,
component probes, red/green/mutation logs, full suite and type checking.
