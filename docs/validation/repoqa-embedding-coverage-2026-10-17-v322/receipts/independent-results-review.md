# Independent results review — V322

**Verdict:** no numerical inconsistency found in the supplied closed reports or `RESULT-TABLES.md`. Review was authorized after capture/finalization. No model execution, recapture, producer changes, or private-reserve access occurred.

Independently recomputed all 18 model/stage/language aggregates from 1,200 report rows, checked all nine fusion aggregates from 600 fusion rows, reconciled control results with the combined report, reproduced the four stratified bootstrap intervals with the registered seed, and checked all six original-span plus six selected-view summaries against their audit rows. Tables agree, including rounded NDCG, seconds and GiB conversions.

| Model | Complete API top-1 / top-10 | Raw context top-1 / top-10 |
|---|---|---|
| CodeRank INT8 | 128 / 178 | 133 / 182 |
| Jina INT8 | 121 / 170 | 116 / 179 |
| Muninn FP32 | 118 / 158 | 95 / 165 |

Every denominator above is 200 original queries. Strictly matched canonical references cover 97/100 C++ and 100/100 Rust queries; the three unmatched C++ cases remain in the denominator. Jina's API differences are 0 gained/7 lost top-1 and 3 gained/11 lost top-10; Muninn's are 1/11 and 1/21 respectively. Thus neither tested replacement improves the complete API on this exposed sample.

Runtime metadata cross-check: recomputing profile fingerprints from each worker's provenance and the query runtime's package versions matches **600/600** response `profile_version` values. Each arm has one distinct fingerprint; all non-contextual profile fields agree across the 60 workers. This supports correct contextual factory selection and provides no sign of an accidental shared baseline profile. It is a metadata/integrity check, not a new execution experiment.

The following qualifications should accompany public conclusions:

1. **Raw Rust complementarity is specific.** Jina improves raw Rust top-10 from 93 to 96, while raw Rust top-1 falls from 67 to 62. CodeRank+Jina RRF reaches 64/97 Rust and 61/89 C++, totaling 125/186. Against raw CodeRank's 133/182, that exchanges eight top-1 hits for four top-10 hits. It is exploratory raw fusion, not the normal API, and supplies no measured ensemble latency or production improvement.
2. **Context-to-API transitions are bidirectional.** CodeRank loses 24 contextual top-1 hits but gains 19, for a net decrease of five; at top-10 it loses seven and gains three, for a net decrease of four. These counts identify cases for later investigation. They do not isolate a forest, reranker, view policy, or other specific cause.
3. **Token maxima apply to the gold targets audited.** All 200 complete original reference spans fit 1,024 tokens for all three tokenizers; their maxima are 821/669/779. The 197 indexed gold full-owner views have maxima 851/699/813. These are not maxima for every source owner in the corpus. For CodeRank, six original reference spans and ten actual indexed gold full views exceed the 512-token budget; these are separate counts, and the raw original spans are not themselves the captured encoder inputs. Neither all-target fit at 1,024 nor most-target fit at 512 proves that increasing context cannot help: no window-size ablation was run. Full-span misses include unmatched references and must not all be attributed to embedding quality.
4. **CPU results are local measurements with different scopes.** API p95 wall time is 4.610/4.695/4.598 seconds; process CPU p95 is summed CPU time, not wall latency. Peak RSS is 1.327/1.664/1.536 GiB and includes preparation, including concurrent source encoding. The contextual replay timings are not full API latency. Source preparation reused 83,338/83,711 CodeRank vectors and 7,579/83,711 Jina vectors; Muninn reused none. Preparation totals are therefore not comparable cold-indexing costs, and the slightly different query timings do not establish a robust speedup.
5. **Preserve the evaluation label in standalone publication.** State that these are 200 exposed English RepoQA C++/Rust queries on shipped snapshots, with Ken's fixed strict path/callable/range matcher rather than official LLM-based RepoQA SNF evaluation. The confidence intervals are descriptive paired, language-stratified repository-bootstrap intervals from this development sample. Jina top-10's interval includes zero; none establishes blind acceptance, isolated causality of language coverage, or a production-default recommendation.

The tables already distinguish API/context/fusion, preparation-inclusive RSS, original-span boundaries and descriptive intervals. A short standalone scope paragraph should retain the remaining qualifications when these tables are copied elsewhere.
