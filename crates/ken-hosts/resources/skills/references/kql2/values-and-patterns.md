# Values, call targets, and reusable patterns

Start with the [basic query guide](README.md). Every example here runs against
its [sample source](sample.py.txt). These queries inspect source relationships;
they do not execute `save`, establish persistence, or prove all runtime paths.

These recipes require `--backend indexed` (the CLI default). `body` and
`return $value;` are executable in this backend. Exploration cannot track this
value flow. Check a complete query with `ken kql2 /tmp/lesson.kql --explain`
before broadening source scope. A parser error such as `unexpected constraint`
is different from a backend capability error: preserve the enclosing
`callable { body { ... } }` structure shown below.

## Follow a call's result, not just its presence

Question: “Which user wrapper returns the value obtained from saving?”

The distinguishing relationship is **produced value -> returned value**. Text
search can find `save` and `return` in all three wrappers below; ownership alone
only establishes that both occur in the function. Capturing the value removes
the manual task of tracing which assignment reaches the return.

```kql
language "kql/2";
module lesson.values;
query forwarded_result {
  callable $owner {
    name: /_user$/;
    body {
      let $value = call $site { name: ["save", "persist"]; };
      return $value;
    }
  }
  select $owner.name;
}
```

Only `save_user` matches on the sample. Compare the evidence:

```python
# Matches: the produced value reaches the return.
def save_user():
    return save()

# Does not match: the saved value is discarded.
def discard_user():
    save()
    return 0

# Does not match: reusing the variable's spelling does not preserve its value.
def overwrite_user():
    result = save()
    result = 0
    return result
```

`body` enters a callable's source operations. `let $value = call ...;` captures
the produced value; it does not require a source variable called `value` or a
separate assignment statement. `return $value;` requires that captured value at
a return. A call occurrence (`$site`), its result (`$value`), a source storage
place (`result`), and a callable declaration are different concepts.

BODY patterns normally permit intermediate source instructions; do not read
the written statements as automatically adjacent. The engine has narrower
explicit sequence/control capabilities, but this recipe does not promise
arbitrary control-flow equivalence, effects, or proof on all branches. Extend a
recipe only after validating the extra condition with a near-miss example.

In the Python statement CFG, `with` preserves its body's normal branches and
abrupt exits; `raise` ends that path. A `try` region whose handler/else/finally
paths are not covered stays a local coverage gap. A complete witness before an
unrelated gap can remain valid; a relationship crossing or depending on that
gap remains unknown. The engine must not join mutually exclusive handler arms
by their lexical order. This describes supported statement paths, not arbitrary
exception behavior, context-manager suppression, or all runtime executions.

CLI and MCP automatically prepare and retain BODY's demanded facts for their
source revision. Initial preparation and source-update waits appear separately
in `analysis.preparation_ms` and `analysis.index_wait_ms`; they are not ready-query
latency. `analysis.semantic_storage` reports `shared_disk` or the session-owned
temporary `session_disk` spill. Repeated queries reuse facts, not answers or
bindings. A changed source revision releases the old index; a refresh that finds
the identical snapshot can keep its still-live reader. The private spill must be
prepared again after the service stops. No manual semantic warmup is needed in
these automatic frontends. Embedded `QuerySession` callers use
`prepare_query(...)` explicitly before measuring.

The name filter above accepts calls with either spelling. It alone does not
resolve which implementation `save` denotes. If that identity matters, bind it.

## Match an already identified callable

```kql
language "kql/2";
module lesson.targets;
query returned_target {
  callable $target { name: "save"; }
  callable $owner {
    name: /_user$/;
    body {
      let $value = call $target {};
      return $value;
    }
  }
  select $owner.name;
}
```

Expected name: `save_user`. Here `$target` was already bound to a callable, so
`call $target` asks for an invocation of that declaration. An unbound `$site`
in the previous example instead captures an occurrence selected by its name.
If several declarations have the same name, constrain the target's `path` as
well, for example `path: "src/sample.py";`. Resolution must be supported by the
source graph; aliases, missing imports, or dynamic dispatch must not be guessed.
For inspecting one known callable's callers and consumers, the higher-level
`ken_related(relation="impact", target="file::qualname")` may be simpler.

