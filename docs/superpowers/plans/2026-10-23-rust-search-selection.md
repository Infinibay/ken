# Native Search Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Select complete native source owners through literal/static/contextual evidence and generic relevance ranking.

**Architecture:** Extend ken-retrieval with intent, owner descriptions, candidate selection and immutable contextual snapshots. Reuse accepted profiles, query models, storage, lexical/dense/fusion kernels and native process evidence. Public services and fitted rankers retain their later M4 boundaries.

**Tech Stack:** Rust1.95, locked rusqlite/serde/onig, accepted Unicode15 and platform BLAS. Reuse pinned dependencies; no new external versions.

**Spec:** `docs/superpowers/specs/2026-10-23-rust-search-selection-design.md`

## Global Constraints

- Preserve every original/user change on codex/rust-migration. Native inline continuous execution, no confirmations or unchanged model/original suite reruns.
- Original Unicode15 semantics and codepoint-based text; exact owners/evidence/error categories. F32 abs1e-6+rel1e-6 and F64 abs1e-12+rel1e-12 never excuse ordering/membership differences.
- source extractor8/parser10, code-lexical-v1/max_tokens256/default representation3; candidate_limit100/rrf_k60; contextual projection1, channel_limit300/broad_limit1200; joint rerank_limit40/four bodies/documentation600codepoints.
- Query-side encoding separate from document encoding. SQLite data and vectors share a pinned generation; no cross-generation cache. Reuse exact platform BLAS and preserve its Linux packaging obligation.
- Complete actual Mac/Linux evidence, one final fresh reviewer and one Important/Critical TDD fix pass. M4b boundary only; completeM4/global remain false.

## Review Focus

1. Shared query encoder owners versus different owners with equal specifications must preserve call counts without accidentally sharing mutable query state.
2. A rollback followed by generation reuse or a second connection must never deliver another source generation's owner descriptions, exact names or vectors.
3. Namespace references inside prose, multiple declarations and Unicode case/word boundaries must not grant a foreign owner an exact shortcut.
4. Same-span evidence from different channels must preserve the original later-measurement rule, complete owned regions and canonical source identity.
5. Storage normalization, contextual owner/view gathering and joint passage ties must preserve the final ordered owner cutoff as well as bounded scores.

### Task 1: Query intent, locators and frozen original corpus

**Files:** Create tools/rust_migration/selection_reference.py and tests/rust_migration/test_selection_reference.py; fixtures/search-selection-reference.json and text-semantics.json; ken-retrieval/src/query_patterns.rs,intent.rs,source_locator.rs and tests/intent.rs,source_locator.rs; extend ken-text Unicode identifier properties only where needed. Associate the existing pinned onig dependency with ken-retrieval.

**Interfaces:** Consume accepted PythonText and Unicode15 word/casefold. Produce a private frozen QueryPattern matcher with captures in original codepoint coordinates, frozen is_identifier(&str)->bool and literal re.I equivalence data. Produce QueryIntent{purpose,identity,identifiers,kind}; interpret(&SearchRequest)->QueryIntent; requested_piece_kind(&SearchRequest)->String; requested_piece_path(&SearchRequest)->Option<PythonText>; SymbolLocator{namespace,qualname} with matches(&EntityKey)->bool; symbol_locator(&PythonText)->Option<SymbolLocator>; module_name(&str)->Option<String>. Exported corpus definitions contain only id/kind/input; original results captured independently.

- [ ] Capture actual frozen-original interpret/requested_piece_kind/requested_piece_path/symbol_locator/module_name/describe_owner/candidate_document/rank/context and native-SQL-equivalent candidate histories, plus their scoped original suites once. Record exact discovery/call/JUnit instead of guessing a test count. Capture Unicode15 identifier ranges and query-literal case equivalences from actual Python3.12.9; input-only tables/hash/provenance. Exclude fitted training/model inference suites owned by M4c.
- [ ] Add complete actual intent/locator/piece comparisons, explicit overrides/modifiers/prose/conjunctions and original-coordinate cases for lookarounds, newlines/end anchors, literal ASCII/Spanish re.I equivalences, Unicode15 non-word/lone-surrogate barriers and identifier start/continuation. Run `$MAC cargo test --locked --offline -p ken-retrieval --test intent --test source_locator`; Expected RED absent APIs.
- [ ] Implement only the pattern operations used by original intent/locator logic, using pinned onig Python syntax, explicit frozen word/space classes and one-character literal case equivalences. Keep original codepoint/capture coordinates; no blanket full-casefold before regex. Implement original query-intent/piece/locator rules through these private matching helpers, with public behavior tests rather than exposing the helper as an API.
- [ ] Run the new tests, reference-tooling tests and affected ken-text/retrieval roots; Expected PASS, fmt/clippy clean. Commit `feat(retrieval): interpret query intent with frozen source identity semantics`.

