# Python operation witnesses implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. One final fresh read-only reviewer, no implementer agents or re-review.

**Goal:** Complete Python operation observations and compose the original observer router.
**Architecture:** Catalog owns immutable inputs; Python AST adapter owns syntax/equality; backend owns observations/caches; router owns dispatch.
**Tech Stack:** Rust1.95/Python3.12.9, pinned rustpython-ruff0.15.8, existing Unicode15/PythonText/GrammarCatalog.
**Spec:** docs/superpowers/specs/2026-10-27-rust-python-operation-witnesses-design.md

## Global constraints
- Linux x86_64 only, no original/model/tolerance/accepted-fixture changes.
- No original pytest recapture, native Python interpreter/library/subprocess or raw-CST approximation.
- Preserve1066sources and every raw/workspace locally outsideGit; authorized migration branch/push persists.
- Complete scoped behavior; SymbolRanker/PieceSearch/M4/global remain pending.

## Review focus
- ast.dump equality preserves contexts, Unicode literal kind, bytes/numbers and f-string shape.
- Whole-file admission matches Python3.12, including Unicode15 identifiers and modern syntax rejection.
- Root selection preserves normalized AST name versus raw catalog key and ambiguous extents.
- Invocation excludes nested classes; direct traversal excludes deferred nodes but observes root class bodies.
- Snapshot triples inspect only adjacent AST statements in body/orelse/finalbody; no comments or unrelated blocks enter adjacency.

### Task 1: Independent Python observations
Files:tools/rust_migration/python_witnesses_reference.py, tests/rust_migration/test_python_witnesses_reference.py, new compressed fixture.
Interfaces:cases(),capture(Reference,out),validate_reference(value).
- [ ] RED missing observer/corpus; first full original capture using real catalogs and explicit synthetic extents where needed, before native implementation. No pytest invocation.
- [ ] Authenticate complete1066inventory/observer/runtime/inputs/outputs, refuse overwrite, tamper tests GREEN and commit.
Expected: scoped tooling passes; original data remain unchanged and retained.

### Task 2: Native Python backend and router
Files:Cargo.toml/Cargo.lock, crates/ken-syntax/src/lib.rs and python_literal.rs; crates/ken-retrieval/src/python_operation_witnesses/{mod,ast,expression}.rs; operation_witnesses.rs/lib.rs; tests/python_operation_witnesses.rs; example/probe support.
Interfaces:PythonOperationWitnesses::new(Arc<SourceCatalog>), OperationWitnesses::new(Arc<SourceCatalog>,Arc<GrammarCatalog>), for_owner->SourceResult<BTreeSet<String>>.
- [ ] RED full corpus/canonical-owner/cache/unsupported/router callers; pin native parser and expose existing lossless literal decoder through a focused API.
- [ ] Implement Python3.12 AST admission/equality and original observations; GREEN all cases and representative preference composition.
- [ ] Input-only native probe; full affected native suites, fmt/Clippy and dependency/license closure.
Expected: exact original observations without native Python use; strict suites pass.

### Task 3: Host validation and closure
Files:tools/rust_migration/python_witnesses_host.py, protocol tests, model workflow/inventory counts, handoff.
- [ ] RED tamper/host gates→GREEN; immutable-source full local and x86CI chain with all prerequisites.
- [ ] One final review/one Important fix pass; sealed Git-authenticated archive and isolated replay; document scoped acceptance/remaining work, commit/push.
Expected: source-bound actual local/CI/probe evidence and isolated replay pass, no global completion claim.
