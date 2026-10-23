# Rust Native Parsers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all19original parser frontends with native Rust extraction at their exact public result boundary.

**Architecture:** `GrammarCatalog` owns verified native grammar lifetimes; `ParserRegistry` chooses language and delegates extraction; language modules own their syntax decisions, sharing comment/scope helpers. Frozen-original captures supply every expected field.

**Tech Stack:** Rust1.95, tree-sitter0.25.10, six pinned official grammar crates, thirteen pinned language-pack1.8.1 C modules, existing serde/sha2/libloading.

**Spec:** `docs/superpowers/specs/2026-10-23-rust-parsers-design.md`

## Global Constraints

- Original1066files and user dirt preserved; no installed CLI or production index writer replacement.
-19languages/44extensions/20grammars, versions and native bundle hashes exactly as in the spec.
- Preparation tooling may use the existing Python environment; all native consumers are independent of Python and perform no downloads/subprocesses.
- Compare full ordered ParsedFile results, including complete scopes/docstrings/annotations; syntax recovery and Unicode byte boundaries preserved.
- Actual native macOSarm64/Linuxaarch64 gates; reuse unchanged M0–M3a histories and model resources.
- One whole-plan final review and one verified Important/Critical repair pass; no confirmation pause under the user's continuing authorization.

## Review Focus

1. Empty, invalid-UTF8 and malformed input must recover like original, with byte-based ranges and full final ParsedFile fields; Tasks1–7 capture these inputs.
2. Nested/one-line/decorated definitions and same-span nodes must preserve scope ownership and final symbol mutations; Tasks2–4 assert the complete dataclasses.
3. Missing/corrupt/wrong-language optional grammars must fail only their consumer; Task1 tests actual modified resource copies and continued static/other-language parsing.
4. Dropping registries/trees in different orders, repeated parses and concurrent callers must not unload a live grammar or share mutable parser state; Task1 exercises real trees and threads.
5. A corpus or platform cannot silently lose cases or fields while reporting success; Task7 rejects missing/duplicate cases, reordered symbols, changed scope docs and altered grammar identity.

---

### Task 1: Native grammar catalog and independent syntax reference

**Files:** Create `crates/ken-syntax/{Cargo.toml,src/lib.rs,src/grammar.rs,src/syntax.rs,tests/grammar.rs}`, `tools/rust_migration/{grammar_prepare.py,parser_reference.py}`, `tests/rust_migration/{test_grammar_prepare.py,test_parser_reference.py}`, `crates/ken-syntax/grammars.lock.json`. Modify workspace Cargo manifests/lock only for pinned new dependencies.

**Interfaces:**
- Consumes frozen `Reference/reference_env`, baseline1066owner hashes; original parser entrypoints and direct grammar sdists in `uv.lock`.
- Produces `Language` enum with19variants; `GrammarCatalog::prepared(manifest: &Path) -> Result<Self, ParseError>`; `GrammarCatalog::syntax(&self, language: Language, source: &[u8], hint: &str) -> Result<SyntaxTree, ParseError>`.
- `SyntaxTree` owns raw tree+grammar lease; `root() -> SyntaxNode<'_>`. `SyntaxNode` exposes kind/byte offsets/points/named flag/children/field/parent/previous named sibling while keeping raw Tree/Language private. No lifetime-escaping raw handle.
- Preparation `prepare_grammars(lock: dict, cache: Path, destination: Path) -> dict` writes authenticated manifest+13modules+license attribution atomically; cached authenticated inputs are reused. An existing destination is reused only with identical verified identities.
- `capture_parser_reference(reference: Reference, out: Path) -> dict` records real original test calls/results and syntax shapes with full raw execution provenance; every language/grammar has an explicit coverage row.

- [ ] **Step 1:** Capture exact original grammar package versions, parser owners and full parser-suite dataclass observations. Add supplemental inputs for uncovered language/error/Unicode/empty cases. Verify raw capture origins, no missing owners and actual original test inventory. Tests `test_parser_reference.py` reject owner drift, wrong module roots and missing language coverage.
- [ ] **Step 2:** Write Rust `grammar.rs` tests:20grammar roots/shapes equal captured original; malformed source returns a tree; real SDK tampering/missing module/wrong platform/unsafe path/duplicate identity fail only affected consumer. Keep a tree after dropping the catalog, traverse its nodes, then run concurrent independent parses. Run `cargo test -p ken-syntax --test grammar`; expect missing crate/API RED.
- [ ] **Step 3:** Add pinned runtime and direct grammar crates; authenticate their parser.c against matching locked sdists (never compile incomplete sdists or Python binding sources). Add thirteen native SDK resources prepared from pinned bundles with per-language source/license metadata. Implement grammar lease and safe syntax-node boundary; instantiate parsers per operation.
- [ ] **Step 4:** Run Rust grammar tests and two focused Python targets; expect exact syntax equality, real lifecycle/resource tests green, fmt/clippy clean on both platforms. Verify no original changes and record any SDK packaging trap.
- [ ] **Step 5:** Commit scoped Task1 files as `feat(syntax): load pinned native language grammars`.

### Task 2: Parsed model, common scopes, Python and Rust

