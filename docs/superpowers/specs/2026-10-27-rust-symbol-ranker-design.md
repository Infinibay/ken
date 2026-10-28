# Native symbol ranking composition on Linux x86_64

Continue the authorized Rust migration inline and push the migration branch.
Implement the complete SymbolRanker composition of the frozen Python contract;
PieceSearch orchestration, other models and M4/global acceptance stay pending.
Reuse the accepted operation backends, views, preferences, physical catalogs and
Ettin adapter; retain prior originals unchanged and execute no original pytest
roots. All captures/receipts/workspaces remain local, outside Git.

Approaches considered: duplicate the Python ranker algorithm in a new Rust
module; compose the existing accepted views/preferences/operations; merge all
ranking policy into PieceSearch. The implementer selects composition: numerical
and preference rules keep their authoritative owners, and orchestration remains
small. Existing user instructions to continue cover this routine migration
choice; no new platform, model, persistence or installed-app behavior is selected.

OwnerDescriptions owns catalog-bound immutable descriptions and their cache.
PieceAssembler and SymbolRanker share it explicitly through mutable borrowing,
with no second cache or hidden global state. SymbolRanker owns the operation
observer, references its immutable catalog and paired model, and composes the
view scores then operation/test/operator preferences. SymbolRanking owns the
result order, code/mean scores, admission flags, witnesses and model details.

Representative caller:
let mut descriptions = OwnerDescriptions::new(catalog.clone());
let mut ranker = SymbolRanker::new(catalog.clone(), neural, grammars);
let ranking = ranker.rank(&request, &keys, &expanded_query,
                          &original_scores, &mut descriptions)?;
A future PieceSearch passes its assembler's descriptions_mut() cache. Keys are
canonical entities extracted from cards by that caller; SymbolRanker does not
own card projection or presentation. Reject a foreign catalog cache before
inference. Preserve <=10 input membership, stable ties, original expanded-query
model calls, whole-code fallback, lazy empty scoring, requested-only witnesses,
explicit purpose semantics and test/operator priority. Preserve source snapshot
behavior if disk changes. Do not introduce new dependencies or numerical rules.

Capture independent full composition cases before native implementation using
frozen1066/Python3.12.9 and the actual original SymbolRanker/make_catalog. Controlled
model leaves trace pair/score calls; add production Ettin frames for composition
with the accepted native model. Compare cold/warm cache reuse, descriptions,
orders, witnesses, flags, scores and errors. No previous fixture/capture changes.
Canonical cache provenance is a native guard; do not copy Python's externally
mutable cache weakness. Preserve the existing finite-score native contract.

Validate RED→GREEN public callers, physical-source corpus, cache sharing and
error ordering; full affected Rust/fmt/Clippy, confined input-only native probe,
complete local and two-replica Linux x86 CI prerequisites, protocol tamper,
one fresh final read-only review/one Important repair pass, Git-authenticated
archive and isolated replay. Report this scoped acceptance and remaining work.
