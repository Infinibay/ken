# Ranking reliability and compatibility

These changes use the existing database schema, vector format and embedding
model. An upgrade does not rebuild the index, re-encode vectors or rewrite
historical sessions. Existing session snapshots retain their raw-score +
pattern interpretation. The default fusion and the optional PageRank flags
keep their existing defaults.

## Durable session memory

New session snapshots retain each file's strongest productive turn across the
whole session. They no longer inherit the reactive channel's 30-iteration
window or recency decay. Repeated reads remain capped. NULL context anchors
in older histories form a single group; existing snapshots remain readable.

Predictive ranking counts the strongest matching prompt per session and file.
Repeated prompts within one session cannot multiply the same historical
evidence. Distinct sessions still corroborate one another. The active agent's
session is excluded before selecting the historical prompt window, so a long
conversation cannot crowd out all past sessions.

Snapshot replacement uses a savepoint under the daemon's connection lock. If
an insert fails after the delete, the previous snapshot is restored. This also
works with autocommit connections and callers inside an existing transaction.

The predictor still consumes session snapshots. Direct prompt-to-turn
attribution was tried during this change but was not retained: on a frozen
copy of the project's real index, it reduced recall on the six curated cases
from 18/20 expected files to 17/20. Visible recall was unchanged at 9/20.
The final implementation preserves all six baseline top-eight file lists.
This small check is regression evidence, not a general retrieval-quality
benchmark. Task-level attribution needs a larger, temporally held-out dataset
before changing default ranking behavior.

## One ranking pipeline

`explain()` collects snapshots from `rank()` instead of implementing another
pipeline. Its final results honor fusion, PageRank, documentation adjustments,
missing-file filtering and the confidence gate. Channel snapshots are copied
before mutable boosts, so their provenance stays accurate.

Existing explanation fields remain available. The response additionally
reports `confidence_gate`, `candidates_before_gate`, and the `ppr` and
`documentation_intent` boost deltas. When confidence is insufficient,
`final_files`/`final_symbols`/`final_findings` are empty, matching production;
intermediate evidence remains available for diagnosis. `top` controls the
result limits being explained.

## Optional PageRank

The source/test lookup now passes the shared path index expected by the
counterpart helpers. Graph weights and the bounded random walk retain their
existing semantics, including non-propagating dangling nodes. Directed edge
arrays replace dense square matrices: storage and each walk scale with files
and edges, rather than the square of the file count. There is no new dependency
or persisted graph format. This change does not enable PageRank by default.

## Visible benchmark results

`ken bench` preserves its existing retrieval metrics and failure thresholds.
It additionally reports `visible_case_recall`, `visible_expected_file_recall`
and `visible_mrr`, plus per-case `visible_files`, `visible_hits` and
`visible_reciprocal_rank`.

These metrics inspect the rendered terse block after its file cap and character
budget. They count the Files section; symbol locations and findings are
separate exposure types. A file ranked fourth can therefore count as a
retrieval hit while remaining a visible miss.

## Verification

Regression tests cover old inline-vector schemas, preservation of model
metadata, embeddings and findings during initialization, read-only ranking,
historical snapshots, rollback after an injected write failure, early-session
edits, repeated prompts, every fusion/PageRank combination, dense-reference
walk equivalence and a 50,000-file graph without a square allocation.
The core ranker and PageRank module now participate in the mypy gate without
per-module error suppression.
