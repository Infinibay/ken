# Native Worktree Text Search

**Goal:** Complete `ken_find(scope="text")` and CLI tools find for live literal
and BM25 text search, without model resources, on Linux x86_64.
**Spec:** docs/superpowers/specs/2026-10-18-rust-migration-design.md; behavior owner
src/ken/grep.py and src/ken/mcp/server.py::ken_find.

`WorktreeTextSearch` owns live source scanning and the incremental derived FTS
mirror. Keep it separate from readonly IndexNavigation: BM25 refreshes only
fts_files/ci_fts_state, atomically, while literal queries remain readonly.
Reuse confined source handles, pinned Unicode, existing BLAKE2b hashing and
ToolDocument/ToolReply. Preserve language filters, limits, snippets, safe literal
FTS terms, stale-mirror behavior and three-decimal scores. Equal-score FTS ties
have SQLite row-order semantics; existing seeded mirrors retain their row IDs.

One implementation batch: capture new original text histories once; implement
both modes and shared CLI/MCP wiring with representative callers; run one combined
targeted validation. Focused reruns only for concrete failures. Review the new
text block once, preserve raw/local evidence, commit/push; no broad CPU/CI/archive
cycle for this block. No new external versions or installed-tool replacement.

- [x] Capture the 29 original queries/history once, preserving raw journals.
- [x] Implement literal/BM25 and shared CLI/MCP arguments and presentation.
- [x] Combined local validation: library4 + CLI21 roots, strict Clippy and format.
- [x] One read-only review and one correction pass; no production Important issues.
- [x] Preserve evidence, update usage/handoff and future qualification inventories.

Review: obsolete unsupported-text assertion fixed to use wiring; output format
now validates before domain execution, including legacy, with no-write regression.
Targeted reruns covered these concrete failures; no broad CPU/CI/archive loop.
Existing-mirror SQLite tie ordering is preserved; cold Python set insertion order
is intentionally not reproduced. Global migration and CPU acceptance remain open.
