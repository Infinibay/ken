# AST storage experiment: FlatBuffers with grouped candidate postings

**Decision:** use FlatBuffers numeric vectors for the proposed persistent syntax
cache, with one SQLite posting-list row per `(kind, file)` rather than per node.
Read vectors once per candidate file through NumPy views. Rebuild changed file
blobs and switch their postings atomically. Keep semantic linking separate.
This decision selects the storage design; the production KQL2 engine has not
been switched to this experiment.

The question is whether KQL2 should store a compact syntax tree per source file,
find candidate roots through an index, and run scoped detectors directly on
those trees. The storage comparison isolates FlatBuffers from that architectural
change: every backend receives exactly the same syntax records and source bytes.

## Plan and acceptance criteria

1. Parse the tracked, supported files of `../codex` with Ken's existing grammar
   versions. Keep only one source tree at a time. Record parsing separately from
   projection and persistence.
2. Preserve every named and anonymous syntax node, parent, field role, exclusive
   preorder subtree bound, source byte range, and named/error/missing flags.
   Keep source bytes once per file and intern grammar names/roles in a dictionary.
3. Compare equivalent numeric SQLite columns, FlatBuffers scalar vectors, and
   a minimal versioned packed column buffer. Use SQLite candidate indexes for
   all three. Include index construction, commits, source and dictionary storage
   in size/build measurements. Rotate per-file write order.
4. Query each cache in fresh processes, repeating in alternating backend order.
   Compare exact source locations against an independent Tree-sitter traversal.
   Measure both FlatBuffers vector views and scalar accessor overhead.
5. Grow a real file, atomically replace its syntax and postings, and verify new
   results plus unchanged hashes of other files. Test rollback and stale-posting
   removal. Retain the original corpus after the experiment.
6. Select a format on both cache construction and search cost, not reading alone.
   Prefer a maintained, versionable format if its measured overhead relative to
   the minimal custom layout is small. A large Python accessor penalty requires
   changing the access strategy, not declaring all FlatBuffers implementations
   slow. Do not migrate production based only on a syntax microbenchmark.

## Scope

The predicates are `if` with identifier `==`/`!=` literal, return containing a
call syntactically, and callable containing a branch and explicit return outside
nested callables. They test small and larger subtrees, alternative operators,
field roles and scope boundaries. They do not evaluate reachability, variable
binding, cross-file linking, or the 23 complete GoF patterns. Error-containing
candidate subtrees are excluded and parse-error files are recorded; this is a
benchmark rule, not a production coverage/unknown policy.

The baseline is a minimal SQLite schema with identical syntax information, not
the current full semantic graph. Its subtree reader materializes selected node
rows; blob readers load the candidate file and use views over its numeric
vectors. No backend caches query results. Fresh process/cache does not mean a
flushed operating-system page cache. Blobs are stored in SQLite and read per
file; no memory-mapping claim is made.

## Reproduce

From the Ken checkout, with NumPy and FlatBuffers installed in the Python runtime:

```sh
PYTHONPATH=.:src .venv/bin/python -m examples.bench.ast_storage.experiment build ../codex /tmp/ken-ast-storage-full
PYTHONPATH=.:src .venv/bin/python -m examples.bench.ast_storage.experiment query /tmp/ken-ast-storage-full sqlite --label 1
PYTHONPATH=.:src .venv/bin/python -m examples.bench.ast_storage.experiment query /tmp/ken-ast-storage-full flatbuffers --label 1
PYTHONPATH=.:src .venv/bin/python -m examples.bench.ast_storage.experiment query /tmp/ken-ast-storage-full packed --label 1
PYTHONPATH=.:src .venv/bin/python -m examples.bench.ast_storage.experiment query /tmp/ken-ast-storage-full flatbuffers_scalar --label 1
PYTHONPATH=.:src .venv/bin/python -m examples.bench.ast_storage.experiment update /tmp/ken-ast-storage-full --label 1
PYTHONPATH=.:src .venv/bin/python -m examples.bench.ast_storage.experiment measure /tmp/ken-ast-storage-full --repeats 3
PYTHONPATH=.:src .venv/bin/python -m examples.bench.ast_storage.experiment repack /tmp/ken-ast-storage-full
PYTHONPATH=.:src .venv/bin/python -m examples.bench.ast_storage.experiment measure /tmp/ken-ast-storage-full --grouped --repeats 3
PYTHONPATH=.:src .venv/bin/python -m examples.bench.ast_storage.experiment build ../codex /tmp/ken-ast-storage-cold --backend flatbuffers_grouped
PYTHONPATH=.:src .venv/bin/python -m pytest -o addopts='' -q tests/common_ast/test_ast_storage_experiment.py
```

