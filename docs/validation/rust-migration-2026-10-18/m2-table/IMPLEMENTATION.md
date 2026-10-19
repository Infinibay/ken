# Native NPZ table profile

Accepted for this profile; Linux and macOS each passed18/18 gates after the single
review correction pass, with matching eight source/input fingerprints and
Rust1.95.0. The [independent review](REVIEW.md) found three Important issues;
all were reproduced and fixed with TDD. This does not close M2.

The original bundled NPZ remains unchanged. Frozen Python outputs for16 histories
were captured before Rust. Native `StaticTableEncoder` owns its converted arrays
and serialized tokenizer policy: UNK/padding/truncation remain intact, with no
Potion prefix/limit policy. Sum and norm preserve NumPy F32 pairwise grouping;
int8 scales, F16/F64 casts, negative LUT, Fortran and big endian are exercised.

Eight independent valid fixtures plus10 malformed artifacts and an overflowing
NPY header regression cover conversion, numerical cancellation and corruption.
The header test first reproduced a panic in npyz; explicit literal shape/payload
checks now return an error before unchecked library arithmetic. No pickle runs.

Both platforms passed15618Python tests+10historicalxfail,62distinctRust tests,
73explicit migration tests,18Potion histories,62M1cases and16table histories.
macOS retains two historical missing-transformers mypy errors; Linux checked409files
without errors. Corrected full raw receipts are retained at `.ken/rust-migration/m2-table/validation-corrected`
and `linux-receipts/validation-corrected`; earlier pre-review runs and the interrupted wrong
snapshot-path attempt is retained separately and was not accepted.

The native probe runs outside checkout with restricted PATH, owned data copies,
strict exact tokens/zero vectors and fixed F32 atol2e-6/rtol1e-5/cosine0.999999.
Public [macOS](macos/summary.json) and [Linux](linux/summary.json) receipts are
verbatim copies; the [matrix](matrix.json) passes. The [Linux trace](linux/native-exec.trace)
contains exactly one initial exec. The additional
[source binding](macos/source-binding.json) (also recorded on Linux) records the
mandatory automatic table_release gate. It requires the selected executable,
freshly built release and actual parity process hashes to match. Process tests
require explicit KEN_TABLE_PROBE; no sibling inference is allowed. Code receipt
commit is f84c472d. The previous17-gate receipts remain historical evidence only.

Duplicate NPY keys are rejected before unchecked npyz arithmetic. A nonfinite
computed norm now returns an inference error before division; frozen Python
also returned false zeros for this overflow, so the stricter error is an
intentional narrow correction. Empty and valid zero inputs retain their results.
Four added Rust regressions, stale-binding/matrix/selection/environment regressions
and the complete suites verified all three changes without widening tolerances.

[Measurements macOS](macos/measurements.json) and [Linux](linux/measurements.json)
retain all16fixed case histories per engine and OS.
They include mixed calls, not30identical benchmark repetitions. Peaks are cumulative
post-exec process peaks. Python reopens/decompresses its artifact per construction;
Rust reads/hashes owned NPZ bytes once as preparation and constructs from those
bytes. No global speedup or new SLA is claimed. The composed gate also retains
all120Potion phase benchmark samples in its raw base receipts.

Other models, native model preparation/policy, data/storage and M3–M8 remain
pending. No installed entrypoint was replaced, no original was deleted, and
no push/PR/remote CI was performed. CI definitions prepare all native examples.

## Execution decisions

- Ruling: human instruction to continue until whole migration is complete carries authorization to elaborate and execute remaining subplans under approved full design and native method — preserve written specs/plans and review gates without asking repeated permission — cost if wrong: scope decision would diverge from intent; no feature scope, originals, installed entrypoints or external publishing changes.

- Ruling: retain prior plan workspaces until raw audit/prototype inputs are durably relocated — current model source archives and reference inputs still depend on them; public review decisions committed — cost if wrong: premature cleanup can destroy reproducibility.

- Ruling: full Python suite runs at T3 close on both platforms, with original table tests and prepared Rust workspace per task — originals unchanged and full suites just passed; avoid redundant repeated long baseline runs — cost if wrong: cross-tooling regression may surface later but blocks profile acceptance.

- Task2: Ruling: add direct py_literal0.4.0 (already transitive) for safe NPY prevalidation — npyz0.9.1 multiplies shape/strides unchecked before returning its header; malformed shape reproduced a panic — cost if wrong: preflight may reject otherwise-valid exotic tables; current declared arrays/versions/layouts covered, no executable Python introduced.

- Task3: Ruling: keep actual process tests in migration_tests like Potion/M1, while ordinary pytest covers comparator/aggregation — full suite must not compile or depend implicitly on a prebuilt executable; explicitly prepared migration suite runs after release build — cost if wrong: missing preparation fails that separate mandatory gate, never skips it.

- Task3: Ruling: table_validate composes complete16 model/M1 gates and adds independent table proof rather than duplicating suites — receipts require all17 gates and eight matching identities; old receipts are not accepted for new code — cost if wrong: inherited gate semantics could drift; negative aggregation tests cover every gate and key identities.

