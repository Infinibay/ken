Independent 88b review — PRE-FIT APTO

The exact corrected freeze and all 16 real-data normalizers passed pre-fit review. All 6,314 physical development files, 64 source artifacts, 51 parent bindings and every registered input match. The 167,360×251 feature matrix, original 66c labels and all 400 per-query choice records reproduce exactly. There are 358 contributing training lists, 37 exact skips and 5 no-positive skips; every 400 evaluation query remains required. The numerical optimizer was not imported or run, no head was created and the reviewer wrote no marker.

The objective is the declared convex list loss: each query contributes `logsumexp(Zq*w) - mean_positive(Zq*w)` and the fixed ridge adds `||w||²/2`. Its gradient is `Σ Zq.T @ (softmax(Zq*w) - target_q) + w`; each original positive receives target mass `1/Pq`. The Hessian is the sum of positive-semidefinite softmax covariance terms plus identity, so the registered ridge 1 objective has a unique solution. Independent synthetic evaluation covered 160 cases and 826 central-difference coordinates: maximum analytic-gradient disagreement was 3.55e-15 and finite-difference error 3.58e-9. This verifies the mathematics, not optimizer convergence or ranking quality.

Normalization gives every eligible training query equal total weight, and every candidate within that query weight `1/Nq`. For every fold, independently computed equal-query means and common-mean variances produce exactly the persisted means/scales, bit for bit. Zero/near-zero variance uses scale 1 as registered. All 16 normalizer NPZ files are byteidentical to preserved 88; the complete normalized matrices, targets and group starts also match their 88 hashes. All means/scales are finite, scales positive, starts int64, target mass 1 per query and prepared arrays immutable.

Every held repository is removed before normalization. In each of 16 folds the review replaced all 25 held query groups, including normally skipped queries, with NaN features and invalid labels. The six prepared arrays, query IDs and repository memberships remained exactly unchanged; 96 array-hash comparisons passed. Training groups legitimately depend on original labels in the other 15 repositories. The held labels are globally recorded for other folds, but contribute nothing to this fold's normalizer or future objective. Source 69 numeric scores remain baseline-only; no trained-score negative mining or feature weighting is introduced.

The frozen 88 attempt is preserved, aborted before any fit. Exactly three tracked source files differ in 88b: the helper, its tests and the 88b protocol supplement. The two reported generic boundaries are closed: nonfinite variance/normalization is rejected and valid bounded unsigned offsets are converted before reduction. The current 13 tests pass; 160 ordinary-input comparisons preserve old/new prepared arrays, losses and gradients bitexactly. No ordinary formula, selector, optimizer parameter or convergence threshold changed.

The pre-fit approval binds:

```json
{
  "engine_receipt": "ba6e660786f6627fd0af8b31d10a63b714255abb27f411f5cbd95e460ed87387",
  "controller_sha256": "5ffb5c5df97f61a50cad46af9e850ada4ef72d8a7b3d122e5233f8004562c50b",
  "pre_fit_registration_sha256": "b2f8b98ed3f4e49f1a3a6009976b80bffc93bf99fb60a5479e7191cdc898bd70"
}
```

This approves only the fixed pre-fit source/row/normalization/isolation boundary. Later review must verify all 16 optimization traces, success and gradient threshold, exports, unchanged baseline, all 400 responses and original strict scoring. Targets remain original 66c whole-owner eligibility; final strict acceptance still requires all decisive anchors in visible, faithful evidence under 10/40/12,000 budgets. No new training target, reference adjudication, private-reserve access, API/default promotion or quality/resource certificate is supplied here.

The future three 251-dimensional float64 arrays have 6,024 raw numeric bytes per head. That excludes metadata and the existing retrieval/feature/encoder pipeline; it is not an end-to-end asset or latency claim. NumPy 2.4.4 and SciPy 1.18.1 match preserved 88.

[Exact pre-fit bindings and all 16 fold checks](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/analysis/listwise-linear-v88b-prefit-review.json), [original helper mathematics and POCs](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/analysis/listwise-linear-v88-helper-review.json), [correction parity](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/analysis/listwise-linear-v88-helper-fix-review.json).
