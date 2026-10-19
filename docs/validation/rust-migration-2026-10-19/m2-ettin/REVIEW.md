# Independent whole-plan review

Reviewer: `gpt-6-astra`, fresh context, read-only. Range:
`161aa2be1d829129bae5c2f7845f2f09e58ded1e..af4c1a3ae5f6e4cd0033c253c4a092e463cc8011`.
The report below is retained verbatim. The executor independently reproduced the
Minor and kept its grade because authenticated source and exact derived hashes
protect the registered profile. No Critical/Important correction pass or second
review was needed. All declined items and the deferred Minor are recorded in
[EXECUTION.md](EXECUTION.md). No merge or installed-entrypoint promotion occurred.

### Strengths

- Clear ownership boundaries: registration and authenticated bytes belong to `RerankerModel`/`PreparedReranker`; graph assembly, cache publication, token policy and inference each have focused owners.
- Preparation consumes verified owned bytes, preserves untouched protobuf fields, verifies the derived graph before publication, and revalidates a concurrent winner. Tests exercise corruption, failed publication, concurrency, arbitrary cache names, permissions and path replacement.
- Scoring preserves lazy-load/error ordering, query capacity, only-second truncation, right padding, remainder batches and raw ordered F32 logits. One mutex protects session initialization and use; returned tokens and scores are owned.
- The thread-count and tiny-token-budget corrections are justified by actual dependency behavior. CPU arena policy feeds both the successful session builder and reported metadata.
- Validation provides substantive native execution evidence: fresh graph assembly outside the checkout, independent source copies, authenticated core, release/executed-binary binding, frozen oracle comparison and fresh original replay.

### Critical

None found.

### Important

None found for the registered Ettin profile.

### Minor

1. **The compiler checks the first opset version without validating its domain or additional imports.**

   **Location:** `crates/ken-models/src/published_head.rs:157`

   `find(|f| f.tag == 8)` accepts the first import with version 18, even when its domain is unrelated to the default-domain operators being appended. It also ignores a subsequent conflicting default-domain import.

   I reproduced both through the public `compile_head` API using authenticated copies of the tiny fixture in `/tmp`:

   - Default-domain version 18 followed by default-domain version 17: accepted, producing 1,820 bytes.
   - The only version-18 import changed to `unrelated.domain`: accepted, producing 1,830 bytes.

   This weakens the compiler’s malformed/ambiguous-input diagnostics and can defer an unsupported graph failure until runtime. It does **not** compromise the registered Ettin result: source authentication and the exact derived size/hash prevent these modified inputs from being accepted under that registration.

   Validate the default-domain import explicitly and reject duplicate/conflicting imports according to the supported recipe. Preserve acceptance of both omitted and explicitly empty default-domain fields. Add focused tests alongside the existing wrong-version case.

### Validation and coverage observations

I read the plan/specification, every ledger `Ruling:`, changed production Rust, probe, Python fixture/oracle/comparator/validator code, prerequisite forwarding, workflows and relevant tests.

Without rerunning the expensive platform suites, I independently:

- Recomputed the matrix against the current checkout: **passed**, all **18 fingerprints**, both registered platforms, **23 gates** each.
- Recompared both retained native Ettin outputs with their frozen platform oracles: **no differences**.
- Recompared both fresh original replays with the frozen oracles: **no differences**.
- Verified the published Python, Rust, typing, formatting, clippy and process-test logs against their receipt hashes.
- Confirmed **15,644 Python passes / 10 historical xfails**, **107 reported Rust passes**, and **79 migration process cases** on each platform.
- Confirmed the retained Linux Ettin trace contains exactly **one exec**.
- Confirmed both published measurement sets contain all **23 histories** and identify source checkpoint `ffb65afc`.

The native output comparisons also revalidated the raw HWM samples and their exact observed-maximum envelope. The implementation does not manufacture monotonic raw measurements.

Review work was read-only in the checkout. The focused compiler experiment used `/tmp/ettin-final-review-hfzlbxe2`.

### Recommendations

Record the opset-validation issue as a deferred Minor. No Critical/Important correction pass is warranted by this review.

### Declined to judge

- **Prior contextual encoder CPU-arena policy:** unchanged owner and already deferred separately; the new Ettin policy was reviewed independently.
- **Whole-M2 completion, remaining runtimes, acquisition/selection, storage and installed-entrypoint promotion:** explicitly outside this scoped migration; receipts correctly retain `M2_accepted: false`.
- **Remote hosted-CI execution and live network preparation:** retained evidence covers local platform execution and declared offline preparation smokes, not an actual remote CI run.
- **Exact allocation peaks, memory SLA or speedup:** measurements substantiate observed kernel reports and elapsed times only; no such performance guarantee is claimed.
- **General ONNX semantic validation beyond this fixed published recipe:** this compiler is not a general ONNX validator. The concrete opset ambiguity above is reported rather than excluded.
- **Additional platforms and architectures:** acceptance is expressly limited to Darwin/arm64 and Linux/aarch64.
- **New hard limits on document length or unbounded token-inspection helpers:** these preserve the original behavior; introducing a broader resource policy belongs to a separately defined contract.

### Assessment

**Ready to merge? Yes, for the scoped Ettin profile, with the Minor recorded.**

The implementation meets the registered model’s preparation, ownership, lexical and raw-score contracts, and the retained current-source evidence supports both platform acceptances. No blocking regression or unsupported whole-M2 claim was found.
