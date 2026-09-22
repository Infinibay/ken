---
name: ken-resume-work
description: Resume an earlier programming investigation using saved conclusions and their validity in Ken. Use when prior reasoning, a decision, or a diagnosed constraint may avoid repeating unchanged work across sessions.
---

# Continue from supported conclusions

Retrieve the most specific relevant memory: a topic from context, a known file,
or an actual error. Examples below are MCP calls. Exact-topic answer retrieval
checks declared inputs without rerunning the earlier KQL investigation.

## Work through: “Continue the change to the saved-record response”

```python
ken_recall(topic="storage-return-contract", detail="answer")
```

Suppose the answer says: “The API must keep an integer ID; the service wrapper
adapts storage's Record to record.id,” supported by the service and API test,
with the assumption that this is the active API version. Decide whether that
question and assumption match today's task before looking at validity.

| Returned state | What to do next |
| --- | --- |
| `unchanged` and sufficient evidence | Reuse the conclusion; proceed to the outstanding implementation step |
| `stale` because the service changed | Read the changed service and rerun the relevant API test; retain unrelated conclusions |
| `unknown` or `untracked` | Inspect the missing support before relying on it |
| `conclusion_omitted` | Expand with `detail="full"` before using the conclusion |

`unchanged` means declared inputs match, not that the conclusion is true or all
dependencies were declared. A remembered hypothesis still needs confirmation.
Use `detail="summary"` for a short rationale or `full` for evidence. If the API
version assumption is wrong, the old conclusion may be irrelevant even when
all files are unchanged.

If the topic is unknown, use `ken_recall(path="src/service.py", detail="answer")`
or search with `query="saved record response contract"`. If nothing relevant
exists, investigate normally. Repeating recall calls cannot create missing
knowledge.

## Save what the next person would otherwise have to rediscover

After verifying the boundary and its test, save the conclusion and support:

```python
ken_remember(
    topic="storage-return-contract",
    content="The API keeps an integer ID; the service adapts Record to record.id.",
    anchor_file="src/service.py",
    justification={
        "kind": "observation",
        "rationale": "The API response contract asserts an integer identifier.",
        "evidence": [
            {"path": "src/service.py", "note": "Converts the stored Record."},
            {"path": "tests/test_api.py", "note": "Checks the integer API field."},
        ],
        "dependencies": [{"path": "src/storage.py"}],
        "assumptions": ["This API version remains the supported interface."],
        "recheck": "Read the conversion and rerun tests/test_api.py.",
    },
)
```

Only save verified facts and existing evidence paths from the real project.
Ken adds evidence files to dependencies. Include the producer if changing its
return contract would invalidate the conclusion, even if the wrapper is
unchanged. For inventory claims such as “these are the only adapters,” include
`{"kind": "tree", "path": "src/adapters", "pattern": "*.py"}` so new or removed
files invalidate the claim. File hashes alone cannot detect a new consumer.

Use a decision or hypothesis kind when that is what you have. Reusing a topic
replaces its content; update it after revalidation. An attached `check_run` is a
historical receipt; running a newer check does not rewrite that old evidence.
Anchors help supported hooks surface the memory, but hooks do not invent the
conclusion or guarantee that every host retrieves it automatically.

```sh
ken tools recall --topic storage-return-contract --detail answer
```

Finish by saying what was reused, what changed and was rechecked, and the next
concrete step. Save the useful constraint or root cause, not a transcript.
