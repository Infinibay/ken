# Native transformer acceptance

The adapters own public behavior; the optional native cores own tensor execution. `SentenceEncoder` preserves ST5.6.1 ordering, prompts, normalization and fresh CPU rebuilding. `MLXEncoder` preserves MLX token ordering, last-real pooling and error propagation. `RelevanceJudge` owns the exact original purpose headers, query/source budgets, raw yes-minus-no scores and conversion of resident lower-precision weights during CPU/F32 recovery. Original Python implementations remain available as immutable references.

Validation has four responsibilities. `transformer_process` owns bounded native processes and cleanup. `transformer_compare` compares public inputs, tokens, order, outputs and state against the frozen original. `transformer_evidence` authenticates native identities and replays saved values and gate outputs. `transformer_validate` requires the complete24-profile macOS and9-profile Linux matrices plus the existing34-gate FastEmbed chain. A resealed passing flag never replaces numerical replay or a current source/runtime identity.

Preparation is explicit. `PreparedNativeTransformer` carries absolute probe, source, catalogue, module, SDK and runtime-registration paths. `transformer_prepare` copies only verified native Torch libraries and headers, verifies the MLX SDK from an isolated preparation environment, builds with the pinned toolchain and records actual allocated workspace/SDK/build/Python footprint. Production children clear loader overrides and use authenticated private native files; Python participates in preparation and reference validation only.

Each execution deadline is frozen from original measurements as `max(60,ceil(3*(preparation+public_calls)))`. The legacy600-second process-test deadline, vector1e-6 and raw-score1e-5 tolerances stay unchanged. Acquisition and compilation occur outside neural deadlines. Linux audits both `execve` and `execveat`. macOS retains private-library loading observations and explicit kernel-audit limitations.

Workspace regressions receive explicit typed SDK paths and metadata-only tokenizer/config sources through the existing validator. This prevents the original environment filter from dropping native test prerequisites, while keeping full transformer checkpoints out of the legacy source lease. The workflow runs transformer inference after the complete legacy93-test process suite. One model source lease is held at a time and released before the next family. Transformer models are never preloaded together with the five FastEmbed families. Capacity checks include the exact source/private model/native-core bytes and an unchanged3GiB reserve, compare measured allocation with declared capacity and check actual free bytes before acquisition. Borrowed sources and unrelated caches survive; only directories created by the owning lease are removed.

The reusable workflow `.github/workflows/rust-transformers.yml` consumes the existing platform artifacts instead of repeating the34-gate chain. macOS requires actual Apple GPU access; Linux runs CPU profiles and records MLX as explicitly inapplicable. Hosted-run success must be demonstrated by that job, never inferred from local success. An undersized or GPU-less runner fails before transformer model acquisition.

The dedicated `transformer_migration_tests` group independently replays the real public-process corpus and runs the actual native owner/concurrency/error regressions. The raw production corpus uses full original checkpoints. Lifecycle fault tests use genuine small parameter archives through the same native cores, keeping their scope distinct from full-checkpoint numerical parity.

Current candidate observations may be reused across integration gates when all relevant source bytes, native modules, host binaries, original references and fixed budgets remain identical. Changing Python evidence tooling does not require rerunning unchanged neural inference; it requires a fresh semantic replay and current tooling/legacy validation. Historical stage proofs retain their pinned commits and must not be compared with unrelated later source revisions.

Replay saved platform evidence:

```sh
.venv/bin/python -m tools.rust_migration.transformer_validate --scope matrix \
  --platform-receipts docs/validation/rust-migration-2026-10-20/m2-transformer-acceptance \
  --out .ken/rust-migration/m2-optional/current-matrix
uv run --isolated --no-project --with numpy==2.4.4 --python 3.12.9 --managed-python \
  python -m tools.rust_migration.transformer_validate --scope matrix \
  --platform-receipts docs/validation/rust-migration-2026-10-20/m2-transformer-acceptance \
  --out .ken/rust-migration/m2-optional/current-matrix-isolated
```

Transformer acceptance is scoped. Global M2 acquisition/integration and the remaining application migration keep their own gates; successful transformer evidence alone never sets `M2_accepted`.
