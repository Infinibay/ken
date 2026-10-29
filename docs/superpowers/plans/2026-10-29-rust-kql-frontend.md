# Native KQL frontend implementation plan

> Use superpowers:executing-plans inline; one fresh final review, no implementation delegates.

Goal: complete typed native KQL2 syntax and explicit library/model preparation.
Architecture/spec: ../specs/2026-10-29-rust-kql-frontend-design.md.
Tech: new ken-query crate, existing ken-program/ken-text value/Unicode support,
serde and pinned Rust1.95. No models, storage, Python runtime or new dependency versions.
User's autonomous execution/large validation batches supersede skill approval
and per-step TDD cadence. Existing feature branch is the authorized workspace;
previous81-root baseline remains accepted, do not repeat before changes.

Review focus: deep/flat hostile syntax and JSON strings; contextual regex and
Unicode byte offsets; query/source AST identity and speculative rollback;
cyclic/mismatched module snapshots and lexical generic/model shadowing;
instantiation limits, source preservation and recursive expansion safety.

1. [x] Capture fresh tagged AST/repr/errors and preparation results from docs,
   catalog/test literals and new adversarial cases once, against authenticated
   frozen original. Keep journal, no original suite invocation.
2. [x] Implement Syntax/ParseError/Limits/lexer and all grammar modules in
   crates/ken-query/src; add workspace member and existing dependency edges.
   Public parse usage exercises complete query and pattern input; no scaffolds.
3. [x] Implement immutable library qualification/model signature specialization,
   ordered generated instances, explicit traversal limits and faithful AST repr.
   Include pure indexed alternative expansion and predicate SCC/stratification,
   preserving separate compiler routes.
4. [x] Group complete corpus parity, error/limits/Unicode/deep/flat/immutability
   and native integration cases, strict Clippy/fmt. No vector/model/CPU tests.
5. [x] One fresh read-only final review; Important/Critical RED→GREEN in one
   pass, whole affected suite, docs/justified memory, commit/push.

Outcome:12 native roots passed, including full tagged original parity and a
red→green public allocation regression; strict Clippy/fmt passed. One fresh
review, one Important fixed, no Critical/Minor. See the handoff for capture pins,
resource compatibility boundary and remaining compiler/runtime scope.
