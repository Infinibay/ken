# Explicit symbol preferences in native retrieval

Continue the approved Rust migration inline, Linux x86_64 only. The neural
symbol views are accepted at206f4861; this slice owns interpretation and stable
source preferences, keeping observation of source operations separate.

SymbolRequirements names the operations/operators/test-case intent requested by
SearchRequest. It reuses the existing intent interpreter and PythonText matching.
SourceCatalog owns immutable source, owner role/extent/enclosing callable;
is_test_case reads this catalog, never current disk. SymbolPreferences applies
three stable passes: matching operation witnesses, requested test cases, then
explicit code operators. Each pass preserves membership and the previous order
within equal groups. Unknown evidence supplies no preference. OperationWitnesses
and full SymbolRanker/PieceSearch remain pending; no placeholder source observers.

Caller: requirements(&request) -> SymbolRequirements; is_test_case(&key,&catalog)
-> SourceResult<bool>; apply_symbol_preferences(&required,&witnesses,&test_cases,
&implementations,&order) -> Result<Vec<usize>>. The caller supplies observations;
this component does not invent source witnesses. All arrays must match candidate
count and order must be a complete permutation. Invalid collaborator shapes
return errors, never index panics. No top10 cap in this reusable policy; the
existing ranker owns that cap. Require no new dependencies or model changes.

Preserve exact frozen requested_operations regex/casefold/negation boundaries;
only uppercase ASCII word tokens or backtick letters request boolean operators,
with original bitwise exclusions. Reuse one TEST_OBJECT pattern for intent and
test-case requests. Explicit purpose overrides inferred tests. Test-case identity
requires function/method, catalog owner test role, and no enclosing callable;
Python/pyi name starts with test; Java matches a known annotation within the
original bounded declaration prefix (12 lines, before first brace).

Alternatives: merging this into the ONNX adapter mixes retrieval policy and model
mechanics; porting all Python AST/source observers in this slice expands another
responsibility. A complete policy consuming explicit witnesses composes with the
existing neural views and later observers naturally. This is the implementer's
choice within the user-approved migration, not a new product behavior.

First capture new independent observations from frozen symbol_requirements and
actual original catalogs BEFORE Rust implementation. Include positive/negated
operations, Unicode/codepoints, purpose/helper/test-double ambiguity, literal
operators/bitwise prose, wildcard/all-required witnesses, stable three-pass
precedence, empty candidates, and Python/Java identities from immutable catalog
snapshots. Keep the1066frozen files, old model/fusion/view corpora unchanged.
Never recapture originals. Test all typed outputs against first observations;
strong native input guards get separate caller tests.

Validate RED→GREEN, full affected native suites, strictClippy/fmt, input-only
native probe, scoped tamper tests, current x86 CI and source/archive authentication.
One fresh final review for this new plan, one Important repair pass, no re-review.
Only preference capability may close; full source observers/search/M4/global stay
pending. Preserve raw/SDK/workspaces locally and outside Git; push authorized.
