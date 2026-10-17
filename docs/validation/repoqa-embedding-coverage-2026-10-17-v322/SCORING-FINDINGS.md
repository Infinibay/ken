# Embedding inputs and ranking follow-up, frozen c4c86543

This extends the earlier `repoqa-parser-ranking-2026-10-16-v249` findings.
It records source-level responsibilities and measured stage disagreements.
This experiment did not capture a new per-tree/per-feature score decomposition.
Do not infer a particular feature's causal contribution from the counts below.

## Source information before tokenization

- `src/ken/retrieval/description.py:describe_owner` gathers every distinct owned
  source region, checks one owner/source version, and rebuilds implementation
  lines. It avoids filling gaps with another owner's text. Consequently a
  complete enclosing reference span may contain nested-owner source that is not
  supplied to that owner's embedding.
- `src/ken/retrieval/context_preparation.py:full_owner_text` supplies path,
  identity, signature, documentation limited to 800 characters, and the owned
  implementation. The implementation itself is not head/tail-compacted here.
- `src/ken/retrieval/source_views.py:owner_view_texts` supplies a separate full
  documentation/empty-source contract view and an implementation/empty-doc view.
  All three views are encoded separately and receive their own cached vectors.
- `src/ken/embedder/contextual_onnx.py:ContextEncoder` uses dynamic, unpadded,
  single-item inputs and a hard 512-token prefix. The frozen Jina/Muninn research
  adapters use that same budget, their native pooling and prescribed prompts.
- `src/ken/retrieval/contextual.py:ContextualRetriever.score` normalizes query
  vectors and scores all canonical owner vectors by dot product. Original and
  expanded queries are separate when different. The raw diagnostic sorts the
  maximum of these scores, restricted to canonical eligible symbol owners.
- Contract and implementation similarities are separate later contributions.
  The raw full-owner diagnostic is not the whole three-view retrieval/ranking
  pipeline. The native forests and Ettin remain frozen across models.

An encoder's supported window, the selected source representation, and the
context returned by the CLI/MCP have different responsibilities. Increasing the
first cannot recover information omitted by the second. A longer document
window mainly changes prepared source vectors and indexing cost; short unpadded
queries do not automatically become 8192-token inference requests.

## Measured ranking losses and counterexamples

Control raw context top-1 is correct in 133/200; complete API top-1 in 128/200.
There are 24 raw-first hits displaced (6 C++, 18 Rust) and 19 errors repaired.
Therefore replacing the complete order with raw context is not a solution.
At top-10 the complete pipeline loses seven and repairs three.
The nineteen repaired first-result cases are saved separately in
`receipts/repaired-cases.json`, including raw wrong choices and target scores.

Examples below are exact strict-reference disagreements, not equivalence claims:

| Query ID | Reference target | API first choice | Reference final rank | Gold full view tokens |
| --- | --- | --- | ---: | ---: |
| `6005bb39a6d95a45ab58042e` | `clickhouse/exceptions.h:ServerException` | `Client.Impl.ReceiveException` | 2 | 90 |
| `a979ba67918bf9f7c3d043a4` | Cargo `uninstall_one` | `uninstall` | 2 | 190 |
| `4029e9939c70440a5eba8e66` | Candle `squeeze_dims` | `Tensor.squeeze` | 3 | 167 |
| `5f57f8e5612e3c77fc4f29f2` | tracing `sparse_value_sets_are_not_empty` | `value_set_with_no_values_is_empty` | 2 | 173 |

The saved 24 cases include exact paths/spans, gold input lengths, raw cosine
values and per-model final/context ranks. They suggest useful investigation
categories: factory/caller versus implementation, overload/file identity, and
positive versus negated/test behavior. These are hypotheses for feature/stage
tracing, not established root causes. Keep criteria unchanged when testing them.

Jina gained seventeen raw first hits over CodeRank, but ten were already correct
in the baseline API; the other seven remain incorrect with Jina's API. Jina has
zero new API first hits overall. Muninn gained six raw first hits, only one of
which was already baseline-API correct; those five raw improvements also remain
incorrect in its API. Better rank in one channel can fail to survive selection.

## What the window audit establishes

For CodeRank, 66/69 indexed top-1 failures have an actual full-owner input fitting
512 tokens. All 197 indexed target full views fit 1024, as do the 200 original
reference spans. No original/expanded query exceeds 512. Counts include model
prefixes, and selected inputs are verified verbatim against actual source caches.
This weakens direct gold-input truncation as the main explanation on this sample;
it does not establish irrelevance of larger windows, outside-owner context,
representation policy or the effect of changing competing candidate embeddings.
A window-size accuracy ablation has not been run.

## Next bounded experiments

1. Trace the exact existing feature/forest/proposal/reranker values for the saved
   24 displaced raw-first targets, and the seven raw-top10 targets missing from
   the API. Separate candidate pruning from reranking; first verify output order
   with diagnostics enabled is identical to the recorded public calls.
2. Trace the nineteen counterexamples repaired by the current pipeline, so a
   proposed fix does not simply promote semantic lookalikes or wrappers.
3. Improve proposal selection and ordering with CPU/RAM gates. API top10=89%
   limits attainable top1 below90% when only reordering those same ten results;
   upstream selection can change that coverage. Contextual top100=197/200 is only
   a candidate-availability signal. Avoid increasing expensive reranking to100
   without measuring cost.
4. If testing a larger embedding input budget, vary it independently on all the
   same original queries and preserve parser/model/ranking/acceptance criteria.
5. Validate on a genuinely untouched acceptance population only after the public
   development work is ready; the private balanced reserve stays closed here.
