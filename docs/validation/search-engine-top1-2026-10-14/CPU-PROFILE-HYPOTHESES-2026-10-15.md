# CPU diagnosis hypotheses, before quality labels

These are source-inspection hypotheses, not measured bottlenecks or implemented
optimizations. The active comparison remains immutable. Do not infer that a
reranker sped up retrieval from the temporally drifting baseline measurements.

## Common ranking

EvidenceReranker.rank calls evidence_features on every proposed owner. The latter
constructs raw/source token fields, then separately computes coverage for the
literal and expanded query. _coverage embeds the candidate term vocabulary,
collects per-field memberships, loops over vector blocks and all memberships,
then calculates maxima/means. The numeric head itself is only one later step.
See the frozen source: src/ken/retrieval/{owner_ranking,evidence_features}.py.

Profile query expansion, contextual retrieval, owner descriptions, raw/source
coverage and card construction separately before changing code. Query-independent
source tokens, stem identities and normalized field means could be indexed with
source/model fingerprints. Bounded caches/compact term IDs may avoid rebuilding
those values; preserve candidate-conditioned IDF and exact feature math. Measure
memory and invalidate on source/model changes. Avoid unbounded per-owner token
sets or materializing a full query-by-all-candidate-token tensor.

## Visible evidence construction

The experimental _window tokenizes every overlapping source window independently
while choosing the earliest maximum query-term coverage. For a width-w excerpt
and n source lines this repeats work across roughly n windows. A rolling union
of matching line terms could preserve the exact score/tie policy while scanning
once. _source_fit likewise retokenizes query-independent owned text. These are
plausible local opportunities, not evidence that they dominate actual latency.
Require exhaustive/randomized equivalence and unchanged ALL200 card/pool hashes
before a timing comparison; do not change quality or ownership along with speed.

## Reranker input and uncertainty

The local adapters cap query+card pairs at512tokens and record every truncated
pair. Card consumers can see up to64source lines/12000canonical characters, so
authenticated response evidence and model-visible context can differ. Report
truncation by piece kind and interpret failures before increasing model size.

The published Ettin example accepts query/document pairs and the model architecture
matches the attached CLS/Dense/GELU/LayerNorm/Dense head. Reconfirmed against
https://huggingface.co/cross-encoder/ettin-reranker-17m-v1 on2026-10-15. No prompt
prefix or additional generative pass is required in that documented example.
Its raw score does not certify response evidence sufficiency. Our separate
calibration protects correct-but-sparse cards from rejection; an inconclusive
card is not automatically nonsense. No threshold is chosen from principal labels.

## Responsibilities retained

CandidateProposal owns Recall@10. RelevanceDecision supplies scores and a
calibrated reject/retain decision. EvidenceCard owns attributed source context.
BlindReview measures suitability and verifiability independently of model scores.
One cross-encoder forward can supply both rejection and ordering; two successive
model calls are unnecessary when both use the same scalar. Test retaining Ken's
order among survivors to isolate negative discrimination from fine ordering.


## Source vectors and whole-process peak memory

The source7/version69 artifacts contain TWO source views, contract and
implementation. The version suffix does not mean seven vector matrices.
SourceViewSnapshot already retains registered read-only float32 memmaps and
scores only gathered candidate vectors; avoid proposing that existing optimization
again. OwnerVectorSnapshot, in contrast, detaches its incoming densefloat32array.
The experimental loader first fetches SQLite vector buffers and np.stack creates
an array passed to that detaching constructor. Temporary buffer/array overlap is
a plausible cold-load peak contributor, not a measured attribution. Whole-process
peak RSS includes asset load/warmup; do not describe it as the model's weight RAM
or steady-state residency. Profile before considering a trusted read-only owner
snapshot path with the same registration, immutability and normalization checks.

## Precision and device hypotheses after the padding correction

The original INT8/CoreML probes used wrong pad0 and are diagnostic only. Corrected
pad50283 probes must precede any new device claim. DynamicQuantizeLinear has a
scalar per-tensor scale derived from the extrema of its complete input tensor
(https://onnx.ai/onnx/operators/onnx__DynamicQuantizeLinear.html). Therefore batch
composition and padded sequence length may affect INT8 approximation even when
attention masks are correct; this is an inference from operator semantics, not a
measured explanation of our old score deltas. Compare the same source-free
pairs/published weights with correct padding across batch1/4 and dynamic/fixed512,
then compare FP32. Align outputs by pair identity before testing scores/order;
do not confuse batch permutation with a different ranking. Main benchmark keeps
its registered4/4/2 batches and cannot be silently changed during execution.

For Apple, CoreML ALL allows compatible CPU/GPU/NeuralEngine devices; a traced
CoreML partition does not prove that the hardware executed on GPU. CPUAndGPU
permits GPU but likewise allows CPU. Report the selected backend and measured
latency rather than asserting GPU hardware attribution without evidence. Fixed
shapes may improve CoreML execution, but padding/conversion parity and cold
compilation costs remain separate checks.
Source: https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html
No additional corpus arm, threshold, model fit or production selector is adopted
from these hypotheses. CPU/GPU inference probes wait until the serial CPU corpus
run and public calibration scoring finish.
