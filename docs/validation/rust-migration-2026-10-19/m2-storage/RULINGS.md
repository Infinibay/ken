# Storage execution rulings

These decisions and their costs are retained in ledger order. No Minor findings were reported.

Ruling: Continue written-spec/plan/implementation natively without new confirmations — the user explicitly required continuous whole migration; retain the same method and all review/testing artifacts — cost if wrong: design corrections require TDD/review; no external promotion or original removal is inferred.

Ruling: Use a focused ken-store crate and share the authoritative SQL resource — storage is a separate responsibility; ken-core keeps read-only status and does not depend on models/store — cost if wrong: future service integration maps domain model decisions to physical storage facts explicitly.

Ruling: Read mutable segment files through owned bounded blocks, not Rust references into file mappings — memmap2 Safety documents potential UB if underlying files change, and current writers intentionally update them concurrently — cost if wrong: extra copy/syscall cost must be measured and meets the unchanged overall resource requirements before promotion; on-disk/mmap compatibility remains unchanged. Primary source https://docs.rs/memmap2/0.9.11/memmap2/struct.MmapOptions.html#safety.

Ruling: Correct manifest/norm/SQL/crash integrity defects separately from valid-data parity — unchanged sources/tests can expose known false-zero or partial-publication defects; identical corruption is not safe acceptance — cost if wrong: affected corrupt states become explicit errors/recovery rather than permissive original behavior, and every correction needs its own regression and receipt.

Ruling: Use F32 little-endian hex for vector probe payloads — preserve exact bits and represent NaN/Inf fixtures without invalid JSON — cost if wrong: validation adapters must decode/compare numeric values independently; product VectorStore API remains typed F32.

Ruling: Split the original child workflow into storage_reference_child.py — parent owns corpus/integrity/process capture, child owns isolated real-source experiments — cost if wrong: one additional validation-only file must travel with the source fingerprint; no original/product module changes.

Ruling: Compare normalized/scored F32 bytes with exactly abs(error)<=1e-6+1e-6*abs(reference), retaining exact JSON types/IDs/slots/BLOBs/shape/order — the registered numeric contract permits rounding while source corruption remains separate — cost if wrong: differences inside that pre-native bound are accepted; NaN/Inf in valid histories still reject. Boundary first failed max-tolerance semantics then GREEN with the specified sum. Segment-file SHA and OS block measurements remain recorded separately, not used to override declared numeric tolerance.

Ruling: Reject a free-list slot still referenced by its real index table — a later SQL unique-index error cannot undo vector bytes already overwritten after allocation — cost if wrong: inconsistent old indexes now require explicit repair before writes; valid reuse remains unchanged. Newtest observedRED→GREEN and asserts counter/freelist/owner preservation.

Ruling: verification scans actual canonical files rather than every possible slot range — corrupted large counters must not stall diagnostics; same seven logical fields and canonical-file counting remain — cost if wrong: unrecognized noncanonical filenames are not treated as valid segments, matching original constructed paths. Fresh wholeworkspace final running; do not advance/commit until CLOSED0 plus originals/fmt.

Ruling: A journal records confined generated names and opened generation device/inode identities, with an operation owner receipt in the new tree — recovery must validate every named generation before any rename/removal; matching only path prefixes is insufficient — cost if wrong: moving/restoring pending generations to other inodes requires explicit repair rather than automatic cleanup.

Ruling: Preserve unmanaged vector-directory files during whole-directory compaction swap — otherwise replacing the directory would discard unrelated data that original per-file replacement retained — cost if wrong: copying extra files can increase maintenance space/time; special files fail explicitly rather than being consumed.

Ruling: Select matching inline BLOB length within each SQL batch — a foreign-dimension first row must not starve later compatible vectors indefinitely — cost if wrong: this corrects the original LIMIT-before-filter gap and is recorded as integrity progress rather than identical defect behavior.

Ruling: Storage marker fixtures pass the model explicitly as caller data and test physicalfreshness/publication; pure model-policy decisions remain in the previously accepted owner — avoids importing inference models or duplicating precedence into ken-store — cost if wrong: future application integration must still bind policy decisions to these storage facts, rather than treating this probe as that integration.

Ruling: The original callback-interruption case is reproduced by a caught unwind in the isolated validation probe, temporarily suppressing/restoring that process's hook; product storage has no failureflag/hook — independently checks wholetransaction rollback while separate externalSIGKILLdriver proves publication recovery — cost if wrong: this callback case proves unwind integrity only; process crash evidence remains required separately.

