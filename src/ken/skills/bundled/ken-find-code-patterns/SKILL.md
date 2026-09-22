---
name: ken-find-code-patterns
description: Find implementations, conventions, or bug hypotheses by code relationships using KQL2. Use when matching text still leaves manual checks of ownership, call targets, returned values, ordering, or correlated absence.
---

# Turn a code question into a relationship

KQL2 describes the condition that makes code relevant: who owns a call, which
implementation it invokes, where its result goes, or how operations relate.
Use it to replace repeated manual checks across text-search results. It can
find ordinary implementation patterns and project conventions as well as bug
candidates. The built-in catalogs are reusable questions, not the language's
expressive limit.

## Start from the difference you need to recognize

1. State the question and put a matching fragment beside a similar non-match.
   For “Which wrappers forward a saved identifier?”, compare `return save()`
   with `save(); return 0`, and with overwriting the result before returning it.
2. Name the distinguishing relation: the returned value must come from that
   call. Presence of the word `save` or even an actual call is insufficient.
3. Express the relation with the smallest query that distinguishes the cases.
   Test them together, then use the query on the relevant project scope.
4. Read the returned owners and witnesses. Reproduce behavior when the task
   requires a bug diagnosis; for a structural inventory, report the pattern
   and locations it actually established.

Start directly with structural search when the relationship is already known.
Use `ken_find(scope="text", literal=True)` or `rg` when spelling alone answers
the question, and `ken_who` when locating a documented responsibility is enough.
If several text matches require the same ownership/identity/flow check, express
that check once in KQL2 instead of repeating it by hand.

## Choose a worked example, then adapt it

For a first investigation, read [from text to relationships](references/kql2/relationships.md).
It evolves a real-shaped publication question through four executable queries:
call owners, exact targets, operation order, then their composition. It includes
same-named decoys, reversed order and mutually exclusive branches, and explains
what manual work each query replaces. All four use **indexed**.

Use the more specific chapter when the needed relation is already clear:

| Relationship | Read | Backend |
| --- | --- | --- |
| Ownership, distinct identities, optional methods | [Selectors and captures](references/kql2/README.md) | indexed |
| Produced/returned value, bound call target, reusable pattern | [Values and patterns](references/kql2/values-and-patterns.md) | indexed |
| Literal, syntax containment, correlated absence | [Syntax recipes](references/kql2/syntax.md) | exploration |
| Explicit graph relation or an existing hazard fact | [Graph recipes](references/kql2/graph-queries.md) | indexed |

The references teach syntax with complete programs; do not invent properties
from a query-language analogy. `body` and `return $value` work in indexed.
`ken kql2 /tmp/query.kql --backend indexed --explain` checks support before
acquisition. Substitute exploration for the syntax recipes.
MCP `ken_find` currently uses indexed for KQL2 and has no backend argument;
run exploration queries through the direct `ken kql2` CLI.

## Execute and inspect the next useful evidence

With a complete indexed query in `source`, a bounded initial MCP search is:

```python
ken_find(scope="structure", query_language="kql/2", query=source,
         path="src/storage", limit=20, timeout_ms=10000)
```

For a saved query file, including exploration recipes:

```sh
ken kql2 /tmp/query.kql --root /project --path src/storage --backend indexed --max-rows 20 --timeout-ms 10000
```

Choose scope from the code, retaining required target declarations/imports.
The `path` argument scopes structural searches; it currently does not constrain
`ken_find(scope="text")`. Use `rg` with an explicit directory for scoped text.
Start with compact MCP results; project the owner and the few operation/value
witnesses needed to answer the question. Read `diagnostics` when the relationship
looks wrong, and use `full=True` for evidence that the compact result omits.
For unresolved value relationships, follow the [unknown-result workflow](references/kql2/values-and-patterns.md#investigate-an-unknown-on-real-code).
For absence, inspect completeness, coverage, unknowns and truncation. A budgeted
candidate list is useful even when it cannot establish exhaustive absence.

If a near miss matches, add the missing relationship. If a known positive is
missing, isolate the failed constraint on the fixture. If preparation dominates,
read `timing`/`stopped_phase` and narrow scope; dropping a target or order condition
changes the question and should be labeled as a broader candidate search.

Use `scope="patterns"` or `scope="bugs"` when a catalog question fits, or to get
leads in unfamiliar code. Low signal from one catalog sweep does not establish
what custom KQL2 can find. Saved rules use `rules=["project.rule"]` separately
from inline query text. Name a recurring query as a reusable pattern; adopt a
validated contract when the user wants a project obligation enforced.

Report the question, relationship searched, relevant locations, and what reading
or reproduction added. A query that finds publication owners contributed
localization; attribute an ordering finding only to a query that expresses order.
