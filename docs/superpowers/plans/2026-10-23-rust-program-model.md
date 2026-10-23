# Native Common Program Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, inline as authorized by the user. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver native common-ast/1 normalization, codec, annotation types, lexical lookup and body ranges with complete original comparisons.

**Architecture:** ken-program consumes ordered structural IR and owns pure program semantics. Normalization creates nodes/scopes, LexicalBindings declares names/imports, and Environment resolves references. Transport/proof tooling stays outside domain code; original producers remain validation oracles until M5a migrates them.

**Tech Stack:** Existing Rust1.95/edition2024, serde/serde_json(raw_value)/regex/thiserror; optional existing ken-text. Python3.12.9/pytest for preserved-reference tooling. Same macOS/Linux native environments.

**Spec:** docs/superpowers/specs/2026-10-23-rust-program-model-design.md.

## Global Constraints

- Branch codex/rust-migration; no original changes/deletion, no reset/stash/user-dirt commits.
- Native inline, continuous tasks without confirmation. Source lowering/linking/query/persistence deferred to their real owners; no Python runtime fallback.
- StructuralIR1.88.0; common-ast/1. Full ordered fields/errors/availability preserved.
- No new third-party versions or weakening assertions/quality gates. Type recursion>32/length>10000 yields opaque.
- Actual macOS arm64/Linux aarch64 gates and1066guard. Reuse prior models/source/parsers/imports proofs; no original-suite recapture for unchanged inputs.
- Each task TDD RED→GREEN and scoped commit. One fresh whole-plan reviewer at the end; one Important/Critical repair pass, no rereview.

## Review Focus

1. Duplicate entity/operation keys and equal-span order must retain Python winner semantics, not serde's lexical map order. T1/T3 direct originals.
2. Invalid forests, inconsistent ids/ancestry and malformed codec payloads must fail; do not impose extra restrictions on otherwise accepted values. T1/T3 negative corpus.
3. Python defaults/global/nonlocal/class scopes, Rust initializer shadowing and JS TDZ/hoisting must preserve identity and availability independently. T4 actual original lookups.
4. Expanded/named arguments, receiver ordinals and conditional/dynamic scopes must preserve uncertain positions and availability. T3/T4 complete source corpus plus direct edges.
5. Unicode annotation syntax, nested types/qualifiers/limits and ignored non-scalar IR attrs must retain spelling/unknowns without invalidating unrelated semantics. T1/T2 original edge corpus.

## Files and dependencies

New crate crates/ken-program: src/{lib,ir,model,types,kinds,normalize,environment,boundaries}.rs;
src/bindings/{mod,declarations,imports}.rs as needed for coherent responsibilities;
tests/{model,types,normalize,bindings}.rs and fixtures/; examples/program_probe.rs.
Original capture/comparison/proof: tools/rust_migration/program_{reference,validate,evidence}.py;
tests/rust_migration/test_program_{reference,validate,evidence,matrix}.py;
docs/validation/rust-migration-2026-10-23/m3-program/.
Cargo.toml/Cargo.lock add only the functional local crate.
Task1 supplies IR/model contracts to2–5;2types to3/4;3nodes/scopes to4;1–4complete programs to5.

### Task 1: Ordered IR, common model codec and independent original capture

**Interfaces:** StructuralIr::from_json(&str)->Result<Self,ProgramError> preserves ordered entities/raw attrs and checks1.88.0. Program::{from_json(&str),to_json(),validate()} uses common-ast/1; public Node/Scope/Symbol/Reference/Link retain every original field/default. body_ranges(&Program)->Vec<BodyRange> has owner/relation/root/subtree_end and final_node().

- [ ] Add failing tooling capture test for actual original common-AST/type suites and cached reuse; expected missing module. Capture full IR/program/type outputs and real test discovery/states/raw process provenance from frozen owners; original reference root verified.
- [ ] Run actual original tests once per platform, with actual SDK cache and supplements for codecs/forest/order/Unicode. Cache immutable observations for later tasks; no parsers/models suite rerun. Expected all selected tests passed, exact independently captured cases.
- [ ] Add native model tests comparing every original codec/body-range success/error, defaults and full roundtrip. Expected missing ken-program RED.
- [ ] Implement ordered IR/model/codec/body-range boundaries, contextual ProgramError; no normalization stubs presented complete. Expected all model tests pass, native fmt/clippy and1066guard.
- [ ] Commit `feat(program): preserve ordered IR and common AST codec`.

### Task 2: Annotation syntax descriptors

**Interfaces:** parse_type(annotation:&str,language:&str)->TypeRef; split_types(&str,separator:char)->Vec<String>; recursive descriptor fields kind/native/arguments/bits/signed/extent/rank/qualifiers.

