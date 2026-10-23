# Authenticated Source Pieces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The user selected native inline execution and continuous progression; no implementation delegation or intermediate approval prompts. Steps use checkbox syntax.

**Goal:** Rank complete requested pieces and return faithful, bounded current source using native code.

**Architecture:** A confined source authority owns physical snapshots; an immutable catalog owns lexical containment. Catalog-owned assembly feeds separate feature/ranking and measured-card components; evidence selectors and presenters consume authenticated source through explicit interfaces. Reuse accepted text/description/coverage/forest/runtime components and capture infrastructure.

**Tech Stack:** Rust1.95 and existing locked dependencies, ken-core source handles, ken-retrieval numeric/word/stem components, Python3.12.9/NumPy2.4.4 frozen oracle for development evidence only.

**Spec:** docs/superpowers/specs/2026-10-23-rust-source-pieces-design.md

## Global Constraints

- Preserve all1066originals, user dirt and accepted receipts; continue codex/rust-migration with periodic verified commits/pushes. Full M4/global remain false.
- Accepted M4c1 FILES9058d60199da6ef080991203bf0b6351361a5c27c2d5e6358bf31c3f3e4d1a6e; reuse861numeric/758selection observations, existing models and35numeric original roots without recapture.
- Source extractor8/parser10; description1; passage256/code-lexical-v1/representation3; Unicode15. Strict physical UTF8 and Python splitlines. SourceFileReader confines all reads/stat to regular handles.
- Piece schema262features; registered1280tree forest fingerprint62846d51f58e5da1cf27ad444073d14341bdc6368f8552a7bb1c30e8d6e7d9b9. Reuse loader/static/stem resources, no new external dependencies or version bumps.
- Queries128terms/fields4096terms/vocabulary4096blocks; original three coverage passes/calls. F64 abs+relative1e-12; approved static F32 feature inputs abs+relative1e-6. All outcomes/paths/evidence/calls/diagnostics exact.
- Group10pieces/20cards; requested-piece-card-v102 ≤64lines/4excerpts/12000Python characters. Owner evidence40total lines; complete regions≤3; judge1owner/6windows/3fragments(default), supported1–4fragments; lexical24windows/1–3fragments.
- Card display16lines/64explain; owner40lines. Count compact JSON Python characters, preserve whole physical lines, stale empty evidence, stable identities/order and original tiny-envelope behavior.
- Both actual macOSarm64/Linuxaarch64; scoped original suites once/new input families; input-only isolated process, full source/binary/runtime/raw provenance, complete affected suites/fmt/strict clippy. One final review/fix pass.

## Review Focus

1. Deeply nested or duplicate-qualified classes with equal extents and catalog-generation changes must not borrow another owner's members or cached descriptions.
2. A file or symlink replaced between catalog creation and display must never cause quoting outside the confined root or quoting bytes different from the recorded hash.
3. Multibyte text, escaped controls, trailing blank lines and very small budgets must retain exact physical ranges, Python-character accounting and honest truncation.
4. Unsorted support, equal/negative priors, missing declarations and symbol bypass must preserve original feature/call order, stable ties and native membership at real forest cutoffs.
5. Many repeated or more-than64distinct cues and disjoint ownership regions must not duplicate votes, truncate bit masks, cross nested gaps or spend more than the total evidence budget.

## File structure

Create src/source_snapshot.rs(source authority/snapshot),source_catalog.rs(containment),piece_candidates.rs(typed units/assembly),piece_features.rs(projection),piece_ranking.rs(forest orchestration),piece_cards.rs(measured projection),source_evidence.rs(lexical cue selection),evidence.rs(judge windows/completion),presentation.rs(public response/budget). Add small private helpers only when a coherent responsibility emerges. Modify ken-retrieval Cargo.toml/Cargo.lock only for existing ken-core path dependency and lib.rs for exports. Tests mirror public responsibility boundaries. tools/rust_migration/piece_reference.py,piece_validate.py,piece_evidence.py and input/reference fixtures authenticate new observations; examples/source_piece_probe.rs plus focused scenario modules provide isolated native use.

Commands use the existing prepared-macos-env wrapper at .ken/rust-migration/m2-optional/review-repair/prepared-macos-env and the accepted prepared-linux-env under /app/.ken/rust-migration/m2-optional/review-repair. Cargo flags: --locked --offline. Linux sets KEN_DENSE_BLAS_DIR to the prepared candidate's .ken/rust-migration/m4/dense-blas. Reuse existing grammar manifest when running ken-index. Never edit Rust while either host is compiling.

