# Frozen KQL2 observations

Captured once from original1066, Python3.12.9, with frozen tree authentication
before/after. Reference fingerprint:
`5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038`.
JSON keeps recursive `__class__` tags and exact original dataclass/tuple repr.
Each compressed resource embeds its observer hash. Tests pin compressed size and
SHA256; raw journals/observers remain local under `.ken/rust-migration/kql-frontend`
and `.superpowers/sdd/2026-10-29-rust-kql-frontend`.

- `frontend-reference.json.gz`:574 docs/test/adversarial syntax inputs and nine
  explicit library/model snapshots. Includes240 seeded mutations (90401), Unicode,
  speculative arguments, BODY and malformed/limited input.
- `regex-reference.json.gz`:890 fresh unique regex inputs, including deterministic
  mutations (441801), Unicode names, escaped ranges and repeat diagnostics.
- `expansion-reference.json.gz`:227 indexed expansion/SCC observations from already
  captured prepared ASTs, including128-branch boundaries and recursion. Capture
  resumed its journal after deep JSON adapter decoding failed; no observed name
  was rerun, and original recursion settings were restored before each observer.

`depth/type/600` is the single named diagnostic exception: native safety guards
preserve resource code/message and a valid source byte span instead of CPython's
caller-stack-dependent emergency cutoff token. Other diagnostics compare exactly.
The tests do not invoke Python or alter these references. New compatibility cases
must be new observations against an authenticated original, not native snapshots.
