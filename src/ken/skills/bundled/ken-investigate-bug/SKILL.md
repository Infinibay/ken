---
name: ken-investigate-bug
description: Trace a concrete programming failure from its symptom through producers, consumers, and tests in a Ken project. Use when finding code is only the first step toward explaining and fixing a bug.
---

# Explain a failure and verify the repair

Start with the observable mismatch: input, expected result, actual result, and
an error or failing test if available. Use Ken to choose the next boundary to
inspect. End with a reproduced cause and a test of the corrected behavior.
Examples are MCP calls; paths are illustrative.

For an open bug hunt, first read the subsystem's responsibilities and failure
boundaries to formulate a concrete hypothesis. A catalog sweep can provide leads;
it is not the only way to use KQL2. Ask what should hold and construct a nearby
case where it does not, then express the distinguishing relationship.

## From a hypothesis to a small candidate set

For “confirmation becomes durable before publication can fail,” searching for
`replace` locates candidates. The distinguishing relationships are the actual
confirmation/publication targets and their supported order. Read the
[worked relationship investigation](references/kql2/relationships.md): it gives
complete queries, mixed positive/negative fixtures and a failure injection.
It progresses from five call owners to one target-and-order witness; each
constraint answers a specific question rather than just shrinking the result.

Use this sequence: **question -> contrasting examples -> minimal distinguishing
query -> candidates -> source reading -> reproduction**. For a traceback that
already identifies the cause, direct reading and a test can be sufficient.
For many similar sites, let KQL2 perform the repeated relational check before
reading each one. The [values chapter](references/kql2/values-and-patterns.md)
shows produced/returned identity; [syntax recipes](references/kql2/syntax.md)
show containment and scoped absence. Indexed supports BODY; exploration supports
syntax relationships. Each reference specifies its backend.

## Work through: “Saving succeeds, but the API receives no identifier”

Reproduce the failure with the smallest existing test or caller. If the traceback
names a file, read it directly and retrieve earlier constraints:

```python
ken_recall(path="src/service.py", detail="answer")
ken_read(path="src/service.py", qualname="save_user", include=["source"])
```

If no file is known, use `ken_who(question="Who saves a user and returns its identifier?", path="src")`
to locate a candidate. Suppose reading the wrapper and producer shows:

```python
# src/service.py
from storage import save

def save_user(user):
    save(user)

# src/storage.py
def save(user):  # Read the real declaration, including its failure paths.
    return repository.insert(user)
```

The working hypothesis is precise: the wrapper discards `save`'s result, so
Python returns `None`. Confirm that this wrapper is the failing caller's path.
For consumers beyond the immediate traceback:

```python
ken_related(target="src/storage.py::save", relation="impact",
            path="src", depth=2, timeout_ms=10000)
ken_find(query="src/service.py", scope="tests")
```

A reported call in `save_user` tells you where to inspect; it does not by itself
prove the value is discarded. Its body above does. Read the candidate tests to
find a missing assertion: a test that only verifies `insert` was called would
miss this defect. Add an assertion that `save_user(user)` equals the identifier
returned by the test repository, see it fail, preserve the result with
`return save(user)`, and rerun the caller's tests.

The useful conclusion is “the wrapper lost the identifier,” backed by the call
path, source statement, and failing/passing test. “Storage has a return-related
finding” is not an explanation.

## If the trace stops before the failure

Impact follows explicit connections and unchanged returned values. A transformed
value, dynamic dispatch, unresolved import, or argument passed into another
function can end the trace. Read that receiving boundary and inspect the
specific runtime observation needed to distinguish hypotheses. Do not connect
two functions merely because they share a name. Expand `path` to include tests
or another subsystem only when that is the missing boundary.

Each consumer's `result_flow` explains these boundaries: `returned_identity`,
`argument_boundary`, `transformed_value`, or a witnessed receiver use. A
`cleanup_candidate` means the same result is the receiver of a call spelled
`close`, `dispose`, or `release`; verify that method's contract and failure
paths before claiming cleanup. `ownership: unproven` is deliberate. A return
or argument use alone does not establish who must release a resource.

For a known error, `ken_recall(anchor_error="the actual error", detail="answer")`
can recover an earlier diagnosis; check its assumptions and input validity.
For an existing structural contract, `ken_related(target="src/service.py", relation="checks")`
shows saved evidence; use `ken_check` to rerun it. A saved receipt is not a new
execution, and a static match is not a runtime reproduction.

Request candidate and witness locations, then use `diagnostics` and coverage to
interpret them. `--explain` validates a custom query without scanning. A result
that localizes candidates and a later reproduction contribute different evidence:
say which query ran, what relation it established, and what source/test work
established the bug. Finding only a few useful catalog leads does not evaluate
the language's ability to express the specific defect.

```sh
ken tools related 'src/storage.py::save' impact --path src --depth 2
ken tools find src/service.py --scope tests
```

Save a non-obvious cause with `ken_remember`, anchored to the responsible file
or actual error, including evidence and the recheck needed after changes. If a
runtime reproduction is unavailable, explicitly separate the source-supported
hypothesis from the unverified behavior in the final answer.
