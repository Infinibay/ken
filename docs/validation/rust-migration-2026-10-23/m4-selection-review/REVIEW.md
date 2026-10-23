# M4b final review — gpt-6-astra, high, fresh context

Reviewer: /root/m4_selection_final_review. Range2439c7c4..1e837ef7. One read-only whole-plan review, no implementation delegation or re-review.

Strengths: snapshot-local SQL prevents connection/generation cache reuse; query sharing follows Rc ownership; fusion preserves later passage measurements, complete regions and stable order; storage normalization uses the accepted platform arithmetic and witnessed cutoff regression. Independent --current receipt replay passed758observations/122original tests/41Rust roots/38tooling roots on each actual platform. Reviewer also compared5293targeted text/locator/module variations against the frozen original; those exploratory comparisons are not added to the sealed758observation denominator.

Critical: none. Minor: none.

Important: standalone SourceViewSnapshot::enrich and ContextualScores::propose did not independently validate supplied passage identities/source hashes. The composed contextual path is guarded, but each public standalone API could attach or return a snapshot's scores with another version's passages. A native source-view probe with snapshot hashes old-version enriched candidates carrying a*64. A Rust caller scored valid owners, changed their passage hashes to new-version, then propose returned new passages with old cosine_code=1.0; subsequent enrich correctly rejected them. The frozen original source-view API also admits this input. This is an inherited guard gap against M4b's explicit freshness requirement, not a Python/Rust parity regression. Recommendation: one authoritative evidence/owner/hash check, used before proposing/enriching, with direct tests for both public APIs.

Declined to judge: fitted forests/features/stemming, piece ranking and bounded fresh evidence remain M4c; production channels/public CLI/MCP/full quality/resources remain M4d; native BLAS acquisition/distribution remains M7/M8; unchanged M0–M3/M4a capabilities/model catalogs are accepted predecessors and were not rerun. Executor rulings retain each obligation and keep M4/global acceptance false.

Verdict: with fixes. Close both public source-identity bypasses before accepting M4b. One Important/Critical TDD fix pass follows; no second reviewer.


## Verified one-pass closure

The Important finding is fixed by model::evidence_matches, shared by contextual score/enrich, contextual proposal generation and standalone view enrichment. Proposals revalidate the complete owner source; source views validate all candidates before any measurement. Two direct Rust regressions witnessed RED (stale evidence admitted) then GREEN, including wrong passage owner, empty evidence, missing source coverage and unchanged inputs. Both actual platforms pass43retrieval Rust roots and38tooling roots; all758valid original observations still match without changing tolerances or captures. No original suite/model was repeated.0Critical/Important remain;0Minor deferred. Full M4 and migration remain incomplete.
