# Explicit symbol preferences implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. No implementer agents. One fresh final scoped reviewer, no re-review.

**Goal:** Complete query requirements, catalog test identity and stable symbol preferences for later SymbolRanker composition.
**Architecture:** symbol_requirements owns query interpretation; symbol_preferences owns evidence preference order and catalog test identity. Existing intent/source catalog own their contracts; operation observation remains separate.
**Tech Stack:** existing Rust1.95/Python3.12.9/PythonText/onig/serde; no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-25-rust-symbol-preferences-design.md.

## Global constraints

- Linux x86_64 only; preserve1066frozen files and all accepted originals/receipts.
- New first capture before Rust APIs; never recapture old corpora/model histories.
- Stable passes operations→tests→operators; preserve all candidates.
- Scalar EntityKey remains unchanged; lossless query/implementation PythonText.
- Full OperationWitnesses/SymbolRanker/PieceSearch/M4/global remain pending.
- Existing isolated branch, inline execution and push authorized; keep raw local.

## Review focus

- Negation/punctuation/casefold and Python regex word/space boundaries preserve explicit intent.
- Purpose and helper/test-double ambiguities match original; shared TEST_OBJECT has one home.
- Test identity reads authenticated snapshot, excludes nested callables, preserves Java12line/brace boundary.
- Stable preference precedence, wildcard causes and unknown witnesses never lose membership.
- Invalid shapes/orders fail before indexing; probes contain inputs only and clean-checkout tests need no local frozen tree.

### Task 1: Independent observations

Files:tools/rust_migration/symbol_preferences_reference.py,new immutable fixture,
tests/rust_migration/test_symbol_preferences_reference.py.
Interfaces:cases(),capture(Reference,out),validate_reference.
- [ ] Write validation tests; REDmissingfixture then first capture original neutral
  pure policy and real catalogs before Rust; selected disjoint pure original tests.
- [ ] Authenticate observer/input/result/source/runtime/test roots, refuse recapture;
  GREEN scoped tooling and commit. Retain all raw locally.

### Task 2: Native requirements and preferences

Files:crates/ken-retrieval/src/{symbol_requirements,symbol_preferences}.rs,
intent.rs shared TEST_OBJECT,lib.rs,tests/symbol_preferences.rs,
examples/symbol_preferences_probe.rs.
Interfaces:requirements,SymbolRequirements,is_test_case,apply_symbol_preferences.
- [ ] Representative typed caller frozen-fixture tests REDmissingAPIs, then implement
  interpretation/catalog identity/stable preference passes; GREEN. Validate malformed
  collaborator shapes/orders separately; complete native suites/fmt/strictClippy.
- [ ] Input-only native probe for all new cases; original owns observations, native
  computes results. No source-operation observer stub or fullsearch acceptance claim.

### Task 3: x86 validation and closure

Files:tools/rust_migration/symbol_preferences_host.py,new scoped host tests,
x86 runtime workflow,current native-root inventory, migration docs.
- [ ] Scoped protocol/audit/fixture/request/output tamper tests RED→GREEN;
  execute full current x86 stack and new policy probe without original recapture.
- [ ] Commit/push actualcandidate CI,one fresh final review,at mostoneImportant
  RED→GREEN repair pass,no re-review; authenticate Git/snapshots/isolatedarchive
  replay. Close only preference capability and document remaining observers/search.
