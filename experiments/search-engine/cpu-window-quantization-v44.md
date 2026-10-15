# Embedding precision ablation v44

Keep all400 original queries, references, strict anchors, budgets and unopened
private acceptance fixed. This does not change v34b training or its frozen
outputs. All native weights and repository-excluded coarse selections stay fixed.

The label-free v39 audit found native/FP32 agreement on real inputs but actual
ranking changes after full int8 quantization. Test the precision tradeoff without
increasing model parameters or requiring GPU: retain the embedding Gather table
in FP32 and quantize only MatMul/Gemm weights, per-channel signed int8. The model
still has22.7M parameters. Record actual graph size, CPU time and RSS; a larger
file is not automatically unacceptable RAM, and no performance win is presumed.

For each completed v34b fold, export alternativeB from its saved FP32 graph using
fixed settings, not another training run. Compare with alternativeA's stored
full-int8 scores on the identical public coarse20 × up-to12 visible hypotheses.
Reconstruct BOTH alternatives with every scored owner passed to the unchanged
v34 presenter, repairing omitted_count identically. Preserve original files.
Original exact authority and stable owner/hypothesis tie order remain unchanged.

Wait for all16 folds and grade all400 final responses with the original scorer.
Report each alternative and graph/timing metadata separately. Compare absolute
logit differences without claiming that either quantized variant is FP32-exact.
The separate32-query native/FP32 audit and the actual final API profile remain
separate checks. Do not infer a global percentage from early completed folds or
choose settings by held-out per-repo labels. This is an offline controlled
development test, not final API/default/acceptance certification.
