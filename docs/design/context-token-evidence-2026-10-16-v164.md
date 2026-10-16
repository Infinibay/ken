# v164: retain contextual token evidence that CLS pooling discards

Diagnostic research, no production change. Existing CodeRankEmbed INT8 graph
already outputs token_embeddings plus sentence_embedding (rawCLS). Current engine
keeps only one768vector per source view. Hypothesis: query-dependent coverage of
contextual code words can distinguish adjacent behavior pieces without another
model. Contrasts with current static term maxsim: these tokens encode context.
The released model was trained for CLS retrieval, NOT late interaction; this is
an empirical hypothesis, not a claim of ColBERT-equivalent training.

Keep pinned graph/tokenizer/query instruction/max512 exactly, CPU2/1,batch1.
Observe both outputs in one unchanged forward call, assert sentence embedding
parity on source-free and each query. Document text is existing full_owner_text,
authenticated source/hash, no labels or query-dependent source fabrication. Retain
normalized contextual word vectors; average the wordpieces overlapping a regex
word then normalize. Exclude instruction prefix/common search/function words
from query scoring, retain uppercaseAND/OR and negation; prefix remains encoded.

For each query word, s_i=max_j cosine(q_i,d_j), computed in64document-word blocks.
Five fixed statistics: mean,min,p25,p75,mean of lowerhalf. Repeated document words
add no votes. Empty documents produce zeros; reject malformed/nonfinite input.
Test normalization, full coverage, duplicate invariance, blocked math equivalence,
instruction exclusion and explicit operator retention before corpus capture.

Capture all250current exposed native10symbols, all400cases in evaluation. Q1 sorts
by raw meanMaxSim. Q2 learns a tiny residual linear head of five statistics plus
existing original rawNN/fullCLS cosine (sixfeatures plus raw offset), using same
query-balanced pairwiseL2=1/N LORO,maxiter1000/ftol1e-12/gtol1e-8; no HPO. Other150
oldqueries keep currentdefault. Missing candidates remain failures. Query source
word matrices are observer-only; no runtime or RAM claim from the prototype.
If promising, index once and use bounded/mapped cache (do not keep all per-token
matrices in heap). Required old>=180/197,new>=180 before final actual CPU/fresh
reserve. No model/graph change, no Torch or GPU, no private references, no release.

Before labels/fitting: Q2 columns standardized by training-fold mean and std
(constant std replaced1); serialize those same values. No held-repo statistics
used for preprocessing. This controls ridge units, not hyperparameter tuning.
