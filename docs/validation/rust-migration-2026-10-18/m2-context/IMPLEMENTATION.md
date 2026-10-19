# Contextual ONNX profile: independent expectations fixed

Status: complete20gate macOS/Linux matrix passed for source4c6db1d8.
Independent whole-plan [review](REVIEW.md) passed with no Critical/Important
findings and one deferred Minor. Context profile accepted; M2 remains pending.

The [shared cases](cases.json) fix20histories. [Original outputs](reference.json)
were captured independently from frozen Python on macOS arm64 and Linux aarch64.
Both have identical registered artifacts, original spec/key/runtime versions and
exact token/mask policies. All six pre-truncation boundaries were checked against
the original tokenizer:511/512/513 including specials and query prefix. Output
vectors retain platform variation at the fixed2e-6/1e-5/cos0.999999 tolerance.
Rust will be compared against its own platform's original, without widening it.

The tiny graph comes from frozen tests/test_context_encoder.py::contextual_model,
adapted through an explicit generator. Its helper hash is retained with one valid
and eight invalid graph fixtures under crates/ken-models/tests/fixtures/context/.
Original raw[sum(ids),sum(mask),zeros] makes prefix/padding/truncation and absence
of L2 observable. Invalid dimension/type/name/input, NaN/Inf and corrupt graphs
fail in Python; extra output rows are silently ignored there and deliberately
become an explicit native error, as declared in the spec.

Targeted capture/original tests pass10/10. Tests first failed for missing capture
and generator modules. The real CLI exposed a relative-output bug missed by the
initial absolute-path test: a regression reproduced it, then normalization fixed
it. The failed fixture attempt is retained privately. Original1066hashes remain
unchanged. No installed command or original source was changed.

[Runtime declarations](runtime-libraries.json) pin native core1.25.1/API25 bytes
for the observed architectures. Private characterization verified owned API
loading/unlink behavior; this does not replace the forthcoming runtime tests.
Linux's one exact CPU-vendor warning is preserved. Zero or one occurrence is
permitted on Linux because CPU identification may succeed; other stderr/counts
fail, and macOS requires silence. Each actual run records its observed stderr.

Raw captures: `.ken/rust-migration/m2-context/oracle-{macos,linux}.json`.
The frozen original reference and model revisions are included in the JSON.

## Native runtime foundation

Commits4f513025/f9a3d00 implement shared bounded regular-file verification and
an authenticated native API owner. Device EOF acceptance and FIFO blocking were
reproduced before the fix; regular HF symlinks remain supported. Runtime
declarations stay lazy, verify requested aliases even when warm, load only a
private authenticated byte copy and remove that temporary file after dlopen.
The mapped handle is retained process-wide before environment construction.

Tests cover actual core1.25.1/API25, malformed C API symbols/pointers/version,
foreign initialization, byte corruption, conflicting identity and an eight-alias
cold race. A strengthened diagnostic test exposed generic macOS dlsym text; the
error now names the missing symbol. Full prepared Rust passes70distinct tests
(71reported including a preexisting nested child), fmt/clippy are clean and
22original Python tests pass on bothOS. Original1066hashes remain unchanged.
Raw Linux evidence is `.ken/rust-migration/m2-context/t2-linux-receipts`; macOS
task logs and ledger retain RED/GREEN evidence. Whole-profile gate/review remains
pending, including CI preparation for the newly explicit native-core prerequisite.

## Contextual encoder

Commitda99f0a matches all20registered histories and exact original spec/key/tokens
on each OS at unchanged tolerances. The encoder owns tokenizer policy, shares
immutable verified graph bytes and serializes one lazy CPU2/1 session. It returns
raw owned768-vectors. Snapshot artifact proof prevents passing a different model's
verified bytes under this model's identity.

Cold-process tests first reproduced use of the native API before initialization;
the session/runtime now initializes before any tensor construction. Empty batches
still succeed without a core, and missing core queries return errors. All eight
invalid graph classes error, including the original extra-row gap. Mixed-input
concurrency and independent result buffers pass. Both platforms passed77distinct
Rust tests (78reported including the old nested child), fmt/clippy and10targeted
original/oracle Python tests. Original1066hashes remain unchanged. Raw Linux
receipts: `.ken/rust-migration/m2-context/t3-linux-receipts`.

## Complete native process and platform proof

Source4c6db1d8303b3c773fd4dd75bae3cad6421a6014 passed20/20gates on both
Darwin/arm64 and Linux/aarch64 with unchanged sources throughout each run.
The [matrix](matrix.json) recomputes13current candidate fingerprints and rejects
matching stale receipts. [macOS](macos/summary.json) and [Linux](linux/summary.json)
retain all nested18table gates plus actual contextual release/parity bindings.
Selected probe == just-built release == executed process SHA-256 on each OS.

Both platforms:15626Python passes,10historicxfails,no new failures/missing IDs;
77distinct Rust passes (78reported because an existing test invokes a nested
child), no ignored tests; fmt/clippy clean;76migration process tests pass with no
skips. Linux mypy checks409files without errors; macOS retains only the same two
historical missing-transformers imports. All1066original hashes and frozen
reference inputs remain unchanged. Original warnings/failure history stays in
raw receipts; no old tests or constraints were weakened.

Each platform repeated18Potion histories,16NPZ histories and62M1 cases, and
retained120Potion phase benchmark samples. Context adds20histories with exact
IDs/masks/legacy identity and tight local-original raw768vector bounds. Native
runs execute owned model/core/executable copies outside the checkout with a
sentinel-only PATH, no native child, separate executable/core dependency audits
and actual Linux [trace](linux/context-native-exec.trace) of exactly1exec.
The macOS core SHA is4478626717e213a1827ab52af61d1a0ac08f9906bcb2c2ab4563124967b2948b;
Linux0ebab581324d80e2975d743eabcf640ac3f8acd429ca8af656ce4f121672afde.
macOS stderr is empty; Linux preserves exactly one calibrated CPU-vendor line.

[macOS measurements](macos/measurements.json) and [Linux measurements](linux/measurements.json)
retain per-case construction/explicit preparation, inference and cumulative
post-exec process peaks. Model-byte preparation is separate for native; original
constructor loads reverify model data. These phases are not equivalent exclusive
allocations and establish no speedup/SLA. Raw vectors/stdout/stderr/every attempt
remain in `.ken/rust-migration/m2-context/validation` and
`linux-receipts/validation`; the public measurements omit only numeric calls,
which the original and actual process JSON retain privately.

Both native workflows now prepare explicit context snapshot, core and probe
inputs. Their shared Python preparation block parsed and ran on macOS using the
actual cached data/core. Linux smoke verified actual core/copy/env, explicitly
substituting only the resolver for its already prepared private data paths in a
throwaway process. This is not network preparation or remote CI evidence. The
workflows target the registered ARM architectures; x86/native installation and
M8 packaging remain pending. No installed entrypoint or user index is promoted.

The native probe exposes factual unloaded/prepared/core state; empty-only input
succeeds even when the declared core file is missing and reports null actualcore.
The comparator rejects altered IDs/masks/raw vectors, nonfinite original/native
values, wrong shape/runtime/core/OS/stderr and stale release.58targeted tooling/
original tests passed before full gates. RED/GREEN logs and all rulings remain
in this plan's ledger until final-review archival. The independent review passed without a correction pass; its one deferred Minor
records the native CPU arena disabled versus original enabled allocation policy. M2 as a whole
still includes remaining runtimes, selection/preparation and storage.
