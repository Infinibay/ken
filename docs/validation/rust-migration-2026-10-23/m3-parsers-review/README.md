# Native parsers — reviewed M3b closure

The single fresh whole-plan review found two Important compatibility gaps and no
Critical/Minor issues. Both now have original-derived RED→GREEN regressions:
strict UTF8 failure for direct/inherited annotations and full Python documentation
containing high/low surrogate escapes, paired/unpaired forms and ordinary text.

PythonText owns Python code points beyond Rust Unicode scalar strings. Normal
text converts explicitly to UTF8; surrogate text remains lossless and serializes
as JSON escapes. ParsedScope.documentation uses this type. The native probe
serializes typed results directly, avoiding serde_json::Value's scalar-only string
boundary. Shared annotation decoding returns an error through all actual callers.
Other lossy text policies remain those of the original language owners.

Each actual macOS arm64/Linux aarch64 platform passes33Rust/38affected tooling
cases and249complete original comparisons, including215syntax shapes and four
original encoding failures. Eight resealed-matrix tests reject manipulated proof.
Original124test-suite and model histories are reused; no inference rerun is claimed.

The receipt preserves the final review, full ledger/rulings, no deferred minors,
current source/tooling snapshots, compressed actual captures and raw test logs.
It pins the initial parser receipt at18418762 and does not overwrite its history.

From the repository root, with the existing validation environment:

```sh
PYTHONPATH=. .venv/bin/python docs/validation/rust-migration-2026-10-23/m3-parsers-review/VERIFY.py --current
```

Omit `--current` after later source edits to replay this historical snapshot.
M3b alone is accepted. Common model, imports and incremental indexing remain M3
work; M4–M8 and installed application cutover remain pending. Originals preserved.
