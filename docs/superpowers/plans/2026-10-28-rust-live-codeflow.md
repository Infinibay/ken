# Native Live Codeflow Implementation Plan

Goal: complete live callgraph, type hierarchy and runtime wiring from syntax
through readonly index resolution to CLI/MCP. Linux x86_64; no model loading,
Python fallback, new external versions, schema changes or original removal.
Execution inline under existing migration contract and deprecation-and-migration;
one implementation batch, combined validation and one final fresh review.

Concepts: StructuralSignals (ken-syntax) extracts calls/base clauses/wiring from
verified syntax views using original per-language registries and traversal.
LiveCodeflow (ken-search/navigation) binds these observations to indexed symbols,
precision tiers and enclosing spans. Installation grammar-only reader supplies
only the grammar resource, independently of model preparation. CLI LiveTools
owns lazy grammar acquisition shared by related and find-wiring, keeping public
argument/format conversion outside domain algorithms.

Public/library usage: nav.callgraph(catalog, request), nav.type_hierarchy(catalog,
qualname,direction,with_overrides), nav.wiring(catalog,query,kind,limit).
CLI tools related TARGET callers/callees/subtypes/supertypes and find QUERY
--scope wiring; MCP uses the same adapters. Existing --resources may point to a
minimal {format:"ken-search-installation/1",grammar_manifest:PATH} for these tools.
Session, knowledge, KQL and other relations remain explicitly pending.

Preserve observable quirks, not speculative fixes: public numeric min_confidence
falls back to tierT2 and remains numeric in its output; original public
subtypes/supertypes pass down/up while library expects sub/super, so both public
relations currently report descendants without overrides. Expose the faithful
library directions and document this original inconsistency. Preserve reverse
syntax traversal, same-line edge dedup, T3 ambiguity, target selection order,
last-definition-wins base map and hierarchy cycle behavior, literal string
stripping, TypeScript grammar selection (not automatic TSX), and limit slices.

- [x] Capture new original syntax/domain/public cases once, with no model/index runs.
- [x] Implement signals, index resolution, lazy grammar-only loader and adapters.
- [x] Combined library/CLI/MCP parity and existing boundary checks, strict Clippy.
- [x] One fresh read-only review; necessary fixes and documentation; push authorized.

Completed: immutable3413B fixture SHAb5586fe9eae7915b49c44f8da201deda952aaa8bf6e87911882fa83028055969
contains19signals/26domain/10public observations. All original comparisons passed
on the first run. One extra local invariant had omitted JavaApp/DartDog from
cross-language Base descendants; corrected only that local expected list.
Combined affected33native roots GREEN and strictClippy6.27s. One fresh reviewer
reported no actionable findings. Same-process tests cover failed grammar config
repair, source edits, missing model fields and JSON/compact/legacy transport.
No originals recaptured, production correction pass, broad CPU/CI/archive cycle
or dependency version changes; ken-syntax moved dev→normal CLI dependency only.
