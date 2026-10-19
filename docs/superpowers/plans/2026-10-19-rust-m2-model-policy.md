# Native model-selection policy implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, task-by-task. Preserve the selected native method. Steps use checkbox syntax; one final fresh reviewer, no implementer agents.

**Goal:** Preserve original model/prompt decisions without loading inference or repinning existing vectors.
**Architecture:** A pure ken-models policy consumes explicit facts/config snapshots. An independent frozen-original oracle fixes outputs before Rust implementation. A native JSON process and composed gate certify the current cut.
**Tech Stack:** Existing Rust1.95/serde/Unicode15 owner and Python validation tools; no new product dependency.
**Spec:** docs/superpowers/specs/2026-10-19-rust-model-policy-design.md

## Global Constraints

- Preserve all1066 originals, installed entrypoints, user indexes and unrelated work.
- Native inline continuous execution; no new stage-confirmation pauses.
- ModelPolicy owns decisions, not SQLite/config I/O, backend factories or process globals.
- A logical presence fact includes inline OR sidecar file vectors; unknown storage never proves empty.
- Preserve exact user strings/prompts and missing-vs-empty marker distinction.
- Python15 whitespace comes from the existing authoritative owner; no duplicate tables.
- All28 gates/current26 fingerprints/BOTH registered ARM platforms required; M2_accepted=false.
- Keep previous timeouts, expectations, original-baseline comparison and no missing-model skips.

## Review Focus

1. Empty recorded metadata must not be mistaken for absent metadata; zero/negative sidecar slots and empty inline BLOBs still imply existing vectors.
2. Whitespace-only user defaults differ from nonempty environment/forced overrides; preserve NUL, zero-width and outer whitespace bytes without normalizing model IDs.
3. Forced process choice must affect active selection but never project resolution; independent or simultaneous policies must not leak state.
4. Prompt matching must retain case, prefix boundaries and exact instruction/newline/trailing spaces, while unknown names remain symmetric without backend aliasing.
5. Missing forwarded probe inputs, wrong/stale executables or altered current/nested proof must fail acceptance; logical fixtures cannot certify storage writes or inference.

### Task 1: Freeze independent original decisions and prospective pins

**Files:** create tools/rust_migration/policy_reference.py,
tests/rust_migration/test_policy_reference.py,
docs/validation/rust-migration-2026-10-19/m2-policy/{cases,reference}.json.
**Interfaces:** policy_cases()->list[dict]; policy_prompts()->list[str];
capture_policy(reference:Reference,out:Path)->dict. Record cases with id/input/
source_setup; input contains user_config, environment, project_visible, facts
and forced variants. Native receives only id/input; source_setup controls real
original rows. Expected outputs come only from actual original functions.
- [ ] RED test_cases_cover_source_storage_and_override_boundaries imports the
  missing module and verifies1292 distinct histories,1280 Cartesian
  plus12 named specials: default_model Boolean/list/object/NUL/control/outer-NBSP,
  env-control, stored-NUL, empty-inline, sidecar-zero, sidecar-negative, NULL-meta.
  Six forced variants are None,"","forced/model"," ",U+001C,NUL.
  Cartesian configs: null,{},empty default,whitespace default,outer-space valid
  default,zero-width default,legacy default,integer default; env None/empty/custom/
  space; stored None/empty/custom/legacy/space; vectors neither/inline/sidecar/both;
  discovery false/true. Assert frozen source import, no encoder singleton, genuine
  logical rows unchanged by selection and observed fresh-pin delta after configure.
  test_capture_uses_real_frozen_policy_without_loading_an_encoder checks source
  provenance and all observations. test_missing_empty_and_existing_vector_markers_preserve_original_pin_decisions
  checks literal selected names/pins. test_capture_rejects_incomplete_reference_before_output
  supplies an empty reference root and requires failure before any output.
  NULL-meta special starts with document-space marker9 and an unrelated key;
  capture the actual overwrite to2 and preservation of the unrelated key.
- [ ] Implement real isolated marker/SQLite/config child and reference integrity
  checks. Prompt corpus includes exact three prefixes, suffixes, mixed case,
  misleading embedded prefixes and symmetric IDs. No native import or generated
  expected policy algorithm; capture actual results and configure metadata delta.
- [ ] Run .venv/bin/python -m pytest tests/rust_migration/test_policy_reference.py -q.
  Expected all pass after observed missing-module RED. Capture BOTH originals and
  require equal logical outputs/IDs/prompts while preserving their runtime stamps.
- [ ] Commit oracle/tooling/fixtures only; no native policy implementation yet.

### Task 2: Implement pure owned Rust model and prompt policy

