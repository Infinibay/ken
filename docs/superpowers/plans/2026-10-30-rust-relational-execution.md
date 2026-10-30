# Native relational execution implementation plan

> Use superpowers:executing-plans inline. One final fresh read-only reviewer;
> no implementation delegates. User authorizes autonomous grouped validations.

Goal: execute native checked graph plans with evidence/unknown and budgets.
Spec: ../specs/2026-10-30-rust-relational-execution-design.md.
Constraints: Linux x86_64, Rust1.95, existing locked versions/schema15, portable
policy in ken-query and thin storage adapter in ken-structural. Original1066
untouched/authenticated; no accepted parser/compiler/BODY/model/global replay.
Raw/workspace retained locally; current branch commit/push authorized.

Review focus: absence/cardinality closure through branches/dependencies; typed
literal/attribute asymmetry and proof JSON; cache seed/scope and proof upgrades;
malformed wide/deep/shared plans; cancellation/resource release during SQLite
planning/scans/evidence detachment, plus bounded public matches/proofs.

1. [x] Capture fresh original execution outcomes over deliberate graph/plan
   snapshots; tag terms and preserve ordered exports/proofs. Pin compressed fixture.
2. [x] Add execution modules in crates/ken-query/src/execution: validated runtime
   plan, GraphRead/MemoryGraph, control, terms/comparisons, evidence/projection,
   planner, operator engine. Expose Execution/QueryBudget/options/outcome.
   Tests: fixture full results and author-order counters; compile→execute usage;
   strict/possible, alternatives/caches, closure/count/path/proof cap and malformed
   records/depth/DAG/large bindings. Regex unsupported syntax is explicit.
3. [x] Add crates/ken-structural/src/query.rs native GraphIndex adapter and public
   execute_query. Add ken-query dependency and existing regex edge, no new version.
   Tests: crates/ken-structural/tests/query_execution.rs memory/SQLite parity,
   persisted graph lifetime, cancellation/deadline/VM callback and cleanup.
4. [x] Group affected ken-query/ken-structural tests, strict Clippy/fmt. Repeat
   targeted checks only for actual changes/failures; no baseline/global replay.
5. [x] Fresh final review of this whole stage, regrade/fix Important/Critical
   with RED→GREEN in one pass, no re-review. Update migration docs/justified Ken
   constraints, commit [skip ci] and normal push branch; verify remote SHA.

Completed:76 affected roots,210 original execution observations plus528 numeric
observations, strict Clippy/fmt, one fresh final reviewer and one repair pass.
Six Important fixed; two inherited certainty bugs intentionally corrected.
Original fixtures unchanged,18 separately authored cardinality expectations.
Snapshot/inventory/path/cardinality decisions and remaining capabilities are in
the migration handoff; raw/workspace retained per user. Commit/push authorized.
