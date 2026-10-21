# Native XLM-R core proof

Nine full registered BGE profiles through the Rust C ABI: macOS CPU and actual MPS, Linux CPU, each F32/F16/BF16. All 963 vectors match the frozen original corpus within 1e-6 and every unchanged original-derived deadline passes. Expected vectors never enter the Rust process.

The native core reads the original 2,271,145,830-byte parameter ZIP through a held regular-file descriptor without Python, extraction, or a second whole-file buffer. Tests cover original positions independent of attention masks, pooling, declared unused pooler parameters, malformed archives, source removal, repeated calls and Qwen regressions.

Each profile preserves inputs, raw outputs, actual device/core identity, loader diagnostics, source hashes and timing receipts. Linux traces both execve and execveat with selective seccomp; each accepted profile executes only the independent Rust host. macOS loader diagnostics are not a kernel child-execution audit. Reproducers and small-contract logs are retained.

This accepts the native core only. Application text/prompt/lifecycle adapters and remaining migration stages are pending. M2 and application acceptance remain false; original sources are preserved.