Ruling: Authenticate the outer storage manifest once and verify the nested policy manifest through owned byte buffers — rereading mutable files afterhashing can authenticate onepayload thenparseanother — cost if wrong: allrequiredlogs/outputs/XML/traces musttravelwithrelativepaths; summary-only/historicalreceipts reject.

Ruling: Mark syntheticfixtures explicitly and reject them at aggregate runtime acceptance, while testing individual contracts with them — mutationtests needcontrolledvalidshapes without beingpresented as execution — cost if wrong: a manuallyconstructedreceipt requires real capture rather than a flagoverride; no productionallow_synthetic bypassexists.

Ruling: One composite preparation action owns the native test prerequisites for bothCIworkflows — independentlyduplicatedsetup alreadyleftM1withoutrequiredtranslation/policy/storageinputs — cost if wrong: changingthe sharedpreparation affects bothjobs, eachstillretainsitsownacceptancegates. PrimaryGitHubcomposite/UVdocs andinstalledCLIflagschecked.

Ruling: Preserve Cargo native test logs byte-for-byte including their terminal blank lines — both execution manifests bind those exact bytes, so trimming for whitespace lint would alter execution evidence — cost if wrong: two explicit raw-log EOF notices remain; all other staged files, including authored prose, still undergo whitespace checks. No product lint/test threshold is weakened.

Ruling: Full application integration, remaining model backends and M3–M8 remain required subsequent migration work — storage acceptance must not imply these are done — cost if wrong: application equivalence is not established until later acceptance.

Ruling: Concurrent ranking readers may observe different write generations and power-loss durability remains unproved, as the storage specification states — this cut guarantees process-crash writer recovery, not snapshot readers or power-loss recovery — cost if wrong: workloads needing these guarantees require an additional protocol before deployment.

Ruling: External replacement of recorded generation inodes fails closed requiring explicit repair — guessing ownership could delete unrelated data — cost if wrong: legitimate manual moves may block automatic opening until repaired.

Ruling: Another filesystem-authorized process rewriting journal/data files is outside the trust boundary — accidental malformed paths and identity mismatches still fail closed — cost if wrong: project permissions must restrict parties who should not alter its contents.

Ruling: Continued use of an AssertUnwindSafe handle after catching a progress-callback panic has no unwind-safety guarantee — callers must reopen/recover the project before further use — cost if wrong: callers ignoring this lifecycle may use a stale generation handle.

Ruling: Remote GitHub workflow execution is not certified by source review or local acceptance — only actual macOS/Linux local executions are claimed — cost if wrong: remote runner differences remain until CI executes.

Ruling: Query committed ownership through an independent read-only SQLite connection while the IMMEDIATE writer lock is held — current SQL state cannot identify rows restorable by rollback; deferred slots stay in the free-list until a later transaction, while previously unowned slots retain deterministic reuse — cost if wrong: each allocation opens a reader and checks candidates, increasing allocation overhead; no persistent schema or vector format changes.

Ruling: Validate both current and committed owner high-water bounds before returning any range or changing allocator state — a missing/lowered counter must fail before physical bytes can be overwritten — cost if wrong: damaged indexes require explicit repair rather than silent allocation.

Ruling: Atomically persist discarding_new in the existing external journal only after validating all generation identities/receipts — recursive deletion may remove its internal receipt first; retries use the recorded inode and refuse committed/displaced generations — cost if wrong: old binaries cannot resume this additional journal phase; mixed binaries must not run concurrent maintenance.

Ruling: sparse-accounting test must observe physical allocation rather than assume the filesystem keeps written files sparse — the declared contract reports blocks separately from apparent size, not a physical-allocation guarantee — cost if wrong: filesystem allocation policy changes remain measurable instead of being confused with a metric bug. No skip/tolerance/threshold lowered; initial failing full log retained; focused5tests GREEN. Fresh fullRust required before commit.

Ruling: exclude the failed fullattempt and require a new complete31gate execution rather than accepting onlya rerunoffailedtest — validacceptance must cover the wholecurrentcandidate — cost if wrong: a latent intermittent CLI/environment stall can recur and mustremainreported. FreshLinuxfull31 restarted sameSourceT6/sameinputs; outputacceptance-t6/linux wasabsent; newlog task-6-linux-31gate-retry.log. Mac52939 continueshealthyfullPython~73%.

Ruling: Permit owner read/write/search only on already-discarded, inode-validated directory generations when ordinary removal is denied — preserving0500 in the live copy must not make committed recovery permanently unavailable; symlinks are never traversed — cost if wrong: an external process retaining a path into a discarded generation may observe changed permissions while it is being removed; published/live data and external targets retain their permissions. Promote the already-pinned libc from test-only to native ken-store dependency for directory/no-follow open flags; Cargo.lock unchanged.
