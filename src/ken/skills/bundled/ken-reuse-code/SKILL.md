---
name: ken-reuse-code
description: Find a compatible existing implementation and a valid way to call it from a Python file in a Ken project. Use before duplicating a helper or introducing a new dependency.
---

# Reuse a behavior with the right contract

Write down what the caller needs before searching: input, output, failure
behavior, and important effects. Then answer two separate questions: does the
candidate satisfy that contract, and how can this caller access it? Examples
below use MCP tool-call notation.

## Work through: “I need to replace a JSON file without exposing partial contents”

```python
ken_who(question="Who writes JSON using an atomic file replacement?", path="src")
```

Suppose results include `write_json` and `atomic_write`. Read both relevant
bodies and signatures. If `write_json` calls `path.write_text` directly, reject
it for this requirement despite its convenient name. If `atomic_write` accepts
bytes, writes a temporary sibling, then calls `os.replace`, it is a candidate;
the caller must encode JSON and honor its cleanup and error contract. Read the
implementation and tests before promising atomicity or durability on a platform.

For a chosen declaration, inspect access from the actual caller:

```python
ken_related(target="src/files.py::atomic_write", relation="available",
            from_path="src/report.py", path="src")
```

If the caller contains `from files import atomic_write as replace_bytes`, the
reported access expression should be `replace_bytes`. Read the call site for
shadowing, and adapt the data as required:

```python
payload = json.dumps(report).encode("utf-8")
replace_bytes(destination, payload)
```

An expression such as `backend.atomic_write` instead indicates a module alias.
Use the actual result; guessing a bare name can create a runtime failure even
when the helper exists.

## If the candidate is unavailable or has obligations

No explicit cross-file import means Ken cannot establish an existing access
path. Inspect imports and choose whether adding one is appropriate. If a cycle
is possible, inspect `ken_related(target="src/report.py", relation="imports")`
before changing it. The tool does not insert imports.

An instance method may require a constructed object; a conditional import may
not exist on every execution path. Read the reported initialization, typing,
shadowing, and condition obligations. Availability does not establish that the
arguments fit or that the effect is safe at every line.

If no candidate meets the required behavior, explain the mismatch. Extending
an existing responsibility is appropriate only if the new contract belongs
there. If changing a shared helper, inspect its consumers with `impact` before
broadening its behavior. Otherwise keep the integration at the caller.

Verify with the caller's relevant tests: successful output and the important
failure/cleanup behavior. Finish with the chosen declaration, access expression,
required adaptation, and any unresolved obligation. “A similar helper exists”
does not complete the reuse decision.

```sh
ken tools who 'Who writes JSON using an atomic file replacement?' --path src
ken tools related 'src/files.py::atomic_write' available   --from-path src/report.py --path src
```
