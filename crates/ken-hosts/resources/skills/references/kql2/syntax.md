# Inspect syntax without inventing a relationship

Use `--backend exploration` for syntax nodes, immediate children, descendants,
and spelling. It does not infer call targets, value identity, implicit `continue`,
or exception propagation. Use `--backend indexed` for declarations, BODY value
flow, and graph facts. BODY is implemented in indexed; an exploration capability
error does not mean BODY is missing from KQL2.

## Compile before acquiring the project

```sh
ken kql2 /tmp/lesson.kql --backend exploration --explain
ken kql2 --capabilities
```

`--explain` validates the selected backend and returns authoring `diagnostics`
without scanning the project. It is not an execution or a positive fixture.
The capability listing reads the same syntax property/relationship definitions
used by the compiler. A successful explanation is not proof that a query encodes
your question. Graph plans currently have no capture-composition lint.

For each recipe below, copy [syntax.py.txt](syntax.py.txt) into a disposable
project as `src/syntax.py`. Save the complete query to `/tmp/lesson.kql`:

```sh
example_root=$(mktemp -d)
mkdir -p "$example_root/src"
cp syntax.py.txt "$example_root/src/syntax.py"
ken kql2 /tmp/lesson.kql --root "$example_root" --path src --backend exploration
```

The CLI command above is the portable entry point for this backend; do not add
an unsupported backend argument to an MCP tool. `ken_find` uses indexed and also
preserves authoring diagnostics in its default compact result.

## Existence is different from containment

This fragment has **two independent captures**:

```text
node $handler { kind: "catch"; }
node $next { kind: "continue"; }
select $handler;
```

One `continue` anywhere in the scope is enough to combine with every handler.
Repeated projected handlers are deduplicated, so a result count equal to the
number of handlers does not show that every handler continues. Ken reports
`disconnected_captures`; it still executes this valid Cartesian query.

To ask which handler contains an explicit continue, state the relationship:

```kql
language "kql/2";
module lesson.syntax;
query handlers_with_continue {
  node $handler { kind: "catch"; }
  node $next { kind: "continue"; }
  where contains($handler, $next);
  select $handler.line, $next.line;
}
```

Expected row: `[17, 18]`, the handler in `retries`. The other two handlers must
not match. Projecting the witness helps verify the relationship on source.
There is no inference of an *implicit* continue here. A nested loop's continue
also differs from continuing the handler's surrounding loop; use control-flow
relations or read the source when the destination matters.

## Negation must have the intended scope

```text
node $handler { kind: "catch"; }
not exists { node $raised { kind: "throw"; } }
select $handler;
```

This is global absence of any throw node in the selected scope. The `raise`
in `reraises` makes it return no handlers, including `ignores`. Ken reports
`uncorrelated_exists`; global absence can be intentional and remains legal.

To search each handler separately:

```kql
language "kql/2";
module lesson.syntax;
query handlers_without_raise {
  node $handler { kind: "catch"; }
  not exists {
    node $raised { kind: "throw"; }
    where contains($handler, $raised);
  }
  select $handler.line;
}
```

Expected lines: `10` and `17`. This means “no descendant throw syntax,” not
“swallows every exception.” Calling another function may raise; returning an
explicit failure value or intentionally retrying can be legitimate. Conversely,
a raise inside a nested function is a syntactic descendant without establishing
that the handler propagates. Read the actual behavior before calling it a bug.

## Immediate children, descendants, and literals

Nested `node` selectors require an **immediate child**. `contains_direct(a,b)`
states the same relation; `contains(a,b)` asks for any strict descendant.
`parent:` is not a property. Conditions, block contents and literal spelling
need separate constraints:

```kql
language "kql/2";
module lesson.syntax;
query literal_true_loops {
  node $loop {
    kind: "while";
    node $condition { role: "condition"; kind: "literal"; text: "True"; }
  }
  select $loop.line;
}
```

Expected line: `21`. `while pending:` at line 25 must not match. Finding an
unrelated literal elsewhere does not constrain the loop's condition. This
recipe says nothing about termination: `forever` actually contains a break.

Use `text`, not `value`, to match literal source spelling. Query booleans
(`true`/`false`) and source text (`"True"` in Python) are different:

```kql
language "kql/2";
module lesson.syntax;
query explicit_return_none {
  node $ret {
    kind: "return";
    node $value { kind: "literal"; text: "None"; }
  }
  select $ret.line;
}
```

Expected line: `29`; `return 1` must not match. Python `None` is a literal, not
an identifier named `None`. Bare `return` and implicit fallthrough are different
syntax and are not included by this query.

Canonical node kinds use `catch` and `throw` across supported languages. For
parser-specific shapes, use `native_kind`; an unfamiliar canonical kind gets
an `unknown_syntax_kind` warning. For example, wildcard import has its own node:

```kql
language "kql/2";
module lesson.syntax;
query wildcard_imports {
  node $import {
    native_kind: "import_from_statement";
    node $star { native_kind: "wildcard_import"; }
  }
  select $import.line;
}
```

Expected line: `34`; the named import on line 35 must not match. An identifier
named `*` would miss the positive case. `text` is available on literals and
leaves; it is not arbitrary full-subtree source text.

## Interpret the evidence

If counts look suspiciously identical, inspect `diagnostics` and temporarily
select both the candidate and witness locations. Test a mixed file containing
both a match and a near miss: separate all-positive/all-negative files can hide
global-correlation mistakes. Change only the relationship being investigated.

`complete` and `coverage_complete` describe execution and acquisition of the
chosen scope. They do not validate the query's intent. No rows only establish
absence of the exact tested property, with complete coverage, no unknown
candidates and no truncation. Never summarize a bare node count as “all errors
are handled correctly.”
