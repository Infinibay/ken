# Native relational KQL2 compilation

Continue56caeceb on Linux x86_64. Complete the relational capability compiler:
source selectors, semantic comparisons, graph edges/walk/count, private scoped
absence/optional, calls/branches/aliases, source requirements/usages/initializers
and existing BODY checking. Produce immutable typed operator plans, not query
text or a runtime evaluation. Preserve original projection/order/definitions and
fingerprint SHA256(repr(prepared File)); cache each reachable declaration once.

Caller: compile_relational(&File, query) -> CompiledQuery; metadata Program uses
the original protocol, relational_plan retains an Arc<RelationalQuery>. Common
Program keeps IndexedProgram as a compatibility alias. RelationalQuery owns nodes,
ordered exports/definitions; RelationalNode owns one operator. PlanValue/Term keep
literal tokens distinct from role strings, including through alias rewriting.
Use ordered tagged maps in capture/plan serialization to preserve map order.

SourceSelector owns immediate ownership/property lowering to canonical clauses;
SemanticComparison owns relation-specific witnesses and comparisons; SourceChecks
owns requirements/usages; RelationalLowering owns bound-role scopes, reachable
patterns and plan cache. Reuse existing BODY/type checking, not duplicated rules.
Optional explicit-snapshot compilation coordinator may compose validation96,
libraries/models and backend choice; packaged-library discovery and public host
CLI/MCP/cache wiring remain separate. No database/source project I/O here.

Constraints: original errors/code/spans/wrapping and source-vs-query/literal tags;
ordered hygienic names and original short forwarding-plan inlining. Existing
512 native depth/65536 work ceilings apply before expansion/materialization. No
new dependency versions. Frozen original1066 untouched, auth before/after new
observations; reuse accepted tagged prepared ASTs without parser/indexed/BODY
baseline replay. Raw/scripts/workspace local; Python installed stays active.

Implement inline, large grouped native parity/resources tests, one fresh final
read-only review and one Important/Critical regression/fix pass. User autonomy
supersedes approval/worktree/per-edit TDD loops. Authorized commit/push current
branch. Full relational execution/KQL1 operator runtime remain next, not claimed.
