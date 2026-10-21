# Public native relevance judge

All twelve original profiles execute through RelevanceJudge::score: macOS CPU/MPS/MLX and Linux CPU, across F32/F16/BF16. Each profile preserves all15 cases,13 neural feeds,43 raw yes-minus-no scores, exact tokens/masks/query truncation, budget15/16 errors, empty-document loading/error behavior and permanent device/dtype transitions. All original-derived deadlines and1e-5 raw tolerance stay fixed; expected scores never enter Rust inputs.

CPU/F32 recovery converts resident tensors, preserving prior lower-precision rounding. It does not reload checkpoint weights. Distinguishable real heads verify explicit versus tied output projection and different Torch/MLX head precision rules. Real tiny-model lifecycle tests cover concurrency, late failures/nonfinite results, whole-request retry, failed conversion and CPU/MLX error propagation. Original Python files remain intact.

All processes run outside checkout with empty PATH and authenticated private model/native-core ownership. Linux retains both execve and execveat audit traces. macOS loader observations prove actual private core loading; they are not a kernel child-execution audit. This accepts the relevance adapter only. Global M2 acquisition/integration and subsequent migration stages remain separate gates.
