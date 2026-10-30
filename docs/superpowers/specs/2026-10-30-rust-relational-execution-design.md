# Native relational graph execution

Continue7c98d0ba on Linux x86_64. Execute the shared relational plan from KQL2
(and later KQL1) over immutable memory and schema15 GraphIndex snapshots. Preserve
fact/literal bindings, alternative and dependency boundaries, closure/unknown,
scoped absence, optional evidence, distinct counts, bounded paths, proof grouping
and limits. Compile+execute is a complete working graph-query slice; do not claim
source BODY, indexed KQL2, sessions or host routing have migrated in this block.

Caller: `Execution::new(options)?.execute(&MemoryGraph::new(&ir)?, &query)`;
`ken_structural::execute_query(&mut GraphIndex, &query, options)` uses the same
engine inside the existing SQLite interruption/lease scope. Execution owns
bindings, budget counters, caches and deadlines; graphs only own snapshot indexes.
No query state shared between runs. All returned evidence is detached before
storage closes. QueryBudget fields default to None; explicit limits must be
positive. Exhaustion/cancellation returns incomplete evidence, never absence.

`ken-query::execution` owns typed validated operators, graph-read protocol,
execution control, comparison/term services, closure, join planning, proof union
and result projection. `ken-structural::query` only adapts native GraphIndex and
its interruption scope. No store dependency in the policy/compiler crate, no new
crate/dependency version, no schema/DDL changes. Reuse GraphValue and existing
immutable RelationalQuery, lossless values and tagged literal distinctions.

Approach chosen by implementer under standing autonomy: portable engine plus
thin graph adapter. A SQLite-only executor would couple policy to persistence;
putting storage in the compiler would invert the existing responsibility boundary.
Memory adapter is a real reusable execution source and deterministic oracle target.

Implement facts/fact_union, where/different, any, match with seeded memoization,
not/optional/count/path, source_receiver, validation and closure. Support author
order and selective positive joins with semantic barriers. Source-specialized
operators not yet migrated fail explicitly during plan validation, including in
unreached branches. Regex matching uses the existing pinned linear `regex` engine
for its supported syntax; unsupported Python-regex capabilities return explicit
unsupported errors, not an approximate successful match. Full advanced matching
and BODY/source semantics remain a later runtime capability.

Query state/row/match/time ceilings retain original meanings; native plan-depth
and validation-work bounds protect malformed caller-built plans. Output matches,
status, unknown, proof order/truncation and dependencies match the original.
Elapsed time and physical candidate counters vary by storage strategy; exact
state/row observations are compared for the author-order memory path. Snapshot
scans stay indexed, streaming and cancellable; native additional materialization
bounds, if needed, must be explicit incomplete reasons rather than silent limits.

Use authenticated original1066 only for fresh execution observations, feeding
new plans/graphs or previously accepted IR without replaying parser/compiler/BODY,
model/CPU/global baselines. Raw observers/workspace local. Group native parity,
resource, cancellation and persistence tests, one fresh final read-only review and
one Important/Critical regression/fix pass. Normal commit/push current branch
already authorized; installed Python/frozen original remain untouched.
