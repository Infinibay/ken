# Native retrieval kernels (M4a)

Parent contract: `2026-10-18-rust-migration-design.md`. The user authorized the entire migration, native inline execution, original preservation and continuous stage progression without further confirmations. This document records the implementer's choices within that authorization.

## Purpose and boundary

Search must propose the same source owners, retain the evidence that proposed them and rank stable ties reproducibly. M3 supplied real source passages, lexical postings and immutable vector views. M4a makes those data searchable through complete native library operations. It does not claim M4 public CLI/MCP acceptance before the remaining search paths and adapters exist.

The M4 capability map is: M4a request/candidate identities, BM25F, dense owner retrieval and proposal fusion; M4b exact lookup/query intent, snapshot candidate union, owner descriptions, contextual views, evidence/features and ranking; M4c production forests/neural reranker, piece selection, fresh bounded evidence and presentation; M4d direct/historical search channels, public CLI/MCP transport, quality/resource and freshness gates. No capability is removed from the denominator. Detailed plans follow each coherent boundary, with previously accepted kernels reused.

## Concepts and use

`SearchRequest` owns validated query, target, purpose and result/output budgets. `Candidate` carries one canonical `EntityKey`, proposed passages, named measurements and complete owned regions. `LexicalRetrieval` scores current matching postings and groups by canonical SQL owner before a budget. `DenseView` owns one immutable ordered vector generation and groups maxima by canonical source identity. `ProposalFusion` combines ordered named runs, voting once per owner per run and preserving source generations, evidence and measurements.

Representative native use:

```rust
let request = SearchRequest::new("COOKIE_JAR_CONFLICT")?;
let lexical = lexical_candidates(db.connection(), &request, 100)?;
let dense = DenseView::new(passages, vectors)?;
let behavior = dense.search(&query_vector, "behavior", 100)?;
let candidates = fuse_proposals(&[("lexical", lexical), ("behavior", behavior)], 100, 60)?;
```

The caller supplies query embeddings; a later M4 adapter invokes the already accepted query-side model operation. These kernels never download models, read source files to answer lexical queries, spawn Python or mutate input candidates. No placeholder service is credited.

## Approach

Extend the existing `ken-retrieval` crate and reuse accepted passage/storage/vector ownership. Translating the NumPy expression into a parallel array framework would introduce a dependency without a needed concept. A second search schema would duplicate the authoritative postings. Use ordinary Rust collections with explicit first-occurrence order and scalar f64 lexical arithmetic. Dense F32 reductions use the original platform BLAS dispatch: final review demonstrated a scalar reduction can reverse exact cutoff/evidence order. macOS uses Accelerate; Linux aarch64 uses the pinned pure-native OpenBLAS/Fortran bundle in `crates/ken-retrieval/resources/dense-runtime.json`, SHA/length verified before loading with the already pinned libloading dependency. M7/M8 must package its30,371,298bytes/licenses beside the executable; no Python runtime. No database format changes. The final receipt records this review-driven ruling and its cost.

`SearchRequest` preserves defaults target=symbol, purpose=auto, limit=10, max_chars=12000, explain=false, piece_kind=None. Positive budgets and nonempty frozen-Unicode15-stripped queries are required; target is file/symbol/passage; purposes auto/implementation/usage/tests/documentation; piece kind class/module/symbol/file or absent. Span merging sorts, deduplicates and merges adjacent inclusive intervals.

BM25F uses field order identity/signature/documentation/body/path, k1=1.2, length normalization b=.75 only for body/documentation and b=0 elsewhere. A term's document frequency counts each matching passage once, including terms shared across fields. Combined field TF saturates once per term; individual field measurements retain their separate saturation. Match unique code tokens in first-occurrence order, at most128. SQL corpus statistics use the same read snapshot; no cache may cross databases, rolled-back own writes or source generations. Candidate order is descending total score then passage ID; group by(file_id,symbol_id), cap owners with max(1,limit), keep at most4 ranked passages per owner and take per-signal maxima across its complete matched group.

Dense scores normalize an actual finite nonzero F32 query against the immutable F32 matrix. Dimension mismatch is an index-version error. Owner maxima use identity first encountered in vector row order for score ties; evidence is stable descending score/vector row order, at most4 per owner. Preserve Python negative slicing behavior if a kernel limit is negative; public request budgets remain positive. Invalid matrix ownership/dimensions fail explicitly, never fabricate evidence.

Proposal fusion requires positive owner and RRF budgets. Named channels preserve caller order. A duplicate owner contributes once per channel at its distinct-owner rank. Retain max named measurements, ordered unique spans, max passage measurements and merged owned regions; reject empty evidence, mismatched owners or different hashes for any proposals from the same file. Sort exact priority, descending RRF, path, earliest proposed span, stable insertion for remaining ties. Do not mutate inputs.

## Differential evidence and numerical contract

Before implementation, capture actual isolated frozen-original calls, inputs, complete outputs/errors and original lexical/dense/proposal suites with module hashes, discovery and JUnit. The native probe accepts only inputs. Use accepted M3 passage inputs, fixed independently generated postings/matrices and scalar boundary cases; expected outputs never enter native requests. Preserve all names, order, owners, spans, hashes, vector ownership and failure categories exactly.

For positive F64 BM25 sums, compare absolute1e-12+relative1e-12: the bound covers libm `log1p` and ordered positive reductions across at most128 query terms/five fields; raw scores remain retained. F32 normalized dot arithmetic uses the previously accepted M2 absolute1e-6+relative1e-6 bound. Neither permits a ranking/membership/tie-order difference; ordered owner/evidence identities must match exactly. Nonfinite observations are encoded explicitly as observed categories, not silently dropped. These bounds are fixed before the new captures or implementation.

Test hand calculations, shared-field saturation, rare literals, unchanged/edit/delete generations, rollback with repeated generation IDs, independent databases, Unicode/negation tokens, owner ties and late evidence, empty/dimension/invalid query vectors, duplicates/overlapping spans, mixed source generations and error propagation. Test actual native SQL usage through indexing fixtures without Python at runtime. Both actual platforms need authenticated input-only process parity, affected native/tooling gates, original preservation and one fresh final review with one Important/Critical TDD fix pass. M4a acceptance remains a kernel boundary; M4/global acceptance remains false.
