# Small query-to-source transport control v53

Keep all400 original requests/references/strict scorer, original v36 pooled
owners/source evidence/budgets and the unopened private reserve. Reuse complete
v26 CodeRank source vectors and all v31 public original/expanded query vectors;
no new encoder or external inference. Training labels are v38's independently
verified complete-owner eligibility, not the earlier identity-only target.

Question: can a small learned correction align question embeddings to the source
implementations they describe, instead of relying only on geometric cosine
postprocessing or a large new model? This is a new experimental hypothesis.

For each training query, target the normalized centroid of all its eligible
pooled source-owner vectors. Original and distinct local expansion are views of
the same query: each view has weight1/view_count. All variants remain in the
same heldout repository. Queries with no eligible pooled owner provide no
positive training target and are recorded; they still count in all400 evaluation.

Three fixed adapters, trained excluding the entire evaluated repository:
(1) weighted mean source-minus-query shift;
(2,3) identity-prior ridge transport W=I+(Y-Q) A Q^T (I*lambda+Q A Q^T)^(-1),
lambda1 and10. A holds the per-query view weights. Solve through the equivalent
sample-space ridge system, verify its normal-equation residual numerically and
bind all matrix/input hashes. No heldout repo/source targets, perrepo parameter
selection, iterative hyperparameter search, neural warm start or meta-fitting.

At inference apply the adapter to each original/distinct expanded vector and
L2-normalize; compare to unchanged source vectors. One contextual-family score
is max(original,expanded), preserving unique original exact authority. A768×768
float64 ridge matrix is4.5MiB; a shift is6KiB. This is extra numeric calibration,
not another heavy encoder. Record actual model sizes/time; no GPU.

Report each adapter alone and equal-weight RRF60 fusion with the existing full
repository-excluded235 ranking (six fixed controls). Include every base owner;
do not refilter by gold or alter retrieved source windows. Use64character profile
fingerprints, original complete strict evaluation and all original strata/errors
over400. Prepared vector replay does not establish final live API latency/RAM,
private acceptance or90%; a measured useful adapter needs explicit runtime
profile integration and reruns before adoption. Preserve every result.
