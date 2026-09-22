# KQL2 investigation: composition, request budgets, and result identity

The reported friction was reproducible. A source query combining `call {target:
$target;}` with a callable-scoped `not exists` failed compilation. The timeout
started after source acquisition, and a nearly full cache repeatedly sent new
revisions into ephemeral storage even when they could fit after eviction.

## Changes and public behavior

- Resolved call targets compose with scoped `not exists`, `optional`, and
  alternatives. Private witnesses cannot escape or be captured by a later alias.
  Negation uses a closed call inventory; unresolved semantic targets remain
  uncertain. Unsupported combinations now explain an applicable next step.
- An explicit KQL2 timeout supervises the entire search, including compilation,
  lock acquisition, parsing, graph construction, and evaluation. Interrupted
  preparation reports its phase and progress. Partial rows survive when the
  evaluator has produced them. Unlimited searches remain unlimited.
- A failed cache allocation retries after reclaiming unleased cache data.
  Active readers and staged revisions stay protected. Reusable SQLite pages
  avoid an unnecessary full-file compaction when the database already fits.
  The project's configured cache remains **1,000 MB**; the global default is
  unchanged. An oversized or pinned working set can still require ephemeral
  storage.
- Scoped searches walk the requested subtree with inherited ignore rules,
  avoiding unrelated sibling directories.
- `usages` accepts `kind: receiver`. Supported local origin tracking distinguishes
  an alias of a result from a reassigned variable or another acquired object.
- `related(..., relation="impact")` adds `result_flow`: return propagation,
  argument boundaries, transformations, and receiver/cleanup candidates, with
  the next review step. A method named `close` is not an ownership contract.
  Ownership remains explicitly unproven and the usage inventory stays open.
- Compact `find` output includes timings and source anchors instead of repeating
  entire graph proof trees. `full=True` / `--full` retains the complete result.
- The English query manual and investigation skill were updated and the three
  affected bundles synchronized into `.agents/skills` for Codex and DeepSeek.

## Measurements in this repository

Scope for the interactive query: `src/ken/mcp/server.py`. The predicate selects
callers of the resolved `_conn` that contain neither `close` nor `closing`.
It returns **30 callables**, with complete coverage and no unknown candidates.
These are candidates for review, not 30 proven resource leaks.

| Observation | Measured time |
| --- | ---: |
| Before admission repair, repeated acquisition into ephemeral storage | 2,733 ms |
| After repair, repeated scoped query | 202 ms |
| After repair, edited predicate using retained graph | 232 ms |
| Whole `src` search, explicit 15,000 ms budget | 15,049 ms inside search |
| Same whole-scope request through CLI, including command startup | 15,710 ms |

The comparison isolates the observed cache failure, not every optimization.
See `before-admission-fix.json` and `stable-focused-measurements.json`.
The first scoped request after broad acquisition took 3.65 seconds, including
cache collection; subsequent requests reuse the retained revision and graph.
An earlier confirming run is retained in `final-focused-measurements.json`. Timings depend
on cache state and host load; no external machine or production latency SLO was
measured. A first reclamation of this large existing cache consumed its budget;
`measurements.json` retains those intermediate failures rather than hiding them.
Broad preparation is still expensive and the whole-scope search ended incomplete
at `persist`, with 67 parsed units. See `cli-budget.json` and
`cli-measurement.json`. The supervisor does not eliminate OS startup/reaping
costs or make indexing instantaneous.

For the same 30 rows, the compact JSON changed from **33,841 to 7,249 bytes**
(about 79% smaller). This is a byte measurement, not a tokenizer measurement;
see `compact-size.json`.

## Investigation against a runtime oracle

The evaluation generates a small resource module, runs only that generated
fixture to establish ground truth, and compares it with source-only Ken results.
It exercises a leak, direct release, alias release after reassignment, closing
the wrong instance, returning the resource, and delegating release.

```sh
.venv/bin/python scripts/evaluate_kql2_investigation.py --output /tmp/ken-kql2-review
```

The generated module is never imported by the search engine. The script executes
it separately as an oracle; it does not execute this repository's production
code. The report includes fixtures, queries, measured retrieval times, coverage,
and review boundaries in `fixture/fixture-evaluation.json`.

- `rg` found six callers in about 8 ms.
- The combined KQL predicate compiled on its first attempt and selected three
  callers: `leak`, `transferred`, and `delegated`.
- The runtime oracle demonstrates why those three are not a leak diagnosis:
  two are safe, while `wrong_close` leaks and is omitted by the coarse predicate.
- The identity evidence distinguishes the two acquisitions in `wrong_close`:
  only the second has a cleanup candidate. It also recognizes the surviving
  alias after the original binding is reassigned.

This is a retrieval and evidence evaluation, not a measured human debugging
session. We do not claim reduced human diagnosis time from these numbers, or
that KQL outperforms text search for locating a spelling. The useful addition
is the relationship and the explicitly stated boundary of what was established.

## Validation

The expanded KQL2/checks/inspection/skills/relational suite passed 1,767 tests.
After the final compact-output and budget adjustments, 60 focused integration
and documentation tests passed; 311 flow and import-alias tests also passed.
The final dedicated regression run passed **128 tests** and is recorded in
`regressions.xml`.
New focused modules and the report projection pass Ruff and mypy.

Regression cases cover blocking cache locks, killing a parser and releasing its
lease, recovery after timeout, partial rows, diagnostics over the subprocess
boundary, scoped traversal, cache admission with an active reader, private
captures, open-world negation, alternatives, and resource identity after aliasing
and reassignment. An intermediate import-alias assertion failed while source
files were being edited; both import-alias variants passed on the subsequent
stable run. No persistent failure remains from that run.

## Try the repository query

```sh
.venv/bin/python -m ken kql2 \
  docs/validation/kql2-investigation-2026-09-22/missing-close.kql \
  --path src/ken/mcp/server.py --timeout-ms 15000
```

The public MCP `ken_find` accepts the same source with `scope="structure"` and
`query_language="kql/2"`. Restart an already-running MCP server to load the
updated implementation. The direct `ken kql2` CLI uses exit 3 for incomplete
execution; `ken tools find` currently exits 0 with `complete:false`, so inspect
that field rather than inferring completeness from the tools wrapper's exit code.

Further useful work: incremental semantic graph publication for broad searches,
and explicit method/resource contracts that can prove release or ownership
transfer. Those are not inferred from method names by this change.
