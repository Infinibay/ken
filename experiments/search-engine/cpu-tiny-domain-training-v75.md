# Query/code domain adaptation with a4.4M model, CPU only v75

Current experimental API74 is286/400strict, source7/policy3, still below90%.
Independent-vector signals and generic33.4M tokenMaxSim did not close the gap.
Hypothesis: adapt a compact joint-attention model to source behavior comparisons,
instead of accumulating more untrained geometric signals. No heavier model/GPU.

Base: official Apache2 cross-encoder/ms-marco-TinyBERT-L2-v2,
revision81d1926f67cb8eee2c2be17ca9f793c7c3bd20cc,4,386,049parameters,
2layers/hidden128,17,552,980B safetensors. Native public artifacts downloaded75
with hashes, no remote code/inference/query uploads. Source73's int8 teacher is
the same pretrained checkpoint, not trained on development references.

Use the complete bound source7 implementation text from69, original40066cpools,
original eligible_owner labels from66c and parent bindings validated73Tiny.
All text/owner/source/generation/hash inputs remain fixed. Read no private reserve.
Do not use source anchors to crop input, summaries from the desired answer, or
held-out queries/labels for training, mining, schedules or checkpoint selection.
Raw and translated requests remain the actual runtime inputs: train/score only
the actual expanded query once, complete query retained by only_second truncation.

For EACH of16folds reload the identical official base and reset optimizer/seed;
exclude every query from the held repository. One source-eligible positive in
original proposal order; four distinct ineligible negatives: firstproposal plus
the strongest remaining pretrained73Tiny expanded logits. Source-ineligible,
allpositive and deterministic exact singletons may lack training pairs, but ALL400
original requests still count at evaluation.7RED/GREEN tests cover held isolation,
held-label/score perturbation, exact/zero-eligible skip and corrupt bindings.

Fixed training: CPU float32/eager attention,2intra/1inter threads,seed20261015,
3epochs,AdamW lr2e-5/weight_decay.01,clip norm1,warmup10% thenlinear decay.
One query rank group per microbatch, crossentropy over1positive+up to4negative
logits (positive index0),4queries gradient accumulation per optimizer step;
last partial step uses its actual query count. Allqueries equal weight, no early
stopping or selecting a checkpoint on the held repository. Train max512tokens,
only_second/padding for a training group; inferencebatch1/no padding. Record
all selected source row IDs/labels, excluded repo, schedules, train losses and
weight/checkpoint hashes. Native weights/optimizer are offline research only.

Export final fixed-epoch models to17MB float32 ONNX (opset17,dynamoFalse) for
CPU-only inference; no Torch is required by the proposed inference artifact.
Before any quality scoring require native/ONNX logits on5label-free empty/Unicode/
identifier/long/ES probes within absolute2e-5. Do not transfer int8 teacher scores
as float32 baseline. Export and score the original untrained float32 checkpoint
too, for a genuine paired pre/post comparison with the same source/text/budgets.

Exactly4 prepared controls: pretrained raw, pretrained equalRRF with69's fixed
repo-excluded rank order, adapted raw, adapted equalRRF with69. RRF constant60,
one vote per canonical owner/model and deterministic original exact authority;
stable ties preserve69 order then original pool position. No weight/epoch sweep
or secondary learned ranker (which would need nested exclusion to avoid leakage).
Source evidence uses explicit policy3, same40lines/12kJSON/10upperbound and the
original ALL-anchor strict scorer; ALL400/EN/ES/implementation/macrorepo reported,
errors/missing0. Keep all models, answers and negative results. These are prepared
controls, not an API/default/acceptance/CPU/RAM certificate. Only a clear strict
gain over286 (at least5queries) can justify further integration/resource work.