### Task 2: Exact namespace/name selection from current SQL

**Files:** Create src/candidates.rs and tests/exact_candidates.rs (under ken-retrieval).

**Interfaces:** Consume Task1 intent/locator functions and accepted snapshot/passage loading. Produce exact_candidates(&Connection,&SearchRequest)->Result<Vec<Candidate>>.

- [ ] Add actual SQL case-sensitive preference/NOCASE fallback/kind filtering; namespace mismatch yields empty; complete owned-region assignment. Assert exact lookup works with no embedding artifacts or model call. Add rollback/reused-generation/two-connection cases.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval --test exact_candidates`; Expected missing API RED.
- [ ] Materialize current owners within each snapshot, no connection/generation cache. Preserve SQL row and first-owner order and original exact-name authority.
- [ ] Run intent/exact and all directly affected text/retrieval roots; Expected PASS; fmt/clippy. Commit `feat(retrieval): resolve explicit source identities without models`.

### Task 3: Complete owner descriptions and snapshot candidate union

**Files:** Create src/description.rs,query_encoder.rs; extend candidates.rs; tests/description.rs,candidate_selection.rs.

**Interfaces:** Produce OwnerDescription{entity,source_hash,fields:BTreeMap<String,PythonText>,owned_lines,implementation_lines,executable_lines,comment_lines,regions,passages}; describe_owner(&[Passage])->Result<OwnerDescription>; owner_passages(&Connection)->Result<Vec<(EntityKey,Vec<Passage>)>>; owner_descriptions(&Connection,&[Candidate])->Result<Vec<(EntityKey,OwnerDescription)>>. QueryEncoder::embed_query(&PythonText)->Result<Vec<f32>>, QueryEncoders{identity:Rc<dyn QueryEncoder>,behavior:Rc<dyn QueryEncoder>}, managed adapter. retrieve(&Connection,&SearchRequest,&RetrievalProfile,&LegacyRuntimeIdentity,&QueryEncoders)->Result<Vec<Candidate>>.

- [ ] Add actual owner-description and SQL selection histories, last duplicate span, codepoint slices/trailing lines/lone surrogates, mixed ownership/version errors. Assert unique exact rrf1/no encoder or vector policy check; normal exact/lexical/identity/behavior union, complete vector coverage/version/policy errors, max owner signals/later duplicate passage signals, stable budget/complete regions; shared encoder once/different owners twice. Add edits/deletes/rollback/two DBs. Include original-versus-native storage-normalize→dense cutoff case before any normalization change.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval --test description --test candidate_selection`; Expected missing API RED.
- [ ] Implement source-owned text projections, explicit query encoding and snapshot-local candidate union using Tasks1/2 and accepted lexical/dense/storage APIs. Normalize storage with the accepted platform arithmetic only if the new end-to-end regression demonstrates a mismatch; preserve existing finite/dimension/transaction validation.
- [ ] Run the new tests and all affected retrieval/index/text roots (including M3 transactional regressions); Expected PASS; fmt/clippy. Commit `feat(retrieval): select complete owners from a pinned source generation`.

### Task 4: Contextual owner and source-view snapshots

**Files:** Create src/contextual.rs,source_views.rs; extend candidates.rs with retrieve_contextual; tests/contextual.rs,source_views.rs.

**Interfaces:** Produce OwnerVectorSnapshot::new(model,generation,owners,hashes,matrix,projection_version)->Result<Self>; ContextualRetriever::new(Rc<dyn QueryEncoder>,EncoderSpec,OwnerVectorSnapshot,Option<SourceViewSnapshot>)->Result<Self>; score(query,expanded,owners,generation,&ContextualRetrieval)->Result<ContextualScores>; ContextualScores::propose(owners,limit)->Result<Vec<Candidate>>, enrich(&mut[Candidate])->Result<()>. SourceViewSnapshot::new(model,generation,owners,hashes,matrix,rows,query_model)->Result<Self>, enrich(candidates,original,expanded)->Result<()>. owner_view_texts(&OwnerDescription)->BTreeMap<String,PythonText>. retrieve_contextual consumes explicit profile/legacy/query encoders, contextual runtime and query expansion callback, returns(candidates,expanded text).

