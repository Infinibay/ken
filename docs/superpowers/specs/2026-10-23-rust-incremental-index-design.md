# M3e — Native incremental indexing

Implements the remaining M3 index boundary from the approved [migration design](2026-10-18-rust-migration-design.md). Execution remains native and continuous as requested; existing sources and receipts remain intact. This is a subsystem specification, not closure of M3–M8.

## Purpose and representative use

`Indexer::index_files(&mut ProjectDatabase, &ProjectPaths, &[PathBuf], &IndexOptions, &mut dyn Progress)` reads changed sources, parses them with `ParserRegistry`, prepares document vectors, and publishes each complete file. A second identical call reports unchanged files without loading models. Edits replace their symbols, imports, intent, lexical postings and both prepared retrieval views; deletes remove the same dependent rows. File order, progress, errors and durable data are compared with the frozen original.

## Concepts and ownership

- `CodeVocabulary` in `ken-retrieval::vocabulary`: the shared name and code token rules for index and later query consumers. Python Unicode 15.0 normalization, word classes, decimal digits and full case folding are pinned.
- `Passage` and `PassagePolicy` in `ken-retrieval`: authenticated physical source regions, canonical owner identity, fields and segmentation. Lossless `PythonText` documentation stays lossless until SQLite requires scalar UTF-8.
- `PassageRepository`: transactional replacement and loading, canonical symbol association, term frequencies and extraction stamps. It never commits its caller's transaction.
- `PreparedProjection`: immutable texts and vectors for both retrieval views, encoded outside the source transaction; publication checks the profile tuple and source generation.
- `PreparedFile` in `ken-index`: one source's hash, parse, canonical symbols, intent, passages and embedding destinations. It contains no database policy.
- `Indexer`: chunk orchestration, change detection, parser execution and progress. `IndexWriter` owns publication, name postings and legacy vectors. `ImportCatalog` remains the single import resolution authority.
- `DocumentEncoder`: explicit fallible document encoding, dimension and actual token count boundary; an adapter delegates to accepted `ManagedEncoder`. Provided deterministic encoders test the boundary without supplying oracle vectors.

## Approach and compatibility

Compose accepted native store, source paths, parsers, imports and model owners. A structural-only index would omit retrieval fields and active-profile updates; translating the Python indexer into one large module would duplicate existing responsibilities. Two functional crates (`ken-retrieval`, `ken-index`) express actual consumers; no future empty crates.

Preserve parser version 10, extractor version 8, name-token version 1, default lexical segmentation `code-lexical-v1`/256 tokens, chunks of 128, max source bytes from the caller, BLAKE2b-256 and SHA-256 generations. Plain inputs publish before parsed inputs within a chunk, while progress follows input order. Stable canonical symbol merging includes nested scopes omitted by outlines. Plain intent limits, weights, embedding text and document-side encoder calls remain exact.

Pin `blake2=0.10.6` and `unicode-normalization=0.1.22` (Unicode 15). Existing dependencies remain locked. Primary references: [variable BLAKE2b output](https://docs.rs/blake2/0.10.6/blake2/type.Blake2bVar.html), [normalization version](https://raw.githubusercontent.com/unicode-rs/unicode-normalization/v0.1.22/src/tables.rs). Full casefold data is generated from and attributed to the frozen original Python Unicode 15 database, not a newer host runtime.

Use scoped native threads instead of Python worker processes: parse outputs remain ordered and SQLite remains on the calling thread. Serial fallback reports parser errors identically. Reuse existing M2 snapshot-safe vector allocation: an edited file receives a safe slot while its committed old slot may still be needed after rollback. This intentionally improves the original in-place file-vector overwrite. Physical slot addresses can differ; raw addresses are retained and audited, while ownership, readable normalized vectors, storage format, rollback and bounded reuse must pass. No other field differences are waived.

## Failure and atomicity contract

Stat/read/parser failures are per-file skipped events; encoding errors abort before publishing the chunk. Oversized files are skipped before reading. No silent model fallback or query prompts on stored documents. Vector-store open failure uses explicit recorded inline BLOB compatibility. Source/profile changes during projection preparation reject publication. Each file has an IMMEDIATE transaction and complete source, terms and views; invalid/nonfinite vectors, missing canonical symbols and non-scalar SQLite text roll back. Immutable retrieval artifacts deduplicate by view/revision/text hash; edits reclaim only retired unreferenced artifacts. Unchanged checks consult stamps, never scan passage bodies or instantiate encoders. A stale name stamp triggers a full postings rebuild.

## Acceptance evidence

Linux and macOS must execute the same native input-only requests. Capture original vocabulary, passage and indexing behavior once in isolated frozen checkouts, including fresh actual SQL and deterministic encoder boundaries. Retain discovery, JUnit outcomes, original-module provenance, requests, outputs, binary and source hashes; never manufacture expected results with native code. Compare all passage fields, line spans, SHA hashes, row order and effects, encoder inputs, progress and failures. Preserve raw slot IDs alongside explained semantic vector comparison.

Tests cover Unicode normalization/casefold, acronym splitting/aliases, nested/overloaded owners, CRLF and Python splitlines, long lines and statement boundaries, invalid UTF-8/NUL, source edits/deletes, stale parser/policy, active identity/behavior profiles, unchanged laziness, MVCC readers, finite vectors, concurrent source/profile change, rollback and bounded slot reuse. Reuse previously sealed M2/M3 parser/import/model results; rerun only directly affected native consumers and new integration. A small real-model document integration uses the prepared native model cache, without repeating M2 model catalogues.

A fresh whole-plan review follows six tasks; Important/Critical findings get one RED→GREEN correction pass. Archive source, tooling, raw gates and rulings in a self-verifying receipt, then remove only this plan's scratch artifacts. M3 can close only after full index integration and its review; M4–M8 remain pending until their own acceptance.
