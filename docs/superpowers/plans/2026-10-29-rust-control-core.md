# Native structured control core — M5a/M5c foundation

Goal: generate structured CFG and lexical control evidence from the persisted
source-operation IR, before expanding public adapters or rewriting every frontend.
Spec: docs/superpowers/specs/2026-10-18-rust-migration-design.md. Linux x86_64 only.
Core→outwards user priority; one implementation batch and grouped validation,
one fresh read-only review. Preserve Python/originals/workspaces; push authorized.

Concepts in ken-program/control: operation graph indexes; lexical execution
(possible/unreachable/unknown); syntax contexts (parent/loop/handler/try); builtin
exception admission/shadowing; completion routing (finally scopes and pending
exits); structured CFG builder (branches/loops/dispatch and explicit coverage).
No parser/model/transport coupling in CFG; Python import shadowing uses the
already-locked native Ruff parser with Python3.12 admission, not token guesses.
Reuse native IR attributes/types and add facts without changing syntax membership.

Use: lexical_execution(&mut ir, invalid), structured_control(&mut ir,
optional_diagnostic_paths), syntax_contexts(&mut ir), then persist/publish using
StructuralStore. Every generated fact retains original ordering/provenance;
partial coverage, exception/generator exclusions and gaps remain explicit.

Preserve original statement routes, limits64/32, finalizer continuation scope,
return evaluation/completion separation, except* subgroup routing, exception-name
shadowing and invalidation, loop else/break/continue, do/for/range distinctions,
JS/TS hoisting, Rust wrappers, unsupported controls and parse-diagnostic coverage.
CFG routes are structural possibilities, never feasibility/runtime proofs.

- [x] Observe fresh original IR→execution/CFG/contexts cases and builtin exceptions.
- [x] Implement native indexed control kernels and completion/exception routing.
- [x] Validate exact new original evidence and native store roundtrip in a batch.
- [x] One final review/fix pass, documentation and commit/push.

The full source frontend/declaration/semantic linker, instruction lowering/query
compiler and graph-segment publication remain separate core slices. This block
must not claim complete frontend production, M5 acceptance or KQL execution.

Validation: ken-program all targets12 roots; ken-store structural_store5 +
control_pipeline1 roots; locked/offline, strict Clippy all targets program/store,
fmt check. Exact 23 new cases across nine languages and roundtrip; no original
replays/models/CPU matrices/CI. Review found nullable/noninteger CALL span lookup
and location-map retention. Regression RED→GREEN, numeric key compatibility,
release temporary map before ancestry; one final native batch all GREEN.
No deferred findings. New core roots5 are separate from public255/Best231 gates.
