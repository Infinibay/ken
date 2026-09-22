# Structural catalogue exploration — 2026-09-17

`structural patterns` now defaults to a hybrid exploration adapter. It shares
FlatBuffers relation/operation buckets across all 23 GoF roots, preserving the
semantic compiler, graph, evidence and CFG verifier. It is not a replacement of
the semantic database with the standalone syntax-only AST backend.

## Complete SDK comparison

Input: `../codex/sdk/typescript`, **26 supported files**, repository HEAD
`4fa7e82274bd70e145da05c66117865f7615e61d`. Both backends ran the entire 23-pattern
catalogue with profiling enabled, no timeout and no result-cache reuse. Each
backend used a separate fresh cache directory, followed by two warm runs.
“Cold” means fresh Ken caches, not a flushed operating-system page cache.

| End-to-end wall time | Indexed | Exploration |
| --- | ---: | ---: |
| Fresh cache | 21.14 s | 20.40 s |
| Warm run 1 | 16.99 s | 15.19 s |
| Warm run 2 | 17.27 s | 15.24 s |
| Warm mean | 17.13 s | 15.21 s |

The measured warm reduction is **11.19%**. Every run completed and returned two
findings with identical bindings, evidence and uncertainty after canonicalizing
evidence order and compilation hash prefixes. The comparable result SHA-256 is
`68a0c59874b83214fb0420e3369829f7041447a8e21b8eac9c3706193efdd5cd`.
Two warm samples are a small measurement, not a general throughput guarantee.

The new bucket cache occupies **7,909,376 bytes** on this scope, in addition to
the approximately 25.4 MB semantic database and 0.84 MB source cache. Generation
of the semantic graph is still required. The earlier full-Codex syntax-only
timings describe a different workload and must not be substituted for this one.

Reproduce each fresh/warm sequence with a new directory:

```sh
PYTHONPATH=.:src .venv/bin/python -m examples.bench.catalog_exploration \
  ../codex /tmp/ken-catalog-indexed --scope sdk/typescript --backend indexed --repeats 3
PYTHONPATH=.:src .venv/bin/python -m examples.bench.catalog_exploration \
  ../codex /tmp/ken-catalog-exploration --scope sdk/typescript --backend exploration --repeats 3
```

[Summary and sizes](sdk-summary.json), [all runs and phase times](sdk-runs.json),
[warm operator profiles](sdk-warm-profiles.json).

## Full Codex snapshot diagnosis

The separate diagnostic uses the pre-existing, compatible IR 1.85.0 semantic
snapshot at `/tmp/ken-codex-perf/native-full-v11/query-index.sqlite`: 2,620,444
entities and 47,154,730 facts. It does not rebuild or verify the current checkout's
source manifest. Both adapters use that same snapshot with **5,000 ms per
pattern**, result caching disabled, and memory-only exploration buckets.

**All 23 patterns exhausted that budget with both backends** in the final run.
No full-repository speedup or complete result equivalence is established.

A timed-out query is incomplete; its zero findings cannot establish absence,
equivalence, or a speedup. This experiment diagnoses remaining large-project
costs rather than measuring time to completion. SQL cardinality planning and
semantic body/initializer checks still consume substantial time.

[Per-pattern outcomes and profiles](full-snapshot-budgeted.json) and the
[snapshot diagnostic script](sealed_snapshot_benchmark.py) preserve the input
provenance and budget. The script requires that local snapshot; the public SDK
benchmark above acquires ordinary source instead.

## Validation

- Broad suite: **13,170 passed, 10 expected failures**, 412.71 s.
- Focused final adapter suite: **104 passed**, including every GoF root in
  Python, Java, TypeScript and Ruby; also covers candidate alternatives, source
  changes, persistence, corruption, interrupted encoding, budgets and CLI output.
- Ruff and the targeted mypy check passed.

The final selective-union optimization was checked by the focused suite after
the broad run. [Validation details](validation.json) record the implementation
fingerprint, commands and the pre-existing unrelated whitespace warning.

After archiving the measurements, 60,321,792 bytes of redundant temporary
benchmark databases were removed. The final exploration SDK cache and the full
semantic/raw-AST reference caches were retained; [cleanup details](cleanup.json).

Implementation and extension boundaries are described in
[catalogue exploration](../../design/kql2/catalog-exploration.md).
