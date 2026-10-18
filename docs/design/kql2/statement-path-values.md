# Value witnesses on Python statement paths

KQL2 BODY clauses identify an ordered source witness. They do not prove runtime
feasibility, termination, exception type compatibility or behavior on every
execution. This distinction also applies to branches and loop iteration.

```kql
language "kql/2";
module example.returned;
query forwarded {
  callable $owner { body {
    let $value = call $site { name: "mark_safe"; };
    return $value;
  } }
  select $owner;
}
```

## Responsibilities

`structural/control_flow.py` owns statement successors and exceptional
continuations. `kql2/path_values.py` owns local value identities for one route.
BODY coordinates those snapshots with query roles. The existing
`structural/return_flow.py` still owns callable-wide may/must summaries; a may
summary is not promoted to must to accept an existential witness.

Consequently an authored catalog BODY (for example Prototype's explicit-copy
variant) can now witness the Python route where a conditional local survives,
or a return after ordinary yield. A generic `RETURNS_VALUE [basis: flow]` query
still observes its previous may/syntax-only summary. Regression tests assert
both contracts separately instead of treating their coverage as interchangeable.

At a completed local assignment, the route snapshots the RHS's current origin.
Copying an alias preserves that origin even if the original place is overwritten
later. Branches retain separate environments. Bare conditional expressions
(`alias = made if flag else None`, or the same expression at return) create
separate alternatives. Boolean literals, including parentheses, select one arm.
The matcher never follows historical `ASSIGNED_FROM` edges as reaching writes.

## Suspension and exceptions

Python generators may follow ordinary suspension/resumption, including delegated
iteration. Yield and return remain distinct consumers. This does not model
externally injected `throw()`/`close()` or asynchronous cancellation. A known
local load at `yield` does not create such an exceptional route.

For a `try` without `finally`, a synthetic dispatch point precedes each atomic
statement that might throw. Its success edge executes that statement; its
exception edge reaches one handler with the environment from the completed
prefix. The failed statement's result and assignment are absent. A completed
statement can therefore feed a handler entered by a later exception, but a
failed RHS cannot feed its own handler. An explicit raise terminates its normal
route. A loop's back edges revisit dispatch before condition/iterator evaluation.

Handler arms and the success `else` have separate continuations. Nested handlers
can propagate to outer handlers; a bare catch stops propagation. The local name
bound by `except E as name` loses its previous origin on entry and is invalidated
on fallthrough, break, continue and exceptional departure. A return evaluates its
operand before that cleanup.

The dispatch graph conservatively allows handler types: it does not establish
which exception class an expression can raise or resolve catch ordering by a
class hierarchy. Atomic expression evaluation can omit routes where a nested
operand completes before a later operand fails. These are source abstractions,
not an exception-sensitive runtime analysis or a sound security dataflow proof.

## Remaining boundaries

- `finally`, exception groups (`except*`) and calls in handler type expressions
  retain local CFG gaps. A `finally` overriding a return cannot create a row.
- Calls/writes inside conditional expression arms need expression CFGs; bare
  conditional aliases are the admitted case. Boolean-expression aliases and
  unknown values retain uncertain provenance.
- Dynamic locals, closure/class scopes, imports, `with` bindings and unsupported
  local writes do not get the new route-level provenance proof. Existing
  structural matching and uncertainty still apply.
- Heap aliasing, injected generator exceptions and all-path cleanup obligations
  are outside this expansion. The broader route policy applies to existential
  `call`/`let`/`return`/`yield` patterns, not to negated/all-path gap obligations.

IR 1.87 invalidates older persisted graphs. Public regressions live in
`tests/kql2/test_path_value_coverage.py` and `test_path_value_expressions.py`.
The Django comparison preserves the 14 original queries, project commit,
default language scope and warm-up protocol; the three focused probes are
reported separately.
