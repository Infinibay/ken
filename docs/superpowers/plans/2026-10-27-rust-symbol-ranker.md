# Native SymbolRanker implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. One final fresh read-only reviewer; no implementer agents or re-review.

**Goal:** Compose complete native symbol ranking with catalog-bound shared descriptions.
**Architecture:** OwnerDescriptions owns synthesis/cache; SymbolRanker coordinates accepted views/operations/preferences; probes and host gates authenticate observed behavior.
**Tech Stack:** Rust1.95/Python3.12.9, existing GrammarCatalog/Ettin and pinned x86 runtime.
**Spec:** docs/superpowers/specs/2026-10-27-rust-symbol-ranker-design.md

## Global constraints
- Linux x86_64 only; preserve all original/model/tolerance data and frozen1066fingerprint5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038.
- Capture only distinct new composition cases; never original pytest roots.
- No new dependencies, native Python runtime, main merge, release or installed-app replacement.
- Keep raw/receipts/workspaces locally; authorized push codex/rust-migration.
- Full PieceSearch, remaining models and M4/global remain pending.

## Review focus
- Original request versus expanded query: requirements use original, model uses expanded.
- Cache provenance, failure order and sharing with PieceAssembler must not admit foreign descriptions.
- No-operation requests return empty witnesses even when source contains operations; empty rank remains lazy.
- Stable priorities compose operation→test→operator after mean ordering without losing duplicate input entries.
- Fallback, model errors and warm cached descriptions preserve the original model call sequence.

### Task 1: Independent full-composition observations
Files:tools/rust_migration/symbol_ranking_reference.py; tests/rust_migration/test_symbol_ranking_reference.py; new compressed fixture.
Interfaces:cases(),capture(Reference,out),validate_reference(value), FIXTURE; physical input plus independent result/calls/cold/warm/cache observations.
- [ ] Write failing corpus/authentication/refuse-overwrite tests; run scoped pytest (expected missing module/fixture).
- [ ] Capture new original composition cases before native implementation, using actual physical catalogs and original API, plus new actual Ettin frames. No originalpytest invocation.
- [ ] Verify frozen1066before/after, exact observer/runtime/input/result bindings and tamper tests; commit immutable fixture.
Expected: original observation/protocol tests pass, previous bytes unchanged.

### Task 2: Shared descriptions and native SymbolRanker
Files:crates/ken-retrieval/src/{owner_descriptions,symbol_ranking}.rs, piece_candidates.rs/lib.rs; tests/symbol_ranking.rs; native probe/support.
Interfaces:OwnerDescriptions::new(Arc<SourceCatalog>),get(&mut self,&EntityKey)->Result<Arc<OwnerDescription>>,len(),is_empty(),belongs_to(&SourceCatalog); PieceAssembler::descriptions_mut(); SymbolRanker::new(catalog,Arc<dyn PairedReranker>,Arc<GrammarCatalog>),rank(request,keys,expanded,originals,&mut OwnerDescriptions)->Result<SymbolRanking>.
- [ ] RED missing API/corpus and public shared-cache/foreign-cache/canonical-owner/empty/error callers; reuse existing components and extract cache without changing PieceCandidate behavior.
- [ ] Implement composition, compare all new observations and calls cold/warm; prove shared Arc identity/cache counts and explicit query separation.
- [ ] Build input-only confined probe; run affected native suites, fmt and strict Clippy.
Expected: scoped differential/caller tests and existing piece candidates pass; no duplicated ranking rules.

### Task 3: Source-bound integration and closure
Files:tools/rust_migration/symbol_ranking_host.py, protocol tests, model workflow, native root counts, handoff.
- [ ] RED protocol/host requirements→GREEN; source-bound full local and two-replica x86CI chain including real Ettin composition.
- [ ] One fresh final review/one Important repair pass; seal complete native+context-support+design/frozen sources and Git proofs, replay outside checkout, document actual scope and push.
Expected: actual full host evidence and isolated replay pass; no global migration completion claim.
