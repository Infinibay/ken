# Catalogue exploration

`ken structural patterns` defaults to `--backend exploration`. All 23 GoF roots
use one `CatalogIndex` and one set of batch execution resources. Existing queries
and their semantic evidence remain unchanged. `--backend indexed` retains the
previous physical access strategy for comparison.

```sh
PYTHONPATH=src .venv/bin/ken structural patterns --path ../codex \
  --backend exploration --cache-directory /tmp/ken-patterns-codex --profile
```

`--profile` bypasses the query-result cache and returns full operator diagnostics,
including selected access order, estimated cardinality, examined rows and time.
Without it, complete query results may be reused. `--scope sdk/typescript` selects
the smaller Codex SDK benchmark. Query budgets (`--timeout-ms`, `--max-states`,
`--max-rows`) still return incomplete outcomes when exhausted, never proof that a
pattern does not exist. They exclude source acquisition time.

## Physical execution

The existing KQL2 catalogue compiler creates relational and CFG instructions;
the Python executor plans and evaluates them. The new adapter changes repeated
fact access and operation traversal:

- Relations of up to 100,000 records become immutable FlatBuffers buckets.
  Endpoint filters use lazy numeric indexes; alternatives form a union before
  independent constraints intersect it. Original record order and duplicates
  are preserved. No SQL runs on a warm endpoint lookup in a resident bucket.
- Large relations can be partitioned by a fixed object or a selective union
  (such as class/interface kinds). These seeds are shared across query role
  names. Unbounded large scans and unions over the bucket ceiling continue
  through the semantic index's native indexes.
- Attribute-filtered seed buckets use the existing indexed selector once, then
  reuse their records. Bound attribute checks retain native access.
- Operations for an owner load as one vector and can be filtered by kind or
  identity without re-reading its SQL rows. Region and ordinal access retain
  the semantic index's bounded streaming path. `GraphSourceView` and the existing
  `BODY` verifier consume these operations and preserve their control-flow rules.
- Up to 32,768 detached facts from small endpoint results are retained across
  the catalogue. Large result views are not retained by this endpoint cache,
  because they would pin whole buffers and defeat vector eviction.

The adapter does **not** compile catalogue queries with the syntax-only
`exploration/compiler.py`. Types, call targets, attributes, source coverage,
cardinality estimates, and CFG semantics still depend on the native semantic
index. It does not remove the cost of building that index, nor implement new
cross-file import resolution. The standalone syntax backend and this catalogue
adapter have different capability contracts.

## Storage and lifecycle

`exploration/records.fbs` defines `KCR1` vectors: a row width, interned strings,
and 64-bit cells. Text cells store dictionary indices; attribute/evidence cells
retain numeric references into the pinned semantic graph. Operations preserve
identity, parent, owner, kind, native kind, role and source bounds. Generic record
vectors do not replace the compact raw AST's `KEX1` schema.

`pattern-buckets.sqlite` stores checksummed FlatBuffers payloads. The semantic
graph revision, publication identity and codec version are part of their keys;
source changes invalidate reuse. Buckets from incomplete acquisition are not
persisted. Publication occurs only after successful encoding and its final
budget check; interrupted work cannot publish a partial bucket. Damaged payload
checksums cause reconstruction from the semantic index.

The resident vector cache targets 64 MB of encoded buffers. Decoded dictionaries,
numeric indexes and active views add memory, so this is not a process RSS bound.
Persistent payload retention is at most `min(256, --cache-mb)` MB after close;
older buckets are evicted and SQLite compacted when necessary. Active work and
SQLite overhead may exceed this retention target. A single oversized bucket can
serve the active query but is not persisted. `--cache-mb 0` disables persistence.

`--cache-directory` relocates the semantic index, source cache, query results and
FlatBuffers buckets together. Without it, standard project cache locations are
used. No destructive migration is required: the semantic database remains the
authority and the new derived bucket database is built lazily.

## Verification and remaining work

`tests/kql2/test_catalog_exploration.py` compares full evidence for all 23 patterns
in Python, Java, TypeScript and Ruby, and covers literal alternatives, duplicate order, persistent
operation reuse, source invalidation, corruption, interrupted publication, cache
budgets, external cache paths, native fallback and CLI profiling.

Reproduce a complete SDK comparison with result caching disabled:

```sh
PYTHONPATH=.:src .venv/bin/python -m examples.bench.catalog_exploration \
  ../codex /tmp/ken-catalog-comparison --scope sdk/typescript --repeats 2
```

See [measurements and limits](../../structural-validation/catalog-exploration-2026-09-17/README.md).
The full Codex snapshot still exhausts five-second per-pattern budgets; SQL
cardinality planning, large candidate domains and semantic body verification
remain substantial costs. Porting storage access alone does not solve them.
