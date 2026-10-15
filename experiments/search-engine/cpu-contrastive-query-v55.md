# Tiny query-only contrastive residual adapter v55

The centroid regression of v53 did not improve ranking. It fits a mean target
without learning which nearby alternatives must be separated. Test that missing
objective explicitly, keeping the encoder and every source vector frozen.
[ADORE](https://arxiv.org/abs/2104.08051) motivates query-side retrieval training
and hard alternatives; this is a small fixed-pool residual-head experiment, not
its full encoder training or a transfer of its reported accuracy.

Use unchanged v26 complete50967 source-owner vectors and v31 original/expanded
actual query vectors, v36 fixed proposed owners and original v38 whole-owner
eligibility targets. No new encoder/download/GPU/external inference. Each of16
folds excludes the entire evaluated repository from every optimizer update.
Reset identical seed42 parameters and a fresh AdamW for every fold/model. Five
queries without an eligible proposed owner cannot supply positive training;
they and all other400 cases still count in every original strict evaluation.

Two fixed residual heads:768x768 linear correction initialized zero; and
768->32->768 tanh correction with deterministic normal down-projection, zero up
projection. Both begin as identity. Unit-normalize q+correction. The existing
source encoder and source/query assets never train. Train20 epochs, query-group
batch8, seed42+epoch shuffle, AdamW lr.001, weight_decay.01, gradient clip1,
CPU2threads. No early stopping, per-repository settings or held-out selection.

For one query, use every original eligible owner as a positive and all other
owners in its fixed source pool as hard alternatives. Loss is logsumexp of all
cosines/.07 minus logsumexp of eligible cosines/.07, plus .1 mean squared unit
query displacement. Average distinct original/expanded views within each query
before averaging queries, so a translated query gets one vote. No other fold's
learned scores select training examples or targets. Candidate source matrices
are gathered per query from the complete vectors, not cached per training row.

At inference take max(original,expanded) adapted cosine per owner; keep exact
unique lookup authoritative. Evaluate each head alone and equal RRF60 with the
existing235 ranker (also excludes the same whole repo). Four predeclared controls,
no learned fusion/meta-model. Export only finite immutable float32 head arrays
and a NumPy forward path, validate against CPU native tensors on every held-out
query and record maximum numeric error (require<=2e-6), model bytes, optimizer
settings and hashes. No inference dependency on training Torch.

Present all400 with the current retrieved-source renderer,64-character profile
fingerprints and original40line/10result/12000canonicalJSON budgets; original
strict ALL-anchor scorer, all strata, missing/errors=zero. Do not interpret
prepared performance as actual API/default/private acceptance or final latency.
No result can weaken the original90%/CPU/low-RAM acceptance criteria.
