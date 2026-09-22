# KQL2 authoring feedback: executable scope, diagnostics and local hazards

2026-09-22. Validation on the current Ken worktree, Python 3.12.9, macOS.

## What the latest review actually queried

The original files are preserved in [originals](originals). Their compile-only
explanations are adjacent `*.explain.json` artifacts.

| Original | Actual meaning | New warning |
| --- | --- | --- |
| `final_try_with_throw.kql` | Independent try, catch and throw domains; projecting try deduplicates combinations | `disconnected_captures` |
| `final_try_without_throw.kql` | Independent try/catch, plus global absence of any throw | Both disconnection and `uncorrelated_exists` |
| `bug_except_continue.kql` | Any continue can combine with every catch | `disconnected_captures` |
| `bug_except_logger.kql` | Catch, call and an identifier named exception are independent | `disconnected_captures` |

Thus the review's counts do not demonstrate that all handlers continue, all try
blocks raise, or only one handler logs exceptions. Coverage is a statement about
the acquired source scope, not the correctness of the query's interpretation.

## Delivered behavior

- `ken kql2 FILE --backend exploration --explain` validates the complete query
  against that backend without acquiring project files. Indexed is the default.
- `ken kql2 --capabilities` lists backend support, canonical kinds and syntax
  properties from engine definitions also used by validation/exploration.
- Source authoring diagnostics explain disconnected captures, global existence/
  absence, unfamiliar canonical kinds, and misleading Python literal/import
  spelling. Warnings preserve valid Cartesian/global-query semantics. They
  survive compact MCP output, cached results and supervised timeouts after
  compilation. Expanded source branches and BODY references are considered.
- Unsupported `parent:`/`value:` constraints suggest executable alternatives.
  A misplaced return explains its required BODY enclosure. Exploration errors
  direct declaration/BODY users to indexed.
- BODY and `return $value` were already implemented in indexed. The guide now
  distinguishes this from exploration, whose capability remains syntax only.
- A shared English syntax reference supplies complete queries with mixed
  positive/negative source examples. The literal Markdown queries are executed
  in tests. Find-patterns, prevent-regressions and investigate-bug skills now
  teach interpretation and witness checking as part of their workflow.

## HAS_HAZARD preparation

`HAS_HAZARD` retrieves predefined analyzer facts, rather than inventing a bug
diagnosis. The mutable-default rule recognizes Python list/dictionary/set
literals in parameter defaults; it does not cover every mutable expression.

Positive plans containing exclusively HAS_HAZARD edges now request a local
hazard projection. Python retains declaration ownership and calls the existing
`structural.effects.syntax_effects` rules without constructing operations or
linking the project. Other languages retain full frontend lowering before
projecting these facts, since their rules may depend on binding semantics.
The relational executor reads those fact columns directly. A mixed graph plan
still requests the full frontend/linker.

Projection-specific source fingerprints prevent partial IR from being reused
as full semantic IR. `--reference` uses full preparation for equivalence checks.
Tests compare the exact rows and evidence, verify source edits and parse errors,
and exercise a full source query after a hazard query.

The existing project cache occupied 899,997,696 bytes of its 900 MB storage
share (100 MB was reserved for compilation). Initially, local acquisition also
timed out while reclaiming that much larger semantic cache. The final path
uses disposable work storage on admission pressure for this cheap projection;
it does not raise the configured quota or evict active readers.

| Run on `src/ken` | Total request time | Result |
| --- | ---: | --- |
| Full preparation, reference path | 15,128 ms | Incomplete; stopped during persist |
| Local hazards before pressure fix | 15,112 ms | Incomplete; expensive cache reclamation |
| Local hazards, cache disabled | 2,715 ms | Complete |
| Local hazards after pressure fix | 2,769 ms | Complete |
| Immediate repeat after pressure fix | 2,661 ms | Complete |
| Final code verification | 2,806 ms externally measured | Complete |

See `full-preparation.json`, `local-hazards*.json` and
`final-project-hazards.json`. The final run acquired 284 files with complete
coverage and found no instances of the **specific mutable-literal-default
signature**. Positive fixtures verify detection. This is not a claim that the
project has no mutable-state bugs. The final project cache-pressure runs were
ephemeral, not claimed warm result-cache hits. Small fixture tests independently
verify persistent unit/result reuse when capacity is available.

The project remains configured for 1 GB; the global default is unchanged.
These timings are observations on this worktree/cache, not a general latency
guarantee. Full semantic preparation can still consume the request budget.

## Reproduce

From the repository root:

```sh
.venv/bin/python -m ken kql2 docs/validation/kql2-authoring-2026-09-22/originals/final_try_with_throw.kql --backend exploration --explain
.venv/bin/python -m ken kql2 --capabilities
.venv/bin/python -m ken kql2 docs/validation/kql2-authoring-2026-09-22/mutable-defaults.kql --path src/ken --timeout-ms 15000
```

The executable authoring reference is
[`src/ken/skills/references/kql2/syntax.md`](../../../src/ken/skills/references/kql2/syntax.md).
BODY examples remain in `values-and-patterns.md` in the same directory.

## Verification and remaining limits

- 1,854 tests passed in `regressions.xml`: KQL2, common AST, CLI/MCP, checks,
  inspection, skills, installation and literal documentation examples.
- 128 tests passed in `graph-regressions.xml`: relational operators/evidence,
  interfaces, catalog migration and check automation.
- Focused Ruff and mypy checks passed. All three edited skills passed the
  skill validator; their behavioral examples also ran in the suite above.

Diagnostics are conservative authoring advice, not complete intent checking.
Graph plans currently have no capture-composition lint. Syntax descendants can
include nested functions/loops; no implicit exception propagation or continue
destination is inferred. General semantic graph cost, ownership transfer and
runtime correctness remain separate problems. Restart an existing MCP process
to load the new runtime; reinstalling skills alone does not reload Python code.
