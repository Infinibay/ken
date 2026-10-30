# Native source runtime

Continue the Rust migration from relational execution toward source queries,
BODY, indexed execution and retained sessions, in that dependency order.

The source snapshot owns identities, entities, operations and indexed facts.
Source semantics interprets those facts: descriptors and source type matching,
closed storage contracts, declaration inventories, effective fields, receiver
effects, initializers and witnessed uses. It never reparses a project or infers
closed-world absence from a missing fact. BODY consumes the same source view and
semantics; indexed query execution composes scans, actions and BODY. A session
owns immutable snapshot resources and prepared plans, while each execution owns
its budgets, cancellation, bindings and results.

Representative usage is a compiled source selector executed against either an
in-memory query graph or the existing schema15 GraphIndex. Source predicates
must run through the relational engine first, with identical bindings, evidence
and uncertainty across both adapters. Literal versus computed values and source
type descriptors remain separate concepts. An opaque/generic descriptor can be
known while its family match remains unknown. Nominal shadowing prevents a
project-defined primitive spelling from matching the primitive family.

Implement complete source-operator slices before adding BODY interpretation.
Keep unsupported later runtime clauses explicit rather than silently dropping
them. Retain the existing compiler fixtures and capture only fresh runtime
observations from the authenticated frozen original. Native safety tests cover
malformed descriptors/plans, cycles/depth, interruption, open inventories and
adapter parity. Existing cardinality safety exceptions remain authoritative.

Linux x86_64 is the validation target. No schema/dependency-version changes,
installed Python replacement, frozen-original edits, model/CPU or global replay.
Group checks at substantial boundaries as requested; retain scratch locally.
