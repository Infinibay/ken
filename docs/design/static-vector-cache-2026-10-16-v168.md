# v168: bounded reuse of immutable static term vectors

Outside-in responsibility: RegisteredStaticEncoder returns the same pinned native
pooling vector for a text, independent of other texts. Reuse repeated short lexical
vectors without changing query/source features, models, ranker weights or defaults.

Boundary instrumentation of actual globally installed default on attrs141files,
2073owners, publicvp-cs-019, three warmrepeats:129–131ms of1870–1911ms spent in
static encoding; within each query the second~6435term source vocabulary repeats
the first. Later repeats reuse every term but currently encode them again. Neural
10pairs takes1107–1119ms. cProfile trace omits several enclosing frames/calls on
this runtime, so use direct boundary records for component timings; do not treat
1.469s instrumented cProfile as a complete-search latency. No p95claim fromonecase.

Add lazy per-encoder LRU for nonempty single lexical texts<=128characters only;
8MiB accounted vectorbytes+UTF8keybytes+256estimated object overhead, max8192entries.
Do not cache long source text, sentences or empty values. Immutable registered
weights/tokenizer are the cache identity; no cross-model/process/repo names. Each
caller receives a mutable fresh vector independent of cached bytes. Cache lookup/
publish/eviction under a short lock; native encode occurs outside it. Eviction
changes recomputation cost only. Empty input remains lazy. No profile fingerprint
change because outputs and pooling semantics must remain exactly identical.

Tests first at actual tiny StaticModel boundary: repeated short terms avoid native
encoding, cache mutation isolation, long/sentence bypass, byte-bound eviction and
mixed-batch/order/duplicates/empty exact vector parity. Then actual Potion vectors
in reordered batches and eviction. Measure fixed public200with full actual MCP
CPU pipeline, preserve every returned order and original191/197; new-stress quality
must not be claimed from old native145/193pools. Bound cache overhead and report
end-to-end p50/p95/RSS separately from component savings. No relevance fitting or
private reserve access. No release. Keep only if lossless and useful within budget.