### Task 1: Confined physical source and canonical catalog

**Files:** Create source_snapshot.rs,source_catalog.rs; tests/source_catalog.rs and catalog fixtures; piece_reference.py. Modify Cargo.toml/lock for ken-core and lib.rs exports.

**Interfaces:** SourceAuthority::new(&ProjectPaths)->Result<Self>, read(path:&str)->Result<SourceSnapshot>; SourceSnapshot owns hash/lines and verifies a required hash. SourceCatalog::new(Arc<SourceAuthority>,Vec<(EntityKey,Vec<Passage>)>)->Result<Self>; extent(&EntityKey),encloses(outer,inner),scope_members(key),enclosing_callable(key),owned_ranges(key,implementation),source_inventory(),primary(key,kind). Expose immutable accessors for owners/by_path/snapshots/classes and source authority; preserve input order with Vec plus identity lookup. PieceIdentity is typed Entity(EntityKey) or Path(String).

- [ ] Capture catalog observations and tests/retrieval/test_piece_catalog.py once per host. Add nested/ambiguous extents, uncovered nonblank scope, merged/gapped owned ranges, module-name policy, empty/mixed/foreign/stale owners, invalid ranges, UTF8/CRLF/Unicode splitlines and confined symlink cases. Capture unsafe-original outcomes explicitly.
- [ ] Write public original-corpus test and source_catalog_confines_current_bytes_and_preserves_owner_gaps: assert nearest Inner for Inner.run, Outer for Outer.read, complete descendants, exact source_inventory, stale/outside rejection and no child borrowing. Run `cargo test --locked --offline -p ken-retrieval --test source_catalog`; Expected missing-API RED.
- [ ] Implement SourceAuthority using accepted SourceFileReader, strict UTF8/Python splitlines, and immutable ordered SourceCatalog. Validate owner/hash/range admission before containment; reuse source_locator::module_name and merge_spans. No alternative unsafe reader or copied module policy.
- [ ] Run all catalog tests, original-capture tooling and directly affected core/source/retrieval suites on both hosts; Expected PASS, fmt/clippy. Commit/push `feat(retrieval): authenticate physical sources and canonical piece catalogs`.

### Task 2: Generation-bound complete piece assembly

**Files:** Create piece_candidates.rs; tests/piece_candidates.rs; extend new reference family.

**Interfaces:** PieceCandidate::new(kind,path,entity,members:Vec<Arc<OwnerDescription>>,matches:Vec<CodeMatch>)->Result<Self>, declaration()->Option<&OwnerDescription>; immutable member/match access. PieceAssembler::new(Arc<SourceCatalog>), assemble(&mut self,matches:&[CodeMatch],kind:&str,limit:usize)->Result<Vec<PieceCandidate>>. Cache is private and tied to this catalog; callers cannot inject another generation.

- [ ] Capture tests/retrieval/test_piece_candidates.py and piece-admission observations once/host, including constructor/destructor source extraction, nested class membership, limits1/10/invalid0, stable unsorted support and malformed source/version/owner/member identities.
- [ ] Write complete_piece_membership_and_generation_cache: assert Inner pieces contain Inner/run, Outer pieces contain Outer/Inner/read, files/modules all owners, symbols one, all canonical support passages, stable score ties and Arc reuse on repeated assembly. New catalog must not reuse old descriptions. Run piece_candidates test; Expected absent API RED.
- [ ] Implement typed immutable membership validation and catalog-owned description reuse using describe_owner. Validate every retrieved match/evidence against catalog identity/version before encoding; no caller-controlled cache. Group in proposal order and sort support stably by score.
- [ ] Run source_catalog/piece_candidates/description and affected selection roots plus tooling/fmt/clippy both hosts; Expected PASS. Commit/push `feat(retrieval): assemble complete requested pieces with catalog-owned reuse`.

### Task 3: Requested-piece feature schema and production forest ranking

**Files:** Create piece_features.rs,piece_ranking.rs; tests/piece_ranking.rs; extend original input families.

