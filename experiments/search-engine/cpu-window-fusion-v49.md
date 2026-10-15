# Visible-window and owner evidence fusion v49

Keep all400 original queries/references, strict scorer, original visible windows
and the complete source snapshots/budgets. Use no new model training, inference
weights, query expansion or GPU. Every neural score remains from a model trained
excluding its entire query repository; every coarse235 score is also from that
repository's excluded model. Never fit a meta-model to other folds' neural scores:
those other models can have trained on this outer repository.

Research question: can independent owner evidence retain useful ordering while a
small joint model selects actual visible support? A high score for any one of
many proposed windows can also favor owners with more opportunities. No formula
is assumed to improve quality before the complete control.

Use the already registered v34b coarse20 hypotheses and both fixed-weight v44
CPU quantizations (A fullint8, B FP32embeddings+int8linear). Test three fixed
owner aggregations: maximum window score, arithmetic mean and stable
logmeanexp(logits)=logsumexp(logits)-log(window_count), temperature1. For each,
the winning source window remains the owner's highest-scoring faithful window.
Record owner/window counts and retain all scored owners for presentation.

For each quantization and aggregation report (1) neural owner order alone and
(2) equal-weight reciprocal-rank fusion k60 with the complete235 owner ranking.
The latter includes every base candidate, preserving original exact authority;
missing neural candidates contribute no neural vote, never an invented logit.
Source windows replace evidence only for owners actually scored neurally; other
owners retain original retrieved evidence. Map by full canonical EntityKey,
including definition ordinal, never by spelling/file alone. The pool and rank
mapping must be exact, and owner source hashes must match. No perrepo formula or
coefficient selection and no exclusions of difficult/empty-positive queries.

Use64-character profile hashes binding formula, score/model/source receipts;
recompute original strict judgments and all strata after canonicalJSON budgets.
All12 fixed controls are reported; no partial global percentage before all16
folds/400queries complete. This is prepared-score research, not final API
quality/latency, private acceptance, default or proof of a90% result.
