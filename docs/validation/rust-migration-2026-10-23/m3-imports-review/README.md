# M3c reviewed import resolution

Two Important findings repaired by RED→GREEN tests: universal newlines before
JSONC stripping and lossless Unicode paths through normalization/inheritance.
Originals preserved. Both actual platforms:79Rust root tests (46core+33syntax),
33tooling,107original inputs,214native cases/216requests in explicit/project modes.
The shared PythonText extraction also preserves all249accepted parser inputs in
native processes. No original suite/model inference repeated.

Replay from repository root:
`PYTHONPATH=. .venv/bin/python docs/validation/rust-migration-2026-10-23/m3-imports-review/VERIFY.py --current`

One fresh whole-plan review; one TDD Important repair pass; no rereview. Archived
ledger/rulings/minors contain every decision. MINORS records unusual deep/huge
numeric JSON acceptance differences. M3c accepted only; fullM3/M8 remain pending.
Initial import/parser/source/model receipts remain immutable.
