# Storage final review corrections

`1a9116641cbd6445c5048668d6ed76e6004f25f7` fixes the one Critical and three
Important findings in [FINAL-REVIEW.md](FINAL-REVIEW.md).
`20db131d1ac56f43fb9d779678d9a5daaa29bbab` fixes the additional readonly-directory
availability gap reproduced during the same correction pass. The final T7 matrix
passes all 31 gates on both platforms with current source fingerprints.

- Rollback and process death: committed owners remain visible to allocation
  through an independent SQLite reader under the IMMEDIATE writer lock.
  Freed slots belonging to those owners wait until a later transaction.
- Missing/lowered counters: allocation checks current and committed owners
  before returning slots or modifying allocator state.
- Interrupted cleanup: the external journal atomically records `discarding_new`
  before recursive deletion. Reopening still checks recorded inodes and refuses
  to discard committed generations or unrelated replacement directories.
- Private directories: compaction restores every copied directory's permissions
  after copying its contents, including nested 0700/0710 paths.
- Readonly directories: a further public-usage regression reproduced successful
  commit followed by permanent reopening failure during backup cleanup. The
  cleanup retries permission-denied removal only for an inode-validated discarded
  tree, enables owner access on directory descriptors opened without following
  symlinks, and retains live 0500 permissions and external symlink targets.
  The four real publication SIGKILL histories also exercise readonly contents.

Each finding was reproduced by a failing public-usage test before its fix.
Both final executions passed 179 Rust test executions across 41 sections with no
failures/ignored tests, 90 actual process tests and the unchanged full Python
baseline. Strict Clippy, formatting and release compilation passed. The new
readonly regression checks preserved live permissions/content and an external
symlink target. Four real publication SIGKILL histories include readonly data;
the additional cleanup SIGKILL test checks partial deletion, displaced inodes
and repeated recovery. All 1066 original files remain byte-identical.

The earlier sparse-accounting test assumed fsync kept a written APFS file sparse.
Independent ftruncate/write/fsync experiments disproved that filesystem
assumption. Exact `st_blocks*512` accounting remains asserted for the written
segment. A genuinely sparse never-written segment also distinguishes allocated
from apparent length and checks exact zero readback. No test is skipped,
tolerance widened or product allocation behavior changed. The initial failed
run and experiment are retained in the execution archive.

No Minor findings were reported. There is one final review and one TDD fix pass,
with no second reviewer. [RULINGS.md](RULINGS.md) retains decisions and their
costs. Remaining model backends/integration and M3–M8 must still complete before
the application migration can be accepted.
