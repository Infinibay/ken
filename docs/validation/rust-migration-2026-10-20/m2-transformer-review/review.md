# Whole-plan native transformer review

Reviewed range: `e6dd00fc6fe23182e676260e9fa3f6ebb8c951b8..f55c17a5936aac0ebeb7a1ece3b40fc2495f9fe4`.

This is the single independent final review of the nine-task native transformer slice. I read the reviewer template, plan, transformer specification, relevant parent requirements, complete extracted rulings, ledger closure, and bounded sections of the supplied review package. I inspected the host adapters, token/model policies, runtime/session/client ownership, shared ABI and tests, Torch/MLX cores and weight readers, native build/compatibility changes, preparation, execution, comparison, replay, and CI wiring. This review does not reopen preceding migration plans.

## Strengths

- Ownership is explicit and coherent. `NativeHandle` retains the mapped module, `NativeBuffer` releases results on decoding failures, and `TransformerSession` destroys its model before its independently owned files. Integer registries avoid interpreting stale foreign handles as pointers. Nullable API slots and header-first validation correctly avoid constructing invalid Rust function-pointer values.
- Adapter policy is separated from tensor operations. Whole-request mutex ownership prevents a concurrent caller from executing an obsolete encoder session after CPU replacement. Sentence rebuilding publishes only after successful preparation; judge conversion preserves already-rounded resident weights instead of reloading a higher-precision checkpoint.
- The difficult numerical details are represented directly: CPU-initialized Torch RoPE, `pow(2)` RMS variance, XLM-R nonpad positions and absent all-one attention mask, separate normalization stages, and backend-specific output-head precision. The MLX bridge's added `std::nullopt` argument is narrowly scoped, with exact-core build import and upstream licenses/provenance retained.
- Validation compares actual token feeds, ordering, vectors, raw scores, and state transitions, rather than accepting passing flags alone. Per-model source leases, separate transformer process gates, and immutable original budgets are sound design choices. The independent FastEmbed producer correction is appropriately excluded only from transformer executable source identity; the rulings do not claim new neural executions for unchanged bytes.

## Issues

### Critical

None found.

### Important

1. **The fresh acquisition workflow does not pass the prepared workspace-test environment to its ownership gate.**

   Locations: `tools/rust_migration/transformer_execution.py:63`, `tools/rust_migration/transformer_execution.py:126`, `transformer_migration_tests/test_ownership.py:7`.

   `execute_platform` overwrites `KEN_TRANSFORMER_SOURCE_ROOT` with `sources`, the acquisition parent, rather than the persistent `slots['metadata_sources']` created by preparation. With the workflow's `--acquire-sources`, checkpoints live under temporary `transformer-lease-*` directories and are deleted as each model finishes. The later ownership gate runs **all** `ken-models --lib` tests, including `transformer_tokens::tests::real_original_feeds_and_raw_counts_require_only_tokenizer_data`, which resolves the three registered tokenizer snapshots directly beneath `KEN_TRANSFORMER_SOURCE_ROOT`. Those paths are absent after acquisition leases close.

   Independently, this gate requires an absolute `CARGO_TARGET_DIR`, but the workflow/shared preparation never exports it and `execute_platform` only supplies it to the separate native Torch/MLX environments. The workspace ownership environment therefore fails its assertion before spawning Cargo on a clean workflow. I reproduced that exact assertion with all native paths present and `CARGO_TARGET_DIR` absent, without launching a build or changing files.

   Effect: the advertised fresh CI path fails after substantial preparation/inference work. Borrowed-source local runs with a preconfigured target can pass, so the retained local results do not detect this wiring problem.

   Fix: construct the ownership/workspace-test environment from the completed typed metadata/core preparation, and explicitly carry the workspace Cargo target used to build the probes. Keep acquisition leases separate from metadata-only test inputs. Add a regression that starts with a clean environment, uses acquisition leases that have already been released, and verifies that the ownership gate receives usable metadata and an absolute workspace target. Both omissions need fixing; exporting the target alone leaves the metadata failure.