**Files:** create crates/ken-models/src/model_policy.rs,
crates/ken-models/tests/model_policy.rs,
crates/ken-models/examples/model_policy_probe.rs; modify src/lib.rs.
**Interfaces:** all public types/signatures exactly as Spec Interfaces; public
module model_policy. No new deps, DB reader, config writer or encoder instance.
Probe stdin: {cases:[{id,input}],prompts:[str]}; stdout actual per-case recommended,
project resolution/prospective pin, upgrade and forced-variant active results,
prompt pairs/asymmetry. Include version/Unicode/runtime-needed=false identity;
strict request shape/types, distinct IDs, no expectations in probe.
- [ ] RED frozen_original_histories_match_model_and_initial_pin_decisions and
  exact_original_prompts_preserve_prefixes_case_and_whitespace import the missing
  module and compare every frozen
  history/prompt. Direct regressions assert sidecar logical presence retains
  legacy, present-empty prevents pin, raw overrides retain whitespace/NUL,
  validated defaults preserve outer spaces, forced precedence is separate,
  legacy-to-same-legacy upgrade is preserved. Returned results/config own data;
  multiple concurrent instances remain independent. Unknown names have no alias.
  Name the ownership/concurrency checks policy_snapshots_and_results_are_owned_and_independent
  and forced_and_environment_overrides_do_not_leak_between_threads.
  known_vector_presence_never_gets_a_fresh_pin covers conservative pin plans.
- [ ] Implement from outside-in callers using existing python_unicode::space.
  No environment/file reads or global model state; prospective pin is a value.
  Add actual JSON probe using these same methods and no model artifacts.
- [ ] Run cargo test --locked -p ken-models --test model_policy, cargo fmt --check
  and workspace all-target Clippy; Expected all pass after RED. Compare exact
  native outputs against Task1 fixtures. Preserve prior core/model fixtures.
- [ ] Commit policy/probe/tests, then task-done with the named policy tests.

### Task 3: Prove standalone process and current both-platform28gate acceptance

**Files:** create tools/rust_migration/{policy_compare,policy_validate}.py,
tests/rust_migration/test_policy_{compare,validate,inputs}.py,
migration_tests/test_policy_parity.py; modify preparation.py and all prior
validate/model/table/context/ettin/translation validators, rust-models.yml, guide,
public evidence. Extend shared fingerprint inputs for policy cases/oracle.
**Interfaces:** policy_environment(probe:Path|None=None)->dict validates an explicit
absolute path (typed override or KEN_POLICY_PROBE), never invents one. Add optional
keyword policy_probe:Path|None through prior validators/_validation_environment.
compare_policy(reference,probe,out)->dict; validate_policy composes26+2=28;
aggregate_policies requires both current receipts and exact26 fingerprints.
- [ ] RED comparator mutations: wrong recommendation/selected model/pin/upgrade/
  forced order/prompt bytes, int-vs-float/bool type damage, extra/missing/reordered
  IDs/fields, model-runtime dependency, process failure/stderr/extra exec, stale
  source/binary/platform/oracle, missing propagated probe, altered nested26 proof.
- [ ] Implement independent fresh original replay and native copied process outside
  checkout/sentinelPATH without model-data env. Audit dependencies/no Python;
  Linux actual1exec; preserve real outputs/logs/measurements. Exact JSON primitive
  types matter (True!=1,2!=2.0). Bind probe to fresh release and recursive prior proof.
- [ ] Run all tooling/process tests, then freeze candidate and execute complete
  BOTH platform28 gates. Prepare all current models and test binaries first;
  preserve unchanged runtime limits. Expected all gates ran/passed, no new Python
  baseline failures/skips/missing IDs/type errors, no Rust failures/ignored tests,
  unchanged original1066 hashes and matching current26 input fingerprints.
- [ ] Publish real receipts/current matrix; Expected Policy_accepted=true,
  M2_accepted=false. Commit only own files; task-done executes printed matrix CLI.
- [ ] One fresh whole-plan most-capable reviewer, all5ReviewFocus verbatim and ledger
  rulings; one Critical/Important TDD correction pass, no rereview, defer Minors,
  rule every declined scope with cost. Accept only this cut; continue whole migration.

## Pre-flight/self-review

T1 cases/results feed T2 fixture tests and T3 comparison. T2 probe/API feed T3
release/process binding. policy_probe must reach nested test environments without
leaking into frozen-original children. Existing fixed Unicode owner is reused;
no independent whitespace implementation. Prospective pins never imply storage
write acceptance. Full prior26 proof is re-executed for the new source; no stale
matrix reuse. Spec coverage is complete within this pure policy boundary.
