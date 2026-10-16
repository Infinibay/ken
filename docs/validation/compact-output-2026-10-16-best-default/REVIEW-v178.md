# Useful default responses for code verification

The user identified that `ken_who` exposed a symbol and docstring claim without
the implementation needed to judge it. Compact output also repeated operational
metadata. The response now gives each candidate's identity and bounded real code.
Its ranking can be wrong; the caller has source to evaluate the suggestion.

The responsibility service ranks first, then attaches excerpts only to returned
candidates and counterevidence. SourceReader reuses the exact byte snapshot and
SHA used for assessment. Python encoding declarations are respected. A short
owner is shown in full; larger owners show declaration context and a query-related
implementation window, skipping long leading Python docstrings. Classes can show
a member far below the class declaration; modules include implementation beyond
their module docstring. Up to16physical lines/4000characters per candidate, no
partial physical line, no invented line numbers. `[partial]` exposes omitted
source. Empty/unavailable previews do not change scores or candidate order.

Duplicate physical lines across returned function/module/class candidates appear
once, with an explicit reference to their earlier location. Distinct candidate
identities remain. Explicit denial, conditions, supplied formulation assumptions,
ambiguity and meaningful verification failures survive. Structural coverage is
still observed; repeated usage-inventory internals become one incomplete-analysis
note. Use `full=True` for hashes and diagnostic traces; `output_format="json"` preserves native structured data.

The selected implementation window uses existing transparent lexical terms; it
does not prove behavior or guarantee every needed dependency appears. The caller
can use the displayed location for a larger `ken_read` when a fragment is partial.
Non-Python source uses its registered parser's ranges. No model, index schema,
learned weight, candidate retrieval, scoring formula or neural input changed.
The added Python implementation-line metadata is used only after ranking.

Other default views were reviewed against the same purpose:

* `ken_related(neighbors)` shows relationship groups and paths, removing repeated
  language/module/internal flags and redundant neighbor entries.
* `ken_recall` retains conclusions, validity, assumptions and source references;
  removes the echoed expansion request, default kind and zero omitted count.
* `ken_check` keeps status/run ID, errors and restricted scopes; removes timestamps
  and repeated generic claims. Non-default selection remains visible.
* `ken_reason` retains facts/bindings, premise sources, conditional semantics and
  incomplete search; removes request echoes and default context/world. Alternate
  context/world remain visible.
* `ken_calculate` returns the expression and exact result for scalar calculations.
* Structural text omits timing breakdowns by default, retaining incomplete/unknown
  coverage and errors; diagnostics restore timing.
* `ken status` shows index counts/coverage, daemon state and actionable problems.
  Full counts, project/database IDs and recommendations remain in JSON. Existing
  status tests now check the complete literal JSON inventory as well as the new
  text contract; retrieval benchmark criteria were not edited.

Actual captures in EXAMPLES.md/captures.json exercise all12MCP tools, seven CLI
forms, a qualified source lookup and a70line class (21captures). The large class
returns its relevant method on lines69–70. The producer checks returned source
against physical fixture lines and snapshot hashes. These are presentation
examples, not a latency or answer-quality benchmark.

Initial eight new tests all failed on the reported omissions/noise; separate
status, scope-preservation and duplicate-source tests also failed before their
changes. Tests cover stale indexes/current code, class selection, counterevidence,
encoding, giant lines, source-budget fidelity, ranking preservation on preview
failure, JSON opt-in and actual MCP transport. An initial editor script left one
literal plus in a comprehension; the failing log is retained and corrected.
Initial mypy exposed missing local annotations, corrected before final capture.
The first full-suite attempt was interrupted so final verification includes the
nondefault-scope/deduplication fixes; retain the partial run and its exit status.

Final test/type/commit/install receipts are recorded in validation.json after
their commands close. No release/tag/version bump and no private acceptance
payload access. This presentation change makes no new top1/Recall10 claim.


Final closure:14958passed,10preexisting xfail,1408.55s,exit0; mypy357source
files clean using the completed matching cache (an unnecessary cold-cache retry
was interrupted and logged). Test-process background policy was removed partway
through the completed suite; the profile and policy receipt are preserved. Suite
wall time is not a product performance measurement. All421package-file hashes
match final example source; retrieval/embedding/model assets are byte unchanged
from c3bb. Archive45gz/131472B, manifest
9da38e6e526e720ddbc29bd77ca25b35f8f9f22d3a4216fed14fa1e9818ff922.
Full actual raw text is in captures.json; Markdown strips only trailing spaces
from otherwise blank numbered source lines to keep the diff clean.


Installation closure: source86faea08ff29b8dd26a024d8744280fdb8a601f0pushed to main
and fast-forwarded locally with63foreign dirty tracked files byte preserved,
zero incoming overlap and empty staging. Actual global uv-tool is a noneditable
local wheel, still0.17.0; all421installed package files match captured source.
All72packages are compatible, same71dependency pins. CLIwho default and explicit
fullJSON verified; a NEW MCP server from the installed global package returns
numbered Reader code and scalar calculation text. PotionCode16Mv2 remains the
default. See installed-v179.json and verification script. Existing connected MCP
process was not restarted; reconnect it to load the update. No release/tag/upload.
