---
name: ken-locate-code
description: Find where a behavior is implemented or an entry point is handled in a Ken project. Use for questions such as who writes this file, where this option is consumed, or which function owns this behavior.
---

# Find the code that actually does the work

The answer is a declaration plus source evidence that it performs the requested
behavior. A documentation match gets you to a candidate; reading its delegation
gets you to the implementation.

Examples below use MCP tool-call notation, not Python imports. CLI equivalents
run from the project root; `ken tools --path /project ...` selects another project.
Replace illustrative paths with the paths the tools return.

## Work through: “Who writes the cache manifest?”

Start with a relevant file or symbol already supplied in context. Otherwise:

```python
ken_who(question="Who writes the cache manifest?", path="src")
```

Suppose the candidates include `Cache.refresh` and `write_manifest`. Read the
best candidate's body, rather than choosing the highest score as the answer:

```python
ken_read(path="src/cache.py", qualname="Cache.refresh", include=["source"])
```

Suppose that source is:

```python
def refresh(self):
    entries = self.scan()
    write_manifest(self.path, entries)
```

This method coordinates refresh, but delegates the write. Read its import to
resolve `write_manifest`, then read the returned declaration:

```python
ken_read(path="src/cache.py", include=["imports"])
ken_read(path="src/manifest.py", qualname="write_manifest", include=["source"])
```

If that body serializes `entries` and calls `path.write_text`, the answer is:
“`src/manifest.py::write_manifest` writes the file; `Cache.refresh` supplies the
entries and invokes it.” Link the actual source lines for both statements.
If it delegates again, follow that specific boundary until you can distinguish
the public operation from the implementation of the requested effect.

## Choose a different first step when the clue changes

| What you already know | Ask Ken | What to read next |
| --- | --- | --- |
| Exact identifier or error text | `ken_find(query="CACHE_DIR", scope="text", literal=True)` | The definition and relevant use |
| Function or class purpose | `ken_find(query="serialize cache manifest", scope="symbols")` | The best declaration |
| File responsibility | Same question with `scope="files"` | Its outline, then one body |
| Route, CLI option, or environment variable | `scope="wiring"` with that trigger | The registration and handler |

`ken_read(path=...)` gives an outline when the qualified name is unknown.
`who` uses documentation from modules, classes, methods, and functions; it does
not require a previously saved finding. Its score ranks candidates and is not a
probability of correctness. Structural verification also does not prove a
natural-language docstring.

## If the result is ambiguous or empty

If `who` reports ambiguity, identify the difference that matters: “creates the
manifest contents” versus “writes bytes,” for example. Read those two bodies;
use `full=True` only if the candidate evidence is needed. For documentation in
another language, explicit alternative `hypotheses` can help, but the source
must still support the answer.

After two unhelpful Ken searches, open the likeliest file or use `rg` on live
source. Do not keep rephrasing the same request. Report an unresolved boundary
if a dynamic or external call prevents locating the implementation.

```sh
ken tools who 'Who writes the cache manifest?' --path src
ken tools read src/cache.py --qualname Cache.refresh --include source
```

Stop when you can name the responsible declaration, distinguish any wrapper,
and explain the relevant lines. A list of candidates alone is unfinished work.
