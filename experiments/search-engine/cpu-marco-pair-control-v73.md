# Small jointly attentive query/code controls v73

70's trained33.4M late-interaction head did not improve69. Test whether joint
attention can identify behavioral constraints better than independent token
MaxSim, using much smaller CPU-only models. Official primary model cards:
https://huggingface.co/cross-encoder/ms-marco-TinyBERT-L2-v2 and
https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2 . They are MS-MARCO
English text rankers, not code-trained models; no published score transfers here.

Pin public Apache2 artifacts downloaded73: TinyBERT-L2 revision
81d1926f67cb8eee2c2be17ca9f793c7c3bd20cc, ARMint8 graph4518071bytes;
MiniLM-L6 revision233902d25c440f23af6f7d6e94d2946bac0bee0a,
ARMint8 graph23200716bytes. Hash tokenizer/config/card/graphs in the registration.
No remote code/queries, GPU, heavier encoder or default change.

Before query access register ALL16 actual source7 implementation texts from69
owner/view SQLite stores, exact entity/source/text hashes/generations. Keep the
registered body projection (path/identity/signature/emptydoc/wholeownedcode),
never borrow factory/caller documentation or nonowned sibling bodies. No new
source embeddings: a cross-encoder scores each actual query/document pair.

Use existing tested bench.PairRelevance, ONNX CPUExecutionProvider only,
2intra/1inter threads,batch1,max512 pair tokens, truncation only_second to preserve
the complete actual original/expanded query. Raw one finite logit per pair,
no arbitrary sigmoid/calibration. Pin all bytes/runtime/tokenization/math.
Measure both original and actual expanded requests for every candidate in ALL400
fixed66c pools. Duplicate exact pair inputs may reuse a scalar with a recorded
cache hit count; timings remain prepared diagnostics, not completeAPIcertificates.
37 deterministic exact singleton bypasses use neutral numeric placeholders only.

For each model/query view add raw/to-poolmax/range-relative/stable reciprocal rank
(8permodel) to the unchanged251source69 columns. Complete request/pool/qid/index/
full251prefix/hash validation precedes derivation and fitting. Keep all800input
text bindings. No relevance labels are read by feature producers.

Exactly3 fixed controls: Tiny259,Mini259,both267; original160tree parameters and
16whole-repo-excluded folds, native/export exact. Score ALL400 original strict
references/ALLanchors with40line/12kJSON and missing/errors0. Keep every result.
No acceptance/private/default claim. Integration requires a clear strict gain
(at least5of400 over69), actualAPI reproduction and measured CPU/RAM; otherwise
reject added inference. No further width/threshold sweep on these controls.
