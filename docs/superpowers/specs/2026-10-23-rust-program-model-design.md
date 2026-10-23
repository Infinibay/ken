# Native common program model — M3d

Continues the approved whole migration with native inline execution, preserved
originals, no confirmation pauses and reuse of unchanged accepted evidence.
M3c closed at f53687a3. Its FILES SHA is
3779ac933aacc766c9372b8e623c4314bd5b65a31bb65735177ba2fa7aa6db6f.

## Purpose and representative use

Convert the existing ordered structural IR into an immutable source model with
stable local node identities, lexical scopes, declarations, references, argument
positions and conservative availability. This is M3's common-model requirement.
The original owners are common_ast/{model,normalize,kinds,symbols,environment,
boundaries}.py and structural/{model,type_refs}.py.

```rust
let ir = StructuralIr::from_json(original_ir_json)?;
let program = normalize(&ir)?;
program.validate()?;
let restored = Program::from_json(&program.to_json()?)?;
assert_eq!(restored, program);
let found = Environment::new(&program).resolve("value", scope, byte_position)?;
let bodies = body_ranges(&program);
```

Source-to-structural-IR lowering, project linking, FactIndex/query engines and
structural SQLite persistence belong to M5a/M5b. This plan does not claim a native
replacement for common_ast.parse until native lowering is connected there.
The incremental M3 indexer consumes ParsedFile and imports independently.

## Concepts and ownership

- StructuralIr is the versioned ordered input graph (1.88.0). Entity insertion
  order, operations, facts and arbitrary attribute payloads survive decoding.
- Program is the common-ast/1 value, owning nodes/scopes/symbols/references/links,
  diagnostics, original validation and serialization defaults.
- TypeRef classifies annotation syntax, retaining native spelling, nested
  arguments, qualifiers, extent/rank and integer/float distinctions.
- Normalizer owns ordered preorder traversal, subtree intervals, kinds, scope
  introduction, argument metadata and canonical links.
- LexicalBindings owns declaration creation and per-language binding policy;
  import bindings form a focused collaborator. Reference creation uses the same
  Environment as public lookup; availability remains separate from identity.
- Environment owns global/nonlocal directives, visibility, overload ambiguity,
  execution boundaries and conservative initialization state.
- BodyRange owns branch-specific syntactic membership independent of flow exits.

A focused ken-program crate holds these concepts and depends only on existing
serde/serde_json/regex/thiserror plus ken-text if lossless text is needed. Core
imports remain independent of program semantics. No new third-party versions.

## Choices and compatibility

Chosen: normalize the actual persisted IR boundary now, then reuse it in M5a.
Porting the entire structural frontend/query engine together would obscure the
common model's independently testable contract; retaining Python normalization
would violate native execution. This boundary gives a complete native capability
without pretending the structural producer has migrated.

Preserve operation dictionary last-value/first-position behavior, source sibling
sort(start,-end,id), root handling, ordered entity span winners, operator fact
ordering, all source fields/flags, unknown kinds and diagnostics. Reject invalid
rooted forests; never return partially normalized success. Preserve Python class
lookup skipping, defaults/comprehension outer evaluation, JS var/TDZ, Rust shadow
visibility, Ruby closures, import aliases, receiver positions, conditional/dynamic
availability and unresolved/member-dispatch reasons. Keep argument source order
and loss of positional certainty after expansion. Canonical links are deduplicated
and sorted by source/relation/ordinal/target.

Program validation reproduces the actual Python validator, not typing.Literal
restrictions that Python does not enforce. Wrong versions, invalid ids/intervals,
ancestry, scopes, symbols/references/links fail explicitly. Do not require child
byte containment or nonnegative ordinals where the original validator does not.
Type annotation Unicode word classification follows the frozen Python Unicode
version, not the host Rust Unicode release. Type recursion>32/length>10000 stays
opaque as originally. Ignored IR attributes must not invalidate unrelated nodes.

## Evidence and exit criteria

Capture actual normalize inputs and complete outputs through existing pure
common-AST tests and type-reference tests, instrumenting the preserved reference.
Capture Environment lookup outputs, BodyRanges, codec successes/errors and nested
TypeRefs. Exercise a direct original malformed-IR/codec corpus and ordered duplicate
cases where normal tests leave gaps. Vocabulary tables may be generated from the
original with source hashes; they are static language data, never precomputed
program outputs used by the native implementation.

Native callers and outside-checkout input-only probes compare complete ordered
results/errors on macOS arm64 and Linux aarch64. Empty PATH, loader audits and
Linux exec/connect trace demonstrate native execution. Original captures run once
per platform then cache. Reuse M0–M3c histories; do not rerun model inference or
parser/reference suites. Affected Rust tests, fmt/clippy and tooling tests must
pass. Authenticated compressed receipts reject altered source/input/output,
missing platforms, dropped errors/cases and false gate summaries. All1066original
hashes stay intact. One fresh whole-plan review, one Important/Critical TDD fix
pass, archive ledger/rulings/minors and clean only this completed workspace.
Acceptance is M3d only; indexing/M3 and M4–M8 remain pending.