- [ ] Add actual contextual/source-view observations for full-owner proposals, stable score ties, owners outside code top-k, identical expansion one call, same query-vector reuse, negative generation/duplicate owners/mixed hashes/bad norms/dimensions/row maps, stale model/policy/query-model mismatch and empty selections. Assert contract/full-doc/empty-source and docless implementation projections exactly; gather only combined owners in their order. Query expansion invalid/nonempty behavior and original exact authority retained.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval --test contextual --test source_views`; Expected missing API RED.
- [ ] Implement immutable owned matrices/row maps and complete identity validation; reuse accepted BLAS dispatch for scoring. Preserve original row-norm admission rather than broadening it. Compose original/expanded static, code and original exact runs via accepted proposal fusion and enrich every owner.
- [ ] Run directly affected complete suites; Expected PASS; fmt/clippy. Commit `feat(retrieval): rank contextual evidence across complete source ownership`.

### Task 5: Entity and passage relevance ranking

**Files:** Create src/ranking.rs; extend query.rs with CodeMatch; tests/ranking.rs.

**Interfaces:** Produce CodeMatch{entity,score,evidence,source_hash,signals,owned_regions}; RelevanceJudge::score(query:&PythonText,documents:&[PythonText],purpose:&str)->Result<Vec<f64>>; candidate_document(&Candidate,purpose:&str)->Result<PythonText>; rank_candidates(&SearchRequest,&[Candidate],Option<&dyn RelevanceJudge>,rerank_limit:isize,rank_unit:&str)->Result<Vec<CodeMatch>>.

- [ ] Add actual original documents/ranking cases for executable/body dedup/documentation600codepoints, identity purpose, unique exact/no-judge no call, entity/passage budgets (including original negative slicing), duplicate spans, nonfinite/wrong-score-count/unknown-unit errors and stable exact/model/path/first-evidence ties. Record judge inputs/call counts and preserve input candidates.
- [ ] Run `$MAC cargo test --locked --offline -p ken-retrieval --test ranking`; Expected absent API RED.
- [ ] Implement original document order and finite score/shape checks. Reuse accepted native joint model through an adapter; fitted forests and feature models remain M4c.
- [ ] Run affected complete suites; Expected PASS; fmt/clippy. Commit `feat(retrieval): rank canonical entities and owned evidence units`.

### Task 6: Both-platform authenticated selection acceptance

**Files:** Create examples/search_selection_probe.rs; tools/rust_migration/selection_{validate,evidence}.py and tests/rust_migration/test_selection_{probe,validate,evidence}.py; docs/validation/rust-migration-2026-10-23/m4-selection/.

**Interfaces:** Strict bounded input-only native probe executes real intent/descriptions/SQL union/context/ranking, complete outputs/errors and observed query/judge calls. Reuse NativeJsonCapture, runtime preparation, source identity, gate/JUnit and standalone receipt helpers; new semantic comparison allows only fixed bounds. Pin M4a predecessor digest above.

- [ ] Add verifier tests for actual positive and changed/omitted inputs, resealed owner/evidence/call-order output, stale runtime/source/binary, skipped tests and original raw-capture changes. Run; Expected missing probe/verifier RED.
- [ ] Implement authenticated complete comparison and native process execution outside checkout with isolated resources, input-only SQL histories and real time/RSS. Execute both actual platforms and directly affected native/tooling gates once, preserve original captures/model evidence and1066original guard. Expected complete PASS; seal/replay independent source/tooling/raw matrix. Commit `test(retrieval): authenticate complete native selection and ranking`.
- [ ] Dispatch one fresh final plan reviewer with verbatim Review Focus and ledger rulings. Regrade, one Important/Critical RED→GREEN fix pass with affected green suites; archive exhaustive review/rulings/minors. Replay final receipt, clean only owned scratch/obsolete build outputs, continue M4c without confirmation or global completion claim.
