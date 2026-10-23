# Native import resolution — M3c

This subsystem continues the approved whole-migration contract after M3b's final
review and verified repair pass. The user authorized native inline execution,
continuous stages without confirmation, preserved originals and reuse of unchanged
validated evidence. This design does not promote production writers or commands.

## Purpose and boundary

Map each pending parsed import to its original indexed-file target, or classify it
as `unresolved` or `external`, with identical precedence. This turns M3b's native
ParsedImport into useful index edges without translating the 1610-line indexer as
one component. Original owners are `indexer.py:1014–1544` and `jsresolve.py`;
SQLite updates/backfill remain owned by the later incremental-indexing service.

The working example is:

```rust
let catalog = ImportCatalog::from_inputs(files, Some(config_bytes))?;
let edge = catalog.resolve(&ImportRequest {
    module: "@app/store".into(), source_path: "src/main.ts".into(),
    language: Some("typescript".into()),
})?;
assert_eq!(edge.target.as_deref(), Some("src/store.ts"));
assert_eq!(edge.resolution, Resolution::Internal);
```

`files: Vec<String>` preserves original SQLite row order. `config_bytes` is an
ordered-file-addressed map of exact bytes for indexed tsconfig/jsconfig/package,
go.mod and composer inputs, or None when the original has no project root.
Preparation errors remain explicit when malformed config shapes crash the original;
missing/unreadable/invalid-JSON configs retain the original tolerant behavior.
No heuristic invents a target for an ambiguous import.

## Concepts and ownership

- `ImportCatalog` owns the indexed path inventory, precomputed Python suffix
  index, nearest Cargo dirs, Go package representatives and language delegations.
- `ModulePath` helpers own original lexical relative joining and JS extension/index
  priority, including `.js` imports selecting an existing `.ts` source.
- `AliasResolver` owns ordered JS/TS config inheritance, nearest config matching,
  workspace-package priority and internal-shape recognition.
- `OrderedJson` preserves Python dictionary insertion order and duplicate-key
  last-value/first-position semantics when reading config objects. It is local to
  config resolution, using existing serde without globally enabling preserve_order.
- Language-specific resolution owns Rust crate/self/super/glob rules, Java/Kotlin
  package matching, Go go.mod packages, Ruby relative loads, C++ quoted includes
  and PHP PSR-4 mappings. Classification belongs beside its language decision.
- `ProjectImportInputs` reads actual indexed config files before pure resolution;
  the pure engine has no filesystem, database, parser, network or process access.

Use a focused public `ken-core::imports` module. Existing project/source owners
remain unchanged. Public types derive serde/Clone/Debug/PartialEq; Resolution uses
lowercase `internal`, `unresolved`, `external`. ImportResolution contains
`target: Option<String>` and `resolution: Resolution`. ImportRequest contains
module/source_path/optional language. ImportError identifies invalid config shape
and contextual file; errors never become successful external classifications.

## Approaches and chosen tradeoff

The chosen implementation separates pure resolution from config acquisition,
then connects its result to the index writer in the next index stage. It exposes
inputs and ordering for independent differential tests and keeps database work in
its owner. Porting all indexer code together couples parser/model/vector/storage
failures. Retaining Python resolution violates native execution. Neither advances
the approved migration with a testable native capability.

No new crate or third-party version is required: ken-core already has serde,
serde_json, regex and standard collections. Local ordered deserialization avoids
changing serde_json features for already accepted model consumers.

## Exact behavior to preserve

Resolution order is generic structural target, JS/TS aliases/workspaces, Java,
Rust, Go, Ruby, C++, Kotlin and PHP according to the importing language. Generic
resolution intentionally runs for all languages before specialized rules.

Relative `./`/`../` first uses the importing directory and JS module matcher.
Exact indexed paths precede extension rewrites; suffix order is `.ts`, `.tsx`,
`.d.ts`, `.js`, `.jsx`, `.mjs`, `.cjs`, then corresponding `/index` candidates.
Python dotted fallback uses unique suffix membership; duplicates stay ambiguous.
Lexical joins clamp parent traversal at the inventory root, as the original does.

JS configs are nearest-first with stable ties, inherited extends depth <3,
original JSONC comment/trailing-comma behavior, baseUrl relative to its declaring
config and ordered paths/package entries. A nearer unsuccessful alias may fall
through to an ancestor. These observed rules take precedence over comments that
imply a different policy. Unresolved classification matches original shapes.

Go selects the first matching nearest module and lexically-first non-test file;
Rust preserves original file-vs-module/glob behavior; quoted C++ matches unique
suffix then unique importing top-level subtree; PHP prefix ordering is stable by
length and keeps autoload before autoload-dev; Kotlin requires one containing
package file. Preserve wildcard, missing, malformed, Unicode and unknown-language
results without improving language semantics during the migration.

## Verification and acceptance

Capture pending requests, ordered inventory, actual indexed config bytes and final
original target/classification through real original indexer tests. Record owner
hashes, test inventory/states and raw captures. Add direct independent original
cases for ambiguity, no-root catalogs, precedence ties, extends/cycles, malformed
config shapes, duplicate JSON keys, Unicode and missing targets. Preserve failures.
Do not repeat model inference or the original parser suite.

Native tests compare complete ordered edge results, not just matching counts.
Native macOS arm64/Linux aarch64 probes run outside checkout with copied binary,
empty PATH, loader audit, Linux exec/connect trace and real config-acquisition
fixtures. Authenticated receipts reject lost/duplicate cases, altered config/source
bytes, missing platforms, fabricated passing gates and swallowed original errors.
Original1066hashes must remain intact. Final review follows the single whole-plan
review plus one Important/Critical TDD repair pass; no confirmation pause.

Acceptance is M3c only. Common AST normalization, incremental writes, full M3,
M4–M8 and application cutover remain pending until their own real gates pass.

Closed M3b predecessor: `docs/validation/rust-migration-2026-10-23/m3-parsers-review`; FILES.json SHA256 `c1541177be2a0716ff52276d7cfe042ae4ff5acea75d3f4c90d4a3452ab48ff8`, repaired commit03400e2b. Its immutable proof is reused; no124parser-suite/model recapture.
