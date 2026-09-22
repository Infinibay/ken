# KQL2: from a source question to an executable query

KQL2 searches relationships in code. It lets you express the repeated manual
check after a text search: which function owns a call, which implementation it
invokes, whether its result is returned, or which local convention is satisfied.
Use it for implementation discovery, architecture, bug hypotheses and project
invariants. Built-in bug/pattern catalogs supply predefined questions; custom
queries express relationships specific to the project.

For a worked investigation, start with [from text matches to relationships](relationships.md):
compare similar source fragments, express their difference, inspect candidates,
and reproduce the remaining behavioral hypothesis. It evolves a publication
query from call names to exact targets and supported operation order. Each step
shows the manual inspection it replaces and the misleading cases it excludes.

Use text search directly when a spelling answers the question. Start with KQL2
when the relationship is known; a preliminary grep is not required. This guide
covers a tested authoring subset, not every production in the design grammar.
Examples target Python; frontend evidence can differ in other languages. The
installed query-authoring skills carry this guide and its fixtures.

Choose the profile before copying syntax:

| Question | Backend | Reference |
| --- | --- | --- |
| Does a handler contain an explicit continue? Is the loop condition literally True? | `exploration` | [Syntax, correlation and literals](syntax.md) |
| Which function owns a call or forwards its returned value? | `indexed` | This page and values below |
| Which concrete confirmation precedes a publication? | `indexed` | [Composing identity and order](relationships.md) |
| Where is a supported hazard, or which declaration is a call target? | `indexed` | Graph queries below |

`ken kql2 --capabilities` lists supported syntax properties from the engine.
`ken kql2 /tmp/lesson.kql --backend exploration --explain` checks a query without
scanning source. Use the intended backend; BODY is available in indexed.

Read this page for indexed selectors, captures, joins, and result interpretation.
Continue with [values and reusable patterns](values-and-patterns.md) when the
question involves returns, callable identity, or reusable query libraries.
Use [graph queries](graph-queries.md) for explicit semantic relationships and
built-in hazard facts and supported composition with source selectors.

## Try the examples on a small project

The supplied [sample source](sample.py.txt) contains `save_user` (returns a saved
ID), `discard_user` (discards it), `overwrite_user` (overwrites it), a mutable
default, and two classes. Copy it to a disposable project as `src/sample.py`:

```sh
# Run from this references/kql2 directory; mktemp chooses a fresh project.
example_root=$(mktemp -d)
mkdir -p "$example_root/src"
cp sample.py.txt "$example_root/src/sample.py"
```

Save any complete KQL block below as `/tmp/lesson.kql`, then run:

```sh
ken kql2 /tmp/lesson.kql --root "$example_root" --path src
```

In a source checkout, `.venv/bin/python -m ken` can replace `ken`. This direct
query command does not require installing skills or adopting a contract in the
fixture. Its output includes `rows`, coverage, and budgets. Project rules are
introduced separately in the regression skill.

## 1. Name the property before choosing syntax

Question: “Which functions contain a call named save?”

```kql
language "kql/2";
module lesson.calls;
query named_calls {
  callable $owner {
    call $site { name: "save"; }
  }
  select $owner.name;
}
```

On the sample, the rows name `save_user`, `discard_user`, `overwrite_user`, and
`write`. The latter is a method: `callable` includes functions and methods.
The query does not say the call result is returned. That requires a value
relationship, shown in the next chapter.

- `language "kql/2";` selects the language version.
- `module lesson.calls;` names the **query namespace**, not a source directory.
  The execution argument `path="src"` selects source scope.
- `query named_calls { ... }` is the entry point. Use descriptive non-keyword
  names: `query body` and `query optional` are invalid because those are keywords.
- `$owner` is a capture for a declaration, `$site` for a call occurrence. They
  are query variables, not source variable names. `name: "save";` matches a
  source name. Semicolons terminate properties and statements.
- Nesting `call` inside `callable` asks for calls belonging to that owner.
  Every required clause must match; this is an existential search for witnesses.
- `select` determines returned columns. `$owner.name` projects a string;
  `$owner` returns an entity object with identity and source location. Prefer
  entities when you need to inspect hits with identical names.

To send the same program through MCP, pass its text as `query`:

```python
ken_find(scope="structure", query_language="kql/2", query=source,
         path="src", limit=20, timeout_ms=10000)
```

Here `source` means the complete program above; this is MCP-call notation.
CLI equivalent for inline text:

```sh
ken tools find 'language "kql/2"; module lesson.calls; query named_calls { callable $owner { call $site { name: "save"; } } select $owner.name; }' \
  --scope structure --query-language kql/2 --path src --limit 20
```

### Current interface boundaries

MCP `ken_find` uses **indexed** for KQL2 and does not expose a backend argument.
Use `ken kql2 FILE --backend exploration` for the syntax recipes. A direct
Python call to `ken.kql2.service.search` exercises the engine; report it as such
when evaluating usability or timing instead of attributing it to the MCP tool.

`path` scopes the structural searches shown here. It currently does **not**
filter `ken_find(scope="text")`; that scope searches the project worktree.
For a directory-bounded literal search, use `rg -n -F 'replace' src/storage`.
A selector's `path:` property constrains a captured declaration within the
acquired source scope; it does not expand that scope to missing dependencies.

## 2. Constrain ownership and names

Question: “Which Writer method has one of these operation names?”

