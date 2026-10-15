# Query-choice trees89: isolate nonlinear ranking under a top-choice loss

Define this single control before any89 fitting. The literal protocol text was
submitted in the same tool invocation that returned the first88b quality result;
no selection or parameter depends on that result. It adds no
encoder, corpus, query rewrite, feature, external inference or runtime service.
All251 original69 features/source7 and400original requests/references remain.

88b isolates a convex linear model for query-level softmax choice.89 independently
isolates nonlinearity using the existing small160tree family and the SAME
positive-choice loss, not a parameter sweep or fusion selected from88b scores.
For a query q, Lq=logsumexp(scoresq)-sum(targetq*scoresq), target uniform over
original eligible owners. Each query weight1 regardless of candidate count.
All395 positive queries currently have one eligible owner; this is top-choice
cross entropy, not XE_NDCG's randomized gain target or a promise of NDCG bounds.

Use exactly88b's358 nonexact positive/negative training groups, all original
candidates in each group. Exclude the complete held repo BEFORE group assembly,
bin construction or training.16fresh excluded-repo fits, no held checkpoint,
validation set or early stopping. Retain37exact/5no-positive training skips;
ALL400 evaluate unchanged. Raw251 feature columns, no new normalization.

QueryChoiceLoss owns stable probabilities/loss/exact gradient p-target and
Hessian diagonal p*(1-p); unit-mass targets and bounded integer starts are
immutable. It reports zero Hessian for saturation. The training callback alone
floors that diagonal at1e-12 for numerical tree updates; it does not change the
loss or reference. Coupled off-diagonal Hessian terms are not represented by
LightGBM's per-row callback; this is diagonal Newton boosting, not a proof of
exact Newton steps or a convex guarantee for the learned tree function.

Keep69's160 rounds,15leaves,min_child_samples40,reg_lambda2,learning_rate.08,
seed42,n_jobs1. No changed depth/feature fraction/bagging, no HP variants. CPU
and force_col_wise/deterministic flags explicit, no intercept/base-score, no warm
start or scores69/88 as training inputs. Exact analytic derivatives are checked
by finite differences before any real fit. Record every training loss, full
membership/source/feature/target bindings and export parity on ALL held rows.

Use existing NumericRanker trees for replay/runtime, no new inference backend.
Same exact-identity authority, original-index ties, full candidate pools,
evidence3,10results/40visiblelines/12000chars,original ALLanchors/alternatives,
errors/missing0,global/macrorepo/implementation/EN/ES unchanged. Reproduce286/298
baseline. Keep the fixed+5strict gate before actual API integration; no blind
reserve/default promotion without original90% acceptance. Failed fits retained.
Require independent review of exact freeze/controller and all16training manifests
before starting16fits. Only one control and one fixed160-round readout.

Primary sources consulted (not claims of measured superiority here):
- https://lightgbm.readthedocs.io/en/v4.6.0/pythonapi/lightgbm.train.html
  documents raw-score custom objectives returning per-row gradients/Hessians.
- https://lightgbm.readthedocs.io/en/v4.6.0/Parameters.html
  documents CPU/deterministic/column flags and the distinct rank_xendcg objective.
- https://arxiv.org/abs/1911.09798
  motivates examining listwise loss, but its XE_NDCG theorem is not transferred
  to our one-positive softmax objective or to top1 strict acceptance.
