# Native syntax operation witnesses implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. No implementer agents. One fresh final scoped reviewer, no re-review.

**Goal:** Complete the original Java/JS/TS operation-observation backend on authenticated x86 native grammars.
**Architecture:** SourceCatalog owns snapshot authority; GrammarCatalog owns parsing; SyntaxOperationWitnesses owns cached body observations. Python AST and the full observer router remain separate capabilities.
**Tech Stack:** existing Rust1.95/Python3.12.9/ken-syntax/serde; no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-25-rust-syntax-operation-witnesses-design.md.

## Global constraints

- Linux x86_64 only; no original/model/tolerance changes or recaptures.
- Preserve1066frozen files and previous scoped receipts; keep raw local/untracked.
- Observe canonical catalog snapshots; never current disk or nested callables.
- Preserve exact CST root selection/recovery and Python whitespace raw comparison.
- Python/fullOperationWitnesses/SymbolRanker/PieceSearch/M4/global stay pending.
- Existing isolated branch, inline execution and push authorization persist.

## Review focus

- Body/root extent selection is identical, including ties, getters, constructors and absent bodies.
- Nested callable exclusion differs from class exclusion; preserve original behavior.
- Parenthesis/target matching removes Python whitespace even within literals; no AST reinterpretation.
- Snapshot parsing and owner caches remain independent of later disk or caller mutation.
- Unsupported Python/JSX is explicit backend rejection; input-only probes and grammar resources are authenticated.

### Task 1: Independent CST witness observations

Files:tools/rust_migration/syntax_witnesses_reference.py,new fixture,
tests/rust_migration/test_syntax_witnesses_reference.py.
Interfaces:cases(),capture(Reference,out),validate_reference.
- [ ] Validation caller REDmissingfixture, first original capture with real catalogs
  and four disjoint original test roots before native implementation; no observer
  substitution. Authenticate inputs/script/outputs/runtime/frozen fingerprint.
- [ ] Refuse recapture, GREEN scoped tooling, retain raw/fixture and commit.

### Task 2: Native syntax witness backend

Files:crates/ken-retrieval/src/syntax_operation_witnesses.rs,lib.rs,
tests/syntax_operation_witnesses.rs,example syntax_witnesses_probe.rs.
Interfaces:SyntaxOperationWitnesses::new, supports, for_owner -> SourceResult<set>.
- [ ] Frozen observations, scope/extent/cache/unsupported callers REDmissingAPI.
  Implement exact traversal on verified grammars and immutable snapshots; GREEN.
- [ ] Input-only native probe plus complete affected native suites/fmt/strictClippy;
  strong admission and grammar failures remain typed errors, no Python stub.

### Task 3: x86 executor and closure

Files:own host/tooling tests; scoped profile sequencing/workflow; migration docs.
- [ ] Gate/protocol/tamper tests RED→GREEN, immutable-source local/CI execution
  of all actual parents and complete native inventory; no original recapture.
- [ ] One fresh final review and at mostoneImportant repair pass,no re-review.
  Git/snapshot/archive authentication and isolated replay; preserve contextual
  variability evidence if it recurs. Commit/push scoped capability and limits.
