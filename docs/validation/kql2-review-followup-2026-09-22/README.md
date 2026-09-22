# Audit of the follow-up KQL2 bug-hunting review

The original `.kql` files were found in `/tmp`. Selected originals are retained
under `originals/`; `original-replay.json` records their actual behavior on a
controlled fixture. Corrected, executable queries are in this directory.
No engine or exception-handling implementation was changed in this audit.

## Query defects reproduced

| Original query | What it actually asks | Controlled result |
| --- | --- | --- |
| `bug_catch_no_throw.kql` | Independent try, catch, and throw nodes; the throw is required, not negated | Selects both the swallowing handler and the re-raising handler |
| `bug_catch_not_exists.kql` | A handler plus global absence of any throw; no correlation to the handler | Selects neither handler because a throw exists in the fixture |
| `bug_while_true_literal.kql` | Independent while, literal, and block nodes | Selects both `while True` and `while pending` |
| `bug_return_none.kql` | An identifier spelled `None` | Misses the explicit `return None` positive; None is a literal |
| `bug_import_star_v2.kql` | An identifier spelled `*` | Misses `from another import *`; the wildcard has its own native node kind |
| `bug_catch_no_throw_refined.kql` | A `parent:` node property | Compilation error: unsupported property |
| `bug_while_true_no_break.kql` | `value:` and `parent:` node properties | Compilation error: unsupported property |

The logger, broad-Exception, except-return, except-continue, and try-finally
queries likewise declare independent captures without connecting them. Their
names do not impose constraints. Project-wide counts from such queries are not
counts of the relationships suggested by those names. Cartesian combinations
can also consume substantial work before projection deduplication.

Use `contains($parent,$descendant)` for descendants, `contains_direct` for an
immediate child, and nested node selectors for immediate structural ownership.
Use `role:"condition"` plus literal `text:"True"` for a Python while condition.
`not exists` without correlation can be intentional, but means global absence.
It is not evidence that correlated negation is broken.

## Corrected searches over current src/ken

Every row below completed with complete source coverage, zero unknown candidates,
and no row truncation. Each positive capability also had a positive/negative
control in `fixture.py.txt`. The zero import-star result is supported by the
corrected query successfully matching the positive fixture.

| Predicate | Result count |
| --- | ---: |
| All catch nodes | 282 |
| Catch without a descendant throw node | 227 |
| While with direct literal True condition | 19 |
| Return with direct literal None operand | 261 |
| Python wildcard import | 0 |
| Catch plus global absence of a throw anywhere | 0 |

`measurements.json` records the six fixture runs and six repository runs;
individual JSON files retain rows, coverage, and analysis metadata. Repository
runs used the exploration backend with a 10-second total budget. These are
source predicates, not six categories of confirmed bugs: returning None,
constant loops, and handled exceptions can all be intentional.

An independent Python AST count found 282 handlers, 74 directly catching
`Exception`, and zero bare `except:` handlers. The broad catches under `checks/`
are in `worker.py` and `automation.py`; `checks/service.py` and
`checks/selection.py` catch explicit exception tuples in this checkout.

The original indexed HAS_HAZARD query also passes a separate positive/negative
mutable-default fixture (`defaults.py.txt`, `indexed-hazard-control.json`). That
control does not establish acceptable latency over the entire project. The
large-scope performance limitation remains, and a timeout is an inconclusive
search rather than zero hazards.

## Review the alleged six defects against their contracts

1. `checks/automation.py:117`: logs the exception with traceback. The enclosing
   finally clears `running` and reschedules pending work. There is no demonstrated
   inconsistent scheduler state. A useful observability improvement would be
   surfacing the failure to the session in addition to the daemon log.
2. `checks/automation.py:167`: catches `relative_to(root)` failing when a supplied
   path is outside the project. This is a scope filter, not parsing and silently
   discarding an invalid source file. If no paths are available, the scheduler
   passes `touched=None` and the check can use Git changes.
3. `checks/execution.py:89`: returns `rows:[]`, **complete:false**,
   **coverage_complete:false**, and **reason**. It does not disguise the failure
   as successful absence.
4. `checks/integration.py:113`: returns unknown validity and preserves the issue
   and its reason. Unknown is the appropriate state when freshness cannot be
   established; it is not marked valid.
5. `checks/model.py:47`: translates invalid rule-construction inputs to ValueError
   and preserves the original exception with `raise ... from exc`. It does raise.
6. `_paths.py:64`: catches ValueError, not Exception, and re-raises a descriptive
   project-containment error with its original cause.

Catching Exception is not sufficient evidence of a bug, especially at a worker
or background-service boundary. Assess whether the failure remains observable,
state is restored, callers can distinguish failure, and a reproduction violates
the intended contract.

## Product improvements this review motivates

The mistakes are easy to write and superficially plausible output encourages
incorrect conclusions. Useful improvements would be:

- Query diagnostics for disconnected captures and uncorrelated negation, with
  suggested `contains`/`contains_direct` relations. Keep intentional Cartesian
  products and global absence available; do not silently change their meaning.
- An explain view that states scope and supported properties before execution,
  and flags unsupported normalized kinds instead of encouraging guessed AST names.
- Ready-to-run validated syntax recipes with a positive and a nearby negative
  fixture. Distinguish backend capability errors, incomplete execution, empty
  results, and actual demonstrated source/runtime defects.
- Selective acquisition of locally derived facts for hazard-only queries, to
  avoid paying for unrelated semantic graph work.

## Run a corrected query

```sh
.venv/bin/python -m ken kql2 \
  docs/validation/kql2-review-followup-2026-09-22/except_without_raise.kql \
  --backend exploration --path src/ken --timeout-ms 10000
```

The corrected negation is explicit:

```kql
language "kql/2";
module review;
query except_without_raise {
  node $handler { kind: "catch"; }
  not exists {
    node $raised { kind: "throw"; }
    where contains($handler, $raised);
  }
  select $handler.path, $handler.line;
}
```

This means no throw *node beneath this handler*. It does not prove that the
exception was swallowed, nor model whether a called helper raises at runtime.
