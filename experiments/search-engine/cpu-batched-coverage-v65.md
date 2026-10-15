# Exact batch query-term coverage v65

Real prepared-request profile v50 spent 0.668 instrumented seconds in 11,280
TermAlignment.summarize calls, including 8,779 quantiles/0.387 seconds. Each
source view already has its query-term maxima. Batch their independent summaries
once per coverage invocation; preserve one-row weighted dot accumulation, empty
views versus measured zero, all six values, query ordering and validation.

Use no new model, representation, features, source data, profile, training or
query-dependent retained cache. Meaningful public boundary tests cover complete,
partial, absent, negative, empty, zero-weight and invalid/nonfinite views plus
read-only input. Compare the old frozen scalar implementation and the new batch
on both float32/float64 inputs before the complete API run.

For an isolated CPU control freeze v56b plus ONLY alignment.py,
evidence_features.py and this protocol. It deliberately retains extractor5 and
the original source5 indices; the concurrent genuine extractor7 C correction
requires its own real reindex and cannot be mixed into speed/parity claims.

Run ALL400 original requests with the same 16 whole-repo-excluded235 models,
source/context/query assets, real prepared API and canonical JSON renderer.
Require zero missing/errors, full response byte equality with v56b SHA
e3ae62e0cc3aade1b26b4de094d11a1f72adb17acbd29c1cc8f7fe2fdbed7ca6,
277 strict and290 identity. Keep startup/index preparation separate and record
p50/p95/max plus worker peak RSS per repo. Concurrent timings are descriptive,
not the final uncontended CPU/low-RAM certificate. Do not open private acceptance,
change original ALL-anchor references, denominator, budgets or thresholds.
