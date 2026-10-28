# Native BestSearch Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. No implementer agents; one final fresh read-only reviewer and at most one Important repair pass.

**Goal:** Implement generation-bound contextual preparation and the native BestSearch library coordinator.
**Architecture:** ken-retrieval owns contextual cache/snapshots; new ken-search composes ken-index and retrieval without a cycle. Resource provider owns shared models; BestSearch owns sequencing and two-project LRU.
**Tech Stack:** Rust1.95/Python3.12.9, SQLite, existing workspace libc/npyz, registered CPU models and x86 numerical profiles.
**Spec:** docs/superpowers/specs/2026-10-28-rust-best-search-design.md

## Global Constraints
- Linux x86_64 only; no installed-app replacement, merge/release/tags or private reserve usage.
- Frozen1066fingerprint5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038 and all old originals/models/tolerances immutable.
- Capture only distinct new API histories; never original pytest roots. Journal rows immediately and keep raw failures.
- No new external package versions; reuse pinned libc/npyz. Keep source and generated artifacts separate.
- Inline/current authorized branch, raw/workspaces/receipts retained locally; push authorized.
- Application-wide concurrency, remaining models and M4/global remain pending.

## Review Focus
- Cold empty/exact paths never construct resources or vectors, including declaration fallback and explicit file/class intent.
- Profile repair cannot skip missing embeddings on unchanged files or publish across an unpinned generation; failed resource/prepared states remain retryable.
- Project identity includes database/root/generation/profile; LRU eviction never mixes catalogs, shared descriptions, source vectors or active old readers.
- NPY sizes/dtypes/offsets/alignment/overflow and mapping lifetimes are checked before unsafe admission; corruption/collision/partial publication fails clearly.
- Original query/expanded query and trim-before-signals behavior stay with accepted owners; warm prepare side effects match original call order.

### Task 1: Original contextual preparation histories
Files:tools/rust_migration/context_preparation_reference.py; tests/rust_migration/test_context_preparation_reference.py; crates/ken-retrieval/tests/fixtures/context-preparation-reference.json.gz.
Interfaces:cases(),capture(Reference,out),validate_reference(value),FIXTURE; physical owners plus model policy/actions only; cold/warm results, artifacts, logical cache rows and calls as outputs.
- [ ] RED missing reference/completeness/refuse-overwrite/resealed-tamper tests.
- [ ] Observe original ContextVectorCache/prepare_context with controlled768basis vectors, Unicode order, duplicates, generation reuse, cache reuse, invalid vectors/collisions/transactions and artifact corruption. Authenticate original source/runtime and journal each case.
- [ ] Scoped pytest passes; commit immutable fixture.
Expected: independently frozen histories and exact controlled artifacts, no prior original/model repeat.

### Task 2: Native contextual cache and immutable snapshots
Files:crates/ken-retrieval/src/{context_preparation,context_vector_cache,npy_matrix}.rs; normalized_matrix.rs/contextual.rs/source_views.rs/lib.rs/Cargo.toml; tests/context_preparation.rs and support.
Interfaces:ContextSourceEncoder:QueryEncoder with spec(),view_spec(),embed_passages(); ContextVectorCache::open(directory,model_key),get(text),put_many(items),count(); prepare_context(catalog,generation,Rc<dyn ContextSourceEncoder>,directory)->Result<ContextualRetriever>. Existing vector constructors retained; private mapped-NPY constructors added.
- [ ] RED public cache/preparation callers against Task1 fixture; transactional rollback, Unicode ASCII order, reuse without encoder, corrupt artifacts, mapped old-generation lifetime and shape/normalization guards.
- [ ] Implement cache/text policy/canonical identity/NPY mapping+publication and accepted-retriever construction. No duplicated projection or norm policy.
- [ ] Run affected Rust suites, full core/retrieval/syntax tests, fmt and strict Clippy; commit.
Expected: original observations match, mapping is read-only and old snapshots remain valid after atomic replacement; no unimplemented scaffolding.

