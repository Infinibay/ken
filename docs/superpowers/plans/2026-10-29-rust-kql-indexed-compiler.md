# Native indexed KQL2 compiler implementation plan

> Use superpowers:executing-plans inline; one fresh final reviewer, no implementer delegates.

Goal: complete checked indexed plans and BODY preparation, preserving original
observables. Spec: ../specs/2026-10-29-rust-kql-indexed-compiler-design.md.
Existing authorized workspace codex/rust-migration; no new worktree or repeated
accepted baseline. Linux x86_64, Rust1.95, existing dependency versions only.
Original1066 auth before/after new observations, no parser/preparation replay.
User's larger/fewer validations supersede per-edit TDD and approval cadence.

Review focus: list/tuple/dict fingerprint framing and wide integers; private and
quantified role scopes, recursive/cross-declaration use; failed BODY captures and
nested outputs/anchor flags; flat or deep resource amplification; diagnostics
wrapped at the same source boundary. Tests cover each at public native entries.

1. [x] Capture tagged indexed Program/BODY outputs/errors and immutable vocabulary
   from accepted prepared ASTs plus fresh focused cases. Journal each once.
2. [x] Add checked-plan records/repr and capability vocabulary. Implement typed
   scalar/domain checking and source matcher validation in focused modules.
3. [x] Implement indexed lowering and checks, hygiene/existentials/exact inventory,
   step/join bounds and original fingerprints; compose indexed branches with
   global limit and original aggregate hash. Complete BODY source/call/control
   checking and output planning; no runtime scaffolds.
4. [x] Group pinned parity plus native resource/scope/immutability cases, Clippy
   strict and fmt. Targeted reruns only for actual failures.
5. [x] One fresh final review, Important/Critical RED→GREEN fixes in one pass,
   affected suite, handoff/justified memory and authorized commit/push.

Outcome:25 affected native roots green, strict Clippy/fmt green;534 indexed and
670 BODY observations preserve plans/repr/fingerprints/errors/roles. Single fresh
review found5 Important, all reproduced red and fixed in one pass. Allocation
regressions: rejected expansion1839935→134699, wide gap271903→6178. Native work
budget counts actual remapping/materialization, not just use statements. No
relational/runtime/public-switch or global qualification claim. See handoff.
