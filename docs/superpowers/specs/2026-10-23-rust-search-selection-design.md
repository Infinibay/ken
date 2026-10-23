# Native search selection and contextual ranking (M4b)

Parent: `2026-10-18-rust-migration-design.md`; predecessor M4a2439c7c4, final `m4-kernels-review/FILES.json` SHA b7143128a6959650bb4bc28d0b94c21e3a12d061627ecdfc40d81745762f644e. The user authorized continuous native implementation, original preservation, verification before advancing and no repeated approval prompts. This records implementation decisions within that authorization.

## Purpose and capability boundary

A request must select the same canonical source owners from literal, lexical and vector evidence, retain all owned regions, and send the intended source unit to relevance ranking. M4b implements query intent/namespace lookup, complete owner descriptions, snapshot candidate selection, contextual owner/source-view scores and generic joint ranking. M4c retains fitted forests, feature extraction/stemming, piece selection, source freshness and bounded presentation; M4d retains historical channels and actual public CLI/MCP/quality/resource acceptance. No capability is removed and complete M4/global acceptance remains false.

## Concepts and representative use

`QueryIntent` owns requested purpose and exact-name authority; mentioning a name in behavioral prose must not grant an unrelated symbol an exact shortcut. `SymbolLocator` binds a complete namespace::qualified symbol. `OwnerDescription` derives complete lexical source views exclusively from one owner/version. `CandidateSelection` reads exact, lexical and dense channels in one SQL generation, groups by owner before budgets and preserves named evidence. `QueryEncoder` owns query-side model use; document encoders keep their existing boundary. `OwnerVectorSnapshot` and `SourceViewSnapshot` own immutable generation/model/source identities. `ContextualScores` proposes from the complete owner corpus and enriches every combined candidate. `RelevanceJudge` scores entity or passage documents without changing exact priority.

```rust
let intent = interpret(&request);
let exact = exact_candidates(connection, &request)?; // works without models
let candidates = retrieve(connection, &request, &profile, &legacy, &encoders)?;
let owners = owner_descriptions(connection, &candidates)?;
let matches = rank_candidates(&request, &candidates, Some(&judge), 40, "entity")?;
```

Query encoders are `Rc<dyn QueryEncoder>` owners. Reusing the same encoder owner for both views embeds once per call; different owners embed independently. Production adapters reuse accepted `ManagedEncoder::embed_query`. New selection APIs take explicit profile/runtime identities; later public adapters resolve defaults/active profiles. A unique exact owner bypasses vector version/policy checks and model calls, yielding rrf1.0. Multiple exact owners remain in normal fusion. No global SQL connection/generation cache is introduced: fresh snapshot-local materialization handles rollback and connection reuse safely.

## Binding behavior

Preserve original defaults and all explicit public purpose/piece overrides. Raw identifier grammar is ASCII `[A-Za-z_][A-Za-z0-9_.]*`; explicit declarations and requested test objects follow the original English/Spanish rules, including modifiers, quotation, relative clauses, conjunctions and purpose overrides. Capture original intent/locator/piece outputs before implementation. Native regex uses the existing pinned Oniguruma engine for lookarounds, frozen Unicode15 word/identifier properties and Python-compatible case equivalences for the literal alphabet actually used by these patterns. Preserve original text/capture coordinates, isolated surrogates as non-word barriers and Python whitespace. Do not use full string casefold where Python re.I applies to one character.

Namespace lookup accepts only a whole-query locator (after its permitted command prefix/punctuation/backticks); rejects traversal/invalid qualified identifiers; matches physical path, established Python/JS module identity or Java package directory suffix. It never falls back to another namespace. Ordinary SQL name/qualname matching preserves SQLite NOCASE candidate filtering, kind filtering and exact case preference before Python-casefold fallback.

Descriptions reject empty/mixed-owner/mixed-version passages. Duplicate spans use the last passage, sorted by start; include every owned region once. Join unique canonical fields in first occurrence order. Implementation starts at the owned implementation offset; classify Python-whitespace-prefixed #,//,/*,*,-- comments, nonblank executable lines, lexical calls and return/throw/raise/yield word matches. Preserve codepoint-based slicing and line splitting, including trailing empty lines and lone surrogates.

Selection requires passages, representation_version3 and exact source policy before non-unique retrieval, identity/behavior vector revisions and complete passage ID coverage. Channel order is exact,lexical,identity,behavior. Fuse each channel's rank with rrf_k60/default candidate_limit100, max candidate signals and later passage measurements on duplicate spans (distinct from proposal-fusion max). Sort exact,rrf,path,earliest span with stable remaining ties; assign complete merged owned regions. Read all source/vector data in the same pinned snapshot, no source reread.

Contextual policies/models/projection_version1/source versions/generation/complete owner set must agree. Owner vectors are finite, nonempty, normalized F32; preserve original row-norm acceptance. Normalize query vectors with original platform arithmetic; require finite norm >1e-9 and indexed dimension. Identical original/expanded strings reuse the same encoder call/vector/scores. Code proposal peak is max(original,expanded), stable owner order, first4 owned passages. Source views require distinct model/query model identities, both contract/implementation row maps and a finite normalized deduplicated vector pool; score only combined candidate owners using the same query vectors. Validate all ownership/version boundaries before enrichment.

Generic ranking defaults rerank_limit40, entity unit. No judge or unique exact bypasses judging. Entity documents use executable-first, descending behavior score, line order; unique bodies up to4, implementation offsets, documentation prefix600 Python codepoints only for identity/documentation purposes. Passage ranking deduplicates spans by last passage, retains executable evidence or first fallback, uses max passage score per owner and complete evidence scores. A judge must return exactly one finite F64 per selected unit; otherwise fail explicitly. Exact priority precedes model scores, with original path/first-evidence tie order. Preserve input immutability and named measurements.

F32 score bound remains abs1e-6+rel1e-6; F64 fusion bound remains abs1e-12+rel1e-12. Exact ordered owners/evidence, complete text/identity/regions/error categories remain mandatory. Use accepted platform BLAS, not a new reduction. Include a pipeline case that stores unnormalized input vectors before searching: storage normalization must not reintroduce the cutoff reversal.

## Evidence and finish

Capture only new original observations/suites once, with actual module hashes, discovery, call states and JUnit. Reuse M4a's accepted292+4case/raw-suite receipt, M2 model catalog and M3 indexing; rerun only native directly affected regressions after source changes. Input-only probe executes complete real selection operations, never consumes expected outcomes. Verify actual native SQL edits/deletes, multiple connections, rollback/reused generation, Unicode and error boundaries, dense/contextual ownership, judge call counts and stable rankings. Both Darwinarm64/Linuxaarch64 need source/binary/input/output/runtime authentication, outside-checkout emptyPATH/isolatedHOME/noPython/no subprocess/network execution audit and honest bounded time/RSS. Reuse generic process/receipt helpers. One fresh final plan reviewer, one Important/Critical TDD fix pass, archive exhaustive ledger/rulings/minors, independently replay final receipt, remove only owned obsolete scratch and continue M4c automatically.
