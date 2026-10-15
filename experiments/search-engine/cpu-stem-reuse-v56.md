# Bounded pure English stemming reuse v56

The v50 profile attributes1.141/7.394instrumented seconds of a real prepared
request to23,457 Snowball stemWord calls. The stem of a fixed word under the
pinned English Snowball3.0.1 implementation is query/source independent. Preserve
exact stem semantics, order and repetitions, returning a fresh list.

Memoize only immutable word->stem strings, maximum32768entries and128input
codepoints per retained word; longer words bypass retention. Every uncached
calculation owns a fresh mutable Snowball stemmer. No stemmer instance is shared
across queries/threads. No tokenizer/feature/source/profile/schema changes;
no training/query/gold-dependent cache values or stale source entries.

Verify unit equivalence with fresh batch stems (Unicode, duplicates, empty,
case, long word), bounded reuse/fresh list and concurrent independent state.
Isolate by freezing v50 plus only owner_ranking.py and this protocol, preserving
extractor5 for its original source indices. The unrelated reviewed extractor6
fix requires its own reindex and is not mixed into this paired performance run.

Run ALL400 actual prepared API+canonicalJSON requests with the same16 original
repo-excluded235models, pinned encoder/query/source assets and budgets. Require
full response byte equality with v50 SHA e3ae62e0cc3aade1b26b4de094d11a1f72adb17acbd29c1cc8f7fe2fdbed7ca6,
original277strict/290identity, zero discarded/error queries. Keep startup/index
preparation separate, p50/p95/max and peak worker RSS for every repo. Concurrent
measurements are descriptive, not the final uncontended latency/RAM certificate.
No private acceptance read, criterion/threshold/denominator/budget changes.

Full-suite compatibility refinement56b:
The original concurrent-buffer test injects the public batch stemWords interface.
Preserve that test and interface. A cache miss now calls stemWords([word])[0] on
its private stemmer and keys reuse by the actual factory plus word, so swapping
an injected/reloaded implementation cannot return another factory's result.
A new RED probe against freeze56 demonstrates that stale-factory reuse; it passes
with the refinement. No existing assertion, barrier or test was removed/relaxed.
The revised full parser/retrieval/bench suite contains357 passing tests.

Freeze56b keeps the same source5/control assets and overlays only this factory-
aware batch calculation and protocol. Repeat ALL400 actual API/full byte parity;
retain56's prior original output/benchmark claims separately until56b completes.
