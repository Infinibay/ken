# Native Incremental Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish complete incremental source, lexical and embedding indices using Rust, preserving the frozen original's indexing contract.

**Architecture:** `ken-retrieval` owns vocabulary, passages and view projections. `ken-index` composes accepted native source paths, parsers, store, import catalog and lazy model encoders, publishing complete per-file transactions.

**Tech Stack:** Rust 1.95, locked rusqlite/serde/SHA-256, blake2 0.10.6, unicode-normalization 0.1.22; prepared macOS/Linux native environments and frozen Python oracle.

**Spec:** `docs/superpowers/specs/2026-10-23-rust-incremental-index-design.md`

## Global Constraints

- Preserve every original and existing user change; stay on `codex/rust-migration`.
- Parser version 10; extractor version 8; name-token version 1; default lexical policy 256/`code-lexical-v1`; chunk size 128.
- CPU, Linux and macOS; no Python runtime in credited native work.
- Compare actual original behavior and raw effects; no oracle vectors or outputs injected into native implementations.
- Reuse prior accepted suites and models; run directly affected native regressions and new boundary tests.
- Existing M2 snapshot-safe allocation is authoritative; retain/audit any different physical slot IDs.
- Execute continuously without confirmation. One fresh whole-plan review, one Important/Critical TDD fix pass.

## Review Focus

1. Unicode code points added after 15.0, unusual full-casefold expansions and acronym/digit boundaries must retain frozen vocabulary semantics (Task 1 differential corpus).
2. Equal-width nested owners, duplicate definitions, lone-surrogate docs and unusual physical newlines must preserve ownership or explicit transactional failure (Tasks 1–2).
3. A model failure after earlier encoding, source/profile races and cached wrong-dimension vectors must not publish mixed generations (Task 4).
4. A reader or rollback that still refers to an old legacy vector must not observe overwritten data; repeated edits must have bounded slot growth (Tasks 3 and 5).
5. Chunk boundary edits, import targets deleted after publication and stale name stamps must preserve progress/order and fresh complete indices (Task 5).

Commands below use `MAC=.ken/rust-migration/m2-optional/review-repair/prepared-macos-env`; corresponding Linux wrapper is `/app/.ken/rust-migration/m2-optional/review-repair/prepared-linux-env` in the prepared candidate. Tests use locked offline dependencies after explicitly preparing the two new pins. Redirect raw output to this plan's workspace. Every verification must exit 0 and its output must be read.

---

### Task 1: Shared vocabulary and physical source passages

**Files:** Create `crates/ken-retrieval/{Cargo.toml,src/{lib,model,vocabulary,passages,roles}.rs,tests/{vocabulary,passages}.rs,tests/fixtures/source-reference.json}`; extend `ken-text` with frozen Unicode properties/casefold; add `tools/rust_migration/index_reference.py`; update workspace manifest/lock and `ken-program` shared-property consumer.

**Interfaces:** Consumes `ParsedFile/ParsedScope`, `PythonText`. Produces `Span::new(usize,usize)->Result<Span>`, `EntityKey`, `Passage{fields:PassageFields,...}`, `PassagePolicy{max_tokens,tokenizer_version}`, `TokenCounter::count(&str)->Result<usize>`, `LexicalCounter`, `extract_passages(&[u8],&ParsedFile,&str,&str,&PassagePolicy,&dyn TokenCounter)->Result<Vec<Passage>>`; `split_camel(&str)->Vec<String>`, `name_tokens(&str,&BTreeSet<String>)->BTreeSet<String>`, `code_tokens(&str)->Vec<String>`, `code_terms(&str,Option<usize>)->Vec<String>`.

- [ ] Capture frozen original calls/results for vocabulary and passages, plus original passage/tokenization suites. Add `vocabulary_matches_original` and `physical_passages_match_original`, asserting every ordered token, owner, field, span, role, split reason and hash; include all five Review Focus 1/2 input classes.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval`; Expected: package/API absent, RED (prepare new pins without upgrading existing locks).
- [ ] Implement source identities, Unicode-15 vocabulary and exact partition. Tokenization has one shared authority. Preserve PythonText; reject invalid spans and invalid budgets; retain original empty passage behavior for NUL/UTF-8 errors.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval -p ken-program`; Expected: both new roots and all existing common-model roots PASS. Run fmt and affected clippy.
- [ ] Commit `feat(retrieval): partition native source and share frozen code vocabulary`.

