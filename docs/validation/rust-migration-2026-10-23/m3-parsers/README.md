# Native parser acceptance — M3b

The 19 original language frontends now have native Rust owners with all 20
original grammars and 44 extension mappings. Each platform runs 31 Rust tests,
38 affected tooling tests and an external native comparison of 239 inputs:
215 original suite/supplement inputs, 19 string/comment edges, three C Unicode
macro spellings and two original encoding failures. Complete ParsedFile fields,
ordering and all 215 original syntax shapes are compared.

The copied executable and copied authenticated SDK run outside the checkout with
an empty PATH, isolated HOME and native loader audit. Linux also records the
actual exec/connect trace. Requests contain only language, hint and source bytes.
The original 124-test captures are reused with their original byte identities;
this receipt does not claim new original-suite or model-inference runs.

`INDEX.json` binds the native source snapshot (including Unicode and grammar
JSON), validation sources, native binary identities and immutable M3a predecessor.
Compressed platform captures preserve raw original/native bytes and audits.
`FILES.json` seals membership and bytes; semantic replay additionally rejects
resealed missing tests, lost platforms, changed sources, grammars and observations.

Run from the repository root using the existing validation environment:

```sh
PYTHONPATH=. .venv/bin/python docs/validation/rust-migration-2026-10-23/m3-parsers/VERIFY.py --current
```

Omit `--current` after later native-source changes to replay this historical
snapshot. This accepts M3b only. Common model, import resolution and indexing
remain pending in M3; M4–M8 and installed-command cutover remain pending.
Original files and the active Python application are preserved.
