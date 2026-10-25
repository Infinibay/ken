# Native symbol relevance views implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. No implementer agents. One fresh final scoped reviewer, no re-review.

**Goal:** Supply the exact bounded second-view relevance policy and actual Ettin adapter for upcoming PieceSearch composition.
**Architecture:** PairedReranker owns paired model calls; symbol_views owns projection/admission/dedup/fallback/means/order. Existing descriptions and ONNX runtime own their current contracts.
**Tech Stack:** existing Rust1.95,Python3.12.9,serde/PythonText/flate2 and pinned ONNX1.25.1; no version changes.
**Spec:** docs/superpowers/specs/2026-10-25-rust-symbol-views-design.md.

## Global constraints

- Linux x86_64 only; original1066files/ec1/b1/2616fusion corpus remain intact.
- No fresh old20/23history capture; new component gets its own first observations.
- Whole-code64lines/12000codepoints,top10,(original+code)/2,stable membership/order.
- Whole symbols/source-operation preferences,CLI/MCP/M4/global stay pending.
- Existing isolated branch and push authorization; retain all evidence locally.

## Review focus

- Oversize views must be rejected whole; Python splitlines/codepoint boundaries include Unicode and surrogates.
- Duplicate accepted views score once, pair checks remain candidate-ordered, empty inference stays lazy.
- Scalar model adapter promotes F32 exactly and preserves model failure/metadata policy.
- Original/mean arithmetic,finite collaborator guards and stable ties preserve all candidates.
- New observations and input-only native requests remain separate from old accepted corpora and expected outputs.

### Task 1: Observe the independent symbol-view policy

Files:tools/rust_migration/symbol_views_reference.py, consumed symbol-view fixture,
new scoped tooling tests; own local preparation workspace.
Interfaces:capture(reference,out),validate_reference, fixed cases and new real-model frames.
- [ ] Characterize frozen code before implementation: neutral requirements, input
  descriptions/card scores, observed pair/score calls, projections, means/order and
  metadata. Cover64/65lines,12000/12001points,allPythonlinebreaks,surrogates,duplicates,
  empty/top10/mismatchedcounts,fallback,ties/negative/overflow; add new fusion witness.
- [ ] Capture new real Ettin first-card/second-code frames from independently
  prepared original model. Scoped original tests once, verify owners/runtime/input
  hashes and preserve raw; refuse recapture. No old corpus edit. Run tooling tests.

### Task 2: Native policy and actual paired-model adapter

Files:crates/ken-retrieval/src/{paired_reranker,symbol_views}.rs,lib.rs,
tests/{symbol_views,paired_reranker}.rs and example symbol_views_probe.rs.
Interfaces:PairedReranker/NeuralScores/OnnxPairedReranker;
complete_code_view;rank_symbol_views->SymbolRelevance.
- [ ] Representative caller and frozen-fixture tests RED missing APIs. Implement
  pure policy using existing OwnerDescription/PythonText/Unicode; preserve calls,
  exact fake results,finite collaborator guards and grouped arithmetic. GREEN.
- [ ] Adapter tests RED then GREEN with real ONNX fixture/production model,
  empty missing-resource path and scalar rejection. Input-only native probe
  computes first-card scores itself, then second views; compare new original frames.
- [ ] Complete affected ken-core/ken-retrieval suites,fmt/strictClippy; no Rust
  edits during Cargo. Commit/task-done with exact recorded source and observations.

### Task 3: x86 executor, review and scoped receipt

Files:own host validation/tooling, existing x86 runtime workflow and migration docs.
- [ ] Execute new Rust roots/probe with authenticated SDK/Ettin data; retain
  source/tooling/inputs/raw/audit and exact command/root completion. Existing core,
  context,Ettin and grammar x86 gates remain required; original capture is never CI.
- [ ] Immutable-source x86 CI,one fresh final whole-plan review and at most one
  Important RED→GREEN repair pass; no re-review. Authenticate Git/snapshots/archive
  replay. Commit/push and state scoped capability, deferred source operations/M4.