**Interfaces:** piece_features(request,&[PieceCandidate],&dyn WordEncoder,&dyn WordStemmer,Option<&PythonText>)->Result<FeatureMatrix>; piece_feature_names()->Vec<PythonText>. PieceReranker::new(Arc<NumericRanker>,Rc<dyn WordEncoder>,Arc<dyn WordStemmer>)->Result<Self>; rank(request,pieces,expanded)->Result<Vec<PieceMatch>>; PieceMatch owns piece and score.

- [ ] Capture tests/retrieval/test_piece_ranking.py once/host and full262column/call observations for four kinds, request-purpose overrides, missing declarations, unsorted/equal/negative priors, empty/mismatched kinds, duplicate/shared fields, expansion fallback and actual registered forest composition. Reuse M4c1 resources; capture actual branch/leaf digests for production inputs.
- [ ] Write piece_feature_columns_calls_and_stable_order: full schema/matrix equality at declared bound, first-proposal relative prior, original/expanded/declaration pass calls, finite cutoff examples, path/exact/stable priorities and zero optional calls for symbols. Test real1280tree score/order/path identity. Run piece_ranking test; Expected missing API RED.
- [ ] Implement documents with explicit original field order and accepted code_terms/coverage. Keep projection separate from rank coordination; use authoritative schema, accepted forest loader and stable tie handling. Do not duplicate numeric prediction or stemming.
- [ ] Run pieces/features/coverage/alignment/numeric/rank_models and affected complete suites/tooling/fmt/clippy both hosts; Expected PASS. Commit/push `feat(retrieval): rank complete source pieces with the registered forest`.

### Task 4: Fixed source-authenticated card projection

**Files:** Create piece_cards.rs; tests/piece_cards.rs and new projection fixtures.

**Interfaces:** PieceUnit{target_kind,path,entity,module_name}, PieceExcerpt{role,path,start_line,end_line,source_hash,entity,content}, PieceCard{unit,source_hash,excerpts,truncated}; build_piece_cards(matches,kind,query,catalog,limit)->Result<Vec<PieceCard>>, build_card(primary,...),validate_card(card,catalog,check_disk),card_text(card)->PythonText,canonical_card(card)->String.

- [ ] Capture tests/retrieval/test_piece_cards.py once/host plus exact cards/card_text/canonical lengths across nested scopes, preferred/rest ties, declaration/docs/implementation, duplicate physical lines, multibyte/escaped text, long64line/4excerpt/12000character boundaries and stale/symlink/provenance tampering.
- [ ] Write fixed_card_projection_preserves_roles_lines_and_limits: assert original helper projection exactly, no ellipses/fabrication, no overlapping physical lines, first36/second16/decl12 rules, class-child provenance, all three budgets and stale/outside rejection after catalog creation. Run piece_cards test; Expected RED.
- [ ] Implement fixed projection policy using source-only query terms and catalog ownership. Canonical serialization counts Python characters and retains Python escaping/key ordering. Freshness validation uses SourceAuthority. Keep public display formatting out of this measured projection.
- [ ] Run cards/catalog/assembly and complete relevant text/budget tooling suites, fmt/clippy on both hosts; Expected PASS. Commit/push `feat(retrieval): preserve authenticated requested-piece card projections`.

### Task 5: Faithful bounded owner evidence and refinement

**Files:** Create evidence.rs,source_evidence.rs; tests/evidence.rs; new evidence reference family.

**Interfaces:** verified_lines(source,match),entity_extent(match),source_bounds(match,passage,line_count,implementation),complete_owned_context(match,source),complete_evidence(matches,source,request); EvidenceOptions{limit,max_windows,max_fragments}; refine_evidence(matches,source,request,&dyn RelevanceJudge,options); refine_source_evidence(matches,source,request,query,&dyn WordStemmer). Reuse existing RelevanceJudge/candidate_document; clone immutable observations before replacing evidence.

