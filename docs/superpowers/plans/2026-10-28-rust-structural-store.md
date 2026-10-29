# Native structural snapshot store — M5a core

Goal: move inward to the program/IR persistence boundary required by KQL,
not add public-tool adapters. Reuse ken-program IR/common AST and migrate the
structural store's real schema, units, projection, snapshots and scan semantics.
Existing Python source remains active; no installed-tool switch or new versions.
Linuxx86_64 only. Existing user approval covers independent implementation/push.

Concepts: StructuralSchema owns exact versioned SQL/ownership/DDL checks and
transactional up/down; StructuralStore owns immutable units and compare-parent
publication; SnapshotScan enforces membership on every access; scalar encoding
preserves Python integer/bool/null/negativezero distinctions; projections own
indexed operations and common AST; leases own lifetime/renewal and conservative
collection. Keep this separate from legacy project/vector DB despite sharing
ken-store crate. Future graph segments/query execution depend on this boundary.

Representative use: open StructuralStore; put_unit(key, ir, hashes, syntax=true);
publish(units, expected_parent,...); prepare_scan(snapshot, filter).rows();
properties(node); load_unit/operations/program. Reader retains old snapshot after
new publication. Two writers publishing against same parent cannot both win.

Production schema/layout resource is extracted ONCE from frozen source SQL as
migration data, retaining all15 checksums/up/down/tables and canonical AST layouts.
Rust executes and validates it natively; no Python invoked at runtime. New original
observations cover schema versions, dedicated ownership and persisted native/legacy
scalar/property/operation/AST/snapshot behavior; preserve immutable raw evidence.

- [x] Capture schema/IR/snapshot originals and frozen SQL/layout resource once.
- [x] Implement native transactional schema, typed scalar codec and projections.
- [x] Implement units/snapshots/streaming scan/properties/leases/GC and AST access.
- [x] Grouped core validation, one fresh review/correction, handoff; push authorized.

Validation: migration up/down/rollback and unknown/future/altered/foreign database
rejection without modification; cross-runtime DB reads; duplicate revisions and
publication conflicts atomic; snapshot isolation/membership; full typed-property
and IR roundtrip; AST/body projections; retention rollback; active reader and
in-progress acquisition protection; lease expiry; no persistence at tiny budgets.
Cache-artifact policy and full graph publication/query/CFG production are later
core slices; this block does not claim complete M5 or a working KQL engine.

Results:5newcore roots+8program roots GREEN; strictClippy GREEN1.40s; fmt/diffclean.
Original schema15/up/down,3IR+AST+operation projections, typed properties and
snapshots match. Original SQLite read succeeds. Review Important view-only foreign
ownership hole RED→GREEN; intentional fail-closed hardening over original empty
check. Quadratic entity reconstruction regraded Important and removed, including
the same IR codec issue newly on this store's read path;7500entity regression
preserves ordering/replacement. Cursor-active lease renewal uses Cell<Instant> and
immutable renewal access, proven on persistent store; no new data-publication API.
No second review. Old dynamic original vector tests were not rerun: broad attempt
stopped for missing KEN_RUST_REFERENCE before that observer launched, and scope
was narrowed to source-only core tests. Previous accepted vector receipts remain
unchanged. No dependency versions changed and no CPU/CI/archive matrix repeated.
