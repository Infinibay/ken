# Compiled exploration: implementation and measurements

Measured September 17, 2026, against `/Users/andres/Projects/codex`, using the
public `ken.kql2.service.search(..., backend="exploration")` API. The implementation
is documented in [exploration-engine.md](../../design/kql2/exploration-engine.md).

The source set contains **5,295 supported files**, 66,872,846 source bytes and
16,096,065 stored syntax nodes, including anonymous tokens. Python 3.12.9,
FlatBuffers 25.12.19, NumPy 2.4.4 and Tree-sitter 0.25.2 ran on macOS ARM64.
`verified.json` records the environment, source-manifest hash and engine hash.

## Results

The cache was built from an empty database. Final acquisition took **26.996 s**,
versus **33.214 s** in the first production implementation. This includes file
enumeration, hashing, parsing, projection, publication and snapshot acquisition;
the first query adds approximately 0.77 s. Phase measurements:

| Phase | First implementation | Final implementation |
|---|---:|---:|
| Read source | 0.353 s | 0.315 s |
| Tree-sitter parsing | 4.529 s | 4.521 s |
| Flatten to vectors | 16.143 s | 11.173 s |
| Persist source, AST and postings | 8.940 s | 8.783 s |
| Total acquisition, including other overhead | 33.214 s | 26.996 s |

Retained database size: **470,773,760 bytes (448.965 MiB)**. Peak RSS was 145.1 MiB
in the process doing the cold build and repeated searches; a fresh process doing
warm searches peaked at 137.1 MiB. These are process high-water marks, not a claim
that FlatBuffers uses less memory than every alternative.

Final warm medians, three repetitions each, with result caching disabled:

| Query | Matches | Execution only | Entire API call |
|---|---:|---:|---:|
| All `if` nodes | 31,968 | 0.785 s | 2.451 s |
| Returns containing a call | 8,566 | 0.841 s | 2.485 s |
| Functions containing both a branch and return | 7,125 | 2.096 s | 3.755 s |

Each API call checks source revisions again, costing roughly 1.6–1.7 s. Summing
these three separate calls costs about 8.69 s; the query-execution subtotal is
3.72 s. The three queries do not share one acquisition in this benchmark.
OS file caches were warm; caches were not forcibly flushed. A cold database is
not the same as cold filesystem storage.

These are **three syntax queries, not the 23 GoF patterns**. The earlier storage
experiment used different predicates and narrower function-scope rules; its
match counts and specialized detector timings are not comparable directly.
`contains` here includes nested callable syntax. The GoF catalogue and
`structural patterns` still use their existing backend.

## Correctness and optimizations

An independent Tree-sitter traversal verifies full `(path, start_byte, end_byte)`
sets, not just counts. All hashes agree between cold builds, repeated warm runs
and optimized execution. `baseline.json` and `cold-final.json` contain the oracle
results; `verified.json` matches those hashes after the final error-barrier and unknown-value fixes. The oracle runs outside the timed API calls.

Optimizations made during implementation:

- Subtree intervals, grouped root postings and parent links replace node-level
  SQL joins. A rare child can seed an ancestor search.
- Per-file in-memory postings plus binary searches replaced repeated array
  scans for every function. The function query fell from 5.141 s to 2.246 s.
- Quantifier domain constraints are compiled once, reducing it further to approximately 2.1 s.
- `.gitignore` matching strips an already-validated ancestor prefix rather than
  rebuilding `Path.relative_to` chains for every applicable rule. Combined with
  avoiding source-path resolution for non-source files, warm acquisition fell
  from approximately 2.4 s to 1.6 s.
- Binding append methods and avoiding per-node tuple/zip construction reduced
  flattening from 16.143 s to 11.173 s. `codec-comparison.json` checks every vector
  and dictionary entry for three large files, with three before/after timings.
- File publication is atomic; unchanged files bypass parsing. Growing files,
  deletion, path-limited acquisition and reader/writer snapshots have tests.

Coverage is explicitly incomplete for this corpus: two Rust files have parser
errors, and eleven C/header files lack a supported frontend. Known syntax
matches are still returned. The final function query reports three uncertain
candidates. Local negative conditions can close a valid enclosing subtree;
global negative conclusions over missing source remain unknown.

## Reproduction

From the Ken checkout:

```sh
PYTHONPATH=.:src .venv/bin/python -m examples.bench.exploration \
  ../codex /tmp/ken-exploration-reproduction --repeats 3 --oracle

PYTHONPATH=src .venv/bin/ken kql2 examples/kql2/exploration.kql \
  --query returns_with_calls --root ../codex --backend exploration \
  --cache-directory /tmp/ken-exploration-reproduction --profile
```

Use a new cache directory to measure construction. Reusing it measures source
validation and warm search. The script writes `benchmark.json` alongside the
cache. `--reference` is intended for small differential fixtures, not full-corpus
benchmarks: it deliberately disables candidate pruning.

Raw records: `baseline.json`, `optimized.json`, `warm-final.json`,
`cold-before-codec.json`, `cold-final.json`, `verified-before-error-barriers.json`,
`verified.json`, and
`codec-comparison.json`. Temporary databases retired during measurement are
recorded in `cleanup.json`; unrelated `/tmp` contents were not touched.

## Validation

The broad regression run passed **13,148 tests**, with 10 expected failures,
covering KQL2, common AST, structural analysis, path/ignore handling and affected
watcher/index-queue helpers. The final focused run passed **32 exploration tests**,
including the subsequent optimizer error-barrier and nested-unknown regressions.
These counts overlap; they are not additive. Ruff passes for the new backend,
benchmark, tests and modified ignore matcher. Scoped mypy checks pass for all
eight backend modules (with silent followed imports and missing external stubs
ignored). The only change after the last timing was a cache-field type annotation.
Both module and `ken kql2` CLI
entry points were exercised, including complete and budget-limited responses.
