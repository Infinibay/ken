# Bounded lexical reuse v46

The actual v42 API is the paired baseline:277/400 strict,290identity, same400
original requests, sixteen whole-repository-excluded235-feature models, complete
source indices, original visible evidence and output budgets. Private acceptance
stays unopened. This experiment targets CPU work only, not relevance math.

One actual public request (regex17) profiled with cProfile spends12.96 of17.80
instrumented seconds in code_tokens:14,248 calls and roughly3million repeated
identifier decompositions. Instrumented times are diagnostic, not user latency.

Memoize only the pure decomposition of an NFKC-normalized raw lexical word:
casefolded full spelling, separator/camel components, stop-word removal and
sorted variants. Repeated source occurrences and repeated query calls must keep
their original token order and duplicates. Return a new mutable token list;
cached values are immutable tuples. Bound retained entries to16,384 and bypass
retention for normalized raw words longer than256characters. No complete source
documents, query responses or relevance labels are cached by this change.

Prove exact ordered token parity for every distinct normalized lexical word in
ALL passages/fields of the16original public source indices and all400original
plus400locally expanded public queries. Keep input hashes and counts. Existing
tokenizer/schema versions stay fixed only because output semantics stay exact.

Rerun ALL400 through the real API+canonicalJSON with the same worker and frozen
numeric models/assets. Preserve prior outputs. Verify every response equals the
v42 response after canonical JSON normalization, in addition to the original
strict scorer retaining all400. Record timings, source preparation/startup and
RSS separately; concurrent execution is not an isolated CPU certificate. Any
different response or token is an unresolved regression, not an allowed tradeoff.
