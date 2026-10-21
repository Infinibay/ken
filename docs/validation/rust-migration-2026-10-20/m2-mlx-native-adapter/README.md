# Native MLXEncoder public API

All 36 original requests and 48 observed feeds match through the public Rust text API on actual Apple GPU, across F32/F16/BF16. Counts, tokens, masks and stable increasing token-length order match exactly. All 321 vectors remain within 1e-6, with unchanged original-derived deadlines. Expected outputs never enter the Rust process.

The public API preserves lazy empty/count/model states, source ownership after removal, calling-thread stream selection, serialized requests and error propagation. Real tiny GPU tests cover repair, concurrency, actual all-zero hidden states and interrupted late requests. MLX keeps its own text policy: Ken prompts and right padding, no ST default prompt/lowercase/sequence clamp, no CPU demotion. Retired-buffer bounds preserve lower caller cache limits and the live host limit, as verified by the unchanged native core tests.

Production runs execute outside checkout with sentinel PATH and verified private native files; loader evidence shows the private MLX core without Torch/Python linkage. macOS loader diagnostics do not constitute a kernel child-execution audit. The exact native core/API source subset equals the separately verified six-profile core proof. Linux runs the shared text/model regressions and records MLX hardware as nonapplicable.

This accepts only the MLX adapter. Relevance judge, acquisition/integration and remaining migration stages have separate gates. M2 stays false and original sources are preserved.
