# Frozen code pair preference85; reuse the existing CPU graph

All tested generic small rerankers73/75c/77/84 are below the286/400 strict
baseline. Do not add their weights to runtime. Hypothesis: code-specialized
joint attention may expose distinctions absent from independent single-text
cosines, without adding another encoder or fine-tuning a heavy transformer.

Reuse EXACTLY registered42 CodeRank int8 graph/tokenizer/CPU2intra/1inter/batch1.
Do not call a remote service, load another model, useTorch/GPU or alter weights.
The graph was trained for retrieval; using paired inputs is an experimental
representation, not a claim that its original authors validated this use.
Encode tokenizer pairs (existing query prefix+expanded query, unchanged69 owned
implementation text). Disable padding, preserve the whole query, truncate only
the second sequence at total512. Run raw sentence_embedding CLS, normalize each
finite nonzero vector with stable float64 L2, storefloat32. Register this distinct
joint projection/tokenization/normalization policy; never reuse single-text
source/query vectors as paired vectors. Fixture tests must show query preservation,
output normalization, CPU-only provider and failures for invalid vectors/budgets.

Rebind all16 physical source7 catalogs/6314files before requests; exact51parent
replay artifacts,66cDATA and69 score/producer hashes. Source projection stays69,
no78/80/82 inputs, child gaps/callee guesses/query crops/new labels. First seal
ALL400 label-free evaluation prefixes: exact20 from source69 repo-excluded rank,
with37exact singleton bypasses. Save indices/query hashes/doc hashes/vector bytes.
Only after this complete phase, read the original66c eligibility labels to form
potential training groups. For each nonexact query with positive and negative
owners, use all original eligible positives and atmost20 negatives by ORIGINAL
untrained RRF signal, with original pool index tie. Encode missing joint pairs
through exactly the same function/cache key; don't alter evaluation prefixes.

Important isolation: trained69 scores select EVALUATION candidates only. They
must NEVER select/weight another repository's training negatives, because its
69model may have seen the currently held repository. Training selection uses
only original labels of training repos and fixed untrained source RRF. No global
centering/PCA/normalizer uses held pairs. A cache keyed by immutable query/doc/
model policy cannot change a pair's vector when training-only rows are appended.
Every held fold excludes all training groups of that repo. Verify by perturbing
held labels/69scores and requiring its training rows/moments/head unchanged.

For one query with P positive and N negative unit joint vectors, define each
preference difference d=z_positive-z_negative and equal weights1/(P*N). Accumulate
C_query=mean(d*d.T), b_query=mean(d). Per-repo accumulation streams queries.
The ONE fixed head minimizes sum_queries mean_pairs(1-w.T*d)^2 + ||w||^2,
so w=solve(sum C_query+I, sum b_query). No intercept, learned encoder, lambda/
sampling/head-width sweep or held-label checkpoint selection. Skip no-positive/
no-negative/exact groups only in training and record counts; all400 remain in
evaluation. Solve/export finite/symmetric checks and residual/closed-form tests;
head payload768float64=6144bytes, with immutable policy metadata.

Before fitting require independent curation/review marker of input/selection/
fold isolation. Train16fresh heads on15whole repos each, same regularization1.
Compare held prefix20 owner scores through ONE head per fold, with raw order and
equalRRF60 readouts of the same logits. Exact authority/ties/tail69 unchanged.
Replay original69 baseline with evidence3 as286/298 before altered grading.
ALL400 originals/ALL anchors/strata,10/40/12000 and errors-as-zero unchanged.
At least5extra strict hits before actualAPI/profile/resource integration work.

The proposed runtime shares its already loaded graph and computes atmost20pairs
plus a768-dimensional dot per search. This is an operation/asset count, NOT a
latency or RAM certificate; measure actual integration if quality clears gate.
No90%, Semble win, default promotion or private acceptance claim from preparation.
Preserve failures/negative results and keep the independent reserve unopened.