- [ ] Locate/capture the complete tests importing evidence/source_evidence once per host; avoid unrelated neural/model tests. Add distant branches, gapped nested scopes, stale bytes, exact/identity/docs bypass, malformed judge scores, duplicate spans, negative relevance, >64distinct cue masks and total40line/fragment boundaries.
- [ ] Write evidence_refinement_preserves_owner_order_and_source_budget: judge receives exact actual documents/purpose; distant decisive blocks become separate faithful fragments with total≤40; duplicated passages add no vote; child scope text never leaks; >64cues retain coverage; no judge calls for stale/exact/identity. Run evidence test; Expected RED.
- [ ] Implement source-bounded windows/bundles and original utility order. Lexical cue selection uses dynamically sized bitsets and deterministic canonical span ties; no query truncation or score-based fabricated evidence. Validate one finite judge score per bundle, preserve rank/owner scores and immutable inputs.
- [ ] Run evidence plus all affected source/ranking/cards/text tests and original tooling/fmt/clippy both hosts; Expected PASS. Commit/push `feat(retrieval): select faithful bounded evidence within source ownership`.

### Task 6: Current-source public owner and card presentation

**Files:** Create presentation.rs; tests/presentation.rs; extend presentation original family.

**Interfaces:** SearchResponse{query,results,profile_version,warnings,truncated,omitted_count} with serializable typed result/evidence records; present(matches,source,request,profile_version),present_cards(cards,request,catalog,profile_version),displayed_matches(matches,request). Shared compact character accounting/whole-line trim helper only; distinct owner/card selection behavior remains with each presenter.

- [ ] Capture tests/retrieval/test_presentation.py and the present_cards-only root test_file_response_identity_is_the_physical_file_and_source_changes_are_detected from test_piece_search.py once/host. Do not run its neural PieceSearch root; defer that root to M4d. Add exact-declaration fragments, file dedup, explain, selected windows, stale/hash/range/symlink failures, empty/trailing blank lines, Unicode/control escapes, round(score,8) and tiny-envelope budgets.
- [ ] Write presentation_quotes_current_whole_lines_with_exact_identity: compare full original response dictionaries, evidence ranges/content/warnings/omitted flags, order retained after trimming,16/64/40line limits, Python-character length and empty-overhead behavior. Mutate physical source after catalog and require empty stale evidence. Run presentation test; Expected RED.
- [ ] Implement presentation through SourceAuthority; preserve exact original float rounding/response serialization at public boundary and source-faithful fragment trimming. Share accounting rather than conflate owner/card policies. No neural/public runtime stub.
- [ ] Run all affected complete native and scoped tooling suites/fmt/clippy both hosts; Expected PASS. Commit/push `feat(retrieval): present current bounded source with honest stale warnings`.

### Task 7: Isolated native piece acceptance and one final review

**Files:** Create examples/source_piece_probe.rs plus focused scenario modules,piece_validate.py,piece_evidence.py and corresponding tooling tests; receipt docs/validation/rust-migration-2026-10-23/m4-source-pieces.

**Interfaces:** Protocol ken-source-piece-probe/1 with unique input-only cases/resources and explicit bounds; only safe disposable scenario files/mutations under an owned temporary root. Comparator defaults exact; only declared feature paths get fixed bounds. Evidence verifier binds complete original/raw/test/native/resource/source inventories and M4c1 predecessor, reports M4c2 accepted separately from false M4/global.

- [ ] Write strict-protocol and tamper tests before probe/verifier implementation: missing/order/schema/source/runtime/hash/line/call/score/diagnostic drift, one-ULP exact scores, stale quoting and resealed raw evidence must reject. Run new tooling/native-probe tests; Expected absent API/protocol RED.
- [ ] Implement bounded input-only caller; resources are registered forest/static/pinned BLAS, no Python runtime or expected answers. Scenario source paths/mutations stay within disposable owned roots; negative escape tests use only their own sibling fixtures. Run outside checkout with empty PATH/HOME, actual loader and Linux exec/connect auditing, time/RSS with explicit scope.
- [ ] Run complete affected Rust/tooling/fmt/clippy gates on both hosts, no filtered/skipped roots. Reuse preserved original/model receipts; reexecute prior native numeric/selection observations on current source if shared boundaries changed. Verify all1066originals, archive source/tooling/raw snapshots and independently replay receipt.
- [ ] Commit/push `test(retrieval): authenticate source pieces and faithful native presentation`. Dispatch one fresh whole-plan reviewer using requesting-code-review and the five Review Focus classes verbatim. Regrade findings/declined behavior first; one Important/Critical TDD fix pass, green complete suites, Minor/ruling ledgers, no re-review.
- [ ] Seal final accepted M4c2 receipt and archived-source replay, commit/push; clean only this plan's owned scratch and reconstructed build debris, then continue M4d without asking for stage confirmation.