- [ ] Add type tests comparing all captured original descriptors, including qualifiers/pointers, arrays/ranks/extents, generics/unions, malformed delimiters, Unicode word boundaries, whitespace and depth/length limits. Expected missing API RED.
- [ ] Implement syntax policy in types.rs using authoritative static mappings; preserve fallback nominal/opaque distinctions. Generate pinned Unicode word ranges only if actual classification requires it, with original provenance and license record.
- [ ] Run full ken-program tests plus affected tooling on both platforms. Expected complete TypeRef equality and prior model gates green.
- [ ] Commit `feat(program): normalize annotation type syntax`.

### Task 3: Ordered tree, scopes, kinds and argument normalization

**Interfaces:** normalize_syntax(&StructuralIr)->Result<Program,ProgramError> is an explicit intermediate builder used by normalize; produces exact nodes/scopes/links/diagnostics before lexical binding. Its output is not claimed final until Task4. Static kind vocabulary generated from original owner may be stored in an authenticated asset.

- [ ] Add tests comparing full original pre-binding tree/scopes/links plus invalid forests, duplicate ids/ordered equal spans, root/unknown/Unicode/default/comprehension and argument cases. Expected missing normalize_syntax RED.
- [ ] Implement kinds.rs and normalize.rs, deterministic rooted traversal with cycle/duplicate handling, subtree intervals, scoped names, flags, literal/type descriptors, argument source/effective positions and sorted unique canonical links.
- [ ] Run complete model/types/tree suite Mac/Linux, fmt/clippy/1066guard. Expected all pre-binding fields exact; malformed forests explicitly fail.
- [ ] Commit `feat(program): normalize ordered syntax and lexical scopes`.

### Task 4: Declaration policy, import bindings and lexical references

**Interfaces:** normalize(&StructuralIr)->Result<Program,ProgramError> calls the syntax builder, binding owner and final validate. Environment::new(&Program); resolve(name:&str,scope:usize,point:i64)->Result<Resolution,ProgramError>; Resolution retains symbol/status/availability/reason. No duplicate reference-resolution policy inside the normalizer.

- [ ] Add complete original-program and actual lookup tests for all captured cases. Explicitly pin hoisting/TDZ, Rust shadowing, Python directives/defaults/class/comprehension, Ruby blocks, parameter receivers, all import forms, dynamic deletion/eval and member dispatch. Expected missing final binding/lookup or mismatched full results RED.
- [ ] Implement focused declaration/import helpers and shared Environment policy. Preserve ordered declaration winners, flag sorting and all source/native/effective parameter positions. Keep unknowns conservative.
- [ ] Run full ken-program tests/affected tooling Mac/Linux, fmt/clippy/1066guard. Expected complete original Program, bodies and lookup equality including errors, no partial successful forest.
- [ ] Commit `feat(program): bind declarations and resolve lexical references`.

### Task 5: Isolated native acceptance, compact proof and final review

**Interfaces:** program_probe accepts bounded input-only IR, codec payloads, type/lookup requests and returns full observed results/errors; never accepts injected expectations. Reuse native_json process capture and existing receipt/gate validators; do not create another process harness.

- [ ] Add failing comparator/protocol/receipt tests for source/input/output changes, missing/duplicate/reordered cases, swallowed errors, altered unknowns, missing platforms and resealed false gate summaries. Expected missing APIs RED.
- [ ] Implement native probe and comparison/capture/replay, pin closed M3c FILES, record exact source snapshot and real discovered/executed test inventories. Actual copied native process, empty PATH/loader/Linux exec/connect audit.
- [ ] Run affected native/tooling gates and complete differential on both platforms, reusing cached original captures and all earlier proofs. Expected full semantics/errors exact and1066guard intact.
- [ ] Compress source/raw histories and independently replay authentic proof; exercise resealed mutations. Expected M3d-only acceptance, M3/M8 false. Commit `test(program): authenticate native common model parity`.
- [ ] Dispatch one fresh whole-plan reviewer, ledger regraded findings and declined scopes. One Important/Critical RED→GREEN repair pass plus green affected suites, no rereview. Archive review/ledger/rulings/minors before removing only this completed workspace; continue incremental indexing without confirmation.

## Self-review

One functional domain boundary, five testable tasks. IR ordering and shared
model schemas precede every consumer; type syntax precedes normalization/binding;
Environment is authoritative for both public lookup and reference construction.
Pre-binding comparisons are explicitly intermediate and final acceptance requires
full programs and original failures. Source lowering is neither duplicated nor
quietly counted complete; it will reuse StructuralIr inM5a. Existing continuous
native authorization settles workflow choices without another approval step.
