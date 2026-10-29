# Native source-operation production — M5a core

Contract: parse source using the pinned GrammarCatalog, retain all named nodes,
source IDs, field roles, operator facts, ownership, diagnostics and lexical
execution. Produce source IR that feeds native CFG/contexts/normalization/store.
Nine structural languages only, Linux x86_64 priority. Complete this producer
stage before adding semantic adapters; unknown syntax stays NATIVE.

Concepts: source syntax (grammar/tree/source bytes); lexical ownership (declaration
identity and scope, types-first traversal, Rust impl/Go receiver/C++ prototypes);
operation vocabulary (canonical kind/operator rules); operation projection
(fields/tokens/text/evidence); domain control remains in ken-program.

API: ken_syntax::structural::lower_operations(catalog, language, source, path)
returns StructuralIr. Owner entities provide identities and source coordinates,
not the complete declaration/parameter metadata. Capabilities include syntax
only: no calls/declarations/resolved-types completeness claim. This is the actual
source producer stage, not an alias for a complete lower_source/semantic linker.
No new dependency versions; syntax adapter depends on program, never the reverse.
Keep Python installed and raw observations/workspace local and untracked.

- [x] Capture new original declaration→operation stage cases, plus CFG/contexts.
- [x] Implement source/ownership/vocabulary/projection as one functional batch.
- [x] Grouped native syntax/program/pipeline tests and strict Clippy; exact IR.
- [x] One read-only final review, one fix pass, docs and commit/push authorized.

Validation includes all nine languages, forward types/impl/receiver methods,
C++ prototypes versus callbacks, type aliases, closures/nesting/class expressions,
operators/operands/uninitialized declarations, async/yield, Ruby modifier roles,
TSX path selection, invalid bytes/parse recovery and persistent snapshot roundtrip.
No accepted original replay, models, CPU/CI/archive loops or global M5 acceptance.

Outcome: stage API implemented with syntax-only completeness. Frozen42 reference
72907 SHA ad1ff86907c7ab717fe00c2d7e2db8996aa2ba9691da076f7512efd48e51cfbc;
review1 reference1909 SHA f72b663a53a4faf339f2939530a4c9b56af84a556aa810a55a6433d3f373d63a.
Original observations are distinct; no accepted replay. A fresh read-only review
found missing parameter bindings in Rust impl ownership and quadratic sibling role
lookup. Both RED→GREEN; role cursor traversal plus relevant Rust parameter names,
20,000 sibling process budget10s. One fix pass, no re-review/deferred findings.
Final grouped tests syntax38 + program12 + store6 GREEN; strict Clippy all-targets
these three crates GREEN, fmt GREEN; Python compilation of updated host inventories
GREEN. Expected future search roots public261/Best237 (six new syntax roots), not
new global receipts. Raw/workspace preserved and push authorized.