2. **A declared `include_prompt=false` pooling policy is accepted and silently executed as prompt-inclusive pooling.**

   Locations: `crates/ken-models/src/transformer_model.rs:212`, `crates/ken-models/src/transformer_tokens.rs:207`, `native/ken-torch-backend/src/output.rs:19`.

   Registration validates selected legacy pooling flags but never validates or stores `include_prompt`. Token preparation prepends the configured default prompt, while the native mean-pooling path averages every real attention-mask position. No prompt-length/exclusion policy reaches the core. A correctly authenticated custom registration with a default prompt, mean pooling, and `include_prompt:false` therefore produces finite normalized vectors in the wrong vector space instead of implementing the declaration or rejecting it. Artifact authentication cannot catch this: the ignored policy can match its registered bytes exactly.

   I verified the behavior against the pinned original installed source: `sentence_transformers/sentence_transformer/modules/pooling.py:126` consumes `include_prompt` and masks the prompt positions; `base/modules/transformer.py:989` computes the prompt length. A bounded original Pooling call with hidden states `[[1,0],[0,1]]`, mask `[1,1]`, and prompt length 1 returns `[0.5,0.5]` with inclusion and `[0,1]` with exclusion. Subsequent L2 normalization preserves the difference. The native code can represent only the first computation.

   Effect: silent embedding incompatibility for a supported architecture/module combination accepted by the public registration API. The three frozen catalog entries do not exercise false prompt inclusion, so this finding does not assert a discrepancy in their 33 recorded profiles. The plan explicitly requires unsupported module/prompt configuration to fail rather than produce plausible wrong vectors.

   Fix: at minimum reject `include_prompt:false` as unsupported before inference (and reject malformed values). Alternatively carry the original prompt length and separate pooling mask through the typed pipeline and prove parity. Add an authenticated default-prompt/mean-pooling fixture exercising this exact setting; a cold registration assertion alone is sufficient if the chosen contract is explicit rejection.

### Minor

1. **Native nonfinite judge failures lose the dedicated public error classification.** `crates/ken-models/src/transformer_client.rs:100`, `native/ken-torch-backend/src/output.rs:112`, and `native/ken-mlx-backend/src/output.rs:63` reject nonfinite scores before `RelevanceJudge` can return `ModelError::RelevanceNonfinite`. The error reaches callers as generic `Inference`. This is a diagnostic/API consistency issue: invalid scores still never escape, GPU retry still occurs, CPU/MLX still propagate failure, and the healthy registered corpus is finite. I do not grade this as an Important numerical or safety defect. A future typed native error category would allow a real nonfinite-core failure test to exercise the public classification rather than injecting nonfinite values after the session call.

2. **Known authored trailing whitespace.** `tests/rust_migration/test_transformer_sources.py:31` has the already-recorded trailing blank. No behavioral effect. Preserve verbatim upstream/raw-evidence whitespace rather than rewriting immutable observations merely to make a whole-range whitespace check pass.

## Verification and evidence limits

- Read-only inspection preserved source, index, HEAD, branch, user changes, caches, and evidence. The only authored file from this review is this report.
- Independently checked every retained acceptance manifest entry for exact size and SHA-256. Inspected both platform summaries: macOS has 24 profiles and Linux 9, with the required gate inventory.
- Ran two bounded, read-only reproductions: the fresh ownership-environment assertion and the pinned original prompt-excluding Pooling operation. Python bytecode writes were disabled. No full neural matrix was rerun and no new full native/Rust/Python suite result is claimed here.
- The reported 2247-vector/516-score numerical coverage and complete prior regression results remain the recorded implementation evidence. They should not be described as a hosted CI run. Neither Important finding requires discarding unchanged healthy neural observations; any fix must still obey the existing consumed-source and current-proof gates.

## Recommendations

Fix the two Important issues in the one authorized TDD repair pass. Keep the configuration repair proportional: explicit rejection is preferable to silently accepting a policy whose semantics are absent. For CI, validate the final consumer environment at orchestration boundaries, not only the individual preparation helper. Retain the strong distinction between source acquisition, metadata-only workspace tests, and timed production execution.

## Declined to judge

- Global native acquisition/profile/factory integration and storage completion: explicitly pending under the next M2 plan; this slice does not claim them.
- M3–M8 application migration and final packaging/distribution: outside this plan and not claimed complete. I reviewed the relocatable native module/build boundary included here, not a final installer.
- Numerical CUDA/ROCm behavior on unavailable hardware: no numerical GPU claim is made for that hardware; the reviewed acceptance matrix is the declared CPU/MPS/MLX scope.
- Quantized MLX inference: the vendor bridge adaptation is explicitly unquantized-Qwen scoped; it does not claim quantized model support.
- Arbitrary remote-Python/custom architectures: not implemented by this slice; explicit rejection remains required. This exclusion does **not** excuse the accepted pooling-policy mismatch reported above.

## Assessment

**Ready to merge? With fixes.**

The core architecture, native ownership, and recorded registered-model numerical evidence are strong. Fix the fresh-CI preparation propagation and fail-closed pooling-policy gap before treating this concrete plan as complete; the remaining diagnostic and whitespace findings are Minor.
