# Native model policy: accepted after review and verified corrections

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
M2_accepted=false. Those are historical pre-review T3 figures; the accepted
post-review T4 figures below supersede them.

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

## Accepted final correction cut

One independent final review found2Important/0Critical/0Minor. Both findings were
reproduced RED→GREEN in one correction pass, commit90a23af2, with no rereview.
Python patch provenance now accepts stable3.12.x only after exact source/Unicode/
observations/decisions/prompts replay. Actual isolated macOS3.12.10 replay matched
the frozen3.12.9 original; its complete result is published separately. See REVIEW.
The original3.12.9 interpreter remains intact; a uv-created outside-project launcher
was detected and exactly removed, and future private setup uses --no-bin.

The receipt now binds execution-artifacts.json. Complete saved execution trees,
including nested raw receipts/outputs/requests/oracles/logs/XML/benchmark/Linux
traces, are required and checked by hash/size before parsing the same owned bytes.
Authenticated policy outputs are compared again to the original. Runtime caches
and root self-reference are excluded, and registered Linux core warnings keep their
existing diagnostic rule. Summary-only or hash-only private-payload bundles fail.

Immutable sourceT4:5505files,manifest
f80c05ad223fa1e35e46dab8fbb43d59bfc211e46f7df71903b861a369f502e1,
code90a23af2. BOTH platforms ran all28gates: each15702Python passes plus the
same10historicxfail,141Rust passes/0failed/ignored,85process passes/0failure/error/
skips. Mac retains2historic missing-transformers typing errors; Linux0; no new
baseline failures/skips/missing IDs/type errors. All1066original hashes unchanged.

The actual public-tree current matrix passes26matching input fingerprints and
153required execution artifacts (73Mac/80Linux). Published raw inventories contain
157hashes including root receipt/manifest pairs. Native-source fingerprint
40aeeec9dbe951629416665c21c16617bc58279c68b48ffbfeca8055d7bab5e5;
validator fingerprint
1c17be6ab5387551b50cf1b0138892f6aba6bc086d71cdfcac1e303601e462e8.
Policy_accepted=true,M2_accepted=false. PriorT3 evidence remains recoverable in Git
and the private archive. This accepts model selection/prompt values only. The
whole migration continues with the documented storage plan and remaining models.
