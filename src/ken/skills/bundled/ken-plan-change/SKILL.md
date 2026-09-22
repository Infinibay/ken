---
name: ken-plan-change
description: Plan the affected callers, compatibility steps, and validation for a refactor or interface change in a Ken project. Use before changing a shared API, return value, module boundary, or persistence format.
---

# Turn a proposed change into a bounded plan

State the old contract and the desired contract first. Investigate the consumers
that distinguish them. Ken's relationships answer different questions; choose
the one needed for the current uncertainty. Examples below are MCP calls.

## Work through: “Make save return a Record instead of an integer ID”

Read `save` and retrieve constraints with
`ken_recall(path="src/storage.py", detail="answer")`. Write down the intended
compatibility decision: callers must now extract `record.id`, or an existing
public wrapper must continue returning an integer. That choice determines what
needs changing.

```python
ken_related(target="src/storage.py::save", relation="impact",
            path="src", depth=2, timeout_ms=10000)
```

Suppose the trace points to `save_user` and `create_response`. Read those bodies.
The following two consumers need different treatment:

```python
def save_user(user):
    return save(user)

def create_response(user):
    identifier = save_user(user)
    return {"id": identifier}
```

`save_user` forwards the changed value; `create_response` exposes it through an
API field. If the API must keep its integer ID, either extract `.id` at that
boundary or preserve the wrapper's contract. Choose based on who should own
that conversion, not on which edit is shortest. Inspect tests of the API field,
not only tests of the storage function.

```python
ken_find(query="src/service.py", scope="tests")
ken_related(target="src/storage.py", relation="checks")
```

If relevant source contracts exist, retain an explicit baseline:

```python
before = ken_check(path="src/storage.py")
# After the authorized implementation and behavioral tests:
after = ken_check(path="src/storage.py", compare=before["run_id"])
```

A contract about forwarding a value may still pass when its type changes. Read
what it checks; it cannot replace the API response test. `path` selects rules,
but each selected rule runs over its complete declared domain.

## Expand only to answer a remaining question

| Uncertainty | Next evidence | How it changes the plan |
| --- | --- | --- |
| Which modules depend on a moved export? | `ken_related(target=path, relation="blast_radius")` | Check import compatibility and re-exports |
| Serialization or configuration may move with this change | `relation="cochange"` | Inspect historically coupled files for a concrete obligation |
| A returned value is transformed or dispatched dynamically | Read that boundary and its tests | Add a manual consumer to the plan; the trace is incomplete |
| No existing contract applies | Read behavioral tests | State the uncovered risk; do not invent certification |

Cochange is a lead, not a reason to edit every associated file. Prefer exact
`file::qualname` targets and narrow analysis scope first. Include all relevant
consumers when assessing the final change, including tests outside `src`.

Deliver a plan with the chosen contract, affected declarations and why each
changes, compatibility sequencing, and tests or checks for each obligation.
Call out any unresolved consumer. If implementation is requested, execute that
plan and report the actual validation. `unknown`, `inconclusive`, or
`not_comparable` check outcomes require explanation; they are not a clean diff.

```sh
ken tools related 'src/storage.py::save' impact --path src --depth 2
ken tools check --path src/storage.py
```
