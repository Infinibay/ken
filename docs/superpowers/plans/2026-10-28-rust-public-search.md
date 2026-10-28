# Native Public Search Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; one fresh final
> read-only review and one Important repair pass, with no per-task subagents.

**Goal:** Run native default file/symbol search through CLI and stdio MCP.
**Architecture:** A pure compact renderer presents existing responses; explicit
installation resources construct lazy BestSearch owners shared by public callers.
**Tech Stack:** Locked Rust1.95/Python3.12.9; existing crates and native CPU cores.
**Spec:** docs/superpowers/specs/2026-10-28-rust-public-search-design.md

## Global Constraints
- Linux x86_64 only for active qualification; retain existing ARM behavior.
- Frozen1066 fingerprint5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038;
  accepted original observations, fixtures, numerical tolerances remain immutable.
- No new external versions, Python runtime fallback, release, tag, merge or
  replacement of the installed application. Branch commits/push are authorized.
- Keep workspaces/raw evidence locally/untracked. Pending CT2 Intel and BestSearch
  SkylakeX remain explicit; this slice cannot certify those profiles.

## Review Focus
- Missing/relocated resource manifests must not cause hidden checkout dependencies.
- Exact/empty searches must not load optional native modules or download models.
- A malformed request must not write a partial success or corrupt shared state.
- Default and compatibility response formats must not silently alias each other.
- CLI stdout and MCP stdout must contain only their intended response/protocol.

### Task 1: Pure compact presentation
Files: new crates/ken-retrieval/src/compact.rs, tests/compact.rs and immutable
fixtures/public-render-reference.json.gz; module export in src/lib.rs.
Interface: `compact::render(&SearchResponse, diagnostics: bool) -> String`.
- [ ] Preserve first-time original renderer observations using existing captured
  response inputs plus literal edge cases, both diagnostic modes. Save source,
  observer/input/output identities and raw execution locally before freezing.
- [ ] RED missing renderer; assert exact original text for every frozen row and
  unchanged serialized input after rendering, including stale/partial precedence,
  separated fragments, Unicode, empty/trailing lines, warnings and omitted count.
- [ ] Implement renderer over typed responses; reuse existing Python string/float
  formatting for diagnostic signals. No source reads or ranking changes.
- [ ] GREEN targeted tests, affected presentation tests, fmt and strict Clippy;
  commit. Expected: byte-identical scalar UTF-8 text and no mutated evidence.

### Task 2: Explicit native installation and search application
Files: new crates/ken-search/src/installation.rs, integration tests;
existing src/lib.rs export only as needed.
Interfaces: `SearchInstallation::open(&Path) -> Result<Self>` resolves a bounded
version1 manifest relative to its directory; `into_search()` returns the configured
lazy `BestSearch`. The shared public application/response policy joins Task3 when
it owns project discovery and transport-facing failures, rather than a wrapper.
- [ ] RED relocation, unknown fields/version, relative runtime sources, missing
  resources, cold exact/empty, actual registered non-exact and retry after failure.
- [ ] Assemble existing ModelFactory/RegisteredSearchResources from explicit paths,
  registered runtime declarations and legacy identity; use existing preparation
  and architecture checks. Do not infer package versions or create fake resources.
- [ ] GREEN full ken-search tests and real public application histories; strict
  Clippy/fmt; commit. Expected: existing library results through shared public owner.

### Task 3: CLI default file/symbol search
Files: crates/ken-cli/src/{args,main,search}.rs, Cargo.toml, tests/search_cli.rs.
Interfaces: typed command dispatch preserving existing status parser compatibility;
search options map to SearchRequest, installation path is captured at the boundary.
- [ ] RED actual subprocess text/JSON/exit streams, joined query, path discovery,
  compact+JSON error, positive budgets, cold exact/empty, missing project and
  explicit unsupported compatibility modes; preserve current status tests.
- [ ] Delegate auto/compact to SearchApplication; print original compact text or
  structured response. Never alias evidence/legacy to BestSearch.
- [ ] GREEN real registered CLI path plus existing status and search suites,
  fmt/strict Clippy; commit. Expected: a usable native default command.

### Task 4: Stdio MCP file/symbol default search and closure
Files: native MCP transport module/CLI dispatch and real stdio integration tests;
source-bound qualification tooling/workflow as required by the global contract.
- [ ] RED initialize/tools-list/tools-call, notifications, unknown methods/scopes,
  malformed JSON, recoverable errors and repeated requests in the same real process.
- [ ] Implement JSON-RPC framing/delegation sharing the application response policy;
  protocol only on stdout, diagnostics on stderr, no shell or Python subprocess.
- [ ] Verify committed-source local/native CI packets, independent original public
  outputs, resource/build closure and archived validator replay; preserve failures.
- [ ] One fresh final read-only review, ledger all rulings/minors, one Important
  TDD fix pass, green suite; update docs, commit/push, preserve workspace.
Expected: public default search slice complete; remaining compatibility scopes,
global quality, Intel/SkylakeX and M5–M8 remain accurately recorded until finished.
