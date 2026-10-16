# Reclaimed experiment storage (2026-10-16, V223)

The authorized cleanup removed **56.688 GiB** of reconstructable experiment data:
43 directories of old SQLite indexes (**46.933 GiB**) and three unused downloadable
Qwen model caches (**9.755 GiB**). The filesystem reported about **68 GiB free**
afterward, versus about **11 GiB** before cleanup. This was chiefly in
`output/search-engine-2026-10-14/workspace`, rather than `/private/tmp`.

No tracked file was removed. Results, queries, references, source snapshots,
experiment scripts, the closed acceptance reserve, and the active V219/V224
benchmark artifacts and runtimes were preserved. The complete frozen V214 engine
(425 files) was verified after deletion against its source manifest:
`b9e86b7fe4e7a405f94c47a1f157b97765eed97f3581f356f927d738e0f79079`.

The compressed receipt records every removed path, allocated/logical size and
mtime, plus filesystem free space before/after. Old index directories contain
only `.db`, `.db-wal`, and `.db-shm` files; their associated configurations,
measurements, models and response records were retained. Historical indexes still
referenced by two waiting controllers were also retained. No current production
model cache was selected.

A historical receipt may therefore refer to an index that is now absent. Such
an index needs regeneration from its recorded source/configuration before a
rerun; its old measurements must not be described as a newly executed test.
The cleanup did not rerun or alter any accuracy evaluation.
