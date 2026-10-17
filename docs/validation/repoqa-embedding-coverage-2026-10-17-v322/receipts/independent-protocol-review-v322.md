# Independent follow-up review — V322

No new required findings in the four reviewed scripts. The four actionable V321 findings are resolved at the source/protocol level. This is not confirmation that native export, ONNX parity, captures, or grades have run successfully.

- **Native pooling and parity corrected:** `export.py:12–20` asserts official CLS configuration and exports CLS. Lines 34–42 check capture-tokenizer IDs/masks against native IDs/masks, compare the actual `SentenceTransformer.encode` output bitwise with the export wrapper, and compare ONNX with that official output. The six synthetic cases include both registered prompt roles and a long truncated source. This addresses the former self-referential mean-pooling parity test. Actual runtime success remains a gate, not an assumption.
- **Pre-grading completeness gate corrected:** `preflight.py:13–31` verifies artifact hashes, registered producer/input pins, absence of worker failure markers, complete CPU provenance, exactly matching request-ID multiplicities, mandatory pinned artifacts, and totals of 60 successful workers/600 calls. Both `grade_control.py:5–6` and `grade.py:13–14` invoke it before importing the criterion or loading references. A closure marker alone no longer permits these graders to proceed.
- **Final top-100 reporting corrected:** `grade_control.py:51–59` and `grade.py:61–67` remove the unmeasured final-stage top100 field from rows, summaries and deltas while retaining contextual top100.
- **Preparation-cost qualification corrected:** `grade_control.py:50` explicitly describes mixed Jina cache state and rejects a cold-indexing interpretation. Existing RSS/source-preparation and FP32/padded-storage qualifications remain necessary.

Lightweight validation used only newly generated synthetic files in an automatically removed temporary directory. The unchanged `preflight()` function accepted a complete synthetic 600-call capture and rejected: a missing ID, a duplicate ID, incomplete provenance, a worker failure marker, and an altered artifact hash. For the ID/provenance mutations the synthetic closure hashes were updated, ensuring rejection came from the semantic gate rather than a hash mismatch. All four scripts parsed successfully. No actual capture data, response/raw files, grades, private reserve, or model execution were used; no producer files were edited.

The original scope limitations still apply: this is a fixed-artifact comparison on exposed English RepoQA C++/Rust queries, not an isolated causal estimate of language-training coverage. RRF diagnostics remain separate from public API results, and any uncertainty estimates should respect repository clustering. The follow-up did not audit other V322 scripts or attest the execution environment.

Reviewed SHA-256 identities:

| Script | SHA-256 |
|---|---|
| export.py | `9be8386b6d83daa8b45f2cbb7c86ca751e63becdda51569a1ee8b0a4a1400fc3` |
| preflight.py | `beac12e6e67bbfbfbcdfc8bbc02b2c9642f09e095030c76293e464aae7d002ce` |
| grade_control.py | `729d99ad30f4b9484d7d93af32ff245a746f40cf3577639004109e33dc74a021` |
| grade.py | `666ef60d802cdc8cc589add772d4a15f57d3e2c23420a7b62cf7be4efa0e8a0d` |
