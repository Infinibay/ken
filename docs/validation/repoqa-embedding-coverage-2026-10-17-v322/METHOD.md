# Contextual embeddings on public RepoQA C++ and Rust

Status: all 600 normal API calls, diagnostic captures, source/evidence checks,
native parity and label-free preflight completed successfully. Independent
results review found no numerical inconsistencies.

## Question

Does replacing Ken's contextual embedding with an artifact whose published
training coverage includes C++ and Rust improve retrieval under the existing
engine? This measures complete fixed artifacts; it cannot isolate language
coverage from architecture, precision, training, prompts or tokenization.

## Models and controlled responsibilities

| Arm | Context model | Artifact | Native vector | Pooling |
| --- | --- | --- | --- | --- |
| Control | CodeRankEmbed, 137M | pinned CPU INT8 export | 768 | CLS |
| Jina | jina-embeddings-v2-base-code, 161M | official CPU INT8 ONNX | 768 | masked mean |
| Muninn | Muninn-small, 47M | original BF16 weights cast to FP32, CPU ONNX | 384 | native CLS |

Muninn's 384 values are padded with 384 exact zeros solely to fit the frozen
768-dimensional preparation interface. This preserves cosine but overstates
native vector storage. The adapter identity includes prompts, graph and
tokenizer hashes, pooling, padding, budget and runtime versions.

All arms use the same full-owner, contract and implementation source views,
512-token contextual limit, batch size one, two intra-op threads, one inter-op
thread and CPUExecutionProvider. Source preparation uses four concurrent
single-item calls only after checking equality against serial execution.
Preparation finishes before query warmup and timing. The static Potion model,
native forest, piece forest and Ettin-68M reranker (1024 tokens) are unchanged.
No fitting occurs. Product source is frozen at c4c86543 with the same 431 file
hashes. Product dependencies, presets and defaults are unchanged.

Source views and tokenizer budgets differ from the context returned by Ken.
An embedding's maximum input window is not a limit on the code Ken can return.
The token audit describes current gold source views and original queries; it
does not imply the whole repository or every expanded query fits that window.

## Cases, criterion and limits

The exact same 200 original English queries are used for each arm: 100 C++ and
100 Rust, ten queries in each of twenty repositories. This is an exposed public
development population, not the private acceptance reserve. The supplied
RepoQA source snapshots contain selected repository files, not full upstream
checkouts. All 100 cases per language remain in every denominator, including
canonical-parser and reference mismatches. Original queries, source revisions,
references and the strict piece scorer are pinned and unchanged.

The criterion checks the original file and callable identity and source span;
it is a retrieval proxy, not the official RepoQA LLM-based SNF task. No added
evidence-sufficiency threshold or result-format matching determines an answer.
Quoted evidence is checked literally against the pinned source for integrity.

Pretraining overlap with the public RepoQA repositories or queries is not established.
Jina reports training at 512 tokens and ALiBi extrapolation to 8192; support for
a longer window is not itself evidence that longer inputs improve this task.
Muninn publishes an 8192-token maximum. This capture compares both at 512.

The private balanced reserve remains CLOSED. This experiment does not establish
90% generalization, compare official SNF scores, or authorize a default change.

## Three distinct measurements

1. Normal public `find_best` responses through the frozen complete Ken engine:
   actual top-1 and top-10.
2. Raw contextual retrieval over all eligible canonical source owners: top-1,
   top-10 and top-100. This observes the full-owner channel, not the complete
   three-view/native/reranker pipeline.
3. Predeclared equal RRF60 over the diagnostic top-100 lists, returning ten
   pieces. These exploratory fusions are not actual Ken API results. A union
   of two or three raw top-ten lists may contain twenty or thirty slots and is
   only an oracle upper bound, never a ten-result recall claim.

A raw embedding improvement that does not survive the complete pipeline
motivates further stage-level investigation. It does not identify a particular
forest, feature or reranker as the cause. Existing forests were calibrated on
the previous embedding distribution and remain frozen here.

## Runtime and integrity

Latency is measured around each real API call, including compact rendering,
after warmup. CPU time is measured separately. Peak process RSS includes source
preparation and its concurrent activations; it is not warm-query-only RAM.
Prepared control caches are reused; Jina has mixed cache state from the earlier
closed infrastructure run. Preparation totals are not a fair cold-index cost
comparison. Query processes assert no Torch, Transformers or SentenceTransformer
imports, and both embedding and reranker assert CPU providers.

Before any reference labels or ranks are read, the label-free preflight checks
all sixty workers, six hundred request IDs with exact multiplicities, success
provenance, mandatory pinned artifacts, producer/input hashes and no failure
markers. Synthetic tests reject missing IDs, duplicates, incomplete provenance,
worker failures and tampering. Every result and excerpt is later checked against
the original pinned source.

Independent review caught an incorrect queued mean-pooling Muninn exporter.
The three waiting V321 jobs were retired before export, candidate captures or
quality inspection. V322 uses actual SentenceTransformer 5.5.1 native CLS,
verifies capture-tokenizer IDs against the native tokenizer, exact native vs
wrapper vectors, and CPU ONNX parity on six label-free synthetic inputs,
including a 512-token input. Original invalid producers and correction receipts
are retained. This was a protocol correction, not a selection from model scores.

## Primary sources

- [Jina v2 base code model](https://huggingface.co/jinaai/jina-embeddings-v2-base-code)
- [Muninn-small model and native configuration](https://huggingface.co/brokkai/Muninn-small)
- [Muninn's published Quarry evaluation dataset](https://huggingface.co/datasets/brokkai/Quarry)
- [ONNX Runtime thread controls](https://onnxruntime.ai/docs/performance/tune-performance/threading.html)

No release, tag or PyPI publication is part of this experiment.
