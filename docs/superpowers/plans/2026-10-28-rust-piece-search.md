# Native PieceSearch implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. One final fresh read-only reviewer; no implementer agents or re-review.

**Goal:** Compose full requested-piece search in Rust on Linux x86_64.
**Architecture:** PieceSearch owns coordination; accepted components own ranking, cards, descriptions and presentation. Input-only probes and host gates compare original complete observations.
**Tech Stack:** Rust1.95, Python3.12.9, pinned x86 cores/Ettin/GrammarCatalog.
**Spec:** docs/superpowers/specs/2026-10-28-rust-piece-search-design.md

## Global constraints
- Preserve frozen1066 fingerprint5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038 and all prior original/model/tolerance data.
- No original pytest reruns, new dependencies, installed-app replacement, main merge or release.
- Keep raw/receipts/workspaces local; authorized push codex/rust-migration.
- Other models, app wiring and M4/global remain pending.

## Review focus
- Exact mode must still invoke numeric ranking and preserve full top ten before display limit; skip neural only.
- Named path stable promotion follows symbol/fusion ordering; original request controls policies.
- Explain signals follow surviving identities after evidence/result trimming, including stale sources.
- Model errors/count/finite checks fail safely before indexing; foreign cache and source guards remain intact.
- Explain max_chars follows observed trim-before-signals lifecycle; do not silently change original behavior.

### Task 1: Independent complete PieceSearch observations
Files:tools/rust_migration/piece_search_reference.py; tests/rust_migration/test_piece_search_reference.py; crates/ken-retrieval/tests/fixtures/piece-search-reference.json.gz.
Interfaces:cases(), capture(Reference,out), validate_reference(value), FIXTURE; input physical/keys/scores/signals/request/expanded_query/exact/model/forest/disk plus observations result/calls/cache.
- [ ] RED missing module/fixture with completeness, refuse-overwrite and tamper tests.
- [ ] Capture distinct original PieceSearch calls once before implementation, actual catalogs and three Ettin frames; journal each row, authenticate frozen sources before/after.
- [ ] Scoped pytest passes and commit immutable fixture.
Expected: at least30 cases, exactly3 real frames, original observer/runtime/input/result authentication passes without originalpytest.

### Task 2: Native PieceSearch composition
Files:crates/ken-retrieval/src/piece_search.rs, presentation.rs/lib.rs; tests/piece_search.rs; examples/support/piece_search.rs; examples/piece_search_probe.rs.
Interfaces:PieceSearch::new(Arc<SourceCatalog>,PieceReranker,Rc<dyn PairedReranker>,Arc<GrammarCatalog>); search(&mut self,&SearchRequest,&[CodeMatch],&PythonText,&str,bool)->Result<SearchResponse>; descriptions()->&OwnerDescriptions read-only.
- [ ] RED missing API with complete controlled corpus and public caller for exact/limit/cache/top10/explain semantics.
- [ ] Compose accepted components, add optional omitted-when-None PieceResult.signals, validate membership and scores, map explain by identity.
- [ ] Input-only probe and actual Ettin tests pass; run native core/retrieval suite, fmt and strict Clippy.
Expected: all cold/warm outputs/calls/cache match, actual scores retain established tolerances, existing presentation callers unchanged.

### Task 3: Source-bound integration and closure
Files:tools/rust_migration/piece_search_host.py, tests/rust_migration/test_piece_search_host.py, workflow, root counts, handoff.
Interfaces:run_host(repo,packet), verify_host(packet,repo); parent complete SymbolRanker chain retained.
- [ ] RED missing capture and resealed tamper protocol tests then implement confinement/resource/output verification.
- [ ] Full local and two-replica x86CI gates pass on final source; one fresh final review/one Important fix pass.
- [ ] Seal native/context-support/design/frozen source and Git proofs, replay outside checkout, document exact evidence and push.
Expected: all host sources/gates/cases authenticate and isolated replay passes; no migration-complete claim.
