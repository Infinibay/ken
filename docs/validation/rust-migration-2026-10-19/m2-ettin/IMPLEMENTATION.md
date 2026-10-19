# Ettin: native preparation and paired scoring

Native graph preparation and all 23 paired scoring histories pass on Darwin/arm64
and Linux/aarch64. Profile acceptance still requires the complete 23 gate platform
matrix and fresh review in Task 4; M2 remains open.

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
The private original helper/data preparation is validation-only. Native assembly
from all 15 authenticated source artifacts independently produces the exact 8e22
graph on bothOS; it does not copy the Python-built graph.

RerankerModel and PreparedReranker own registration and verified graph/config
bytes. The head compiler preserves untouched protobuf data and emits the exact
published operators. Cache publication verifies a sibling stage, syncs it and
atomically publishes an ordinary umask-readable directory; concurrent winners
are reverified. Twelve native preparation tests pass on both platforms, including
corruption, bounded malformed protobuf, namespace collisions, owned source
bytes after path replacement, concurrent publication and failed publication.

OnnxReranker coordinates lazy preparation, one serialized CPU session and raw
ordered scores. Its private PairedTokenizer owns model limits, query capacity,
only-second truncation and right padding. Fourteen native tests pass on both platforms, covering
the 23 independently frozen real histories, synthetic arithmetic, batch remainders,
Unicode character/token boundaries, empty/top11/load-error ordering, malformed
configuration/output, concurrent first use, independent returned results and
an actual cold-process first score. The registered profile explicitly enables the
CPU arena and uses four intra-op threads and one inter-op thread.

Two explicit integrity decisions preserve the registered profile while rejecting
unsupported requests. Thread counts above i32::MAX error before any I/O because
pinned ort casts usize to C int; 2^32 would otherwise wrap to zero (all cores). Native
outputs must be F32 as registered. The original accepts finiteF64 outputs; an
independent Cast fixture captures its score 29, while Rust rejects that dtype.
All prior fixture bytes remain unchanged. The original/reference/preparation tests
include this characterization. These decisions do not change any original file.

An additional regression exposed unchecked subtraction inside tokenizers 0.22.2
when the token budget is smaller than its special-token count. Rust now configures
the paired tokenizer without that overflow and checks capacity before encoding.
Budgets 1–4 preserve the original load ordering, false pair_fits result and query
error; empty token inspection still returns an empty list. The regression first
reproduced the panic, then passed on both platforms. The portable original test
independently checks the same behavior.

The corrected source passes the complete native workspace on both platforms:
103 distinct tests (104 reported, including the existing nested context test),
formatting and clippy. All 29 original/reference/preparation tests pass, and the
1,066 original file hashes remain intact. All 13 existing source/input fingerprint
fields match across platforms. Raw checkpoints are retained under
.ken/rust-migration/m2-ettin/t3-{macos,linux}-corrected-receipts/.

Native runtime code uses no Python, subprocess or network fallback. Task4 must
still prove a fresh native executable and cache outside the checkout, actual
Linux exec traces, authenticated core dependencies and all prior profile gates
bound to the current sources. Earlier accepted context receipts describe their
own earlier source revision and cannot substitute for this fresh matrix.
