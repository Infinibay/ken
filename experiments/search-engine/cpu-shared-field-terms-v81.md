# Share identical field terms81; preserve every feature and full API answer

Profile79 instruments actual API request development-logrus-13, with full answer
bit-identical to74b, separate unprofiled warmup and copied source index.2,047,467
calls/1.396instrumentedseconds: evidence_features0.666s, code_terms6,647calls/
0.175s, word encode0.135s. Concurrent/instrumented, not final request latency.
Probe79b confirms4,196 distinct word texts and repeated native vectors identical,
but a new word-vector cache would require explicit batch-semantics and memory
guarantees. Defer that broader change; no vector cache is implemented81.

Remove directly redundant parsing: raw/source identity, signature, documentation
and path have the exact same OwnerDescription string and4096term limit. Share
their request-local token lists. Preserve each view's original combined-all
projection/order/limit; sourceall is not the raw union. No global cache, added
model, new fields, arithmetic, model weights, feature schema or profile identity.
One core function changes; no new class/API. No shared state between requests.

Two meaningful RED/GREEN tests cover once-per-shared-field parsing through the
public feature factory and independent raw-union/source-prefix4096 behavior
with4200documentation words. Existing feature tests/mypy stay unchanged. Run
the relevant retrieval/bench/parser suite, then actual ALL400 source7/251/policy3
API with the same16repo-excluded69 models and identical original requests.
Require full response bytes SHA58c24a5525ad8d8ab3dc9281b494f2de403eb6278ee49648d6926c6acf553c99
and strict286/400/identity298/400, no missing/errors or budget changes. Measure
p50/p95/max/RSS and perrepo indexedci_files; record concurrency limitations.

Before/after profiling copies the same source/model/one request, retaining all
function/word counts and full-answer parity. Timings are diagnostic, not isolated
causal speedup. This removes waste without claiming an accuracy gain. Acceptance
thresholds/private reserve/default original checkout remain unchanged.