**Files:** Create `crates/ken-syntax/src/{model.rs,registry.rs,helpers.rs,scopes.rs,python.rs,python_literal.rs,python_names_delta.json,rust.rs}`, `crates/ken-syntax/tests/parsers.rs`, `crates/ken-syntax/tests/fixtures/reference.json`; modify lib exports.

**Interfaces:**
- Consumes Task1 `Language/GrammarCatalog/SyntaxTree` and complete original captures.
- Produces serializable/equatable `ParsedSymbol {kind,name,qualname,line_start,line_end,docstring}`, `ParsedImport {module,line}`, `ParsedScope {symbol,signature,documentation,owner,statements,implementation_start_line,annotations}`, `ParsedFile {symbols,imports,docstring,scopes}` with source-compatible Option/vector field values.
- `ParserRegistry::new(catalog: GrammarCatalog) -> Self`; `parse(&self, language: Language, source: &[u8], hint: &str) -> Result<ParsedFile, ParseError>`. Pending language extraction returns an explicit error until its task; grammar parsing is already complete.
- Internal `extract(source: &[u8], root: SyntaxNode<'_>) -> Result<ParsedFile, ParseError>` in each language module. Shared `enrich_scopes` and `scope_for_node` preserve exact original ownership/signatures/comments.

- [ ] **Step 1:** Add Python/Rust full-result tests covering all original captured calls, lexical nesting, decorators/attributes, literal docstrings, inner/trailing comments, one-line spans, imports, empty/broken/invalidUTF8 input. Assert vectors/scopes, ranges and final shared-symbol values without normalization.
- [ ] **Step 2:** Run `cargo test --locked -p ken-syntax --test parsers python` and equivalent Rust subset; expect missing extraction API RED.
- [ ] **Step 3:** Implement model/helpers/scopes and the two original extraction passes where present. Keep language selection in registry and exact language rules in their module.
- [ ] **Step 4:** Run the two parser subsets plus Task1 gates, fmt/clippy. Expect all captured fields exact. Confirm original owner hashes still match.
- [ ] **Step 5:** Commit as `feat(syntax): extract Python and Rust symbols and scopes`.

### Task 3: ECMAScript, Go and Java

**Files:** Create `crates/ken-syntax/src/{ecmascript.rs,ecmascript_scopes.rs,go.rs,java.rs}`; extend registry and `tests/parsers.rs`.

**Interfaces:** Consumes Task2 model/helpers/registry; produces `extract` functions at the same signature. `ecmascript::extract(..., typescript: bool)` handles JS/TS syntax decisions, while Task1 catalog chooses TSX by literal hint suffix.

- [ ] **Step 1:** Add complete original JS/TS/Go/Java captures: generator/export wrappers, class signatures, arrows and assignment scopes, destructured/dynamic targets, generic/type/interface/enum nodes, grouped imports, pointer receivers, annotations and malformed/Unicode cases.
- [ ] **Step 2:** Run affected `cargo test --locked -p ken-syntax --test parsers` filters; expect explicit pending-language failures.
- [ ] **Step 3:** Implement original walks and lexical ECMAScript enrichment, preserving final symbol mutations and extra scopes. Share only rules identical in original JS/TS.
- [ ] **Step 4:** Run all implemented parser tests plus grammar lifecycle tests and fmt/clippy on both platforms; expect exact ordered full results.
- [ ] **Step 5:** Commit as `feat(syntax): extract ECMAScript Go and Java programs`.

### Task 4: C, C++ and C# plus language detection

**Files:** Create `crates/ken-syntax/src/{c.rs,cpp.rs,csharp.rs,detection.rs}`, `crates/ken-syntax/tests/detection.rs`; extend registry/parsers tests.

**Interfaces:** Consumes Task1 catalog and Task2 model. Produces `ParserRegistry::detect(&self, path: &Path, source: Option<&[u8]>) -> Result<Option<Language>, ParseError>`; cpp `has_cpp_syntax` uses actual nodes. Known missing optional C++ grammar preserves the original C fallback for ambiguous .h; direct C++ parse still errors explicitly.

- [ ] **Step 1:** Write full-result corpus tests for namespaces, nested types, operators/destructors, overloads, templates, preprocessor wrappers, imports/includes and C# members. Detection asserts all44suffixes/case behavior and original .h positive/negative examples, including C++ words inside comments/strings and C identifiers.
- [ ] **Step 2:** Run parser subsets/detection tests; expect pending extraction/detection RED.
- [ ] **Step 3:** Implement language-owned algorithms and exact extension table; unknown extension returns None. Keep optional grammar failure boundaries explicit.
- [ ] **Step 4:** Run all current syntax tests, fmt/clippy and original guard in each native environment; expect exact captures and detection outcomes.
- [ ] **Step 5:** Commit as `feat(syntax): preserve C family extraction and detection`.

### Task 5: Ruby, Kotlin, Dart and PHP

**Files:** Create `crates/ken-syntax/src/{ruby.rs,kotlin.rs,dart.rs,php.rs}`; extend registry/tests.

**Interfaces:** Consumes Task2 model/common helpers; produces each language `extract` with the same explicit signature.

