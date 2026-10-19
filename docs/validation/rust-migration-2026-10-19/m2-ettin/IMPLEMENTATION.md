# Ettin: independent expectations fixed before native implementation

Only Task1/original expectations are complete. No native Ettin preparation or
scoring is accepted yet; M2 remains open.

[Cases](cases.json) fix23histories; [original outputs](reference.json) were captured
independently from frozen source on Darwin/arm64 and Linux/aarch64 before native
Ettin code. Each original assembled the declared274035078B graph exactly:
8e22c1a014dbb6bf803824b531943ee067de4e9c6dea72f8c178348732db38bf.
Original runtime versions and all15source/fourprepared artifact hashes are retained.
Raw pair boundaries1023/1024/1025 were verified, not estimated. Hyphen queries
at65536characters tokenize to256tokens, isolating the character guard from the
independent default1020querytoken limit. The allowed case actually scores;65537
rejects. Top11 rejects without loading. Original CPU arena is enabled, threads4/1.

Tiny independent data under crates/ken-models/tests/fixtures/ettin adapts explicit
frozen test_reranker_head/registered_reranker helper functions and records helper
hashes. The graph exposes head arithmetic, raw scores, right padding, query/doc
limits and dynamic batches. Twelve malformed head/pair/config variants all fail
in the original.27targeted/reference original tests pass on bothOS.

TDD first reproduced missing modules, then a temporary-HOME pollution bug in the
generator: the validation environment would become fixture data. A failing test
pinned it; TemporaryDirectory fixed it. Portable tests now freeze their own copy
of source/helper files, matching established tooling, without requiring a private
M0path. Production Rust/runtime dependencies were not added.1066original hashes
remain unchanged. Sandbox DNS failure and successful anonymous pinned-data
preparation are retained privately; no original cache/source was modified.

Raw: .ken/rust-migration/m2-ettin/oracle-macos.json and t1-linux-receipts/.
The private original helper/data preparation is validation-only; actual native
assembly from authenticated sources remains a mandatory next gate. No graph
copied from Python will count as native preparation.
