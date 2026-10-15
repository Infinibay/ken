# v110: fixed68M FP32 precision control

Same-weight precision control, not a newly trained model or default adoption.
The17M FP32 control v108 is closed: raw identity146/200, RRF50 165/200, RRF25
171/200 versus native168/200; all Recall10197/200. This does not establish joint
quality, generalization, or a reliable improvement over baseline. Keep all arms.

Repeat the same preset raw/RRF60(0.5)/RRF60(0.25) policies on the frozen v102
cards/expanded queries, with the already registered68M model's same revision,
head, tokenizer and padding50283, replacing only its published INT8 encoder with
the published FP32 ONNX encoder. Revision d166fa88ddde3c42bc3ee92f7df476d941c8204a,
encoder272978775bytes SHA95505bbc6a95f9bdfad71e55998fec30c5cc0be490e921cbd796d2dbf0243f2f.
Source API and SHA-authenticated local download receipts are retained.
Published source: https://huggingface.co/cross-encoder/ettin-reranker-68m-v1/tree/d166fa88ddde3c42bc3ee92f7df476d941c8204a/onnx

No Gold/private inputs in production. CPU only, same2 intra/1 inter threads,
fixed batch4, max512 tokens, only-second truncation and exact bypass. Retain ALL
200 cases, the same10 candidate identities, every preset arm, errors and misses.
Do not select weights after scoring or interpret reranker-only replay RSS/time
as complete Ken cost. Check head parity/source pins, close every output before
identity scoring. Joint utility requires independent current-card review.
