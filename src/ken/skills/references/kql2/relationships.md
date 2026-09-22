# From text matches to a question about code

KQL2 lets you describe the relationship that makes a piece of code relevant.
Use it to automate repeated checks you would otherwise perform while reading
text-search results: who owns a call, which declaration it invokes, which value
it returns, or how supported source operations are ordered. Those relationships
can describe a bug hypothesis, an implementation pattern, or an architectural
convention. The built-in bug catalog is one collection of predefined queries.

Start with **a question and two similar fragments that should get different
answers**. Identify the difference, express it, test it, and inspect the resulting
candidates. Use text search directly when the spelling alone answers the question.
You can start directly with KQL2 when the distinguishing relationship is known.

## A complete investigation: confirmation before publication

Suppose reading a storage contract suggests a risk: confirmation may become
durable before the corresponding files are published, and publication can fail.
The first structural question is “Where does this confirmation precede this
publication?” Compare:

```python
def commit_then_publish():
    commit()
    replace()

def publish_then_commit():
    replace()
    commit()
```

Both mention the same calls. Their order differs. An unrelated subsystem may
also define `commit` and `replace`, so the final query should identify the actual
declarations as well. These names alone say nothing about durability.

The supplied [publication fixture](relationships/publication.py.txt) contains
both functions, a publication-only function, calls in mutually exclusive
branches, and a string mentioning the calls. The [preview fixture](relationships/preview.py.txt)
defines same-named functions with a different responsibility. All implementations
are teaching stubs; they do not modify files or a database.

Run from this reference directory:

```sh
example_root=$(mktemp -d)
mkdir -p "$example_root/src"
cp relationships/publication.py.txt "$example_root/src/publication.py"
cp relationships/preview.py.txt "$example_root/src/preview.py"
```

Each KQL block below is a complete program. Save one as `/tmp/publication.kql`:

```sh
ken kql2 /tmp/publication.kql --backend indexed --explain
ken kql2 /tmp/publication.kql --root "$example_root" --path src --backend indexed
```

All four queries use indexed. `$name` captures a code entity or value, `name:`
matches its source spelling, `path:` constrains its source file, and `select`
chooses the returned evidence. Read [the syntax basics](README.md) when adapting
those constructs. `module lesson.relationships` names the query namespace, not the files
being searched; `--path` selects the source scope.

### 1. Replace manual ownership checks

A textual search such as `rg -n '\b(replace|rename)\s*\(' src` finds spellings,
including the teaching string and declarations. To return the functions owning
actual matching calls:

```kql
language "kql/2";
module lesson.relationships;
query publication_owners {
  callable $owner {
    call $site { name: /^(replace|rename)$/; }
  }
  select $owner.name;
}
```

Expected names: `commit_then_publish`, `publish_then_commit`, `publish_only`,
`split_branches`, and `preview_update`. `mentions_only` is excluded. Nesting
the call within `$owner` replaces the manual task of locating its enclosing
function. This is useful for locating candidates even before investigating
ordering. For real repositories, `select $owner;` provides source locations
when names are not unique.

### 2. Distinguish identical spellings by their declaration

Now ask which functions call `replace` defined in `src/publication.py`:

```kql
language "kql/2";
module lesson.relationships;
query actual_publication_owners {
  callable $publisher { name: "replace"; path: "src/publication.py"; }
  callable $owner {
    body { call $publisher {}; }
  }
  select $owner.name;
}
```

Expected names: the same four functions in `publication.py`; `preview_update`
is excluded. `$publisher` is bound to a declaration **before** BODY, so this
call refers to that declaration. An unbound call capture in the first query
instead selected occurrences by spelling. KQL2 replaces the manual identity
check; keep the relevant definitions/imports within the analysis scope.

### 3. Distinguish presence from order

Next test the order alone:

```kql
language "kql/2";
module lesson.relationships;
query commit_before_replace {
  callable $owner {
    body {
      call $confirmation { name: "commit"; };
      call $publication { name: "replace"; };
    }
  }
  select $owner.name;
}
```

Expected names: `commit_then_publish` and `preview_update`. The reversed order,
missing confirmation, and mutually exclusive branches are excluded. BODY
describes an ordered subsequence of supported source operations; unrelated
operations may occur between them. This removes a repeated inspection of order
and branch compatibility. Ordinary sibling `call` selectors require presence
in the same owner, without this sequence constraint.

This query still selects the preview implementation because it uses names.
That is a useful result: the next constraint has a concrete purpose.

