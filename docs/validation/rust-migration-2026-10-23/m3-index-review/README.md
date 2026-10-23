# Reviewed native source indexing (M3)

M3 source discovery, all19language parsers, imports, common program model and complete incremental source/retrieval indexing are accepted within their documented boundaries. This final M3e receipt closes the one review with all3 Important findings corrected. The entire migration remains open for M4–M8; the installed application still uses preserved Python originals.

Both macOSarm64 and Linuxaarch64 pass47 affected Rust roots and43 tooling tests, fmt and clippy. Four regression roots reproduce all3 findings RED→GREEN: stale mapped slots after inline/unencoded edits, invalid or wrong-dimension preparation (including complete caches and a later file in a chunk), and concurrent bulk profile changes. Inline slot retirement/release rolls back atomically; invalid preparation publishes no earlier files; concurrent metadata is preserved.

Each freshly rebuilt native input-only process still matches all12 original incremental histories over14 SQL tables and full effects. The source corpus also retains195 vocabulary inputs,496 passages,26storage,31publication and93projection histories. The22source/27integration original test outcomes are reused; macOS's27tests have explicitly hashed prior-suite provenance. Previous accepted M2/M3 captures and real three-document Potion integrations are retained under their original identities; they are not claimed as new runs.

Normalized F32 uses the pre-existing M2 abs1e-6+rel1e-6 arithmetic contract; inline/document bytes, metadata, IDs, order and effects remain exact. Physical COW slots are retained and audited. Whole-process timing/RSS includes all12histories and grammar caches: macOS1.941925125s/66,191,360bytes; Linux2.655623501s/44,994,560bytes. Both100-file workloads stay below1s. No language-only speedup claim.

Legacy readers kept across multiple later commits remain an explicit M4/M7 coordination requirement: rollback-safe allocation alone does not pin a retained physical slot. Later public legacy consumers must own/materialize their data under writer exclusion or coordinate reader lifetimes. Immutable SQL retrieval views already have MVCC. This receipt does not certify global cutover.

`REVIEW.md`, `RULINGS.md`, `MINORS.md` and `LEDGER.md` retain the one fresh review, every decision/cost and the single verified fix pass. The initial pre-review receipt remains intact. Sources/tooling, binary/request/output provenance, raw original captures, test inventories and execution logs are archived and hashed. All1066original files remain unchanged.

Replay from the repository root:

```sh
.venv/bin/python docs/validation/rust-migration-2026-10-23/m3-index-review/VERIFY.py
```

Add `--current` only while the current Rust sources equal this archived boundary. Continue automatically with the documented M4 retrieval kernels; no additional confirmation is required.
