# Convex feature ranking88: question-level loss, no extra encoder

85b's frozen joint CLS representation did not produce a useful relevance head;
keep its negative results. The measured512 prefix already contains the original
anchors in79/90 implementation identity failures, so missing source prefix alone
does not explain most of them. Next isolate the ordering mathematics instead of
adding representations or an encoder. Existing early linear controls used only15
handcrafted features, not the current251 source69 features.

Use EXACTLY all251 parent69 features, source7 candidate identities/owned regions,
original66c whole-owner eligibility y and all400 requests. No85 vectors/scores,
new feature, query rewrite, corpus change, external inference, GPU or heavy model.
For each of16 folds exclude the entire held repository BEFORE any statistics or
optimization. Fit only original nonexact training groups with both positive and
negative owners; record skips. All400 remain in evaluation and scoring.

Standardize columns on training groups with equal query weight: each group's
candidate distribution has total weight1. Use the mean of group means and mean
of within-group squared deviations about that common mean. Zero/near-zero
variance columns (variance<=1e-16) use scale1. No held input contributes, even
unlabelled; no global-minus-held aggregate. Normalization arrays are part of the
exported head, finite and immutable.

One fixed convex objective, no intercept or hyperparameter sweep:
L(w)=sum_training_queries[logsumexp(Zq*w)-mean_positive(Zq*w)]+||w||^2/2.
Zq=(Xq-mean)/scale. All original eligible positives share equal target mass within
a query; every original candidate participates in its training list. Use stable
shifted softmax and exact analytic gradient. Ridge1 gives a unique solution.
Start at zeros, SciPy L-BFGS-B, maxiter1000/maxls50,ftol1e-15,gtol1e-7; require
optimizer success and max absolute gradient<=1e-4. Numerical failure is retained,
never a missing query or lower convergence/acceptance bar. Finite-difference,
translation invariance, equal-positive, export and held-data perturbation tests
precede fitting. Save full traces and optimizer/residual metadata.

Runtime is a251-dimensional standardized dot per owner (three251float64 arrays,
6024rawbytes), no extra encoder/model service. Fit16 fresh heads only after an
independent pre-fit review binds sources/arrays/selectors and fold exclusion.
Verify export scores bitexact and immutable. Use linear order alone; no fusion,
parameter variants or held-label checkpoint choices. Preserve exact authority,
stable original-index ties, all candidates, source hashes and evidence policy3.

Reproduce original286strict/298identity baseline before scoring the new order.
Use all400 original references/ALL anchor lines/strata,10/40/12000 budgets,
errors/missing=zero, no exclusions or private reserve. Same preregistered+5strict
hits before considering an actual API/profile integration. A prepared result
cannot demonstrate90%, a Semble win, API resources or default promotion.
