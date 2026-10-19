# Contextual ONNX profile: independent expectations fixed

Status: oracle/fixtures and native runtime complete. The runtime passed the
prepared workspace and original tests on bothOS. Contextual encoder, actual
native process and full platform gates remain pending; this is not context-profile
or M2 acceptance.

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
