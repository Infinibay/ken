# Native query graph publication and indexed access

Continue frombc336c2c on x86_64, core outward, large implementation batches and
grouped validation. Commit/push authorized, installed Python stays active. Preserve
raw evidence/workspaces local; no accepted original replay or model/CPU/CI loops.

Concepts: QueryView normalizes full source IR into query occurrences and coverage.
GraphValue owns lossless typed JSON values and Python-compatible keys/identity;
GraphDictionary/ValueCodec own schema15 dictionary/native-column encoding.
GraphPublication owns READY/lease state and bounded transactional batches, cleanup
on failure and ownership-transfer buffers. GraphIndex owns immutable lazy indexed
fact/entity/operation access, attribute projection, syntax ranges and reader lease.
ProjectAcquisition connects a captured manifest, builder and published index.
Keep query compilation/execution policy separate from persistent data access.

Usage: normalize_query_graph(&source) -> query IR; publish_graph(store,snapshot,key,
query,options,check) ->graphID; GraphIndex::open(store,id) provides ordered lazy rows,
counts/endpoint/attribute candidates, entities/operations/syntax bounds. Storage
schema15 reused, source snapshots remain unchanged. APIs preserve full attributes,
evidence/order and conservative coverage; no loading the complete graph for a
single indexed lookup. Native query normalization has deterministic result order
where original iterates a set; compare all facts/attrs/provenance as multiset only
at that boundary. Frozen normalized input→columns→reader preserves exact order.

1. Capture new normalization/projection/index/value observations once using frozen
   full linker inputs; no upstream source/linker original replay.
2. Implement shared lossless value semantics and query view; preserve opaque attrs.
3. Implement column dictionaries, values/overlays, READY publication and readers,
   syntax intervals, leases/cancellation and original database compatibility.
4. Connect project acquisition; group parity and failure/large graph boundaries.
5. One final fresh read-only review/fix pass, docs and authorized commit/push.
KQL text compiler/operators and public transport closure remain separate work;
this block is their executable data foundation, not a complete migration claim.