This remains an existential property. If a bad wrapper exists alongside one
good wrapper, selecting the good wrapper is not proof that all wrappers work.
`some_match` in a saved contract has exactly that limitation. To prohibit a
class of defects, search for violations and use `no_matches`, or use behavior
tests when the obligation exceeds supported static evidence.

## Investigate an unknown on real code

A value relationship can remain unknown even when a return looks straightforward
in the source. The current result may expose only an unknown count, without the
candidate and failed relation. `full=True` can reveal available detail but does
not guarantee a per-candidate explanation.

1. Run the owner-and-call query below without the value constraint. This is the
   candidate baseline. A target already bound to a callable declaration stays
   inside BODY; moving `call $target {}` into ordinary selector children can
   produce `incompatible selector types for $target`.
2. Select a known owner by name/path and add the produced-value and return
   constraints separately. Keep relevant target declarations in scope.
3. Compare rows, unknowns, coverage and diagnostics after each addition. This
   isolates where evidence becomes insufficient; it does not establish why.
4. Read that owner's return and assignments. Report the supported baseline,
   the unresolved relationship, and the source observation separately. If the
   engine supplies no cause, say so; do not infer aliasing or dynamic dispatch
   merely from the count.

```kql
language "kql/2";
module lesson.recovery;
query target_call_candidates {
  callable $target { name: "save"; path: "src/sample.py"; }
  callable $owner {
    body { call $target {}; }
  }
  select $owner.name;
}
```

On the sample this returns `save_user`, `discard_user`, `overwrite_user`, and
`write`. The returned-target query above keeps only `save_user` because its
owner name is also constrained. Adapt both queries to the same source scope
and owner restriction when comparing their coverage. This broader baseline
finds calls; it does not establish that their result is returned.

For example: “The query located this wrapper's `connect()` call. Adding the
returned-value constraint left the result unknown; the engine gave no specific
reason. Source inspection shows `return connect()`.” A missing row with unknowns
does not establish that the wrapper discards the value. Preserve a small source
reproducer when the unsupported relationship blocks the investigation.

## Give a repeated concept a name

Patterns also support ordinary code discovery. Suppose several investigations
ask which types implement a local write convention. Reuse that relationship
with different surrounding constraints instead of inspecting every class again.
This small pattern expresses an owned method; richer conventions can compose
other tested relationships. KQL2 patterns name reusable query fragments; they
can express conventions beyond the built-in design-pattern catalog.

Save this library as `/tmp/writers.kql`:

```kql
language "kql/2";
module lesson.writers;
pattern WithWrite(in TypeDecl $type, out Callable $method) {
  class $type {
    method $method { name: "write"; }
  }
}
```

Use it from an entry query saved as `/tmp/writer-query.kql`:

```kql
language "kql/2";
module lesson.client;
import lesson.writers;
query imported_writer {
  class $owner {}
  use lesson.writers.WithWrite(type: $owner, method: $action);
  select $owner.name, $action.name;
}
```

Expected row: `["Writer", "write"]`.

- `in TypeDecl $type` requires the caller to bind a type before invoking the
  pattern. The outer `class $owner {}` does that.
- `out Callable $method` exposes the selected method. An already-bound output
  can also constrain the result. Pattern-private captures stay local.
- Arguments name pattern parameters without `$` (`type:`), and pass caller
  captures with `$` (`$owner`). Names inside the pattern need not match those
  in the query.
- `import` names a KQL module, not a Python import or filesystem search path.
  Save the module in Ken or pass the matching source explicitly. Patterns can also be declared before
  a query in one module. Recursive pattern expansion is rejected.

```sh
ken kql2 /tmp/writer-query.kql --root "$example_root" --path src \
  --library /tmp/writers.kql
```

For MCP, pass `libraries={"lesson.writers": library_source}` along with the
entry program to `ken_find`. `library_source` and `entry_source` below stand for
the complete respective blocks above:

```python
ken_find(scope="structure", query_language="kql/2", query=entry_source,
         libraries={"lesson.writers": library_source}, path="src")
```

The declared module must match the library key. A missing module is an error;
imported queries do not become the entry query automatically. With multiple
entry queries, the direct CLI's `--query name` selects one. Library contents
participate in cache invalidation.

To stop passing library text on every call, follow [saved modules](saved-modules.md):
save `lesson.writers` first, then `lesson.client`. The same entry program resolves
its imports automatically, and can be executed by module and query name.
