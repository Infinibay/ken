# Native Retrieval Kernels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retrieve and fuse actual native source owners from lexical postings and immutable vector generations.

**Architecture:** Extend ken-retrieval with validated request/candidate models and three focused retrieval operations. Reuse accepted M3 storage, vocabulary, snapshots and native indexing; no public transport is credited until later M4.

**Tech Stack:** Rust1.95, existing locked rusqlite/serde and native scalar arithmetic. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-23-rust-retrieval-kernels-design.md`

## Global Constraints

- Preserve every original/user change on codex/rust-migration; execute native inline continuously without confirmations.
- Field order identity/signature/documentation/body/path; k1=1.2; b=.75 for body/documentation; unique query-term cap128; owner evidence cap4; default owner budget100 and rrf_k60.
- F64 BM25 bound abs1e-12+rel1e-12; normalized F32 bound abs1e-6+rel1e-6; exact ordered owner/evidence membership despite score bounds.
- Frozen Unicode15 semantics; existing passage/model/storage contracts remain authoritative.
- Both actual platforms, input-only native probe, complete original provenance/gates, one final fresh review and one Important/Critical TDD fix pass. No unchanged model catalog reruns.

## Review Focus

1. Repeated same-owner proposals with different spans and conflicting signals must vote once and preserve all legitimate evidence.
2. Different SQLite connections, caller rollback and generation reuse must not reuse stale corpus statistics or passages.
3. Shared terms in multiple fields and duplicate posting entries must retain original saturation/document frequency and field diagnostics.
4. Dense owner maxima ties, evidence beyond the early top rows, negative slicing and invalid vector shapes must preserve ordering or explicit failure.
5. Unicode15 whitespace/query tokens, invalid budgets and nonfinite arithmetic must retain validation and diagnostic behavior rather than disappear.

### Task1: Request identities and original numerical corpus

**Files:** Create `ken-retrieval/src/query.rs`, tests/query.rs and fixtures/kernel-reference.json; tools/rust_migration/retrieval_reference.py plus tests/rust_migration/test_retrieval_reference.py; extend EntityKey with Hash/Ord where consumers require it.

**Interfaces:** Consume EntityKey/Passage/Span. Produce SearchRequest{query,target,purpose,limit,max_chars,explain,piece_kind} with new/validate; Candidate{entity,passages,signals,owned_regions}; merge_spans(&[Span])->Vec<Span>; preserve default/serde validation.

- [ ] Capture actual isolated frozen-original request/merge/BM25/postings/dense/fusion observations and the original suites test_lexical.py,test_dense.py,test_proposals.py once, with discovery/JUnit/module ownership. Establish deterministic input-only case IDs and frozen numeric bounds before capture. Add query defaults/invalid Unicode whitespace/budget/kind and inclusive merge tests.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval --test query`; Expected RED absent API.
- [ ] Implement complete validated models and shared spans; no empty service or schema scaffolding.
- [ ] Run the query tests and existing retrieval roots; Expected all PASS; fmt/clippy. Commit `feat(retrieval): define validated source search requests and candidates`.

### Task2: Fielded lexical retrieval over native snapshots

**Files:** Create ken-retrieval/src/lexical.rs and tests/lexical.rs.

**Interfaces:** Produce bm25f_score(frequencies,lengths,averages,document_frequency,documents,k1,weights)->Result<f64>, score_postings(&[Posting],documents,averages)->Result<BTreeMap<i64,Signals>>, lexical_candidates(&Connection,&SearchRequest,isize)->Result<Vec<Candidate>>. Posting owns pid/field/term/tf/length; Signals is ordered name→f64. No read of source files or model call.

