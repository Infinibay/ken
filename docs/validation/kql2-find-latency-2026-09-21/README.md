# KQL2 find latency on Ken, 2026-09-21

The public CLI is fast on a prepared small scope, but a whole-source search can
spend tens of seconds preparing its index. Increasing cache size alone does not
solve the cost of queries requiring derived semantic relationships.

These measurements precede the assistant-skills implementation in this task.
The captured source inventory contains **271 Python files under `src`**. The
full repository inventory contained 952 supported files; this report does not
claim whole-repository timing. Each run used a fresh CLI process and an isolated
copy of the source. Within a scope, repeated queries shared the fixture cache.

| Scope / query | Cache | First run | Repeated runs | Outcome |
| --- | ---: | ---: | ---: | --- |
| `src/ken/vectors.py`, named callable | 500 MB | 1.585 s | 0.725 / 0.714 s | Complete, one row |
| `src/ken/checks`, named callable | 500 MB | 2.126 s | 0.773 / 0.770 s | Complete, one row |
| `src`, named callable | 500 MB | 79.164 s | 54.265 s | Complete; acquisition remains ephemeral |
| `src`, named callable | 1,000 MB | >90 s | Not run | External wall-clock timeout; no result |
| `src`, named callable | 2,000 MB | 61.365 s | 0.771 / 0.778 s | Complete, retained index |
| `src`, call named `chmod` | 2,000 MB | 0.888 s on prepared index | 0.779 / 0.770 s | Complete, two rows |
| `src`, callers via `TARGET` / `HAS_CALL` | 2,000 MB | 26.188 s | 26.473 / 26.944 s | Incomplete: query timeout |
| `src`, mutable-default hazard | 2,000 MB | 26.196 s | 25.634 / 25.434 s | Incomplete: query timeout |
| `src`, result usages | 2,000 MB | 25.673 s | 26.063 / 26.503 s | Incomplete: query timeout |

All durations are wall-clock seconds, including process startup and acquisition.
These few local samples are diagnostic observations, not percentile estimates
or a controlled claim that 1 GB is slower than 500 MB. The 1 GB trial exhausted
the external 90-second watchdog; it provides no completed cache statistics.

## What explains the results

The 500 MB full-source run allocated about 969 MB while preparing the snapshot.
The cache could not retain that acquisition: the first run parsed all 271
files, and the repeat still parsed 169 while reusing 102. The named-callable
query itself took about 0.5 milliseconds. Index preparation dominated.

With a temporary 2 GB allowance, the index stayed available and repeated simple
queries fell below one second. This was an isolated benchmark override, **not
a project or product default**. Queries requiring the graph's derived semantic
relations still spent roughly 25–27 seconds and returned incomplete results.
Their zero rows do not demonstrate absence of callers, bugs, or usages.

Every query requested `timeout_ms=10000` and `limit=100`. Preparation and some
derived graph work are outside effective query-budget interruption points, so
that timeout is not a ten-second end-to-end guarantee for `find`.

The user-requested local setting is `.ken/structural.json` with
`{"cache":{"max_mb":1000}}`. The default for other projects remains 500 MB.
At this setting, compilation reserves up to 100 MB, leaving a 900 MB disk
allowance, smaller than the observed 969 MB allocation. The source index needs
less storage or better selective acquisition to reliably fit this project cap.

## Improvements suggested by the evidence

1. Acquire the requested declarations and relevant imports selectively for
   direct `find`, following the bounded exploration used by `impact` and `who`.
2. Reduce snapshot size and repeated materialization; retain useful fragments
   when a complete acquisition exceeds the disk allowance.
3. Build derived relations only for the requested relation and candidate set.
4. Make end-to-end preparation cancellable and include it in a shared deadline.
5. Expose acquisition time and cache pressure in concise diagnostics so a
   caller can choose a narrower source scope instead of repeating a costly query.

## Reproduction and evidence

```sh
.venv/bin/python docs/validation/kql2-find-latency-2026-09-21/measure.py --output /tmp/ken-find-default
.venv/bin/python docs/validation/kql2-find-latency-2026-09-21/measure.py --scope src --cache-mb 1000 --output /tmp/ken-find-1000
.venv/bin/python docs/validation/kql2-find-latency-2026-09-21/measure.py --scope src --cache-mb 2000 --output /tmp/ken-find-2000
```

Use a new output directory for each run. See `result.json`, `cache-1000/result.json`,
and `cache-2000/result.json` for completed observations and the raw CLI artifacts
beside them. `source-manifest.json`, `repository-scope.json`, and `environment.json`
record the inputs and environment. The default run was interrupted during a
third expensive ephemeral acquisition after two completed observations; the
metadata records that interruption explicitly.
