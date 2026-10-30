# Native source runtime implementation plan

Use superpowers:executing-plans inline, with one final fresh read-only reviewer
per completed implementation stage. User authorizes autonomous implementation,
grouped validation, commit and push on codex/rust-migration.

Spec: ../specs/2026-10-30-rust-source-runtime-design.md.

1. [x] Capture new frozen-original source runtime observations, pin fixtures and
   write representative source-query/adapter tests before implementation.
2. [x] Implement a reusable source semantic runtime and operation reads in memory
   and SQLite: descriptors/matchers, storage/type filters, quantifiers, effective
   fields, receiver effects, initializer roots and occurrence-level usages.
   Validate full outcomes, uncertainty and evidence across both adapters.
3. [ ] Continue BODY using the checked BodyPattern/source AST and shared semantics;
   preserve control-flow completeness, clause ordering, matching and uncertainty.
4. [ ] Continue indexed execution over checked scans/actions/BODY, including typed
   expressions, projection/order/deduplication and invocation budgets.
5. [ ] Continue native session ownership and prepared-resource reuse with immutable
   snapshots, invalidation/refresh and deterministic release.
6. At substantial implementation boundaries run grouped targeted tests and
   strict Clippy/fmt, final review and one Important/Critical repair pass. Update
   migration handoff and Ken findings, commit [skip ci], push and verify SHA.

Review focus: source descriptor cycles/nominal shadowing, evidence and open
inventories; operation probes and parent ownership across nested callables;
missing initializer links versus known non-call roots; occurrence identity versus
historical data flow; unsupported patterns and interruption during lazy reads;
session cache lifetime and cross-snapshot isolation.

Pre-flight: source semantics and operation reads are shared by all later tasks;
keep stable local identities and per-execution control separate from retention.
Do not introduce a second source rule set for indexed or BODY evaluation.

Source stage completed:700 fresh original observations match memory/SQLite;
31 affected roots, strict Clippy and format pass. One fresh final review found
three Important (typed constructor counts, interruptible region discovery,
exact storage numeric/null semantics), all repaired with failing-then-passing
regressions in one pass. Minor deferred: clarify the OperationProbe exactness
contract for third-party adapters; built-in adapters already filter exactly.
Raw captures, scripts and ledger remain local as requested. BODY/indexed/sessions
remain the next implementation stages; this is not a claim of M5 completion.