### Task 2: Transactional passage repository

**Files:** Create `ken-retrieval/src/storage.rs`, `ken-retrieval/tests/storage.rs`; extend captured source fixture with actual original SQL histories.

**Interfaces:** Consumes Task 1 Passage/Policy and `WriteTransaction::connection`. Produces `replace_file_passages(&WriteTransaction,i64,&[Passage],Option<&str>,&PassagePolicy)->Result<Vec<i64>>`, `load_passage_map(&Connection,Option<&[i64]>)->Result<Vec<(i64,Passage)>>`, `source_extractor_current(&Connection)->Result<bool>`; no commit.

- [ ] Add `replace_edit_delete_matches_original`, `missing_symbol_and_non_scalar_docs_roll_back`, `stale_policy_blocks_load`, comparing passage rows, term frequencies, lengths, extraction stamp and reconstructed owners/ordinals against actual original SQL.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval --test storage`; Expected: missing repository API RED.
- [ ] Implement canonical association, ordered fields JSON, term tables and source validation in caller transaction; preserve generation stamps/defaults and scope loading order.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval`; Expected: all PASS, including rollback/no partial replacement; run affected fmt/clippy.
- [ ] Commit `feat(retrieval): persist complete source passage generations`.

### Task 3: Canonical index publication and legacy documents

**Files:** Create `crates/ken-index/{Cargo.toml,src/{lib,prepared,writer,intents,documents,postings,encoder}.rs,tests/publication.rs}`; extend oracle and fixture histories.

**Interfaces:** Consumes Task 1/2, accepted `ProjectDatabase`, `allocate`, `VectorStore`. Produces `PreparedFile` (source metadata, canonical parse, intent, passages, vector destinations); `DocumentEncoder::{dim,token_count,embed_passages}`; `IndexWriter::publish(&mut ProjectDatabase,&PreparedFile,&WriterOptions)->Result<i64>`; `delete_file(&Connection,&str)->Result<bool>`, `delete_path(&Connection,&str)->Result<usize>`, `rebuild_name_tokens(&Connection,&BTreeSet<String>)->Result<()>`. WriterOptions supplies stores, policy, clock and prepared projections explicitly.

- [ ] Add `canonical_publication_matches_original`, `plain_intent_limits_and_document_inputs`, `delete_path_is_exact_subtree`, `legacy_vectors_survive_rollback_and_reuse_bounded_slots`; assert all canonical rows, IDs/order, postings, intent weights/text, document calls, storage/inline vectors and cascades.
- [ ] Run `$MAC cargo test --locked --offline -p ken-index --test publication`; Expected: absent publication API RED.
- [ ] Implement canonical merge by kind/qualname/start, stable start/-end order, original intent rules and embedding strings, atomic file/symbol/import/intent/posting/passage write. Use document encoding only, finite normalized vectors and safe M2 allocation; preserve explicit all-space inline fallback.
- [ ] Run `$MAC cargo test --locked --offline -p ken-index -p ken-retrieval`; Expected: all PASS. Check old committed vector values after failure and bounded steady edit growth; run fmt/clippy.
- [ ] Commit `feat(index): publish canonical files and document vectors atomically`.

### Task 4: Immutable active-profile projections

**Files:** Create `ken-retrieval/src/{projections,representations,embedding_store}.rs`, `ken-retrieval/tests/projections.rs`; add actual original profile/vector histories and model adapter in `ken-index/src/encoder.rs`.

**Interfaces:** Consumes Task 3 DocumentEncoder boundary (move trait to retrieval if required to avoid crate cycle; ken-index reexports it), accepted `RetrievalProfile/EncoderSpec/ManagedEncoder`, Task 1 policy. Produces `ProjectionIndexer::{for_active,policy,prepare}`, `PreparedProjection::publish(&WriteTransaction,&[i64])->Result<()>`, `put_embeddings`, `load_vectors`, `reclaim_retired`; expected profile tuple pins preparation to publication.

