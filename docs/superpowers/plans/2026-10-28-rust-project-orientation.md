# Native Project Orientation Implementation Plan

Execution: inline, following executing-plans, with one final fresh review.
Goal: complete model-free ken_rank scopes project/architecture/changes through
library, CLI tools rank and MCP without routing back to Python.
Spec: docs/superpowers/specs/2026-10-18-rust-migration-design.md.
User overrides per-edit checks: one functional implementation batch, one grouped
validation, focused reruns only for concrete failures. Linux x86_64 only; preserve
source/reference/raw evidence locally, no installed Ken replacement. Existing
codex/rust-migration branch and push authorization remain in force.

Apply addyosmani/agent-skills deprecation-and-migration (installed locally):
migrate a complete consumer interface via shared adapter, characterize observable
quirks, retain old implementation until its remaining consumers have migrated.
No schema change or source removal in this block; cutover remains M8.

Concepts: ImportTopology loads resolved indexed graph and coverage; its focused
algorithms own SCCs/condensation layers, label communities and PageRank. Indexed
architecture presentation owns bounded samples and quality flags. WorktreeChanges
owns bounded Git status collection; IndexNavigation enriches paths with existing
symbols/tests. Tool boundary owns rank argument parsing and model-free scopes;
session ranking remains explicitly unavailable pending its complete subsystem.

Files: navigation/architecture.rs and graph.rs for topology/report/algorithms;
navigation/changes.rs for bounded Git status/enrichment; existing tools/mod.rs
and args.rs for shared rank adapter; one original fixture/support/library target
and one real CLI/MCP integration root. No new external dependency versions.

- [x] Capture frozen-original graph edge cases and actual Git change states once.
- [x] Implement graph algorithms, summaries, changes and shared CLI/MCP rank.
- [x] Grouped targeted parity, existing navigation/tool boundaries, strict Clippy.
- [x] One final review, necessary fixes and usage/handoff; commit/push authorized.

Validation boundaries: empty graph, unresolved/external/self/duplicate/dangling
edges, disconnected components, cycles, deep chains (iterative algorithms),
bounded samples, convergence and rounding; staged/unstaged/deleted/renamed/new
Git paths, porcelain quoting and non-repository behavior. Compare original data
and compact output without loosening existing references or hardware profiles.

Completed:24domain+20public original JSON/compact observations match. First setup
failed FK enforcement before0queries; preserved it, disabled FK only in synthetic
corrupt-index fixture setup. Next setup accepted42observations then failed before
Git queries because rename source was absent. Preserved all42; corrected only
remaining setup and observed2Git queries, sealed immutable fixture24430B
SHAc6813356a1dfaeb9a9bcc19700a47cadfec8f6f18bf46d45ecb43b6ac4ef51c7.
No accepted originals repeated or expectations relaxed. One grouped native pass
GREEN31roots, strict Clippy2.67s, fmt/diffclean. Fresh reviewer found no
Critical/Important/Minor requiring changes. No correction/re-review cycle.
Only existing locked libc gained a dependency edge; no external version changes.
