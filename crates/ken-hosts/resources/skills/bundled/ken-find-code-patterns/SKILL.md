---
name: ken-find-code-patterns
description: Use when finding code requires KQL2 relationships such as ownership, exact call targets, returned values, operation order, or absence within each candidate.
---

# Turn a code question into a distinguishing relationship


For natural-language code discovery with `ken_find` or `ken_who`, write the
query in **English**, translating the user's intent yourself. Keep identifiers,
paths, quoted source, literal searches, regexes and KQL unchanged. Reply to the
user in their preferred language. Memory lookups keep exact stored topic keys
and use the language of the saved finding when appropriate.
Use KQL2 to perform the repeated relationship check that remains after finding
spellings: whose call, which declaration, the same produced value, or an operation
in the right context. Custom queries describe project conventions and ordinary
implementations as well as bug candidates; catalogs are reusable questions.

## Design the smallest useful query

1. State the desired result and its quantifier: one witness, an inventory, an
   absence within each owner, or an obligation on every path.
2. Put a matching fragment beside a near miss. Name the relationship separating
   them: ownership, target identity, value identity, order, or correlated absence.
3. Read the matching recipe below. Preserve its enclosing selectors and BODY
   structure; adapt names, paths and captures to the actual code.
4. Execute on the small fixture, then the relevant project scope. Select owners
   with source locations and the few witnesses needed to assess the answer.

For spelling alone use literal text search; for a documented responsibility use
`ken_who`. Start directly with KQL2 when the relationship is known. Scope must
retain required declarations and imports. `module` is the query namespace;
`path` selects source. Two similarly named captures need not be distinct, and
names alone do not establish target identity.

## Load the reference for the current question

| Need | Read | Backend |
| --- | --- | --- |
| First query, selectors, distinct captures, per-owner absence | [Query basics](references/kql2/README.md) | indexed |
| Value returned from an exact target, aliases, reusable patterns | [Values and targets](references/kql2/values-and-patterns.md) | indexed |
| Save a tested query, discover existing modules, import project patterns | [Saved modules](references/kql2/saved-modules.md) | indexed |
| Compose call ownership, target identity and order | [Worked investigation](references/kql2/relationships.md) | indexed |
| Syntax containment, literals, handler-local absence | [Syntax recipes](references/kql2/syntax.md) | exploration |
| Semantic graph relations or hazard facts | [Graph recipes](references/kql2/graph-queries.md) | indexed |
| Every modeled normal path of a Python function | [Path contracts](references/kql2/path-contracts.md) | specialized tools |

The references contain complete programs and contrasting fixtures. Check the
intended backend with `ken kql2 /tmp/query.kql --backend indexed --explain`.
Indexed supports BODY; MCP KQL2 uses indexed and has no backend argument.
Use the direct CLI with `--backend exploration` for the syntax-only recipes.

## Execute, inspect, refine

With the complete indexed program in `source`:

```python
ken_find(scope="structure", query_language="kql/2", query=source,
         path="src/storage", limit=20)
```

CLI: `ken kql2 /tmp/query.kql --root /project --path src/storage --max-rows 20`.
For timing and optional deadlines, see [budgets and preparation](references/kql2/README.md#budgets-and-preparation).

Compare hits with the near miss. A wrong hit needs the missing relationship;
a missing known positive needs one constraint isolated at a time. For an unknown
return, use the complete [candidate recovery query](references/kql2/values-and-patterns.md#investigate-an-unknown-on-real-code), retaining BODY for a bound target.
Read diagnostics and request `full=True` when compact evidence is insufficient.
Absence requires complete coverage, zero unknowns and no truncation; a complete
execution alone is insufficient. A BODY witness does not prove every path.

Report the question, encoded relationship, scope, source locations and supported
conclusion. Add what source reading or a behavioral test established separately.
Use a catalog when its question fits, a named pattern for a recurring relation,
and a validated rule when the user requests an enduring project obligation.
For a recurring search, inspect `ken_query(action="list", prefix="project.")`
before duplicating it. Read a candidate with `show` to check its scope and
quantifier; save a useful tested module when the task calls for reuse. Execute
it with `ken_find(..., saved_query="project.module", query_name="entry")`.