### 4. Compose identity and order, then return the witnesses

```kql
language "kql/2";
module lesson.relationships;
query confirmed_before_publication {
  callable $commit { name: "commit"; path: "src/publication.py"; }
  callable $publish { name: "replace"; path: "src/publication.py"; }
  callable $owner {
    body {
      call $commit {} as $confirmation;
      call $publish {} as $publication;
    }
  }
  select $owner.name, $confirmation.line, $publication.line;
}
```

Expected row: `["commit_then_publish", 13, 14]`. `as` captures each matched
operation so its location can be inspected. Neither reversed order nor a
same-named preview operation satisfies the composed question. For a real
project, select `$owner` alongside the witness lines to retain its path.

| Case | Calls by name | Correct publication target | Order by name | Target and order |
| --- | --- | --- | --- | --- |
| `commit_then_publish` | yes | yes | yes | yes |
| `publish_then_commit` | yes | yes | no | no |
| `publish_only` | yes | yes | no | no |
| `split_branches` | yes | yes | no | no |
| `preview_update` | yes | no | yes | no |
| `mentions_only` | no | no | no | no |

### 5. Read and reproduce what the query leaves open

The composed query establishes an ordering witness under supported analysis.
It does not establish durable confirmation, the effect of replace, exception
handling, compensation, or correctness on every runtime path. Read the selected
operations and their contracts to decide whether this ordering is a defect.

For the toy failure model, load the teaching fixture and substitute a recording
commit and a failing publication:

```python
namespace = {}
exec(open("src/publication.py", encoding="utf-8").read(), namespace)
events = []
namespace["commit"] = lambda: events.append("committed")

def fail_publication():
    raise OSError("simulated publication failure")

namespace["replace"] = fail_publication
for name in ("commit_then_publish", "publish_then_commit"):
    events.clear()
    try:
        namespace[name]()
    except OSError:
        pass
    print(name, events)
```

Run this only on the supplied teaching fixture from its temporary project.
It prints `['committed']` for the first function and `[]` for the second.
That demonstrates the assumed failure model. In an actual repository, adapt
the existing tests and inject failure at the real publication boundary; a
crash after publication but before confirmation may require another contract.

## Transfer the method to another question

Name the relationship your manual reading is checking:

| Question | Contrast to put in the fixture | Recipe |
| --- | --- | --- |
| Which wrappers return a produced value? | Return the call result versus overwrite or discard it | [Values and call targets](values-and-patterns.md) |
| Which classes implement a local method convention? | Methods in one class versus matching names scattered across classes | [Ownership and reusable patterns](README.md), [named patterns](values-and-patterns.md#give-a-repeated-concept-a-name) |
| Which handlers lack an explicit raise? | A raise in this handler versus a raise in another handler | [Correlated absence](syntax.md) |
| Which parameter defaults use mutable literals? | A default literal versus the same literal in the body | [Predefined hazard facts](graph-queries.md) |

Use `scope="bugs"` or `scope="patterns"` when a catalog question fits, or as
leads for an unfamiliar subsystem. To investigate a domain-specific obligation,
write the relationship directly or adapt a validated pattern. Sparse catalog
results do not measure the full query language. Conversely, a general code
review need not invent KQL queries where reading an already known function
answers the question more directly.

## Keep exploration useful

Start on the smallest scope containing the candidates and required definitions.
For initial inspection, `--max-rows 20 --timeout-ms 10000` bounds output and work.
Read compact results first, adding the few witness locations needed for the
question. Check `diagnostics`, completeness, coverage and unknowns before an
absence claim; use `--full` on `ken tools find` when detailed evidence is needed.
The direct `ken kql2` command already returns the detailed result.

If preparation consumes the budget, narrow the scope or report it as incomplete.
Removing target/order constraints changes the question: keep such a result
labeled as candidate discovery. A cheaper backend is appropriate only when it
can express the required relationship. Runtime cost remains a separate issue
from whether the query accurately distinguishes the cases.
For a performance comparison, keep query, source revision, scope, backend and
budget constant; record the interface used, cache settings and warm/cold state.
Compare reported preparation and execution timing with total elapsed time.
One slow invocation does not identify which phase or interface caused it.

A useful investigation reports: **the question, the relation encoded, source
locations, what the query established, and what reading or reproduction added**.
When the relationship recurs, name it as a reusable pattern; when it expresses
an adopted project obligation, preserve it as a validated source contract.