### Task 3: Original complete BestSearch histories
Files:tools/rust_migration/best_search_reference.py; tests/rust_migration/test_best_search_reference.py; crates/ken-retrieval/tests/fixtures/best-search-reference.json.gz.
Interfaces:cases(),capture(Reference,out),validate_reference(value),FIXTURE; physical source/database/action/model inputs and logical response/calls/database/cache observations.
- [ ] RED missing complete histories/authentication tests.
- [ ] Observe original search_best/prepare_best with real indexing/ranking/preparation and explicit controlled model leaves; empty/cold source/exact callable/class/qualified/file/non-symbol declarations, fallback kinds, ambiguous names, projection repair, contextual queries/expansion, repeat/warm/generation/source change, two-DB identities, LRU2 and failures. Include bounded new real-model compositions when available from registered source overrides without changing rules.
- [ ] Authenticate/journal new observations, scoped tests pass; commit original fixture before coordinator code.
Expected: complete original endpoint histories, all calls traceable to real consumers, no expected answers in inputs.

### Task 4: Resources and native BestSearch
Files:new crates/ken-search/{Cargo.toml,src/lib.rs,src/resources.rs,src/context_encoder.rs,src/best_search.rs,tests/best_search.rs,examples/best_search_probe.rs,examples/support/*}; workspace Cargo files; minimal shared APIs in retrieval query/presentation/source_catalog and syntax registry.
Interfaces:SearchResourceProvider::build()->Result<SearchResources>; SearchResources::new(shared words/query/document/context/rankers/neural,base/full profiles,legacy) validates policies; RegisteredSearchResources wraps explicit ModelFactory/ProductionRankModels; BestSearch::new(Arc<GrammarCatalog>,Rc<dyn SearchResourceProvider>),search(&mut self,&mut ProjectDatabase,&ProjectPaths,&SearchRequest),prepare(...)->PreparationReport. ParserRegistry shared-catalog constructor; immutable request.with_piece_kind and public response construction/symbol eligibility keep old APIs compatible.
- [ ] RED endpoint histories and public cold/no-provider caller; cache/provenance/failure/retry/LRU/DB/generation tests. Watch failures before implementation.
- [ ] Compose accepted Indexer/index_embeddings/retrieval_snapshot/exact/retrieve_contextual/EvidenceReranker/PieceSearch. Keep source writes outside pinned read snapshots and resource acquisition lazy.
- [ ] Production resource assembly identities/lazy defaults and input-only probe pass; full affected native tests, fmt and strict Clippy; commit.
Expected: Task3 responses/calls/logical state match; no circular dependencies, stale global models or test-only ranking path.

### Task 5: Source-bound complete host integration
Files:tools/rust_migration/best_search_host.py; tests/rust_migration/test_best_search_host.py; examples context preparation probe/support; workflow/native discovery root counts.
Interfaces:run_host(repo,packet),verify_host(packet,repo); complete PieceSearch host chain is parent; include native syntax/index/search roots and both new reference/protocol scopes.
- [ ] RED missing captures, answer injection, source/generation/order/cache/mapped-artifact/resource/BLAS tampering; then implement confined native captures and strict verification.
- [ ] Preflight complete new captures before the expensive full source-bound chain. Run complete local and two-replica x86CI on final source, preserve every failed epoch without counting it as acceptance.
Expected: complete named profile states and actual command discovery match; no summary-only or partial acceptance.

### Task 6: Review and portable closure
Files:handoff/migration docs, local sealed receipt/archive with archived validators/Git proofs/new designs/frozen1066sources.
- [ ] One fresh read-only whole-slice reviewer with Review Focus, spec/plan and ledger rulings. Regrade; one Important fix pass with reproducer RED→GREEN/full suites, no re-review; deferred minors and rulings recorded.
- [ ] Verify all3hosts against exact final code/tooling snapshots; seal original journals, resources, Git proofs and recorded CPU profiles; replay extracted transport outside checkout with Python-I-B.
- [ ] Update actual scope/evidence/remaining steps; commit and push authorized branch; clean Git tree, zero tracked docs/validation(s), preserve raw/workspace.
Expected: bounded BestSearch/preparation acceptance, M4/global and installed app unchanged. No global migration-complete claim.
