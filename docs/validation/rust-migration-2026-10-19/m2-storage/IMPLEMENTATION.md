# Native project storage

Implementation: `ea0e73d6fd4066f1617be72d3f91daaa6fda3484` and its storage
predecessors. This cut implements the approved
[storage specification](../../../superpowers/specs/2026-10-19-rust-storage-design.md)
and [five-task plan](../../../superpowers/plans/2026-10-19-rust-m2-storage.md).
The current both-platform acceptance is recorded in [MATRIX.md](MATRIX.md).
The final whole-plan review is pending at this proof cut.

`ken-store` owns physical persistence. `ProjectDatabase` owns SQLite setup and
schema initialization; `WriteTransaction` is the real `BEGIN IMMEDIATE`
capability shared by slot and metadata operations. `StoredModelState` reports
physical facts; model selection remains in the accepted model-policy owner.
`ProjectStore` coordinates recovery before exposing the database and vectors.
The existing SQL resource remains authoritative, and `ken-core` does not depend
on storage or inference.

The store preserves WAL, synchronous NORMAL, foreign keys, the 5000 ms busy
timeout, existing table/space names and the segmented vector format: version 1,
little-endian float32, 65536 rows per default segment. Metadata distinguishes an
absent/NULL value from a present empty string. Allocation checks ownership in
the same immediate transaction and rejects a corrupt free list before bytes
can be overwritten. Pin writes are atomic and recheck the physical state.

Segment publication creates complete files exclusively and never resizes an
existing mapped file. Reads own their buffers and use bounded positional I/O;
they do not expose Rust references to concurrently mutable mappings. Batch
validation precedes writes. Dirty tracking marks both before and after I/O so
a concurrent flush cannot consume the only mark before new bytes arrive.
Verification enumerates existing canonical sparse segments rather than walking
every possible segment up to an untrusted high-water mark.

Inline migration commits complete batches, preserves foreign dimensions and
can resume. Compaction prepares all three spaces in one writer transaction,
publishes an owned journal and complete directory generations, and records its
database commit marker transactionally. Recovery validates all generations
before choosing the complete old or new mapping; cleanup is idempotent.
Unmanaged files and directory permissions are preserved. Vacuum/checkpoint
errors do not undo an already committed data migration.

The frozen original corpus contains 32 histories: 23 valid-data compatibility
cases and nine separately declared integrity corrections. IDs, slot ownership,
SQL effects, ordering, types and exact byte fields remain exact. Registered
floating-point comparisons use `abs(error) <= 1e-6 + 1e-6 * abs(reference)`;
physical segment hashes and allocated bytes are recorded separately.
Original observations were captured before the native store was implemented.

Five externally interrupted histories prove actual process recovery:

- `compact-journal_published`
- `compact-backup_renamed`
- `compact-new_published`
- `compact-database_committed`
- `inline-first-batch`, including a separate resume process

Frozen Python seeds and reads the native generations in all three spaces.
Every history checks rows, slots, vectors, inline bytes, high-water/free state
and internal markers before, after, finally and after repeated recovery.
The validation driver uses ordinary progress callbacks; product storage has no
failure flags or test hooks.

The composed validator retains all 28 policy gates and adds fresh storage
release binding, standalone storage parity and recovery. All 29 current input
fingerprints are required. Synthetic receipts cannot certify acceptance.
The complete nested execution tree is authenticated into owned bytes before
parsing and semantic comparison, including re-sealed incorrect outputs.
Shared CI preparation supplies all seven probes and the native prerequisites;
remote GitHub CI has not been executed for this cut.

The installed Python entrypoints, all 1066 original files, user work and
persistent project data are preserved. This is storage acceptance within M2;
remaining model backends/integrations and M3–M8 remain pending. These tests
establish process-crash recovery, not power-loss durability or serializable
ranking readers. The measured native I/O cost is not a speedup or SLA claim.
