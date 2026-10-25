# Linux x86_64 contextual model test plan

Use superpowers:executing-plans inline. User authorized Linux x86_64, continued
migration and pushes to codex/rust-migration. Preserve local evidence and originals.
Spec: docs/superpowers/specs/2026-10-24-rust-x86-context-design.md.
Base:26ec740d, after accepted CPU-core sourceece7a0c6.

## Review focus

- Never select Linux/aarch64 observations merely because the current OS is Linux.
- The new consumed fixture must match the actual already captured original bytes.
- ARM selection and unknown-target rejection must remain explicit.
- Do not weaken vector tolerances, fixed20histories, source hashes or lazy checks.
- No full-model/index/M4 acceptance from this single contextual capability.

## Task 1: Characterize the host guard and preserve the original

- [x] Actual original20histories and4original scoped tests captured once; initial
  native input-only20history experiment PASS. Preserve original/transport hashes.
- [ ] Run existing production contextual root with actual x86 weights/core before
  edits. Expected RED at the aarch64 guard, not missing-data setup.
- [ ] Add a test-private selector invariant test before implementation: exact
  supported original metadata, same fixed20cases, immutable x86 fixture SHA and
  unknown/crossed target rejection. Expected missing-helper/fixture RED.

## Task 2: Consume the own-host original and execute native parity

Files: crates/ken-models/tests/context_encoder.rs, its consumed JSON fixture,
tools/rust_migration/context_host.py, tests/rust_migration/test_x86_context_evidence.py
and the existing three-host runtime workflow. Reuse parent core snapshots plus
bounded contextual registration/reference/spec/plan support. No production API
or dependency changes.

- [ ] Copy exact observed JSON bytes; select only the actual OS/architecture.
  Keep original ARM paths and explicit unsupported-target rejection. Existing
  history/model comparison code and numerical bounds stay unchanged.
- [ ] Run all contextual native roots with real production weights and the
  authenticated standalone ORT. Expected complete GREEN, no skipped roots.
- [ ] Fresh native input-only execution against the reused original, source and
  binary/resource fingerprints, actual Linux exec/connect/loader audit. No
  recapture. Requirefmt/strictClippy and affected complete tooling/regressions.

## Task 3: Review and record the capability

- [ ] One fresh final whole-plan reviewer; rule on all findings and declined
  behaviors, one Important/Critical RED→GREEN repair pass if needed, no re-review.
- [ ] Authenticate source/tooling/gates and archive/replay the scoped receipt.
  Keep raw local; update handoff with exact capability and remaining models/index.
- [ ] Commit/push to the authorized migration branch; continue remaining x86
  model/oracle requirements. Never claim complete M2/M3x86 or M4/global here.
