# Supplemental location-only retrieval diagnostic

Registered after the complete v1 API scores, before producing this diagnostic.
The v1 scores and responses remain immutable. No engine, model, ranking,
candidate limit, query, source revision, or reference changes are allowed.

Observed motivation: v1 Ken file API returns 6.744 results on average under
the approved 12,000-character return budget, versus Semble's native top ten.
This diagnostic reports the native ranker's first ten returned locations
before presentation. Symbol mode retains owners; file mode retains the first
owner of each file, exactly as presentation already does. Unique exact-name
short circuits still return one item; do not fill them artificially.

Each location uses the unchanged match entity and entity_span. No source-body
output is manufactured. Use the same v1 official Semble scorer and macro-repo
aggregation. Check every v1 response's identity sequence is an exact prefix
of the corresponding diagnostic sequence (all four modes, all 1,251 queries).
If prefix parity fails, do not attribute the difference to output budgeting.

This is a public retrieval diagnostic with no new optimization or parameter
selection. It does not replace the v1 public API or the strict 90% acceptance
gate, which still requires correct owner and ALL decisive visible anchors
within the approved output budgets. The private reserve remains unused.
