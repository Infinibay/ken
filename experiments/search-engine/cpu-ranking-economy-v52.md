# Ranking objective and feature economy control v52

The user asked what information each part contributes and to reconsider ranking
math, not accumulate signals indefinitely. Keep the original all400 corpus,
167328 v36 owner rows, exact235 v38 features/whole-owner eligibility targets,
source evidence, original strict scorer/budgets and unopened private acceptance.
No new encoders or source changes. All predictions exclude the complete query
repository, never select parameters per outer repo or train a meta-model on
other folds' predictions.

Fixed family ablations with the existing160tree/15leaf/minchild40/lambda2/
learning-rate.08/seed42/oneCPUthread settings:

1. channel46: original20base intent/role/shape features,18normalized channel
   relative/rank features,8contextual cosine summaries. Remove all term coverage.
2. expanded181: remove only54 raw-query term-coverage features, retain all other
  235. Original query intent/channels remain; do not replace actual queries.
3. compact117: channel46 plus6coverage summaries (exact,stem,min,weighted,
   mean_cosine,log_words) from6expanded source views (identity,signature,
   documentation,executable,calls,returns),13kind indicators,7source shapes,
  15operation counts. Remove redundant raw/body/comment/path/all coverage.

All three use original LambdaRank truncation5. Also run full235 with truncation1,
compact117 with truncation1, and full235 truncation1 with monotonic nondecreasing
constraints on the8contextual summaries only (all other constraints0). These are
six fixed controls, not a search for a coefficient on heldout answers. The
monotonic rule is a hypothesis, not a claim more cosine must always be better.

[LightGBM's parameter documentation](https://lightgbm.readthedocs.io/en/v4.6.0/Parameters.html)
ties truncation to the desired NDCG cutoff and notes somewhat larger cutoffs can
help by including more pairs. Therefore truncation1 is an explicit top1-focus
ablation, not presumed superior to5. No source/reference threshold changes.

Export each fixed model through NumericRanker and require bit-exact native
predictions. Render every original query's full candidate order with current
retrieved-evidence policy and64character model fingerprints; all400/errors and
all original strata remain in reported strict results. Paired baseline235 under
this renderer is277/400. Report all six outcomes and feature/model sizes;
feature-only prepared controls do not establish saved API time/RAM or90%.
