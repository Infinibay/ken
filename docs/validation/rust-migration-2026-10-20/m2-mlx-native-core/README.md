# Native MLX Qwen core

Actual Apple GPU execution through the bounded Rust C ABI, with the exact MLX 0.32.3 core/shader and mlx-rs 0.32.0 / vendored mlx-sys 0.6.0. Three encoder profiles preserve 321 original vectors within 1e-6; three judge profiles preserve all 129 original raw scores exactly. All original-derived deadlines pass. Inputs contain captured tokens and masks, never expected outputs. Public text adapters retain their separate gates.

Runs execute outside checkout with sentinel PATH and privately copied verified native files. Loader evidence shows the private MLX core without Torch/Python linkage; macOS loader diagnostics are not a kernel child-execution audit. MLX is recorded as nonapplicable on Linux; shared Qwen declarations, API and mandatory Torch CPU regressions ran there. Current shared Torch tests use the new configuration/header owner, while compatibility tests retain the immutable previously accepted production module.

The native reader authenticates bounded floating safetensors metadata, holds the opened inode and uses an owned suffix-bearing descriptor alias for native I/O. I/O is explicitly scoped to a CPU stream; graph operations use the calling thread's GPU stream. Tests cover source removal, repeated/cross-thread calls, malformed weights, dtype/layout/finite checks, shader failure and cache bounds that preserve lower prior limits and the live host limit.

Vendored licenses, published archive checksums and exact modified-source hashes are in native/ken-mlx-backend/PROVENANCE.json. The local build imports the exact core rather than fetching upstream 0.32.2; gather_qmm supplies the new optional global_scale default. Quantized models are outside the accepted family. An initial preparation restriction incorrectly applied ST Normalize metadata to MLX; that failed attempt is retained, and the corrected complete candidate follows the original MLX policy.

This accepts the native core only. M2 and application acceptance remain false; original application sources are preserved.