```kql
language "kql/2";
module lesson.declarations;
query selected_methods {
  class $type {
    name: /^(Writer|ReadOnly)$/;
    method $method { name: /^(write|read)$/; }
  }
  where $type.name != "ReadOnly";
  select $type.name, $method.name;
}
```

Expected row: `["Writer", "write"]`. The method belongs to the captured class;
this does not combine an unrelated class and a globally found method.
`where` adds a predicate after binding its captures. Equality between captures
compares identity; equality between `.name` values compares spelling.

Use exact double-quoted strings for exact names, `/pattern/` for regular
expressions (`/^prefix/i` for case-insensitive prefix), integers for positions,
and `true`/`false` for boolean properties. For example, a nested
`param $input { position: 0; }` selects the first explicit parameter, excluding
a method receiver. Property values depend on the selected kind and frontend;
missing metadata may leave a candidate unknown.

Lists are **context-specific**: `name: ["save", "persist"];` is supported on
BODY calls, and graph fact filters accept lists. The declaration selector
`method { name: ["write", "read"]; }` is rejected by the current compiler.
Use a regex or alternatives there. A quoted `"write|read"` is a literal name,
not an alternative. Do not infer executable support from the broad parser grammar.

## 3. Join by identity, and require distinct captures when needed

Question: “Which class owns two different methods?”

```kql
language "kql/2";
module lesson.identity;
query method_pairs {
  class $type {
    method $first {}
    method $second {}
  }
  where $first != $second;
  select $type.name, $first.name, $second.name;
}
```

Expected rows are Writer's `(write, close)` and `(close, write)` pairs. Different
capture names alone do not require different entities. Reusing a bound capture
constrains that same entity; it is not a new scan with an unrelated identity.
Two unrelated top-level selectors can form combinations: express containment or
a shared capture when a relationship is part of the question.

## 4. Alternatives, correlated absence, and optional evidence

Use alternatives when either structure answers the question:

```kql
language "kql/2";
module lesson.choices;
query selected_wrappers {
  { callable $owner { name: "save_user"; } }
  or
  { callable $owner { name: "discard_user"; } }
  select $owner.name;
}
```

Expected names: `save_user`, `discard_user`. An output capture must be bound in
**every** branch. Selecting `$first` when only one branch binds it is an error.

To find classes without their own `close` method, correlate the absence to the
outer class:

```kql
language "kql/2";
module lesson.absence;
query missing_close {
  class $type {
    not exists { method $method { name: "close"; } }
  }
  select $type.name;
}
```

Expected name: `ReadOnly`. `Writer.close` must not suppress the result for
`ReadOnly`. A top-level `not exists { class ... }` instead asks about absence
in the selected project domain. Local captures inside `not exists` do not
escape. Absence needs a closed, sufficiently analyzed domain; unknown coverage
is not a negative witness. This example concerns directly owned methods, not a
universal claim about inherited runtime access.

If the method is useful evidence but not a requirement:

```kql
language "kql/2";
module lesson.annotations;
query optional_close {
  class $type {
    optional { method $method { name: "close"; } }
  }
  select $type.name;
}
```

Both classes remain. Full output's `optional_evidence` records `matched` for
Writer and `absent` for ReadOnly; incomplete analysis can produce `unknown`.
The optional capture cannot be selected outside the block. This is evidence
annotation, not SQL's nullable output column.

## 5. Decide what the result actually establishes

An abridged direct-query result for `missing_close` is:

```json
{"rows": [["ReadOnly"]], "complete": true, "coverage_complete": true,
 "unknown_candidates": 0, "results_truncated": false}
```

`ken_find` presents a compact wrapper instead; request `full=True` or `--full`
for detailed query evidence. Do not assume all wrappers have identical JSON
nesting. Inspect the installed tool's result rather than inventing field paths.

| Observation | Permitted next step |
| --- | --- |
| A row with a source location | Read the source and check it matches the intended property |
| No rows, complete coverage, zero unknowns, no truncation | Report no matches for **this property in this scope** |
| Timeout, incomplete coverage, unknowns, or truncation | Narrow scope or investigate the limit; do not report absence |
| Compilation error | Correct the query's syntax/semantics; do not silently weaken it |

Start on a small relevant scope. Preparation can dominate runtime;
`ken_find`'s `timeout_ms` covers compilation, cache acquisition, indexing, and
query execution. Compact responses include `timing`; an interrupted request
also reports `stopped_phase` and preparation progress. A timeout during `parse`
or `link` means preparation consumed the budget, not that the property was
checked and absent. Narrow the scope or explicitly allow a larger budget.
A result limit also prevents interpreting an empty or partial report as exhaustive.
The direct `ken kql2` command returns exit 2 for an error and 3 for incomplete
execution; a completed command can still have uncertainty or truncated rows.
Inspect the JSON before concluding anything about the code.

When a query surprises you, reduce it to the selector that should find one
known entity, add one constraint at a time, and compare a positive source with
a nearby negative. If a property name or graph attribute yields zero rows,
first check a positive fixture: some invalid metadata assumptions produce empty
results rather than a useful compiler error.

Read authoring `diagnostics` in both compact and full results. Warnings about
independent captures or global negation explain the executed meaning; they do
not change it. Complete coverage cannot compensate for a missing relationship.
The [syntax chapter](syntax.md) reproduces these mistakes with mixed positive
and negative examples and gives their corrected queries.
