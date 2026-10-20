**Ready to merge this FastEmbed block: With fixes.** Three Important findings; no Critical findings. The native implementation and retained CPU compatibility proof are strong, but CI preparation and process deadlines need repair.

### Strengths

- Clear responsibilities: file ownership, ONNX dependency traversal, tokenization, pooling, provider construction, and lazy coordination each have an identifiable owner.
- Private files are copied and hashed through the same opened regular inode, published only after verification, and retained beyond session destruction.
- Tokenization preserves special-token insertion order and serialized padding; batching occurs before padding. Pooling preserves the F64 promotion and final F32 cast boundaries.
- Compatibility proof recomputes actual tokens/vectors from authenticated raw records. Re-sealing altered native evidence does not bypass semantic comparison.
- The original German FP16 failure is narrowly bound to its model/revision/graph/error signature. This is an explicit preserved baseline, not a broad missing-vector exception.
- `.gitattributes` is appropriately scoped to byte-exact acceptance evidence. Its effect does not conceal source changes.

### Critical

None found.

### Important

**1. CI eagerly downloads more model data than the configured runners’ documented storage.**

- **Location:** `.github/actions/prepare-native-validation/action.yml:89`
- **Trigger:** A fresh standard runner executes the unconditional catalogue snapshot loop.
- **Effect:** The unique registered sources total **18,952,301,850 bytes**, before private copies, earlier model prerequisites, Python dependencies, build products, and evidence. GitHub currently documents **14 GB SSD** for both configured ARM runner labels. The workflow therefore requires capacity beyond its declared runner contract and can fail before producing any acceptance evidence. Actual GitHub free space was not measured; this finding does not claim an observed GitHub ENOSPC failure. [GitHub runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- **Remedy:** Make acquisition and lifetime bounded within an explicitly owned CI cache, or use an already authorized adequately provisioned runner configuration. Preserve all models and gates. Add a capacity check covering source/private-copy/build/evidence peaks; a preflight rejection alone improves diagnostics but does not make the present eager workflow runnable within documented capacity.
- **Validation:** Exercise the complete acquisition/release schedule under a bounded disk budget and confirm all 30 models, five ownership families, and 34 gates remain covered. Never solve this with global cache deletion or implicit paid infrastructure.

**2. The isolated matrix job lacks its new NumPy dependency.**

- **Location:** `.github/workflows/rust-models.yml:81`; dependency consumers at `tools/rust_migration/fastembed_reference.py:246` and `fastembed_compare.py:87`.
- **Trigger:** The fresh matrix runner executes `uv run --no-project ...` without installing project dependencies or explicitly supplying NumPy.
- **Effect:** Authenticated replay raises `ModuleNotFoundError: No module named 'numpy'`, preventing matrix acceptance and even normal summary publication despite valid platform receipts.
- **Evidence:** Replayed the actual retained matrix with site packages disabled. It failed at `validate_model_record()`’s NumPy import. The same matrix passed with the prepared environment.
- **Remedy:** Explicitly provide the pinned numerical dependency for this isolated command, or implement equivalent bounded standard-library F32 decoding/comparison without changing tolerance or finiteness checks.
- **Validation:** Run the exact matrix command in a fresh environment containing only its explicitly declared dependencies, against both complete retained platform trees.

**3. Native process framing can bypass the promised whole-process deadline.**

- **Location:** `tools/rust_migration/fastembed_process.py:76` and `:79`
- **Trigger:** A native process writes part of a response line and stalls without a newline or EOF. Similarly, writing a request can block if the child stops consuming input.
- **Effect:** `select()` only establishes that some bytes are readable. The subsequent blocking `readline()` can wait indefinitely, so the 1800-second deadline no longer bounds validation. This matters precisely when a native regression causes malformed or incomplete output.
- **Evidence:** Exercised `send()` with a real child that emitted `{`, flushed, and stayed alive for 1.5 seconds. With a 0.1-second deadline, `send()` returned only after **1.52 seconds**, raising a JSON error at EOF rather than timing out.
- **Remedy:** Use deadline-aware incremental pipe I/O with bounded framing, covering writes and reads. Ensure timeout cleanup terminates/reaps the owned native execution, including the Linux tracer arrangement.
- **Validation:** Add real subprocess tests for partial-line stalls, a child that stops reading, oversized output, and timeout cleanup. Assert bounded elapsed time and no surviving owned process.

### Minor

None raised.

### Mandatory review-focus assessment

1. **Hidden external initializers and overflow:** Reviewed model/graph/node/attribute/function/training/sparse traversal, range arithmetic, path checks, metadata ambiguity rejection, and bounded protobuf parsing. No escaping dependency defect found.
2. **Source mutation, failed copies, special files, lifetime:** Reviewed streamed copy cleanup, opened-inode regularity checks, FIFO/device tests, post-preparation source removal, and session-before-owner destruction. No product ownership defect found. The separate controller deadline defect is Important finding 3.
3. **Padding, specials, configuration bounds, batch257, cast timing:** Reviewed implementation and distinguishing tests for each. No parity defect found.
4. **First use, concurrency, provider fallback, failed CPU construction:** The mutex covers complete requests, preparation publishes only after successful construction, and CPU retry errors propagate. Real C API fallback tests and CPU failure tests support these paths. No readiness/result-crossing defect found; numerical GPU execution remains unproved as explicitly disclosed.
5. **Bad output and stale/resealed proof:** Shape/dimension/finiteness checks, source/model/binary binding, bounded authenticated decompression, and semantic replay are present. Focused mutation tests passed. No false-certification defect found.

### Verification performed

- Read the binding specification, plan interfaces/tasks, ledger rulings, native implementation, controller/comparator/evidence code, shared validator changes, and relevant tests in bounded passes.
- Replayed the retained current two-platform matrix: **exit 0, `passed: true`, `FastEmbed_accepted: true`, `M2_accepted: false`**.
- Ran the focused comparator, evidence, input-forwarding, and validator test modules: **all passed**.
- Reproduced the NumPy-free matrix failure and partial-frame deadline failure.
- Independently recomputed the unique catalogue source-byte total.
- Did not rerun heavy neural inference, launch Docker, or modify repository sources, Git state, or model caches.

### Declined to judge

- **Numerical GPU parity:** No usable GPU execution hardware was supplied; availability/fallback behavior was reviewed, and CPU proof is not downgraded for this limitation.
- **Remaining M2/M3–M8 integration and installed application replacement:** Explicitly outside this seven-task block; no whole-migration completion assessment.
- **Unrelated pre-existing subsystem defects:** Prior blocks were reviewed independently; this review covered their changed interfaces and acceptance interactions.
- **Arbitrary same-user/root tampering with private staging directories:** The defined ownership boundary protects against source mutation and borrowed-file lifetime errors; it does not establish a sandbox against another process with the same filesystem authority.
- **Exact hosted-runner free space and end-to-end GitHub execution time:** No live GitHub run was performed. Capacity grading uses the committed acquisition behavior, registered byte totals, and documented runner contract.

The three fixes should be combined into the authorized single repair pass, followed by the required fresh acceptance.
