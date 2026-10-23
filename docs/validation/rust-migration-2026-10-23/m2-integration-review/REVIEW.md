# Final whole-plan review

Reviewer: one fresh `gpt-6-astra` agent, high reasoning, read-only.
Range: `4b1efd9d5345779220a82fba23ed62ea54b0988f` through
`6eca4cb12752a342cee2dc4df2c9c4fc879424a1`.
Plan: `docs/superpowers/plans/2026-10-21-rust-model-integration.md`.

## Strengths

- Clear ownership boundaries between profile identity, acquisition, transport,
  catalog selection, and backend execution.
- Cache tests exercise real files, failed streams, concurrent publication,
  symlink substitution, and winner preservation.
- Profile identity tests compare literal original captures, including nested
  optional configuration.
- The retained evidence distinguishes fresh factory calls from previously
  accepted numerical coverage. The unmodified complete matrix replay passed
  independently during this review.

## Critical

None found.

## Important

1. **Reject a judge runtime whose backend differs from the selected profile.**
   `crates/ken-models/src/model_factory.rs:128`. `judge()` selects resources.mlx or
   resources.torch but never checks runtime.backend(). Both fields accept the same
   public type, and neither RelevanceJudge nor TransformerSession subsequently
   binds that runtime to the profile backend. Supplying a valid Torch runtime in
   resources.mlx permits Torch execution under an accredited MLX identity. The
   reviewer reproduced mismatched owner acceptance with the recorded native
   binary, without loading a model. Require the selected backend and test both
   crossed assignments cold.
2. **Check preparation capacity on the filesystems receiving allocations.**
   `crates/ken-models/src/model_sources.rs:132`. All checks used the artifact cache
   even though model copies and derived artifacts use private_parent and native
   runtime copies use system temporary storage. These may be separate volumes;
   one volume's capacity cannot authorize filling another. complete_capacity also
   charged source bytes when already cached or borrowed. Calculate incremental
   allocations by actual destination filesystem and combine allocations sharing
   one filesystem, applying the reserve there. Cover cached/borrowed sources and
   separate cache/private/runtime destinations.
3. **Bind FastEmbed replay to authenticated actual preparation.**
   `tools/rust_migration/integration_replay.py:161`. The branch checked model name,
   family and vectors but ignored prepared state and preparation fingerprints.
   In a temporary copy, the reviewer changed Linux offline model_fingerprint and
   verified_artifacts_fingerprint, set prepared=false, and resealed the file hash;
   aggregate_integration still returned passed=true and M2_accepted=true. Compare
   preparation to pinned registration/direct evidence in public and offline phases
   and add resealed whole-matrix controls.

## Minor

None identified.

## Declined to judge

- Previously accepted transformer mathematics and backend numerical proofs:
  explicitly outside this integration review.
- Search/indexing entrypoint integration and M3–M8 completion: outside this plan.
- Fresh execution of complete neural matrices and regression suites: retained
  results were inspected and the complete saved-evidence matrix was replayed;
  focused reproductions were sufficient for these findings.

## Original verdict

**Not ready for acceptance; fix the three Important findings.** Implementation
substantially follows the plan, but runtime selection, physical capacity
enforcement, and one model-identity acceptance boundary remain incomplete.
No checkout files, index, HEAD, or branch state were changed by the reviewer.

The executor owns grading and the one TDD repair pass. No second reviewer is
dispatched. Subsequent results are separate from this original review.
