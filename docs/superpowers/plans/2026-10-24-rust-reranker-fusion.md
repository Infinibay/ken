# Native Ordinal Reranker Fusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Continuation and pushes are authorized; one fresh whole-plan final reviewer, no implementation agents or routine approval stop.

**Goal:** Supply the fixed-membership ordinal fusion policy needed by future PieceSearch.
**Architecture:** One pure public function owns weight/rank validation and stable permutation. Existing proposal aggregation and neural inference retain their responsibilities.
**Tech Stack:** Rust1.95.0,serde_json test fixtures,Python3.12.9/Unicode15;no dependency changes.
**Spec:** docs/superpowers/specs/2026-10-24-rust-reranker-fusion-design.md.

## Global Constraints

Preserve all accepted original bytes and receipts. Capture only this new original scope once. Exact errors/order,one-based ranks,no tolerance or top10 restriction. Raw stays ignored;only consumed fixture enters Git. Core/retrieval full gates,fmt,strict Clippy and native ARM matrix remain mandatory. M4d/M4/global acceptance stays false;no install/merge/release/tag.

## Review Focus

1. Empty scores still validate configuration before returning an empty permutation.
2. Signed-zero/neural/fusion ties preserve native identities and order.
3. Extreme finite scores/offsets and subnormals follow original IEEE ordering.
4. Invalid weight,offset and score combinations retain original error precedence.
5. Pools above ten remain complete because membership limits belong to the caller.

### Task 1: Freeze the ordinal policy and implement its native caller

**Files:** Create crates/ken-retrieval/src/reranker_fusion.rs,crates/ken-retrieval/tests/reranker_fusion.rs,crates/ken-retrieval/tests/fixtures/reranker-fusion-reference.json. Modify crates/ken-retrieval/src/lib.rs. Local evidence in this plan workspace.
**Interfaces:** `pub fn fused_reranker_order(scores:&[f64],neural_weight:f64,rank_offset:f64)->crate::Result<Vec<usize>>`;existing RetrievalError::Invalid supplies exact original messages.

- [ ] Capture immutable Python owner source and exact12-root scoped suite,exhaustive small tied pools plus weight0/.25/.5/.75/1,offset0/tiny/60/max,empty/singleton/>10,signedzero,subnormal/extreme scores and invalid-value/precedence cases. Store complete process receipt locally and consumed expectations in fixture.
- [ ] Add public-use differential test calling the absent API on every original case,checking complete index permutation and exact error messages. Run `cargo test --locked --offline -p ken-retrieval --test reranker_fusion`;Expected missing API RED.
- [ ] Implement the pure function without model/source/project dependencies. Run the differential test;Expected GREEN. All five Review Focus conditions belong to this corpus.
- [ ] Run complete core/retrieval discovery and execution,fmt,strict Clippy. Commit the tested implementation and fixture.

### Task 2: Preserve integration gates and finish the bounded slice

**Files:** Modify tools/rust_migration/piece_evidence.py only for actual additional full-suite root count,if needed;retain existing receipt schema. Local raw/review under docs/validation/rust-migration-2026-10-24/reranker-fusion. Update handoff/guide and this plan after verification.
**Interfaces:** Existing NATIVE_ROOTS reflect current full suites;old archived validators/receipts remain frozen. Existing rust-pieces.yml executes native complete suites on Linuxaarch64/macOSarm64.

- [ ] Update expected discovery by exactly the roots added in Task1;use complete current actual gates in tooling checks. Re-capture affected native observations only where source identities changed;reuse accepted originals. Run all affected174piece tooling tests and audit actual current native packets,without rewriting historical receipts.
- [ ] Push;require both full native ARM integration jobs and preserve their raw results. No original recapture. Record exact discovered counts and all tests actually executed.
- [ ] Dispatch one fresh read-only whole-plan reviewer with spec/plan/base/head/corpus/gates. Rule on every finding and declined behavior;one Important/Critical TDD repair pass if needed,no second review.
- [ ] Preserve local original/review/verification evidence,record bounded completion and next M4dsource/symbol/piece work. Commit/push tracked status;keep M4d/M4/global pending.
