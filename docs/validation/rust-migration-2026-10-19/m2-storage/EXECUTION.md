# Storage execution evidence

Both final T7 executions use implementation `20db131d1ac56f43fb9d779678d9a5daaa29bbab`,
Rust 1.95.0 and the same 6078-file immutable candidate.
Input fingerprint: `e1e46f97b3f0ca4e0724a013335bcc30bb06dd9262a552cbda8047225626a060`.
Manifest SHA-256: `2f36cb474f366342227b14fa227b507d7e0f8d47fd60691f16721e66c0a2291d`.
All 29 current Root/macOS/Linux fingerprints match. Preparation built all three
native packages and precompiled the Rust workspace before the unchanged runtime
deadlines. Executions used `CARGO_INCREMENTAL=0`.

| Check | macOS arm64 | Linux aarch64 |
| --- | ---: | ---: |
| Composed gates passed | 31/31 | 31/31 |
| Python passed | 15731 | 15731 |
| Historical expected failures | 10 | 10 |
| New failures/skips/missing baseline IDs | 0 | 0 |
| Rust test executions passed | 179 | 179 |
| Rust sections | 41 | 41 |
| Rust failures/ignored tests | 0 | 0 |
| Real process tests passed | 90 | 90 |
| New typing errors | 0 | 0 |
| Original files changed | 0/1066 | 0/1066 |
| Storage histories | 23 compatibility + 9 corrections | 23 compatibility + 9 corrections |
| Interrupted/recovered histories | 5 | 5 |

macOS retains the same two missing-`transformers` typing errors: mypy exits 1
and the baseline comparison passes. Linux has zero typing errors and exits 0.
All previously failing baseline tests covered here passed; no baseline IDs were
removed. The ten historical xfails remain recorded.

The original storage runtime is Python 3.12.9, SQLite 3.47.1 and NumPy 2.4.4;
all five frozen source owners are checked. The policy-only Python patch
relaxation does not apply to storage. Native storage reports Rust, `ken-store`
0.18.0, bundled SQLite 3.53.2, float32/little-endian format 1 and no inference
runtime requirement.

| Measured storage endpoint | macOS | Linux |
| --- | ---: | ---: |
| Own-process peak RSS, bytes | 15024128 | 9502720 |
| Own elapsed time, ns | 838279375 | 1539524376 |
| Copied-native process wall time, ns | 1180981000 | 1592769167 |
| Original process wall time, ns | 2494138083 | 2379227001 |

RSS and own elapsed time end after observations, before JSON transport. The
separate wall times include transport. These observations establish no speedup,
SLA, power-loss durability or reader serializability.

Copied probes run outside their checkout with a sentinel PATH without Python.
Linux traces require exactly one exec for storage parity and every recovery
role. Only newly created controller process groups are killed. Dependency audits
identify the native store; original Python seed/read processes are independent
reference operations.

## Retained proof

- [macOS receipt](macos/summary.json), [execution manifest](macos/execution-artifacts.json),
  [byte inventory](macos/artifact-manifest.json), [measurements](macos/measurements.json):
  176 required raw files.
- [Linux receipt](linux/summary.json), [execution manifest](linux/execution-artifacts.json),
  [byte inventory](linux/artifact-manifest.json), [measurements](linux/measurements.json):
  200 required raw files.

All 376 raw files are authenticated and
semantically re-compared, including nested receipts, full logs/XML, benchmarks,
requests, original/native outputs, dependency audits, recovery readbacks and
Linux exec traces. Disposable validation `environment` directories are excluded.
Inventory/measurement documents are additional publication metadata.

Cargo's final blank lines are retained byte-for-byte in both raw Rust logs.
The scoped Git whitespace check passes for this change. Authenticated output
is never trimmed to change its hash.

## Earlier attempts and corrections

T5 first used one incorrect Linux baseline path. Later host disk exhaustion
caused I/O errors and Docker lost its socket. Those incomplete runs were
excluded and retained. Project-only cleanup removed 183052 temporary files
across the checkout and its dedicated container, about 24.15 GiB allocated,
plus safe SQLite WAL checkpoints. Source/proof/ownership checks preserved
originals, notes, frozen sources, current binaries and active jobs. Automatic
review rejected a broader mixed cleanup; it was not executed. Narrower actions
followed concrete ownership and manifest checks. Official Docker Desktop
stop/start recovered the backend; no unrelated container/image/volume was deleted.
Later, two fully duplicated host transfer archives were removed after complete
source/archive hash comparison and an exact open-handle check: 236425216 allocated
bytes, with all 12154 source files and both source manifests retained.

The one final review found four gaps. Their RED/GREEN corrections are recorded
in [FINAL-REVIEW.md](FINAL-REVIEW.md) and [FINAL-FIXES.md](FINAL-FIXES.md).
T6 then passed all 31 gates on both platforms. An additional readonly-directory
recovery gap was reproduced during the same fix pass, requiring this fresh T7
candidate and complete acceptance. T5/T6 historical proof is retained privately.

The first T6 Linux attempt exceeded the unchanged 30-second deadline in the
original `python -m ken structural catalog --help`. Only its owned job was
stopped, and the partial tree was excluded. The exact test, ten fresh command
invocations and a new complete T6 run passed without source/timeout changes.
The initial stall's cause remains unproved. T7 uses the same deadlines and
baselines. A first local T7 Rust attempt lacked loopback sandbox permission;
the unchanged full suite passed with that required permission enabled.
