# Native Ettin preparation and reranking — specification

Continues the approved whole Rust migration and explicit instruction to proceed
without intermediate confirmations, using native inline execution. Contextual
ONNX is accepted with20gates on bothOS and fresh review; M2 remains open.
Original sources/tests/resources, installed entrypoint and user indexes stay intact.

Status: this scoped profile passed all 23 gates on both registered platforms and
the independent review, with one deferred Minor. See the
[implementation record](../../validation/rust-migration-2026-10-19/m2-ettin/IMPLEMENTATION.md).
The whole M2 stage remains open.

## Purpose, concepts and caller

Execute the existing Ettin reranker and prepare its graph without Python.
Preserve raw ordered logits; retrieval owns candidate selection/fusion. Limit
this plan to one working model profile, not storage or a general ONNX framework.

- RerankerModel owns registration, source/derived artifact identity and recipe.
- PublishedHead owns validation/compilation of the published FP32 head.
- PreparedReranker owns verified graph/tokenizer/config bytes and their provenance.
- OnnxReranker owns paired token policy, lazy serial CPU session and scoring.
- NativeOnnxRuntime retains authenticated API/executable lifetime, unchanged.

Representative use: parse original registration; verify source; prepare/reuse a
published cache; construct OnnxReranker(model,optional prepared source/cache,runtime,
options); score(query,documents) or pair_fits(query,document). Empty score batches
must succeed without source/cache/core access. Public getters support actual
prepared state and exact tokens for differential validation.

Approach chosen: reuse existing ORT/tokenizers/safetensors and compile the small
published head into the authenticated backbone. Alternatives rejected: runtime
Python assembly or consuming only a Python-built graph (no native preparation);
reimplementing ModernBERT attention (unnecessary new numeric/runtime surface).
A small bounded protobuf field editor can preserve upstream wire data and emit
exact head fields; a generic generated schema is unnecessary unless exact-byte
characterization shows the editor cannot preserve the published serialization.

## Fixed model and preparation

Original owners: src/ken/retrieval/{neural_assets,neural_reranker}.py.
Registration src/ken/embedder/data/ettin-68m-fp32.json remains authoritative.
Source cross-encoder/ettin-reranker-68m-v1@d166fa88ddde3c42bc3ee92f7df476d941c8204a;
all15declared artifacts verified, no remote code/credentials. Backbone272978775B,
SHA95505bbc6a95f9bdfad71e55998fec30c5cc0be490e921cbd796d2dbf0243f2f.
Derived graph274035078B,SHA8e22c1a014dbb6bf803824b531943ee067de4e9c6dea72f8c178348732db38bf.
Tokenizer/config/tokenizer_config retain source sizes/hashes. No floating refs.

Validate CLS pooling, hidden512, square no-bias Dense/exactGELU, LayerNorm512,
output Dense1withbias/Identity; finite F32 weights exact published shapes.
Backbone has one output/opset18. Append Gather(axis1,index0), MatMul(transposed
Dense), exact GELU(x*.5*(1+erf(x/sqrt2))), LayerNormalization(axis-1,epsilon1e-5),
MatMul(transposedout)+bias. Name prefix ken_published_head/. Replace output with
FLOAT[batch_size,1]. Preserve original bytes/hash exactly, not merely equivalent
operators. Small fixtures use the same recipe at hidden3.

Bound all protobuf varints/lengths/offsets, reject malformed/ambiguous graph and
unsupported wire forms or recipe collisions. Preserve untouched fields and
explicit default-valued field presence. Primitive encoding is characterized
against original ONNX1.20.1 before implementation. No native protobuf dependency
is required initially; add one only after a recorded design ruling.

Native cache preparation verifies an existing published cache without needing
upstream; corrupt existing cache errors. A new cache uses a private sibling
stage, verifies derived size/hash and copied config/tokenizer, syncs and atomically
publishes. Concurrent winner is reverified. No partial cache on failure. Use the
shared bounded regular artifact reader/ModelAssets provenance; no unchecked path
reopen between verification and consumption. Runtime is offline; downloading
pinned public data belongs to later native acquisition policy, not inference.

