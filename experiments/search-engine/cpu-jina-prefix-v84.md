# Compact joint comparison84 in a fixed20-candidate cascade

73/75c/77 small general MS-MARCO rerankers and their adaptation did not improve
the current286/400 strict result.80/82 semantic coordinates,78 bare source and83
top1-focused training also failed the fixed integration gate. Do not adopt them.
Test one different pretrained compact joint comparator, without domain fitting:
jinaai/jina-reranker-v1-tiny-en, official pinned revision, Apache2,4layers/384hidden/
about33M parameters and official 8-bit quantized ONNX graph. Source:
https://huggingface.co/jinaai/jina-reranker-v1-tiny-en
https://huggingface.co/jinaai/jina-reranker-v1-tiny-en/tree/main/onnx
The author's distillation/long-context descriptions are hypotheses, not code
benchmark evidence. Download only graph/config/tokenizer/card; no remote Python
code, project upload, API inference, GPU or requiredTorch/Transformers at runtime.

Register immutable artifact hashes/commit/runtime/license before real queries.
Use existing PairRelevance with CPUExecutionProvider,2intra/1inter threads,
batch1, max512 tokens, preserve full query and truncate only document. No8192
token use or sequence-length/model/hyperparameter sweep. Validate graph input/
output shapes and synthetic paired encoding before the quality run.

All16 source7 own contract/implementation69 catalogs and their physical source
hashes already precede the queries. Retain those exact implementation texts,
without body rewriting/query cropping/callee guesses. Bind16source DBs/vectors,
model spec/generation/fullcontext and parent51 replay artifacts, original66c DATA
and original69 scores/producer hashes. Source69 rank selects exactly the first20
owners before new model scores, with its deterministic/exact-name authority.
Use the actual saved expanded query (English unchanged, registered ES translation),
same original query/ID/pool bindings.37 exact singletons bypass new inference.

Two declared readouts of ONE score set: raw pair-logit prefix order, and equal
RRF60 of source69 prefix rank and pair-logit rank. Ties retain source69 order.
All candidates outside the selected prefix retain original69 tail order; no new
candidate or discarded query. Baseline69 plus evidence3 must reproduce286/298
before altered results. Return evidence3, same10/40/12000 budgets and original
ALL-anchor strict scorer on ALL400/EN/ES/implementation/macrorepo, errors-as-zero.

Save all selected indices/query hashes/doc hashes/logits, graph/provider/runtime,
per-query pair time and RSS/heavy imports. Prepared prefix memory includes the
evaluation's complete400 pools; do not pass it off as finalAPI resource usage.
No new training or held-label selection, no candidate expansion/crossrepo lookup.
At least5 extra strict hits over286 remains necessary before API integration and
real latency/RAM validation. Negative readouts stay recorded. No90%, public
Semble win/default promotion or blind acceptance claim. Reserve remains unopened.

Post-run provenance clarification: the unchanged official model_int8.onnx mixes
INT8 and UINT8 initializers. The original frozen84 protocol and asset receipt are
preserved; describing every weight as signed would be inaccurate. Its actual
inputs are input_ids/attention_mask, and the harness only supplies declared
inputs. No graph/tokenization/scoring/evaluation change follows this wording fix.
