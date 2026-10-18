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
asynchronous cancellation. Injection is explicit in the query; a known local
load at `yield` does not invent an exception under ordinary resumption.

```kql
// Inside a callable BODY:
yield _;
resume close;
call $cleanup { name: "close"; };
```

`resume next;`, `resume throw;` and `resume close;` must immediately follow a
matched yield. `throw` selects an injected exception of unspecified type;
`close` injects GeneratorExit and follows cleanup until that invocation ends.
A close that yields outward fails with RuntimeError: it delivers no yield and
does not execute the tail during that close. A later invocation after that
failed close is outside this successful-yield interaction syntax. Injected
`yield from` protocols and yields inside complex expression carriers remain
uncertain, rather than being treated as ordinary fallthrough.

For a `try`, a synthetic dispatch point precedes each atomic
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

## Pending completions and exception groups

IR 1.88 routes normal exit, return, raise, break and continue through finally.
`structural/control_completions.py` owns the continuation points; the immutable
`kql2/body_continuations.py` state owns their path-local guards. The syntax IR
contains no synthetic operations. A shared finalizer can resume only its own
pending destination. Return operands are captured before cleanup mutates locals.
A finalizer's abrupt exit may replace that completion; a failed inner return
caught inside an outer finalizer restores the suspended outer completion.

`except*` visits zero or more matching subgroups in source order, retaining
completed writes across arms. An exception raised by an arm is held until the
remaining arms finish, then propagated together with any unmatched remainder.
No successful continuation follows a raised portion. A successful BaseException
catchall has no unmatched remainder. Selected, unshadowed builtin headers cannot
consume the same subtype twice. Source binding references keep imported,
shadowed and custom exception types uncertain for GeneratorExit matching.
The unknown exception types produced by arbitrary expressions still have no
runtime type or feasibility proof. Ordinary except siblings remain exclusive.

The language rules are checked against Python 3.12 runtime contrasts and the
[finally reference](https://docs.python.org/3.12/reference/compound_stmts.html#finally-clause),
[except* reference](https://docs.python.org/3.12/reference/compound_stmts.html#except-star),
and [generator methods](https://docs.python.org/3.12/reference/expressions.html#generator-iterator-methods).

## Remaining boundaries

- Calls in dynamic handler type expressions retain local CFG gaps.
- Calls/writes inside conditional expression arms need expression CFGs; bare
  conditional aliases are the admitted case. Boolean-expression aliases and
  unknown values retain uncertain provenance.
- Dynamic locals, closure/class scopes, imports, `with` bindings and unsupported
  local writes do not get the route-level provenance proof. Existing
  structural matching and uncertainty still apply.
- Heap aliasing, asynchronous cancellation, delegated injected protocols,
  expression-level suspension and all-path cleanup obligations remain outside
  this expansion. The route policy applies to existential
  `call`/`let`/`return`/`yield`/`resume` patterns.

IR 1.88 invalidates older persisted graphs. Public regressions live in
`tests/kql2/test_completion_paths.py`, `test_completion_regressions.py`,
`test_path_value_coverage.py` and `test_path_value_expressions.py`.
The Django comparison preserves the 14 original queries, project commit,
default language scope and warm-up protocol; the three focused probes are
reported separately.
