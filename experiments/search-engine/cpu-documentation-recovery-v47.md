# Rust documentation recovery control v47

The independent v43 failure review confirmed a source extraction defect:
Rust attribute_item siblings stop the preceding-comment walk, dropping full
documentation from owner projections. This is a source-only fix, not a query
rewrite or special handling of any symbol/repository. Interleaved attributes
annotate the same declaration; their string values are not doc comments. Stop
at any other declaration. Remove only comment-node terminal CR/LF before joining
so intended blank doc lines remain. Legacy compact symbol outlines stay intact.

Increment EXTRACTOR_VERSION from5 to6 so persisted retrieval source projections
require rebuilding; do not silently relabel old projections as updated.

Paired control: keep v36's exact167328 proposed owners, original retrieved source
evidence, all400 requests/references/scorer/budgets, and v38's raw contextual
cosines fixed. Before reading queries, rebuild documentation from the current
Rust syntax trees for ALL Rust owners in ALL16 complete public source indices.
Match canonical identities and exact definition spans; verify file hashes and
preserve original regions and source text. Other languages' description fields
remain identical. Record missing-to-present and changed doc counts, not accuracy.

Recompute the existing227 source features for every query whose pool contains
changed owner documentation; preserve each row and the eight contextual features.
Unchanged source projections may reuse exact original235 feature rows with a
declared identity proof; no reuse based on relevance. The feature producer reads
only public requests, translations, pools and source, never gold alternatives.

Use the same160tree parameters and sixteen entire-repository-excluded folds,
original complete-owner eligibility targets joined by query/owner row, native/
export exact parity, and the current retrieved-evidence renderer with64-character
model fingerprints. Report ALL400 strict and every original stratum, retaining
errors/missing as failures. Reevaluate the paired existing235 baseline through
the same renderer (v45 baseline already277/400). This only tests contribution of
recovered documentation to source features; it does not establish new contextual
encoding, changed candidate selection, an API result, default or acceptance.
