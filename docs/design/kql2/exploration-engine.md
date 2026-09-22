# Compiled syntax exploration

The `exploration` backend compiles typed KQL2 queries into executable predicates
and scoped exploration instructions over persisted Tree-sitter syntax. It does
not lower source into the semantic IR, build the relational graph, resolve
source imports, or translate predicates into SQL. SQLite stores file revisions,
FlatBuffers blobs and candidate posting lists; evaluating relationships and
filters uses numeric arrays in memory.

Run from the Ken checkout:

```sh
PYTHONPATH=src .venv/bin/python -m ken.kql2 examples/kql2/exploration.kql \
  --query returns_with_calls --root ../codex --backend exploration \
  --cache-directory /tmp/ken-exploration-user --profile
```

The same options work with `ken kql2`. Without `--cache-directory`, the cache is
`<root>/.ken/structural/v2/syntax.sqlite`. The default backend remains `indexed`
for compatibility. `ken structural patterns` now defaults to a separate
[hybrid catalogue adapter](catalog-exploration.md): it shares FlatBuffers record
buckets while preserving semantic graph and CFG verification. That adapter is
not the syntax-only compiler described on this page.

## Execution and extension points

1. The existing language parser and type checker produce a `Program`.
2. `exploration/compiler.py` validates backend capabilities and produces immutable
   `Explore` and `Calculate` instructions. Expressions compile to Python closures;
   source code and query text are never passed to `eval`.
3. `exploration/execution.py` orders independent conjunctive scans using posting
   cardinalities and already-bound relationships. It may start with a rare child
   and walk its ancestors. Calculation barriers preserve expression order.
4. Root scans read grouped posting lists. Descendant scans intersect a cached
   in-memory posting list with `[node + 1, subtree_end)` using binary search.
   Direct children additionally check their numeric parent. These steps issue no
   SQL predicates or per-node database lookups.
5. A stack of binding frames keeps alternatives and candidate scopes independent.
   Leaving a frame discards its state. `exists` short-circuits at a witness;
   negative conditions wait until their bounded domain has been exhausted.

Add syntax properties and native-kind classification in `exploration/tree.py`;
add expression operations in `exploration/expressions.py`; add instruction
lowering in `exploration/compiler.py`. Execution, acquisition and storage are
separate modules. Public language additions also need their parser/type-checker
contracts, as with the indexed backend. Extensions should have an independent
Tree-sitter fixture oracle and compare optimized/reference execution; root
posting hints must be supersets of valid candidates. In particular, constraints
inside `or` or negation must never be pushed down as unconditional filters.

## Supported language subset

- `node`, `expression`, `statement`, nested direct-child selectors, literal and
  regex property filters, projections, calculations, ordering, limit and unions.
- `contains`, `contains_direct`, `stable_id`, `in_directory`; compiler-generated
  `owns` and `kind_is` for syntax selectors in existential blocks.
- `exists`, `forall`, `count` over CodeNode/Expression/Statement, including
  correlated conditions and `not exists` blocks.
- Properties: `kind`, `category`, `native_kind`, `role`, `name`, `text`, `operator`,
  `path`, `language`, byte bounds, `line`, `normalized`, literal `type_kind`.

The reported capability is **`syntax-exploration/1`**. This is the concrete
Tree-sitter tree with a grammar-kind vocabulary, not full common-AST/semantic-IR
equivalence. It includes named nodes in searches and retains anonymous tokens for
operator inspection. Parenthesized expressions remain explicit; Rust implicit
returns are not synthesized. `contains` includes all syntactic descendants,
including nested functions. To exclude a nested function, express that exclusion
in the query; containment alone does not imply common execution context.

For example, a return belongs to `$function` without crossing a nested callable
when the query also requires:

```kql
where not exists(CodeNode $nested |
  $nested.kind == "callable" and contains($function, $nested)
  and contains($nested, $return)
);
```

Semantic selectors (`callable`, `class`, etc.), symbol/type relations, recursive
predicates, enum domains, optional evidence, CFG `BODY` clauses and relational
graph queries currently produce an explicit capability error **before source
acquisition**. Imports/resolution remain deferred. CFG and relational operators
are separate pending work, not something that enabling imports will solve.
There is no silent fallback and unsupported queries do not become empty results.

## Storage and revisions

`exploration/ast.fbs` defines seven vectors per file: `uint16` kind/field-role IDs,
`int32` parent, `uint32` subtree-end/start-byte/end-byte, and `uint8` flags. Kinds
and field roles reference an interned dictionary. Each file retains its source
bytes once; token spellings are slices, not duplicated strings or JSON metadata.
The adapter uses the official FlatBuffers Builder/Table APIs and NumPy views;
scalar accessor calls are deliberately absent from the matching loop.

Files are visited in deterministic path order, independently of source imports.
Each tree is flattened iteratively in preorder. Source hashes and parser/codec
fingerprints invalidate changed entries. A growing file replaces only its own
blob and posting lists; this is editable at file granularity, not an in-place
resize of an individual FlatBuffers vector. Old indexed-backend databases are
untouched; this backend builds its separate schema on first use.

Publication of source, AST, dictionary additions and postings is transactional.
A query reads a pinned SQLite snapshot after acquisition, so concurrent updates
cannot mix a new blob with old node IDs. Checksums and vector/range validation
reject damaged AST blobs before navigation. A small LRU retains two loaded file
views; active binding frames may retain additional files when a query joins them.
Node results and aggregate identities detach from their owning buffers.

WAL with `synchronous=NORMAL` suits this derived cache: a power loss may lose
recent cached revisions, which are rebuilt from the source. A failed publication
does not publish partial postings. Deleted/ignored files are removed within the
acquired path scope; a partial search leaves unrelated cached files available.

`--cache-mb` controls retained capacity. Below 0.512 MB storage is ephemeral.
An active query may need more than the retention budget; after it finishes, old
entries are evicted and the file compacted if necessary. Concurrent readers can
delay WAL reclamation. This option is not a bound on query memory or peak working
disk space. A budget smaller than the project causes reparsing on future runs.

## Debugging and verification

The response reports physical scan order, seed constraints, parsed/reused files,
source coverage, phase times, visited states, scanned nodes and optional
`--profile` per-role counts. `--reference` disables candidate pruning and scan
reordering for differential testing. There is no query-result cache masking
execution time.

`--timeout-ms`, `--max-states` and `--max-rows` bound query execution after cache
acquisition. Budget exhaustion returns `complete: false` and a reason. Regex
execution is bounded. `coverage_complete` is separate: unsupported files and parse
errors remain visible even when execution finishes. A valid local subtree can
prove absence despite errors elsewhere; unbounded negative queries over missing
source cannot. Unknown values are never evidence of absence.

See [the measured implementation results](../../structural-validation/exploration-2026-09-17/README.md)
and [the storage comparison](../../structural-validation/ast-storage-2026-09-17/README.md).