`build` requires a fresh output directory. The experiment writes only that
directory, never `../codex`. FlatBuffers and NumPy were already installed; no
production dependency was added. The `.fbs` schema is checked in alongside an
adapter using official Python Builder/Table APIs. A production integration
should generate/version its API with `flatc` and validate buffers before use.

## Integration proposal to evaluate after the measurements

- Publish immutable syntax blobs per content hash plus frontend/schema version,
  with candidate postings switched in the same SQLite transaction.
- Represent hot fields as numeric vectors and read them once per candidate file.
  Keep original source bytes for captures; avoid repeating token strings.
- Seed scoped detectors at selective indexed nodes and navigate parents when
  the seed is not the syntactic root. Track independent candidates and nested
  callable boundaries; finalize negative predicates only at scope closure.
- Preserve KQL2's bindings, evidence, uncertainty and budget contracts. Keep
  semantic facts/linking as a separate layer for queries requiring them.
- First integrate an opt-in syntax execution path and compare complete results
  against the existing backend. Promote only after real catalog workloads,
  incremental invalidation, cancellation and schema upgrades pass.

Official references: [Python vector views](https://flatbuffers.dev/languages/python/),
[schema evolution and representation](https://flatbuffers.dev/schema/).

## Measurements and decision

The corpus is all 5,295 tracked files supported by the structural frontend in
`../codex`: 4,340 Rust, 750 TypeScript, 198 Python, 6 JavaScript and 1 C++.
It contains 66,872,846 source bytes, 16,096,065 total syntax nodes and 8,719,607
named nodes. The two existing Rust parse-error files appear in `build.json`.
Python 3.12.9, FlatBuffers 25.12.19, NumPy 2.4.4 and SQLite 3.47.1 were used on
macOS arm64. See `manifest.json` for exact source hashes.

| Representation and index | Persist AST + source + index | Three-query median | Full DB MiB |
|---|---:|---:|---:|
| SQLite numeric node rows | 45.301 s | 21.757 s | 653.10 |
| FlatBuffers, one posting row per node | 26.680 s | 2.102 s | 640.65 |
| Custom packed columns, one posting row per node | 26.146 s | 1.954 s | 640.16 |
| FlatBuffers, grouped postings | 3.947 s | 2.024 s | 447.66 |
| Custom packed columns, grouped postings | 3.765 s | 1.876 s | 447.17 |

Persistence excludes parsing and syntax projection for every row of this table.
The first three layouts were written from shared live syntax arrays; the final
two were repacked from the identical cached syntax, with input reading/decoding
excluded. Their separate build run and raw measurements are retained. The SQL
baseline runs the same procedural detector over selected subtree rows; it does
not represent the best possible SQL rewrite of each individual predicate.

Grouped posting lists contain all the same named-node IDs in typed uint32
vectors. They reduced posting rows from 8,719,607 to 262,680. In the original
FlatBuffers database, postings occupied 151,666,688 bytes and their unit index
another 109,846,528 bytes. This is why merely changing the AST payload format
did little for total size. Grouping cut total database size from 671,768,576 to
469,401,600 bytes and made index construction substantially cheaper.

An independent fresh-cache build of the selected layout from source confirmed:

| Phase | Seconds |
|---|---:|
| Read source files | 0.496 |
| Tree-sitter parsing | 4.875 |
| Numeric syntax projection | 16.089 |
| Persist AST, source, dictionary and grouped indexes | 4.511 |
| Sum of cache construction phases | **25.970** |

The harness also spent 12.616 s computing its independent correctness oracle;
that validation work is excluded from the construction sum. There is no reuse
of a prior AST in this independent run. OS filesystem caches were not cleared.
The source manifest, oracle hashes, node counts and database size exactly match
the first build. See `cold-build.json` and `cold-query-cold-flatbuffers_grouped.json`.

### Correctness, updates and memory

All backends and all repetitions returned identical source-location multisets:
1,310 identifier/literal comparisons, 8,508 returns syntactically containing a
call, and 6,853 callables containing a branch and explicit return outside nested
callables. These are syntax matches, not GoF findings.

Updating the largest Python file (391,129 source bytes) with a new function and
branch took a median **0.126 s** with grouped FlatBuffers, including parsing and
projection. Publication alone took **0.0108 s**, versus **0.363 s** with per-node
FlatBuffers postings and **0.417 s** with SQL node rows. Three update runs verify
the new candidates against Tree-sitter and unchanged hashes of other units, then
restore the original file in the cache. No source repository file was edited.

Peak query-process RSS was 79.5–83.9 MiB for grouped FlatBuffers, 79.5–84.9 MiB
for grouped packed columns, and 74.8–75.8 MiB for SQLite rows. **FlatBuffers did
not win on query RSS in this experiment.** The independent single-backend build
peaked at 139.7 MiB, including the oracle and Python/NumPy runtime. The original
three-backend build's peak is not an individual-backend memory comparison.

Using scalar FlatBuffers accessors instead of array views took **20.217 s** for
the same three-query batch, compared with 2.102 s for array views with the same
index. Avoiding per-field Python access overhead is part of the selected design.

The full common-AST test directory passed: **131 tests**, including **18 focused
experiment tests**. They exercise wrappers, comments, Unicode byte offsets,
chained comparisons, operator distinctions, error nodes, nested callables,
round trips, file growth, stale posting removal and rollback. Production files
and dependency declarations were not changed by this experiment.

### Why FlatBuffers instead of the custom packed format

Grouped packed columns are about 0.148 s faster per three-query batch (7.9%) and
0.484 MiB smaller (0.11% of the database). That modest advantage does not justify
owning a new general binary format and its evolution tooling. FlatBuffers keeps
the hot vectors contiguous while providing an explicit schema and established
cross-language tooling. This is an engineering tradeoff supported by the
measurements, not a claim that FlatBuffers was the fastest format tested.

The main improvements are **grouping candidate postings** and **walking compact
arrays directly**. The format itself is secondary. Parsing was only 4.875 s;
projection is now the largest measured cache-building phase and should be the
next optimization target. Direct Tree-sitter queries may still be preferable for
a one-off query or changed files already parsed in memory.

### Concrete integration sequence

1. Add a versioned syntax-blob backend behind the existing store boundary, using
   generated FlatBuffers bindings, input validation, content hashes and frontend
   versions. Persist grouped postings transactionally. Keep the existing backend
   available for result comparisons and unsupported operations.
2. Compile a supported subset of KQL2 BODY patterns into scoped detectors over
   numeric arrays. Preserve captures and exact byte ranges. Cache plans and
   dictionary bindings; share candidate-file reads. Expose candidate counts,
   nodes visited and phase timings for debugging.
3. Add selective seed planning, semantic lookups on demand, and incremental
   invalidation of affected cross-file dependencies. Replacing syntax for one
   file is insufficient to invalidate semantic results elsewhere.
4. Run the complete catalog with both engines on the same corpus and verify
   bindings, evidence, unknowns, cancellation and budgets. Benchmark cold cache,
   unchanged cache and file updates through the public CLI. Only then migrate
   the default backend and retire redundant storage.

No claim is made that the existing 23-pattern command now completes in two
seconds. That command still uses its existing engine. The experiment and this
decision provide the plan and evidence for the next implementation stage.

### Dependency resolution: current implementation and proposed boundary

`structural.service.source_manifest` sorts paths. `build_project` lowers or loads
each unit sequentially, then calls `semantic.link_project` over all collected
units. There is no dependency-first parse order. An unchanged persistent query
index bypasses this rebuild through `structural.index_service`.

The linker resolves selected explicit imports and lexical names: Python
`from ... import`, some Rust `use` paths, Java imports, and named relative
JavaScript/TypeScript imports with known exports. It does not implement a full
package/build-system resolver; non-relative JS/TS aliases require another
resolver, and Python resolution uses known source paths rather than installed
distributions. The inspected frontend/linker does not resolve C/C++ `#include`
or expand the preprocessor. Such gaps must not be interpreted as proven absence.

The FlatBuffers experiment performs no semantic linking. A local syntax query
such as identifier-equality-literal needs no imports. A query identifying a real
callee across an import alias or an inherited type may need local bindings and
cross-file resolution. The planned query compiler should declare these needs
explicitly and acquire the corresponding semantic data, rather than requiring
full project linking for every syntax search. All source syntax can be parsed
independently before resolving names against collected declarations.
