# v153: preserve already-computed joint evidence, learn a tiny decision head

All exposed source-score controls v147–v152 fail new-symbol180/200LORO. H1native
source258gets149new/190old, H2adds purpose/test150/190; H2expand100Recallnew195
(vs193baseline), original197unchanged. Prefix100has every250symbol answer, so
candidate presence is now confirmed100%, yet source-statistical ranking is weak.
No failed learner is promoted. Existing independent88.5%result remains a failure;
fresh balanced200Gold stays private and unevaluated.

Outside-in concept: DecisionHead scores relevance from the joint query/document
representation already computed by the fixed68M reranker. Original final scalar
projects512values onto one general-purpose relevance direction. Hypothesis: learn
a code-task direction with a few kilobytes of weights, rather than another larger
encoder or more independent neural calls. Same512token CPU model and inputs.

Source inspection and official model card establish architecture: CLS512→Dense512
GELU→LayerNorm512→Dense1. Add the existing pre-final-linear norm tensor as a second
ONNX output, preserving all initializers/nodes/first output exactly. Check model,
source-free first-logit parity, finite shape(batch,512), then observe all250exposed
symbol queries/native10v102cards. Actual raw score parity must be recorded against
frozen145observations; no new view or tokenization. No labels in capture. Other150
old piece queries remain default untouched. Never access either consumed or fresh
private Gold for fitting. All250queries remain evaluation cases, including7whose
positive is missing from10. No expected candidate injection or source rewriting.

Two prospectively fixed decision heads, repo-excluded250symbol development:
J1 a linear pairwise logistic head on512existing joint values; J2 a residual
linear head added to original neural logits. Both L2lambda1, equal total pair
weight per complete positive+negative query group, all pos-negative pairs,
float64 deterministic L-BFGS maxiter1000/ftol1e-12/gtol1e-8. No HPO. Direct dot
products at runtime,512coefficients, same stored source/model/token limits. No
Torch/training framework at runtime, GPU or new neural weights. Scores are ranks,
not calibrated correctness probabilities. Original150non-symbol requests keep
actual frozen default. Unique exact/path priority remains absolute. Preserve
allnative10units, top10original197; report cohorts separately. Required old>=180
andnew-symbolCV>=180before actual final public CPU/independent reserve.

Choose the better new-symbol LORO only if both gates pass, tie residual. Pooled
training score is not independent validation. Any promising head requires actual
public source/asset freeze, complete development capture, CPU/RAM measurement,
then independent reserve closure/preflight and one Gold opening. No release.

Primary references: https://huggingface.co/cross-encoder/ettin-reranker-68m-v1
(Apache2, English general text model,512hidden); https://onnx.ai/onnx/intro/python
and https://onnx.ai/onnx/api/helper.html (typed extra output and checker).
