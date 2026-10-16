# Compact CLI and MCP output implementation plan

> **For agentic workers:** Use superpowers:executing-plans; implementation stays in this session. Independent agents remain restricted to benchmark curation/review.

**Goal:** Default to useful, compact text throughout CLI and MCP, with explicit JSON compatibility.

**Architecture:** Keep domain results and ranking intact. A shared presenter renders locations, names, numbered code and interpretation-critical status. An MCP registration adapter applies it only at the public transport boundary; internal Python calls keep their native data.

**Spec:** User request of 2026-10-16; existing response-format and quality constraints in CONSTRAINTS.md.

**Global constraints:** This presentation slice performs no search-profile promotion, release, ranking change, silent code truncation, hidden errors/coverage, or foreign edits. JSON preserves native results. Explicit full/explain retains diagnostics. Code lines retain whitespace and accurate line numbers; FTS excerpts without source ranges remain unnumbered.

**Review focus:** Nested internal tool calls must retain native data; MCP/CLI schemas must agree; all tool defaults must be text without duplicate JSON; disjoint/partial source ranges must stay honest; status/coverage/negative results must remain actionable.

## Task 1: Shared compact presentation and transport boundary

- [x] Add tests for numbered source, disjoint ranges, empty/errors, warnings/unknown coverage, no mutation and size reduction.
- [x] Add an MCP transport test using the real SDK: all tools publish optional output_format compact/json, default text, JSON opt-in; domain functions retain raw results.
- [x] Observe red; implement src/ken/presentation.py and src/ken/mcp/presentation.py, register adapters in server.py; observe green.
- [x] Retain explicit response_format=evidence/legacy and full/explain semantics.

## Task 2: CLI defaults

- [x] Add public CLI tests for tools default text, explicit JSON and legacy single-line JSON compatibility.
- [x] Update direct search, explain and structural/KQL2 command presentation to use the shared presenter, preserving existing JSON opt-ins and exit codes.
- [x] Add --json to commands that previously emitted only JSON; verify module entry points and help.
- [x] Update existing JSON-contract callers/tests to request JSON explicitly and preserve their assertions.

## Task 3: Validation and documentation

- [x] Run affected CLI/MCP/retrieval/structural suites, real persistent stdio calls and typing.
- [x] Record representative before/after output sizes and limitations; document JSON migration and unchanged ranking.
- [x] Review exact owned diff, commit and push without release after integration with concurrent engine work.

## Verification closure

Full compatibility run:14843 passed,10 existing xfailed in528.51s. After final
source-line fidelity refinements,160 focused tests passed in9.69s. Mypy checked
342 source files with no issues. Real SDK captures cover all12tools and7CLI
invocations. Mutation of the output-format guard was detected by its test.

Integration/commit is the final checklist item; best-profile integration continues
under docs/design/best-default-search-2026-10-16.md and is not claimed here.
