# Source-only vector geometry control v45

Keep the original400 requests, source/reference snapshots, strict scorer, all
decisive anchors, budgets and unopened private reserve fixed. The baseline is
v38's235-feature prepared ranking on v36's exact same full source proposal pool.
No new model weights, external inference, query-label source preparation or GPU.

Research hypothesis: a contextual vector may point partly toward frequent source
patterns shared by many owners. Additional source-only geometry could distinguish
that commonness from query-specific support. It is not established that a
contrastively trained code encoder benefits from postprocessing. Test before
adding production complexity. Primary motivation, not transferred accuracy:
[All-but-the-Top](https://arxiv.org/abs/1702.01417) and
[sentence whitening](https://arxiv.org/abs/2103.15316).

Compute the mean and covariance from ALL v26 source-owner vectors of each repo,
without reading any request while fitting those statistics. Use float64 mean/
covariance, eigendecomposition and projection, then store normalized transformed
vectors as float32. Normalize transformed queries the same way; a genuinely zero
centered/projection vector contributes a measured zero score. Raw vectors/scores
remain available, and no equivalence with calibrated probabilities is claimed.

Fix three geometric views before outcomes: (1) mean-centered cosine;
(2) mean-centered cosine after removing the top3 principal source directions;
(3) PCA whitening in the top128 directions with ridge floor
max(1e-8,0.1*trace(cov)/dimension), keeping at most dimension and N-1 directions.
Source-only statistics are transductive preparation for that repository, never
fit to development query vectors or labels. Keep each basis/source projection
and its hashes. Query inference can reuse the raw encoder; no source reencoding.

For original and locally expanded public queries, append each view's raw,
to-maximum, range-relative and reciprocal-rank summaries (8 features per view),
plus source dot mean and centered source norm (2 source commonness features).
The public feature producer reads no references or relevance. Baseline235 plus
all26 additions yields261 features. Core235 values are reused unchanged from
v38, with row/owner equality assertions and no new candidate-selection rules.

Four fixed ablations: centered+commonness245, top3-removed+commonness245,
whitened+commonness245, all261. Use identical existing160tree parameters and16
repository-held-out folds. Correct complete-owner eligibility remains the
training objective; score all400 original retrieved-evidence final responses
with the strict evaluator. Exported/native predictions must agree exactly.
Do not select parameters per outer repo or drop failed queries. Report every
ablation, all strata, cost and source provenance, preserving neutral/failed ideas.
Only measured value could justify a later explicit profile/API integration.

Paired rendering control: rerun the existing235 held-out numeric models through
the same current renderer as every geometric ablation. Use the64-character
numeric model fingerprint as profile_version in every mode so metadata length
does not change the canonical JSON budget. Join unchanged training eligibility
targets by public query ID and original owner index, asserting parent235 feature
values and all167328 owner rows agree. This also controls the source-extent
metadata correction since the earlier prepared replay.
