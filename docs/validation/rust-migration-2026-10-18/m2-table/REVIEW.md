# Independent whole-plan review

Fresh reviewer: `gpt-6-astra`, `/root/m2_table_review`, read-only, range
`a649edb4..bcdb15ff`. Verdict: Ready with fixes. No Critical, three Important,
no Minor findings. This report records the returned findings and disposition;
the author performs one TDD correction pass, without re-review.

Strengths: responsibilities are clear; independently captured fixtures cover all
five Review Focus classes; shared RSS and CI behavior remain appropriate. The
reviewer checked eight fixture hashes, ran all twelve table integrations and
comparator/aggregation tests, recomputed the matrix and verified the observed
source bindings. Changes after `110685ef` were documentation only.

1. **Important: duplicate NPY fields bypass preflight.** `table_npz.rs` chooses
   the first field while npyz chooses the last. A valid first shape followed by
   `(18446744073709551615, 2)` panics in debug arithmetic. Release returns a later
   error. Reject duplicate header keys, including shape, dtype and order, before
   handing the header to npyz. Private reproducer and stderr are retained under
   `.ken/rust-migration/m2-table/review-audits/`.
2. **Important: overflowing normalization returns a false zero embedding.**
   Finite weights and projected components can produce an infinite F32 squared
   norm; division then returns finite zeros. Frozen Python has the same defect,
   so this is an intentional narrow error-contract correction. Reject a
   nonfinite computed norm before division; preserve valid empty/zero outputs,
   grouping and existing tolerances.
3. **Important: acceptance is not automatically bound to the table executable.**
   The base validator rebuilds examples but binds only `model_probe`. The process
   suite can choose a stale sibling, and the table validator accepts an arbitrary
   output-compatible executable. The observed receipts were manually checked and
   do match; future runs must require the supplied table hash to match the fresh
   in-tree release, record that binding and select the process executable
   explicitly. Reject stale/missing/mismatched bindings in local and matrix gates.

All three are retained as Important by the author and enter the single fix pass.
No numerical expectation or tolerance is weakened.

## Areas the reviewer declined to judge

- Existing M0/M1/Potion behavior and deferred cache items were reviewed previously.
- Model selection, `KEN_STATIC_HEAD`, storage, remaining runtimes and M3–M8 remain
  pending and are not covered by this table profile.
- Additional permissive NumPy conversions are explicitly outside this profile;
  unsupported representations return errors.
- Windows is outside the approved Linux/macOS matrix.
- No new table SLA or thirty-repeat benchmark was required; the sixteen case
  histories support no global speedup claim.
- Unrelated original dirty files and private future-runtime experiments are
  outside this review range.

Each boundary is ruled on with its cost in the execution record; none is treated
as completion of the full migration.

## Verified disposition

All three Important findings are fixed in f84c472d, in one author correction pass.
No re-review was dispatched. Duplicate dtype/order were first observed accepted
and duplicate shape panicked; all three now return errors. The initial test
builder had an invalid comma and was corrected before accepting RED evidence.
Overflow norm first returned a false zero; it now errors while empty/zero stays
valid. Stale binding, missing explicit selection, ignored matrix binding and
missing environment forwarding each failed before the fix and pass afterwards.

The complete corrected matrix passes18/18 gates on both macOS arm64 and Linux
aarch64:15618Python passes+10historicalxfail,62distinctRust tests,73real process
migration tests,44tooling tests,16table histories,18Potion histories and62M1cases.
Format/clippy pass. macOS has only its two historical missing-transformers mypy
errors; Linux409files clean. Original1066hashes and frozen sources are intact.
Both receipts bind the actual table process to its newly built release; Linux
trace contains exactly one initial exec. No Important/Critical finding remains.
