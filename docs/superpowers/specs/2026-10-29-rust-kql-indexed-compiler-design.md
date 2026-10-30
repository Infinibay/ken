# Native indexed KQL2 checking and BODY preparation

Continue e7a36fb5, Linux x86_64. Implement the complete indexed capability
compiler and BODY checker as a pure native boundary in ken-query. The relational
backend remains a distinct subsequent slice: no fallback, placeholder plans or
claim that the public compiler dispatcher is complete.

Caller: prepared syntax -> expand_indexed_alternatives ->
compile_indexed(&File, Option<&str>) -> Result<IndexedProgram, ParseError>.
compile_body(&Clause, owner, mapping, &mut roles, expected_types) -> BodyPattern
checks source-expression captures and control patterns, without executing source.
The input to compile_indexed is already resolved/specialized/expanded; this is
Python _compile, not its public compile dispatcher.
compile_indexed_branches(&File, query) composes native bounded expansion and
checked branches, retaining the global limit and SHA of ordered branch hashes. Public compiled-source
validation/dispatch, packaged library loading and relational plans remain next.

Concepts: IndexedProgram is an immutable checked sequence of scans/actions/BODY
patterns plus predicates, projection/order/limit and exact original fingerprint.
IndexedLowering owns role binding, hygienic use expansion, private existentials,
inventory constraints and ordered steps. ExpressionChecker owns scalar/domain
rules and scoped quantified roles. BodyChecker owns anchor state, source operands,
call/construct constraints, output captures and nested/conditional plans.
CapabilityVocabulary owns shared selector/property/domain/relation constants.

Keep exact AST types/spans, original error code/message/span wrapping, declaration
and role/capture order, generated counters, and Python repr fingerprint framing
(list vs tuple vs dict). Support arbitrary-size integer limits. Preserve join96,
pipeline256, recursive pattern detection and source matcher rules. Guard native
recursive work with existing bounded topology and stack growth, no new dependency
versions. Frozen1066 untouched; capture only new compiler/BODY observations,
consuming accepted tagged prepared/expanded ASTs without parser/preparation replay.
Keep journals/workspace local. Installed Python stays active.

Alternatives considered: combine both compiler backends now (also requires source
selector/quantifier/usages lowering; too broad for one coherent checked slice),
or port expression checks alone (would leave no usable checked plan boundary).
Chosen full indexed/BODY slice can be exercised independently and later composed
with the public dispatcher. Choice is the implementer's under user autonomy.

User opts out of approval/per-edit validation loops. Implement inline, group
parity and adversarial tests, one fresh final read-only review, one regression/fix
pass, docs/memory and authorized commit/push. No original/model/CI baseline replay.

Native safety additions: bounded typed-record topology and required-slot validation
before remapping/indexing; cross-declaration pattern depth512 and expansion/remapping budget65536 units.
Units count AST records/parameters, payload blocks of64bytes and BODY role-map
entries. Charge before cloning/materializing expressions, BODY/optional subtrees;
share a budget across nested BODY checks. Stop retaining the discarded pipeline
past256 steps while continuing binding validation until error/budget. Native
resource diagnostics stay resource_limit instead of ordinary BODY wrapping. Three malformed manually built original ASTs raised StopIteration;
these and other broken records return structured native errors. Costs are explicit:
pathological expansions may return resource_limit before Python would finish;
corrupt-AST diagnostics are not host exceptions. Parsed normal inputs and all
captured outputs preserve exact diagnostics and fingerprints.
