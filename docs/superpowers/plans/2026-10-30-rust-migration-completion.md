# Finish the Rust migration

Spec: ../specs/2026-10-30-rust-migration-completion-design.md.
Baseline:59477a7d70b6f55923b585f02d2521b62538e382.
Execution: continuous implementation, independent domains dispatched with the
parallel-agents skill; coordinator owns shared interfaces and grouped validation.
No routine approvals or per-edit full-suite reruns. Preserve local scratch.

## Global constraints

Linux x86_64; Rust1.95; current locked dependency versions/schema15; original
sources and frozen reference untouched. No Python runtime fallback. Existing
numeric/cardinality/proof safety remains. Only native work is credited. Budgets,+uncertainty and stable identities reach public responses. Commit/push authorized.

## Tasks and shared interfaces

1. Shared runtime values/read contracts (coordinator): add typed query values,
   source node metadata and snapshot lookups in ken-query; adapt MemoryGraph and
   GraphSnapshot without duplicating source semantics. Add exact numeric arithmetic
   using existing locked crates when needed. Tests pin type identity, metadata,
   option/unknown semantics and interruption before integrating consumers.
2. BODY runtime (coordinator): consume checked BodyPattern; implement source
   expression matching, CFG coverage/walks/ordering, calls/returns/writes/controls,
   iteration/collection effects, path values, exceptions and generator continuations.
   Reuse existing compiled fixtures as runtime inputs; observe fresh runtime
   outcomes and prove live compile-to-execute parity in memory and SQLite.
3. Indexed runtime: consume Program/Scan/Action/BodyPattern and shared query values;
   implement expression/predicate evaluation, domains, scans/actions, optional
   evidence, alternatives, distinct projections/order/limits and budgets. Preserve
   public Outcome serialization and invocation cleanup. Integrate via a single
   execution entry point after shared interfaces are implemented.
4. Native sessions: own prepared source revisions/readers, module resolution,
   graph/semantic resources and compile caches; implement refresh/invalidate,
   owner/lease checks, dirty delivery guards and close. No cached query answers.
5. KQL1 (independent domain): implement parser/pattern validation and graph
   execution in crates/ken-query/src/legacy/** with public parse/execute APIs over
   execution::GraphRead. Preserve directives, paths, counts, variants, constraints,
   optional/forbid, capabilities, evidence and bounded execution. Coordinator
   wires module exports and public adapters. Add dedicated fixture/runtime tests.
6. Remaining native application inventory: map Python public capabilities to
   implemented Rust owners; implement missing knowledge, reasoning, checks,
   inspection and responsibility operations over existing data/native query APIs.
   Retain justification validity, anchors, delivery deduplication and unknowns.
7. Complete service/public integration: native daemon/queue/watcher/lifecycle,
   remaining CLI/MCP/hooks/hosts/config/catalog/cache contracts and saved queries.
   Prove real-process transport, fresh source changes and shutdown/restart behavior.
8. Native packaging/promotion: package resources and models, run affected/final
   x86_64 application checks without Python, exercise data upgrade/rollback on
   fixtures, update default entry points only after parity, document remaining
   external qualification honestly, commit/push and verify remote SHA.

For every substantive capability: author meaningful tests before implementing,
capture their failing outcome, implement the complete slice, then group its
affected checks. Keep detailed status/evidence in the ignored plan workspace.
Independent workers do not touch shared manifests, lib.rs/mod.rs, docs or another
worker's paths, and never run shared Cargo without coordinator authorization.

## Review focus

- Stable identity versus historical value provenance across exclusive CFG arms.
- Exact scalar/enum/option identity, arithmetic and open quantifier domains.
- Source/graph snapshot ownership across refresh, cancellation and delivery.
- Lossless persistence, cross-language read compatibility and failure rollback.
- Public transport/packaging running without Python or silent unsupported success.
