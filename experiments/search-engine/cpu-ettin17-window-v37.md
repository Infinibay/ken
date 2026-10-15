# Small CPU reranker control v37

The acceptance contract and all original references remain unchanged. This is a
paired development control, not adoption, the private acceptance run, or the
final API latency certificate. The private reserve remains unopened.

Use the publisher's cross-encoder/ettin-reranker-17m-v1 at revision
9e4aa35321a6dd1a43ca313f500c4b4f7cfb5cc6, Apache-2.0. The official arm64 int8
ONNX encoder outputs token embeddings; append the exact published CLS256,
Dense256/GELU, LayerNorm(eps1e-5), Dense1 head. Register every source artifact and
assembled graph and verify head parity against the native published head. This
does not by itself establish encoder FP32/quantized equivalence.

Evaluate all 400 original development requests on the same public, source-only
visible hypotheses prepared in v34b and the same coarse20 owner selection from
v32's repository-excluded models. No relevance, reference, anchor, purpose label
or answerability field enters inference. Local translated query bytes are fixed.
Use exactly the existing path/identity/signature512/documentation128/visible
source document, but retokenize using the model's own pinned tokenizer. Preserve
the complete query and truncate only the document to 384 pair tokens. Use CPU
ExecutionProvider, two inference threads and batches of four. There are at most
12 hypotheses per owner, hence at most 240 pairs per request; this remains an
offline quality control with a deliberately reported runtime cost.

Order by raw logit, preserving original-query exact authority. Select the best
hypothesis for each canonical owner. Pass all scored owners to the unchanged
presenter so its top10, 40-line, 12000 canonical JSON character budgets and
omitted_count remain authoritative. Empty/nonrenderable hypotheses do not become
answers, and empty queries remain counted failures. Score all 400 final rendered
responses using the original evaluator only after inference completes. Preserve
scores, source/model/data receipts, tokenization/projection/model/presentation
timings, p50/p95/max and peak RSS. No partial-repository percentage is a global
result, and a small graph file does not prove low total runtime RAM.