## Scoring and lexical contract

Positive integer options: batch_size1,intra_threads4,max_tokens1024 by default;
inter_threads1, CPU only. Explicit arena enabled, matching original ORT default:
CPU::default().with_arena_allocator(true). Report that policy in actual metadata.
Use existing authenticated ORT1.25.1/API25 core/ownership and declared ARM pins.
No hidden library search, subprocess, GPU or Python fallback.

Before model load, more than10documents errors and empty[] returns empty scores
plus token_ms0,inference_ms0,truncated_documents0,pair_tokens[]; no pad_id.
Model/config loading remains lazy; pair_fits loads policy/session like original
but runs no inference. Declared max_position_embeddings and model_max_length, if
present, must be positive integers and at least requested max_tokens; real both7999.

Only-second truncation, right padding, special tokens enabled. Config pad ID must
match tokenizer's published pad token (string or content object); real50283.
Unbounded no-padding/no-truncation query tokenizer owns pair capacity checks.
Score rejects query over65536Unicode characters or no-special query tokens over
max_tokens-pair_specials-1. Real pair_specials3. Preserve query tokens and trim
only documents. Feeds are I64 input_ids/attention_mask; no token_type_ids.
Return one finite F32 raw logit per document in original order, no sigmoid/L2,
with pair_tokens=sum(mask), count of encodings with overflow, actual timing and
pad_id. Batch sizes1and3and remainder exercise padding/order. Keep independent
owned outputs and serialize session use. Malformed/missing graph outputs, count,
dtype or nonfinite results error; no plausible success scores.

## Independent expectations and evidence

Private pre-port original already assembled the real graph to its exact declared
hash and scored two documents [5.218017578125,-4.434664249420166] on macOS.
This is characterization, not acceptance. Source data downloaded anonymously to
private cache; sandbox DNS attempt and successful network attempt retained.

Reuse frozen original test_reranker_head/test_neural_reranker fixture helpers
through explicit adapters with helper hashes. Tiny head preserves every operation;
tiny pair graph exposes IDs/masks/padding/truncation. Include corrupted head,
weights, outputs, padding/config limits, graph/protobuf and interrupted cache.
Capture fixed real histories independently on bothOS before native scoring.
Exact assets/assembled bytes/IDs/masks/order/counts/state. F32 logits atol1e-5,
rtol1e-5, finite, zero exact; no tolerance widening. Timings vary and cannot prove
speedup/SLA. Retain original runtime/core/platform and actual native identities.

Fixed histories: empty-pool,empty-query,empty-document,spanish,code,unicode,
emoji-nul,repeated-documents,pool10,empty-pool-then-score,batch3-remainder,
pair-boundary1023/1024/1025,long-document,query-capacity-allowed/rejected,
query-char-limit-allowed/rejected,pool11-rejected,custom-budget512and2048,
pair-fits-before-and-after-truncation. Verify raw boundary counts with original
tokenizer; do not guess BPE repeat overhead. Synthetic fixtures also pin invalid
constructor options, absent/changed assets/core, config limits and all error paths.

Acceptance: existing20context/table/Potion/M1gates plus Ettin release, actual
native preparation and real reranker parity. Fresh bothOS immutable-source full
Python exact-baselineIDs/mypy, Rust/fmt/clippy, original1066hashes; process outside
checkout with authenticated owned model/core, sentinel PATH, binary/core audits,
actual Linux1exec. Extend current-source matrix and explicit prerequisites/CI.
One fresh whole-plan review then one TDD correction pass for C/I; defer Minors.
Only this profile accepted; selection, other runtimes, storage and M3–M8 remain.

Sources: pinned original code/tests and ort CPU provider source2.0.0-rc.14;
[official ONNX protobuf schema](https://github.com/onnx/onnx/blob/main/onnx/onnx.proto),
[ONNX IR](https://github.com/onnx/onnx/blob/main/docs/IR.md). The installed1.20.1
Python descriptors/serialization supply version-exact data characterization.
