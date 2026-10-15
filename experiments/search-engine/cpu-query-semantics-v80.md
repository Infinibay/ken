# Conditioning ranking on16 query semantic contrasts80

Current227+8+16 features retain candidate similarities and a few lexical query
flags, but no direct semantic query coordinates. Test the missing information:
whether the ranker should weight the same candidate signals differently for a
query asking creation versus update, parsing versus formatting, failure versus
success, conditional versus unconditional execution, delegation versus algorithm,
choice versus execution, ordered versus independent operations, release versus
acquire, fallback versus abort, mutation versus computation, async versus sync,
iteration versus access, configuration versus application, missing versus valid
values, tests versus implementation, entry point versus helper.

Freeze the exact16 generic English template pairs in query_semantics.py before
any fit. They contain no repository/file/symbol/benchmark text. This is adaptive
development research informed by error classes, not blind acceptance. Encode all
32 templates before reading any real query, using the pinned existing42 CodeRank
query prefix/CPU2thread/batch1/512/rawCLS encoder. No new/heavier model.

For each pair normalize both raw vectors in float64, subtract negative from
positive and normalize the difference. Save16×768float64 unit axes plus the raw
template vectors, source strings/model/runtime/normalization hashes. These are
correlated signed semantic similarities, not an orthogonal basis or verified
behavior/intent labels.16RED/GREEN tests+mypy check ordering, extremes, immutable
arrays, asset roundtrip, degenerate and invalid vectors.

Project the actual expanded query vector from the unchanged31 cache through
these fixed axes, with the same stable float64 unit formula. The complete545query
text/800view recode64 and69 expected cache/text bindings remain prerequisites.
Use one vector at a time in preparation and proposed inference to keep arithmetic
identical. Broadcast16 query-only columns to every candidate of its query; keep
all251 parent columns/owners/proposals exact. Exact37 singleton controls receive
the same neutral numeric bypass, never removing a query. No supervision/PCA/
fitting/template selection uses the held repository or private reserve.

One267column control, same160tree/15leaf69parameters and16 whole-repo-excluded
fits, expected original66c labels and complete68parent/extension guards. Native
export is exact. Replay unchanged69 scores withpolicy3 as286/400 before new
scoring. ALL400originals/strata/ALLanchors/10hits/40lines/12000JSON unchanged;
at least5 strict hits above286 before API integration. No further feature-width
or template sweep. Keep failures/negative results. Prepared quality cannot claim
the90%, Semble/public victory, default promotion or final CPU/RAM certification.

Intended runtime cost is one16×768 projection of an already computed vector;
the axis payload is98,304bytes. This is an operation count/asset size, not a
measured speedup or end-to-end latency claim. Private acceptance stays unopened.
