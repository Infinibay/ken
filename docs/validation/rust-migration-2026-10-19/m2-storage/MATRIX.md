# Current storage matrix

The current worktree matrix accepts the complete macOS arm64 and Linux aarch64
proof with 31 gates and 29 matching input fingerprints:

- `Storage_accepted=true`
- `Policy_accepted=true`
- `M2_accepted=false`

The final whole-plan code review is pending at this proof cut. This receipt
does not complete M2 or the application migration.

[matrix.json](matrix.json) is the machine result. [EXECUTION.md](EXECUTION.md)
links both full execution trees and reports tests, measurements and rejected
environmental attempts. [IMPLEMENTATION.md](IMPLEMENTATION.md) describes the
public storage responsibilities and limitations.

Reproduce from the current project root with the prepared native inputs:

```sh
PYTHONPATH="$PWD:$PWD/src" CARGO_INCREMENTAL=0 \
  .ken/rust-migration/m2/prepared-macos-env .venv/bin/python \
  -m tools.rust_migration.storage_validate --scope matrix \
  --platform-receipts "$PWD/docs/validation/rust-migration-2026-10-19/m2-storage" \
  --out "$PWD/.ken/rust-migration/m2-storage/matrix-current"
```

Expected: exit 0, `passed=true`, no errors, exactly the two registered platforms,
`Storage_accepted=true` and `M2_accepted=false`. Fingerprints are recomputed from
the current sources/prepared inputs; historical receipts or synthetic fixtures
cannot replace this check. All nested raw proof is required, and incorrect
re-sealed storage/policy output still fails semantic comparison.
