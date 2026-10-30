# Save a useful search and compose its patterns

Use the registry for recurring searches and project relationships. Modules are
stored per project in `.ken/ken.db`, survive restarts and structural cache
cleanup, and remain available to inline or saved queries. Each module owns its
queries, patterns and auxiliary declarations. A module name is a KQL namespace;
the execution `path` still selects the code to inspect.

## Discover before recreating

```python
ken_query(action="list", prefix="lesson.", limit=50, offset=0)
existing = ken_query(action="show", module="lesson.client")
```

`list` returns metadata, exported query/pattern names, imports and revisions;
paginate with `offset` up to `total`. `show` includes full source. Inspect the
encoded relationship, quantifier and required inputs before reusing a module.
Descriptions should state the question answered and its limits, not claim a
stronger guarantee than the query establishes.

## Save the working example

First run the matching and near-miss fixtures in the
[values chapter](values-and-patterns.md#give-a-repeated-concept-a-name).
Use its complete `lesson.writers` library as `/tmp/writers.kql` and its
`lesson.client` query as `/tmp/writer-query.kql`. Save dependencies first:

```sh
ken kql2 /tmp/writers.kql --root "$example_root" --save \
  --description "Types owning a method named write; existential source witness"
ken kql2 /tmp/writer-query.kql --root "$example_root" --save
ken kql2 --saved lesson.client --query imported_writer \
  --root "$example_root" --path src
```

Expected row on the sample: `["Writer", "write"]`. The saved library resolves
automatically; no `--library` is needed. Inline queries importing it work too.
`--query` chooses one entry when a module contains several queries. A module
containing only patterns can be imported but cannot be executed as a query.

For MCP, `library_source` and `entry_source` mean the complete two programs from
that chapter, not paths or abbreviated KQL:

Restart an already-running MCP server after upgrading Ken so it publishes
`ken_query` and the new `ken_find` parameters.

```python
ken_query(action="save", source=library_source,
          description="Types owning a method named write; existential witness")
ken_query(action="save", source=entry_source)
ken_find(scope="structure", query_language="kql/2",
         saved_query="lesson.client", query_name="imported_writer", path="src")
ken_find(scope="structure", query_language="kql/2", query=entry_source, path="src")
```

`ken tools query --action list` and `ken tools query --action show --module
lesson.client` expose the same management API in a Ken-initialized project.
`ken tools find --scope structure --query-language kql/2 --saved-query
lesson.client --query-name imported_writer --path src` executes by name.
With a standalone fixture, use the direct `ken kql2 --root` commands above;
ordinary `ken tools` needs project initialization (`ken install --no-wire`).

## Compose patterns with explicit bindings

`import lesson.writers;` loads declarations; `use
lesson.writers.WithWrite(type:$owner, method:$action);` composes the pattern.
Bind `in` parameters before `use`; consume the named `out` captures afterward.
Patterns may call imported patterns transitively. Private captures remain local.
Imported queries with `select` do not become relations or entrypoints: execute
them by module/query name, and factor the reusable relationship into a pattern.
Pattern recursion remains unsupported. Imports may form cycles without running
initializers; this does not make recursive pattern expansion valid.

Explicit CLI `--library` or MCP `libraries={module:source}` takes priority over
the saved module, including its transitive imports. This is useful to test a
candidate revision before replacing it. Built-in `ken.core` and `ken.catalog.*`
namespaces cannot be overwritten in the registry. Missing imports fail clearly;
save them first. Saving validates syntax and import availability; use `--explain`
with the intended backend or execute against fixtures to verify actual support.

## Update deliberately and inspect the result

```python
old = ken_query(action="show", module="lesson.writers")
ken_query(action="save", source=revised_library_source,
          expected_revision=old["revision"], description="Revised convention")
```

CLI equivalent: `ken kql2 /tmp/writers.kql --root "$example_root" --save
--expected-revision CURRENT_REVISION`. Identical saves are idempotent; changed
contents require the current revision to prevent overwriting another edit.
On a conflict, read and reconcile the source rather than blindly retrying.

Each request uses one registry snapshot. A later request sees committed updates,
and the compiled-plan key includes resolved source text. No source-index rebuild
is needed for a library edit. Full results expose used revisions in
`analysis.registry_modules`; compact MCP exposes `registry_modules`. Execution
still reports coverage, unknowns and truncation. Reuse does not strengthen the
evidence, and saved searches do not cache answers in prepared sessions. Timing
includes registry resolution; see [budgets and preparation](README.md#budgets-and-preparation).

Delete consumers before their dependencies. `ken_query(action="delete",
module="lesson.client", expected_revision=existing["revision"])` refuses a stale
revision or deletion of a module still imported by another saved module.

## A saved query and an adopted contract have different jobs

`ken_query` retains reusable searches. `ken_rule` adds examples, validation and
explicit enablement for an enduring obligation. Creating/updating a contract
copies resolved registered library sources into its definition so validation
continues to describe that exact rule after registry edits. To adopt new imports,
update the rule from the intended query and library inputs, validate and enable
again. Supplying a prior full definition with old `libraries` intentionally keeps
those explicit sources. Neither registry storage nor source validation proves
runtime behavior or all-path correctness.
