# Verified x86 execution references implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. No implementer agents; one fresh final read-only reviewer, no re-review.

**Goal:** Close x86 numerical validation using independent full-corpus original references selected by verified execution profile.
**Architecture:** actual capabilities/BLAS identity → immutable registry → original reference; numerical callers remain unchanged.
**Tech Stack:** Rust1.95/Python3.12.9, existing SHA/serde/libloading/flate2, no new dependencies.
**Spec:** docs/superpowers/specs/2026-10-25-rust-execution-profiles-design.md

## Global constraints
- Linux x86_64 only. Preserve1066frozen files, alllegacyoracles, tolerances/models.
- Full original20context/245alignment before native selection; no old pytest-root recapture or native answers.
- Unknown/ambiguous profiles reject, never fallback by architecture/model name.
- BLAS one-thread policy is validation-only; production math unchanged.
- One local and bounded4remote first-profile captures; preserve all and reject descriptor collisions.
- Source snapshots include all profile data/helpers; independent native detection, archived recorded identity.
- Existing migration branch/push/keep-local authorization persists; no main/release.

## Review focus
- Capability mask reflects effective OS-supported execution, not marketing name.
- Reference selection cannot look at candidate numerical results.
- Unknown/changed/ambiguous descriptors, reference bytes and runtime pins reject.
- New original capture is full-corpus, independently sourced, immutable and not a re-labelled native output.
- Archive replay preserves remote profile identity and source closure instead of detecting the replay host.

### Task 1: Original profile captures
Files: shared std-only CPU capability source/probe under ken-models/tests/support;
Python profile capture tools/tests; optional profile-capture mode in existing workflow.
- [ ] RED missing capability/capture protocol; implement effective feature probe,
  authenticated original20/245 observers, one-thread metadata, strict validation and no-overwrite; GREEN.
- [ ] First local capture, bounded4CI captures from restored immutable1066source,
  inspect/authenticate all, retain originals before native selector implementation.

### Task 2: Immutable profile registry and native callers
Files: profile data/index; shared test-support registry; dense_math identity;
context_encoder/alignment tests; Python registry/host preparation.
- [ ] RED actual-profile/unknown/tamper/native caller tests; import original data,
  reject conflicting descriptors, add native BLAS identity and independent typed selection; GREEN.
- [ ] Context20/alignment245 and existing edges, strict native suites/fmt/Clippy;
  no tolerance or arithmetic changes.

### Task 3: Integration and closure
Files: context_host/workflow/source snapshots; scoped tooling tests; handoff.
- [ ] RED profile host/packet/source tamper tests→GREEN; full pinned local and x86CI
  chain on immutable sources, no ignored numerical failures.
- [ ] One final review/one Important pass; Git-authenticated source and raw receipt,
  sealed isolated replay, truthful scoped acceptance and remaining migration work; commit/push.
