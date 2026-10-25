# x86 numerical execution diagnosis implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. No implementer agents; one fresh scoped final reviewer and no re-review.

**Goal:** Establish and correct the demonstrated x86 numerical compatibility failure without altering frozen answers to get green.
**Architecture:** fixed diagnostic inputs → independent Python/native observations → raw command records → scoped comparison report. Runtime gates remain separate.
**Tech Stack:** pinned Rust1.95/Python3.12.9/NumPy2.4.4/ORT1.25.1 and existing native probes; no dependencies added.
**Spec:** docs/superpowers/specs/2026-10-25-rust-x86-numerics-design.md

## Global constraints

- x86 only. Frozen1066, original observations, vectors/tolerances/model bytes unchanged.
- Preserve every local/raw/workspace, including cancelled/failed CI; no main merge or installed runtime replacement.
- Actual Python APIs and native callers; input-only requests. Diagnostic success is not model acceptance.
- Two bounded CI replicas; compare baseline/current on each actual host; never re-run until green.
- Root cause before runtime correction. Explicitly label unsupported attribution and CPU coverage.

## Review focus

- A mismatch shared by Python/native must not be labelled a Rust regression.
- Missing/malformed/failed observer commands cannot silently count as a complete diagnostic.
- Native requests cannot receive expected answers from frozen observations.
- Kernel intervention runs in a fresh process before NumPy/OpenBLAS initialization.
- Baseline identity, full-vs-filtered suites and actual runner metadata refer to the executed revisions, not old hardcoded candidates.

### Task 1: Bounded independent numerical observers
Files: tools/rust_migration/x86_numeric_{diagnostic,context,alignment}.py;
tests/rust_migration/test_x86_numeric_diagnostic.py.
Interfaces: fixed_inputs(repo), record(command,request,env), context_observe,
alignment_observe, validate_report.
- [ ] RED missing observer/protocol tests; implement fixed input selection, independent
  original Python adapters, raw command records and strict report validation; GREEN.
- [ ] Local same-host native/Python observation and Haswell intervention, hashes,
  no overwrites, unchanged frozen fixtures; commit.

### Task 2: Same-runner CI and justified closure
Files: .github/workflows/rust-context-x86-diagnostic.yml; handoff and scoped receipts.
- [ ] RED workflow/coverage tests; wire two replicas and authenticated preparation,
  full/filtered baseline/candidate commands; GREEN local tooling, push/dispatch.
- [ ] Inspect every actual result, retain all observations and source identities;
  reproduce a cause before any runtime/test-contract change. One final review,
  Important repair if needed, sealed isolated replay and truthful handoff.