- [ ] Add differential scalar/posting tests, shared-field/duplicate saturation and complete diagnostics. Add native SQL tests initial rare literal, edit/delete, independent DBs, rollback and reused generation. Assert owners, four-passage caps, field maxima and snapshot statistics.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval --test lexical`; Expected absent lexical API RED.
- [ ] Implement native f64 arithmetic and SQL matching/statistics within retrieval_snapshot. Prefer uncached per-snapshot aggregate SQL initially; cache only with measured need and full provenance. Preserve original grouping and deterministic ordering.
- [ ] Run all affected retrieval/index roots; Expected PASS; fmt/clippy. Commit `feat(retrieval): search current source postings with fielded BM25`.

### Task3: Immutable grouped dense retrieval

**Files:** Create ken-retrieval/src/dense.rs and tests/dense.rs.

**Interfaces:** Consume ordered Vec<(i64,Passage)> and accepted VectorView; produce DenseView::new(passages,vectors)->Result<Self>, search(&[f32],view:&str,limit:isize)->Result<Vec<Candidate>>. Own all backing vectors and identity/row labels; no external mutable array.

- [ ] Add original fixed-matrix differential cases, stable owner/evidence ties,600rows/17owners with late winning evidence, negative/zero/large limits, empty/dimension/zero/NaN/Inf queries and missing/mismatched ownership errors.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval --test dense`; Expected missing DenseView RED.
- [ ] Implement finite normalization, ordered F32 dot products, per-owner peaks and stable selected-owner/evidence sorting with four passages each. Preserve immutable snapshot ownership and index-version failures.
- [ ] Run all affected retrieval/index roots; Expected PASS with exact ranking and fixed numerical bounds; fmt/clippy. Commit `feat(retrieval): rank immutable dense views by canonical source owner`.

### Task4: Proposal fusion preserving owner evidence

**Files:** Create ken-retrieval/src/proposals.rs and tests/proposals.rs.

**Interfaces:** Produce fuse_proposals(&[(String,Vec<Candidate>)],limit:usize,rrf_k:usize)->Result<Vec<Candidate>>. Consume Task1 Candidate/merge_spans; named run order explicit and unique.

- [ ] Add differential repeated owners, run order/ties/exact priority, duplicated spans with max signals, no input mutation, overlapping complete regions, empty evidence, foreign owners and mixed per-file source hashes.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval --test proposals`; Expected absent fusion API RED.
- [ ] Implement distinct-owner channel voting, max measurements, stable evidence and exact-priority sorting; reject inconsistent evidence before returning results.
- [ ] Run all affected retrieval/index roots; Expected PASS; fmt/clippy. Commit `feat(retrieval): fuse owner proposals without duplicate votes`.

### Task5: Cross-platform kernel parity and final review

**Files:** Create ken-retrieval/examples/retrieval_kernel_probe.rs, tools/rust_migration/retrieval_{validate,evidence}.py, tests/rust_migration/test_retrieval_{probe,validate,evidence}.py; docs/validation/rust-migration-2026-10-23/m4-kernels/ and capability documentation.

**Interfaces:** Input-only bounded strict JSON probe invokes actual complete operations. Output complete results/errors with owned values and platform/process measurements. Verifier authenticates binary/source/input/output bytes, original captures/suites, affected discovery/gates and accepted M3 predecessor. No summaries alone accepted.

- [ ] Add adversarial verifier tests for forged/resealed output, missing/reordered owners/evidence, omitted inputs/tests, changed binary/source/observer and raw-log tampering. Run new tests; Expected RED missing verifier/probe.
- [ ] Implement actual NativeJsonCapture and semantic replay under only predefined bounds; complete finite/error categories and exact owner ordering. Preserve before/after input immutability observations.
- [ ] Execute new native/tooling roots on Linux/macOS plus directly affected M3 regressions, fmt/clippy, full input-only differential corpus and1066original guard. Expected every required root and case PASS. Reuse old model/original suites rather than recapture them. Seal source/tooling/raw gates and standalone VERIFY.py; replay it. Commit `test(retrieval): authenticate lexical dense and fusion parity`.
- [ ] Dispatch one fresh whole-plan reviewer with this plan/spec/ledger and Review Focus verbatim. Regrade findings; one Critical/Important RED→GREEN pass and green affected suites; defer minors with records. Archive exhaustive decisions/review, independently replay final receipt, remove only owned scratch/obsolete package artifacts. Continue M4b automatically without a partial global completion claim.
