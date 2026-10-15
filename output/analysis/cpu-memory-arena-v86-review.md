Independent review of CPU memory arena86 — bounded parity verified

The 57 bound files and frozen85b receipt match. All 32 source probes are independently confirmed as the shortest/longest implementation text in each of 16 source69 repositories, using character length and vector-index ties. They precede the 545 unique query texts reconstructed from all 800 original/expanded views. Selection uses no query similarity, labels or relevance.

All 577 saved normalized vectors equal their31/69 references byte for byte. All four saved raw/vector/token-hash arrays are exactly equal; normalization from each raw vector reproduces its unit vector. Independent retokenization verifies every input, token ID and attention-mask hash. Reports, vector-file hashes and all latency percentiles match the persisted records.

| Fresh process | Peak process RSS, bytes | Recorded p95, ms |
|---|---:|---:|
| default | 794,296,320 | 29.4684 |
| arena off | 816,906,240 | 33.2345 |
| arena off | 854,589,440 | 31.4246 |
| default | 864,206,848 | 28.2670 |

These four runs do not show consistent arena-off memory savings. They provide no basis to adopt the setting. RSS is macOS process high-water RSS, including imports, the input corpus, saved arrays and tokenization. Per-input time includes tokenization, inference, normalization and the expected-vector assertion; its p95 pools 545 queries with 32 source inputs. It excludes initialization and the rest of search. Other research jobs coexist, so this is neither isolated causal timing nor an API resource certificate.

One provenance limit remains explicit: prepare verifies physical model artifacts, but individual worker/final input checks bind the model registration rather than directly hashing graph/tokenizer bytes again. The review confirms all physical artifacts still match registration and all expected vectors/token records agree. Historical per-process artifact-rehash receipts are absent; no observed value mismatch was found. The reviewer did not rerun the four timed processes.

No engine/model/configuration change, fit, relevance scoring or private-reserve access was performed. Detailed sampling identities, physical hashes, array checks and measurements are in [the mechanical report](/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace/output/analysis/cpu-memory-arena-v86-review.json).
