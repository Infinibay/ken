# Final document review

No required numerical correction or blocking overclaim found in `README-FINAL.md`, `METHOD-FINAL.md`, `SCORING-FINDINGS-FINAL.md`, or `bottleneck-cases.json` at the hashes below. No producers, models, captures or grades were changed or rerun; the private reserve was not accessed.

Verified against existing reports/captures:

- 66 of 69 indexed CodeRank top-1 misses have an actual full-owner view of at most 512 tokens. Original-span maxima and selected-view maxima remain distinct; all audited gold spans/views fit 1,024, without claiming the whole corpus fits or that an 8k ablation was performed. The pinned model cards support Jina's 512-token training/ALiBi extrapolation and Muninn's 8,192-token supported context.
- The 24 displaced raw-first targets are exactly six C++ and eighteen Rust cases. The API repairs 19 other raw-first misses; top-10 loses seven and repairs three. All 24 saved final first choices and raw cosine fields match the captures; all saved per-model ranks and token lengths match the metric/token audits. The four displayed examples have the reported names, ranks and lengths.
- Jina's 17 new raw-first hits comprise ten already correct in the baseline API and seven still incorrect in Jina's API. Muninn's six comprise one already correct and five still incorrect in its API. These statements do not conflate raw improvements with new API hits.
- Control wall median/p95 normalized per 100 supplied files independently reproduce 4.113/13.834 seconds. The documents correctly say the one-second goal is not met under that normalization and explicitly reject treating selected-file counts as full repository sizes or a scaling law. Wall p95, preparation-inclusive RSS and separate contextual replay are labeled appropriately.
- Root-cause language stays conditional: stage disagreements do not identify a specific forest, feature or reranker. The exposed development population, unofficial strict criterion, unchanged denominator and closed reserve are explicit.

Optional precision: the statement that API top10=89% limits attainable top1 below90% is a ceiling **when only reordering those recorded ten results**. Upstream candidate selection or reranking a broader pool can change that ceiling. The surrounding discussion already calls for improving selection, but this short qualification would make the sentence unambiguous in isolation.

Reviewed SHA-256 identities:

| Artifact | SHA-256 |
|---|---|
| README-FINAL.md | `47be696237eefb8615d8063ba42ccd3c395a62051c1892bc57c2ec2c7577d4f5` |
| METHOD-FINAL.md | `4d928ca550011c918a1538ed63febf13b8cee278883b8977e8d511ab331e6fe5` |
| SCORING-FINDINGS-FINAL.md | `dcc51c65711013420b90e046986b6ce751e954cce728313b8a4554e9f6382211` |
| bottleneck-cases.json | `1cc2d6444a2bc4aabd3ac3d59b9a656c29048c925ad3c79f2a0d4cc75f694fe3` |
