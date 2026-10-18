# Independent review: first native Potion profile

Reviewer: fresh `gpt-6-astra`, read-only. Range:
`e1ae714b0f3fb2553ea038519c24440f8acf786e..1892da4113d9bc3c48845d175330c7a8cd879fac`.

## Report

**Strengths**

- Responsibilities are coherent: registration verifies and owns bytes; tokenization owns lexical policy; the encoder owns arithmetic and batching; the cache owns bounded retention; the probe coordinates real execution.
- `VerifiedSnapshot` closes the verification/load race: consumers use the owned, checked bytes rather than reopening paths.
- The port preserves difficult compatibility details, including Unicode character prefixes, UNK/PAD treatment, F16 rounding, empty-row promotion, missing-only batching, cache history, and independent returned vectors.
- Native-execution evidence is substantive: copied executable, isolated working directory, restricted PATH, dependency audits, and an actual Linux execution trace.
- Acceptance distinguishes Potion from complete M2 and preserves compatible identity separately from effective runtime identity.
- Tests use independent Python expectations and exercise meaningful boundaries, corruption, and misleading process outputs.

**Critical findings:** None.

**Important findings:** None.

**Minor findings**

1. **Eviction scans the entire cache while holding its mutex.** `crates/ken-models/src/term_cache.rs:63`. Every insertion into a saturated cache finds the oldest entry by scanning all entries. A stream of distinct short terms therefore incurs thousands of entry visits per insertion, unlike the original ordered cache's constant-time oldest-entry removal. This can increase latency and lock contention; the published sentence workloads do not measure cache churn. Suggested improvement: add a saturated-cache churn benchmark before integrating sustained term-heavy consumers, then use an explicit ordered recency structure if the measured cost warrants it. This is a performance concern, not a demonstrated correctness failure or violated SLA.
2. **The concurrency test exercises only prewarmed hits.** `crates/ken-models/tests/model2vec.rs:175`. All workers repeatedly request the same already-cached term. This verifies synchronized lookup and independent returned values, but does not exercise concurrent cache misses, insertion, or eviction—the more involved mutation paths. Suggested improvement: add a barrier-started scenario with distinct and overlapping misses, keeping expected results insensitive to permissible thread ordering. Include eviction pressure and verify returned vectors and subsequent usable cache state.

**Independent verification**

- Six new Python tooling tests passed.
- A deterministic additional experiment compared 1,000 varied real-vocabulary inputs in ordinary and empty-promoted batches: **2,001 passage outputs passed the existing comparator**, without changing tolerances.
- Original and frozen-reference manifests showed no drift.
- All six current source/input fingerprints matched both platform receipts.
- Published summary, parity, and benchmark files matched their corresponding raw receipts byte-for-byte.
- The platform aggregator passed; the vendored Potion tokenizer matched its declared SHA-256.

The reviewer inspected the full production/tooling/test changes and reviewed large fixtures through their schemas, hashes, and selected content. The reviewer did not independently rerun the complete Python/Rust suites or both platform benchmarks; those results remain the author's recorded evidence.

**Recommendations:** retain the two Minor findings as follow-up items. Preserve the current profile-specific acceptance boundary while implementing subsequent runtimes.

**Declined to judge**

- Other model families, quantized Model2Vec formats, data/storage migration, and M3–M8: explicitly pending and outside this first-profile review.
- Arbitrary custom-model compatibility beyond the implemented policies and fixtures: this review certifies the pinned Potion profile, not every Model2Vec-compatible registration.
- Unchanged M0/M1 implementation: already reviewed; its changed validation tooling and cross-stage integration were included here.
- Preexisting Python/docs/test edits: frozen oracle inputs that this task requires preserving.
- Windows and unobserved architectures/devices: outside the demonstrated Linux/macOS CPU profile.
- Remote CI execution: workflow definitions were inspected, but no remote run was performed.
- End-to-end retrieval quality or whole-application speedup: neither is established by encoder-level parity and phase measurements.

**Ready to advance: Yes, for this first Potion profile.** No blocking correctness or plan-alignment issue was found. Advancing means continuing the remaining M2 work; it does not accept all M2/M8 or authorize a merge.

## Author disposition

Both Minor findings retain that severity after assessing actual user effects:
no correctness failure, deadlock, or violated latency contract was demonstrated.
They remain deferred, with cache churn to be measured before sustained term-heavy
integration. No fix pass or second review was needed. The omitted scopes remain
pending in the migration matrix; no omitted capability is credited as migrated.
