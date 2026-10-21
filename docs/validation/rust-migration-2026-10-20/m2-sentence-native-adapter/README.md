# Native SentenceEncoder public API proof

Eighteen full original profiles: Qwen3 and BGE-M3, CPU macOS/Linux and actual macOS MPS, each F32/F16/BF16. All 1,926 vectors match within 1e-6; raw counts, every token/mask, original NumPy ordering and original-derived deadlines match. Expected outputs never enter the Rust process. The real native module and privately copied cores load outside checkout with an empty sentinel PATH; Linux traces execve and execveat. macOS loader traces are not a kernel child-execution audit.

The public API owns lazy tokenizer/model state, empty batches, dimension-triggered loading, verified independent files, serialized whole requests and atomic CPU rebuilding after GPU failures. Model-dtype normalization, pre-canonicalization GPU guards and final outgoing CPU F32 normalization are separate operations. Real tiny CPU/MPS tests cover source removal, failed repair/rebuild, concurrency, late failures and permanent device changes. NumPy ordering and tokenizer fixtures additionally cover boundary lengths and ties.

An initial comparison runner called passage instead of query for the original singular side name. Its failed log is retained; the corrected runner checks the allowed mapping before running, and every accepted profile is from the complete fresh v2 run. Numeric thresholds, original deadlines and product sources were unchanged by that runner fix.

This accepts only the SentenceEncoder adapter. MLX/judge/acquisition/integration and remaining migration stages still have separate gates. M2 remains false and original application sources are preserved.
