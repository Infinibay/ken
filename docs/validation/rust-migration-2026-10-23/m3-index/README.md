# Native incremental index: cross-platform evidence

M3e implements complete incremental indexing alongside preserved originals. Final whole-plan review is pending; M3 and the overall migration remain open.

Both actual platforms (macOS arm64, Linux aarch64) pass43 affected Rust roots and43 tooling tests, format and clippy. Actual frozen-original observations cover195 vocabulary inputs,496 passages,26 storage histories,31 publication histories plus18 intent boundaries,93 two-view projection histories and12 complete incremental histories. The22 source tests and27 integration tests pass per platform; macOS reuses its previously captured27 test outcomes explicitly after fixing observer chunk controls. Earlier accepted models/parsers/imports/program suites are reused, not claimed as new executions.

Every full history compares14 SQL tables, canonical IDs, source hashes, owners, loaded passages, term frequencies, encoder requests/loads, progress, error effects and legacy vectors. Normalized F32 arithmetic retains the previously approved M2 abs1e-6+rel1e-6 bound. Raw inline encoder bytes remain exact. Physical legacy COW addresses are retained and audited for live/free ownership, readable values and bounded reuse; arbitrary old legacy readers across multiple subsequent commits require coordination in M4/M7. Immutable retrieval views have MVCC coverage.

Native input-only processes run outside checkout with empty PATH, native loader audits and Linux exec/connect tracing. Whole-process measurements include all12 histories and grammar caches: macOS1.772597584s /65,175,552bytes peakRSS; Linux2.589153667s /45,084,672bytes. The100-file workload stays below1s on both platforms. Debug timing is not a speedup claim. Fresh three-document integrations use the accepted native Potion model on both systems, without Python inference.

`INDEX.json` pins sources, validation tooling, binaries and the accepted M3d predecessor. Archives retain original scripts/owners/results, raw native process receipts, discovery/JUnit and Rust gates. Verifier unit samples are labeled synthetic and never counted as execution evidence. The1066 original files are guarded against the initial manifest.

Replay from the repository root:

```sh
.venv/bin/python docs/validation/rust-migration-2026-10-23/m3-index/VERIFY.py
# Add --current only while current source bytes match this receipt.
```

`LEDGER.md` retains all decisions, their costs, RED/GREEN records and reuse boundaries. No original source was removed or replaced.
