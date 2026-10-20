# Current storage matrix

The current macOS arm64 and Linux aarch64 proof passes all 31 gates with 29
matching source/input fingerprints after the one final review and TDD fix pass:

- `Storage_accepted=true`
- `Policy_accepted=true`
- `M2_accepted=false`

[matrix.json](matrix.json) is the current machine result.
[EXECUTION.md](EXECUTION.md) records both full execution trees, measurements and
excluded attempts. [IMPLEMENTATION.md](IMPLEMENTATION.md) describes ownership and
limits; [FINAL-FIXES.md](FINAL-FIXES.md) maps the regressions to their corrections.
Remaining model backends/integration and M3–M8 remain required.

Reproduce from the project root with the prepared native inputs:

```sh
PYTHONPATH="$PWD:$PWD/src" CARGO_INCREMENTAL=0 \
  .ken/rust-migration/m2/prepared-macos-env .venv/bin/python \
  -m tools.rust_migration.storage_validate --scope matrix \
  --platform-receipts "$PWD/docs/validation/rust-migration-2026-10-19/m2-storage" \
  --out "$PWD/.ken/rust-migration/m2-storage/matrix-current"
```

Expected: exit 0, `passed=true`, no errors, both registered platforms,
`Storage_accepted=true`, `M2_accepted=false`. This recomputes current fingerprints,
authenticates the whole nested raw tree and rejects synthetic/historical receipts
or incorrect re-sealed output.