- [ ] Add `two_views_match_original`, `unchanged_texts_are_not_encoded_again`, `nonfinite_second_view_rolls_back`, `source_and_profile_races_reject`, `old_reader_observes_complete_generation`; assert actual encoder inputs, text hashes, model revision/dimension and finite vector values.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval --test projections`; Expected: absent projection API RED.
- [ ] Implement exact bounded view text and actual tokenizer policy, cached text deduplication, immutable normalized f32 artifacts and retired-only reclamation; preserve lazy model loading and MVCC.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval -p ken-index`; Expected: PASS. Run one small real accepted document-model integration on fresh texts; reuse M2 model proofs; fmt/clippy.
- [ ] Commit `feat(retrieval): prepare and publish immutable profile views`.

### Task 5: Incremental native index orchestration

**Files:** Create `ken-index/src/{indexer,changes,parse_batch,imports}.rs`, `ken-index/tests/incremental.rs`, input-only `ken-index/examples/index_probe.rs`; extend native operation fixtures/oracle.

**Interfaces:** Consumes Tasks 1–4 plus `ParserRegistry`, `ImportCatalog`, `ProjectPaths`. Produces `Indexer::index_files(&mut ProjectDatabase,&ProjectPaths,&[PathBuf],&IndexOptions,&mut dyn Progress)->Result<IndexStats>`, `IndexOptions` explicit parser/encoder/profile/policy/clock/size/chunk/workers, `IndexStats` original fields, `Progress::file(&str,&str)`; `is_unchanged` checks hash/parser/vector/policy stamps without model acquisition.

- [ ] Add `initial_edit_delete_and_unchanged_match_original`, `plain_rows_publish_first_progress_stays_ordered`, `worker_counts_and_parse_failures`, `stale_parser_policy_and_name_tokens`, `chunk_boundary_and_import_target_deletion`, `all_languages_use_accepted_native_parsers`; assert stats except declared elapsed clock, rows, imports, progress, document batches and unchanged no encoder load.
- [ ] Run `$MAC cargo test --locked --offline -p ken-index --test incremental`; Expected: absent Indexer API RED.
- [ ] Implement BLAKE2b-256 checks, confined source reads, native ordered scoped parsing/fallback, chunk prepare before writes, per-file durable publication, vector flush and final native import resolution/postings rebuild. Preserve statuses and failure behavior; no CLI stub credited as indexing.
- [ ] Run `$MAC cargo test --locked --offline -p ken-index -p ken-retrieval`; Expected: PASS including active-profile integration and races, plus new representative workload timing/RSS; fmt/clippy.
- [ ] Commit `feat(index): orchestrate complete native incremental indexing`.

### Task 6: Authenticate cross-platform parity and review

**Files:** Create `tools/rust_migration/{index_validate,index_evidence}.py`, `tests/rust_migration/test_index_{reference,validate,evidence}.py`, receipt `docs/validation/rust-migration-2026-10-23/m3-index/` and update capability matrix.

**Interfaces:** Consumes actual isolated original captures, input-only native index probe and all raw gates; produces replayable source/tooling/binary/request provenance and self-verifying receipt with accepted predecessor digests, preserved original guard and M3/M8 status.

- [ ] Write adversarial evidence tests: forged output, missing cases, rewritten inputs, skipped tests, binary/source/tool mismatch, owner/projection side-effect changes and altered raw receipts must reject. Run tooling tests first; Expected RED until verifier exists.
- [ ] Implement capture/verifier with authenticated native process I/O, all-platform coverage, raw SQL/vector records, only declared dynamic normalization and explicit physical slot audit. Reuse original tests already captured; no unchanged whole-M2/M3 reruns.
- [ ] Run both platforms' new Rust/tooling tests, fmt/clippy, input-only full parity matrix and baseline original hash guard. Expected: all new roots/cases PASS, no silent omissions. Receipt must fail on every tamper test.
- [ ] Commit `test(index): authenticate native incremental parity on Linux and macOS`.
- [ ] Dispatch one fresh whole-plan reviewer with this spec, plan, ledger rulings and Review Focus verbatim. Grade by user effect; fix Important/Critical once with RED→GREEN and affected suites, ledger deferred minors. Archive the review and final source/tools/raw gates and independently replay receipt verification.
- [ ] Commit verified corrections, archive exhaustive ledger/rulings, remove only this plan's scratch/obsolete transfers and package build artifacts. Continue M4 automatically; no partial global completion claim.