- [ ] **Step 1:** Write full-result tests from original captured calls plus nested ownership, singleton/member forms, constructors/accessors, source/package imports, comments/docstrings and empty/broken/Unicode cases.
- [ ] **Step 2:** Run four affected parser filters; expect pending-language RED.
- [ ] **Step 3:** Port original node traversal and naming decisions into their owners, reusing only shared scope/comment rules already verified.
- [ ] **Step 4:** Run all implemented syntax tests and fmt/clippy on both systems; expect every full dataclass field and order exact.
- [ ] **Step 5:** Commit as `feat(syntax): extract Ruby Kotlin Dart and PHP programs`.

### Task 6: Shell, stylesheet, markup and declarative parsers

**Files:** Create `crates/ken-syntax/src/{bash.rs,powershell.rs,css.rs,html.rs,graphql.rs,sql.rs}`; extend registry/tests.

**Interfaces:** Same Task2 extraction signature/model. Domain-specific symbol kinds remain the original strings; no new cross-language taxonomy changes them.

- [ ] **Step 1:** Write complete captured-result tests for Bash functions/source, PowerShell functions/filter/class/import forms, CSS selectors/custom properties/imports, HTML tags/ids/script sources/templates, GraphQL declarations/fields/imports and SQL definitions. Include comments, nesting, duplicates, Unicode and malformed syntax.
- [ ] **Step 2:** Run six affected filters; expect pending-language RED.
- [ ] **Step 3:** Implement original syntax rules and attach scopes only where original does; remove the last explicit pending extraction branches.
- [ ] **Step 4:** Run full ken-syntax suite, fmt/clippy and complete coverage inventory: exactly19languages/20grammars/44extensions represented in both environments.
- [ ] **Step 5:** Commit as `feat(syntax): complete native parser language coverage`.

### Task 7: Native differential acceptance and final review

**Files:** Create `crates/ken-syntax/examples/parser_probe.rs`, `tools/rust_migration/{parser_validate.py,parser_evidence.py}`, `tests/rust_migration/{test_parser_validate.py,test_parser_evidence.py}`, `docs/validation/rust-migration-2026-10-23/m3-parsers/`; update `docs/rust-migration.md`.

**Interfaces:** Consumes complete `ParserRegistry` and original capture; produces bounded strict JSON probe with actual language/source bytes/hint only, and authenticated platform acceptance. No expected fields are accepted by native requests. Matrix accepts M3b only; M3 and whole migration remain false.

- [ ] **Step 1:** Write comparator/evidence RED tests rejecting missing/duplicate/reordered cases, changed symbol ranges/kinds, lost docs/scope/annotations, injected expected results, altered grammar/source hashes, false passing summaries and absent language/platform coverage. Real process tests exercise unknown fields, invalid source encoding and resource failures.
- [ ] **Step 2:** Implement strict native batch transport and full ordered semantic comparison. Record actual copied binary, outside-checkout cwd, sentinelPATH, complete input/output and loader/exec/connect audit; grammar preparation occurs before isolated native execution.
- [ ] **Step 3:** Build and run full syntax/tooling gates and one current native differential per platform; compare complete case inventories and grammar shapes. Reuse prior source/model receipts at exact snapshots; verify original1066files unchanged.
- [ ] **Step 4:** Replay authenticated evidence independently; resealed mutations must reject. Record source/bin/resource/test identities and compression of raw artifacts; no hundreds of disposable files left as product sources. Do not promote indexing or installed commands.
- [ ] **Step 5:** Commit scope-specific evidence. Run one fresh whole-plan review, one TDD Important/Critical repair pass and affected gates. Archive complete ledger/rulings/minors/review before deleting own workspace; continue common-model/import-resolution/indexing plan without asking for confirmation.

## Self-review

All spec capabilities map to Tasks1–7; no parser language or ParsedFile field is
omitted. Task1 precedes all grammar consumers; Task2 establishes shared model and
scope interfaces before language groups; detection follows available C++ extraction.
Every review-focus condition has a boundary test. Preparation remains separate
from native consumption and final distribution is reserved for M8. Native inline
execution and no approval pauses are the user's continuing selected method.

Task1 source verification amendment: Python binding0.25.2 vendors C engine0.25.10 at da6fe9be. All42original C/header inputs match Rust0.25.10 exactly; the compiled lock records this evidence. The initial Rust0.25.2 corpus happened to pass all215inputs, but matching the actual engine avoids untested runtime behavior differences. No original capture or model inference was repeated.

Task2 model refinement: PythonStringLiteral owns full docstring decoding; py_literal
alone does not decode the captured triple-quoted docs or raw/Unicode-name forms.
The native adapter normalizes delimiters/line breaks and preserves raw/u/bytes/f
behavior. Pinned unicode_names2=1.2.0 supplies formal names, with a reproducible
original-Unicode15 filter (627new15.1codepoints excluded,473original aliases).
Its derived dataset carries Unicode-DFS-2016 attribution/license. A separate
19case original corpus tests these forms and CRLF comments without rerunning the
124original tests. Shared text splitting treats CRLF as one boundary.
