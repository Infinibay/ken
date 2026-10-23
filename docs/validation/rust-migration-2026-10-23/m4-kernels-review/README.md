# M4a retrieval kernels: final reviewed acceptance

Both actual platforms passed44affected Rust roots and46validation cases after the one final-review TDD fix pass.292original observations and13original tests/platform remain preserved; only4new original regression calls/platform were added. The native process matches all296cases with exact owner/evidence order and unchanged pre-implementation numeric bounds. Two Important review findings are fixed; no Minor findings.

Run `.venv/bin/python docs/validation/rust-migration-2026-10-23/m4-kernels-review/VERIFY.py --current` from the repository root. The standalone verifier restores its own pinned source/tooling snapshot and authenticates both actual platform captures, raw original/native I/O, complete affected gates, predecessor and all1066preserved original files. `M4a_accepted=true`; completeM4/global remainfalse. No public CLI/MCP search acceptance or speedup claim is made.

`LEDGER.md`, `REVIEW.md`, `RULINGS.md`, `MINORS.md` retain all decisions/findings. The historical pre-review `m4-kernels/` receipt remains intact.

Dense ranking now uses macOS Accelerate and the exact Linuxaarch64 OpenBLAS0.3.31.188.0 ILP64 reduction. Linux packaging must include the30,371,298-byte pure-native two-file bundle identified in `crates/ken-retrieval/resources/dense-runtime.json`, with its distribution licenses. Before loading, Rust verifies both lengths/hashes. The default distribution layout is `<executable-directory>/dense-blas/`; explicit preparation/testing can set `KEN_DENSE_BLAS_DIR`. No Python runtime is required. Acquisition/installation of this bundle is an explicit M7/M8 delivery obligation, not a completed public installer. Single-row and width1 dispatches are retained. The bundle is process-cached after first verified load.

Native debug process measurements (request parsing + all292base kernels, before output serialization): macOS0.073201875s/13,877,248bytesRSS; Linux1.9517471259999999s/40,296,448bytesRSS, including first-load runtime integrity verification. These are bounded kernel evidence, not complete search latency.
