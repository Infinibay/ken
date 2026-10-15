# Real-input quantization and response replay audit v39

Do not alter the running v34b training, its saved models, scores, input hypotheses,
or original responses. The original strict scorer and all400 references remain
fixed; no private acceptance files are opened.

For every completed v34b fold, select two requests without relevance labels:
the lexically first public request whose local expanded query equals the original
and the first whose expansion differs. If one group is empty, fill from the
remaining request IDs in lexical order. This produces32 audit queries across16
repos. Use precisely their existing coarse20 selections and all renderable v34b
hypotheses, preserving384 token input IDs, masks and type IDs.

Load the saved native weights on CPU and verify their complete state hash against
the training receipt. Compare native and FP32 ONNX for eight deterministic real
pairs per query (evenly spaced in public hypothesis order, or all if fewer),
checking maximum absolute logit error against1e-4. Then score ALL hypotheses of
each selected query with FP32 and int8 graphs. Record absolute logit errors,
complete raw-score rank differences, winning hypothesis and canonical-owner
changes both with and without original exact authority. Do not silently assert
ranking equivalence or generalize this32-query sample to all400. The final strict
evaluation of the actual quantized profile remains a separate all400 gate.

Independently reconstruct all400 responses from v34b's stored int8 scores once
all16 folds finish. Rebuild every scored canonical owner with its winning real
visible hypothesis and pass ALL owners to the original presenter, which owns
top10 and omitted_count. Preserve the original response files. Register the
reconstruction, store new responses, and run the unchanged original evaluator
again. This repairs response metadata without re-training or selecting new
scores/windows. Do not turn a partial response replay into a global percentage.
