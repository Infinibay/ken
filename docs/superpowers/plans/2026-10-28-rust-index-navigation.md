# Native Index Navigation Implementation Plan

> Execute inline using executing-plans, adapted to the user's explicit larger
> implementation/validation batches. One fresh final read-only reviewer, no
> per-task agents. Preserve the workspace and original observations locally.

**Goal:** Native indexed-code navigation through shared library, CLI and MCP.
**Architecture:** Read-only IndexNavigation owns indexed facts/live source;
ToolDocument owns ordered data and compact projection; transports parse/delegate.
**Tech Stack:** Existing locked Rust/SQLite/serde; Linux x86_64, no new versions.
**Spec:** docs/superpowers/specs/2026-10-28-rust-index-navigation-design.md

## Global constraints
- Never modify accepted original fixtures, numerical tolerances or the Python app.
- No release, merge, tag or installed-tool replacement. Branch push is authorized.
- Keep bulky evidence local/untracked and preserve the plan workspace.
- Perform combined verification at the block boundary, not after every edit.

## Review focus
- Source-path confinement, invalid UTF-8, Unicode budgets and missing live files.
- Graph caps must retain only edges whose endpoints are returned.
- Test ranking must preserve ecosystem conventions, ties and structural stems.
- JSON and compact text must preserve negative/unknown status and field order.
- Model-free CLI/MCP must work without an installation and leave index data intact.

## One implementation block
- [x] Capture first-time original navigation/public presentation cases once; save
  input/source/output identities, raw journal and compact immutable fixture.
- [x] Add representative library and actual CLI/MCP caller tests against that
  fixture, including read-only operation and unsupported capabilities.
- [x] Implement ToolDocument/presentation; indexed navigation/files/source;
  relations/test ranking; CLI tools and shared MCP dispatch in one batch.
- [x] Run the combined affected-scope validation once; investigate and repair
  concrete failures with focused reruns. Review once, address material findings,
  update handoff, commit/push. Leave broad CPU qualification at the milestone.
