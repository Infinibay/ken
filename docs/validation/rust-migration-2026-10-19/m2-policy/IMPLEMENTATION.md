# Native model policy: verified matrix, final review pending

Policy implementation:82d2e97. Original-oracle cut:8a091c79; both originals were
captured before native code. Spec/plan:9e98e95f. Native inline; originals preserved.

`ken-models::model_policy` owns decisions from explicit configuration snapshots
and established project facts. `InitialModelPin` is prospective metadata, never
a database write. The shared PythonUnicode15 owner validates defaults; raw
nonempty process/environment overrides and prompt prefix bytes are preserved.
Backend selection, acquisition, singleton lifecycle and storage are still pending.

Task1 full Python:15675passed/same10historicxfail,0new failures/skips/missing IDs.
Task2 full Rust/all-targets:141passed,0failed/ignored; fmt and Clippy pass. Five
public API and two probe tests observed RED before GREEN. A real copied executable
outside the checkout with sentinelPATH/no model environment exactly matched both
originals for1292histories and23promptnames; six forced variants per history.
Task3 tooling115passed/0skip/error; policy-only process3passed on each platform.
The full28gate matrix then passed for Darwin/arm64 and Linux/aarch64: each ran
15689Python passes plus the same10historicxfail,141Rust passes/0failed/ignored,
and85process tests/0failed/error/skipped. Exactbaseline IDs, typing, source hashes,
release binding and all26current fingerprints passed. Policy_accepted=true;
M2_accepted=false. Final independent review is still pending.

Fresh captures verify their current frozen manifest before and after execution.
Historical full manifests include unrelated checkout files; CI freezes a newer
checkout. The comparator therefore binds the full stamp to the current verified
Reference while retaining exact original owner hashes, runtime, rows and outputs.
The policy receipt binds its current source digest to the common26input identities.
Actual recapture on a source-only freeze reproduced the old full-manifest mismatch;
RED→GREEN tests protect both policy and prior translation comparators. Cost of this
ruling: whole-checkout equality is against current Reference rather than an old
manifest. Original source/baseline and exact owner/history checks remain mandatory.

The composed Rust gate now runs all targets so the probe's unit contracts execute;
preparation compiles all targets outside the unchanged600s execution deadline.
The cost is two small probe tests; prior model tests retain their expectations.
CI configuration is prepared, without claiming a remote run or publishing changes.

No M2 acceptance is claimed until storage and all remaining model responsibilities
are migrated and verified. The installed command, original files and user indexes
are preserved. No merge/push/install is part of this cut.
