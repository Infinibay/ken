---
name: ken-understand-architecture
description: Explain how a request crosses modules and responsibilities in a Ken project. Use to map one subsystem or execution path, identify ownership, and understand delegation before changing architecture.
---

# Explain responsibilities along one real path

Choose an entry and an observable outcome: “How does the rebuild command update
the manifest?” A useful architecture answer shows who makes each decision and
what crosses each boundary. Examples below use MCP tool-call notation.

## Work through a command-to-file path

For a known CLI trigger, start with wiring:

```python
ken_find(query="rebuild", scope="wiring")
```

For a behavior without a known entry point, start with
`ken_who(question="Who rebuilds the cache manifest?", path="src")` instead.
Suppose the result names `src/cli.py::rebuild`. Read its body, then follow the
actual imported callable. Use a bounded role map if the neighborhood is unclear:

```python
ken_read(path="src/cli.py", qualname="rebuild", include=["source"])
ken_related(target="src/cache.py::Cache.refresh", relation="roles",
            path="src", depth=2, timeout_ms=10000)
```

Suppose the bodies establish this path:

```text
rebuild(args) -> Cache.refresh() -> scan(root)
                                -> write_manifest(path, entries)
```

Do not stop at the arrows. Read enough to fill this explanation with evidence:

| Boundary | Responsibility demonstrated by source | Data crossing it |
| --- | --- | --- |
| `rebuild` to `Cache.refresh` | CLI resolves user options and chooses a root | Root and output path |
| `Cache.refresh` to `scan` | Coordinator requests the current inventory | Root -> entries |
| `Cache.refresh` to `write_manifest` | Coordinator chooses what to persist | Output path and entries |
| `write_manifest` to filesystem | Writer serializes and replaces the file | Encoded bytes |

These are illustrative findings, not facts about the current project. Verify
each against the real source, including who chooses the path and owns failures.
An import map from `ken_related(target="src/cache.py", relation="imports", depth=1)`
helps resolve module boundaries; it does not establish runtime call order.

## If a role or boundary is uncertain

`roles` infers labels such as coordinator or executor from observed calls.
A leaf in that partial graph may call an unresolved plugin; an apparent entry
may have callers outside the scope. Read the relevant body before assigning
business ownership. Use `full=True` when the observations behind a label matter.

For a plugin dispatch, name the known interface, arguments, and unresolved target.
Follow registration or inspect a concrete configured implementation only if
needed for the requested explanation. Do not complete a diagram with a
same-named function that has no demonstrated connection.

Stop when the requested path is explained, with source links for responsibilities
and explicit unknown boundaries. Avoid mapping the whole repository to explain
one command. If there are several real implementations, show the common
interface and the relevant alternatives instead of pretending there is one path.

```sh
ken tools find rebuild --scope wiring
ken tools related 'src/cache.py::Cache.refresh' roles --path src --depth 2
```

Save a non-obvious architectural constraint with `ken_remember`, its source
dependencies, and assumptions when it would save future investigation. A list
of module names or a copied call graph alone is not such a constraint.
