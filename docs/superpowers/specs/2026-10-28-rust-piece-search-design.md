# Native PieceSearch composition

Continue the Rust migration on Linux x86_64 by composing the accepted source cards,
PieceAssembler, PieceReranker, SymbolRanker, reciprocal fusion and presentation.
PieceSearch owns a catalog, concrete numeric piece ranker, shared paired model,
shared description cache through its assembler, and symbol ranker. It coordinates
rather than duplicating their policies. No new dependencies or Python runtime.

Public usage: PieceSearch::new(catalog, ranker, neural, grammars).search(request,
matches, expanded_query, profile_version, exact) returns Result<SearchResponse>.
It builds and assembles at most ten distinct native units; ranker output is mapped
by unit identity. Preserve exact-mode numeric ranking while skipping all neural
inference; ordinary non-symbol requests fuse ranks with weight .5, offset 60;
symbol requests delegate to SymbolRanker using original request and expanded model
query. Stable named-path promotion applies last. Verify complete native top-ten
membership before applying display limits. Model score cardinality/finite errors
fail before indexing. Empty requests keep existing laziness and call behavior.

Presentation retains canonical identity, physical evidence, stale-source handling,
limits and profile version. Attach explain signals by identity after presentation
may drop results, never by positional zip. Optional PieceResult.signals is absent
for other presentation callers. Original lifecycle trims before attaching explain
signals: an explain response can exceed max_chars after adding diagnostics. Preserve
that observed behavior; no new budget policy in this composition slice.

Before native implementation capture distinct complete original API observations:
controlled encoder/stemmer/numeric forests/paired model, three actual Ettin frames,
cold/warm outputs, neural calls and shared descriptions. Journal every row. No
original pytest reruns or modifications of accepted reference/model/tolerance data.
Frozen 1066-file fingerprint remains
5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038.

Native probes accept physical catalog and requests only, never answers. Authenticate
native process/resource closure and source-bound full local/two-replica CI gates;
preserve all raw attempts and seal portable evidence with archived validators and
Git source proofs. One fresh read-only final reviewer, one Important fix pass,
no repeated review. Commit/push codex/rust-migration remains authorized. Keep
all raw docs/validation, .ken and workspaces local. Remaining model inventory,
application wiring and M4/global acceptance remain separate; installed app stays
Python. No global completion claim.
