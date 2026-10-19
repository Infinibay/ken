# Storage execution evidence

Both final executions use implementation
`ea0e73d6fd4066f1617be72d3f91daaa6fda3484`, Rust 1.95.0 and the same 5691-file
immutable candidate. Its input fingerprint is
`94492b1a5bca590feb7233c0f0fa897d3b791de403fb62951bbceb6ceb73bd54`;
the manifest file itself has SHA-256
`7c20776a09af4a01e9c66556a55ada63d76368cd2c5fe53261733b5a6a6f5bbd`.
The current macOS worktree and Linux candidate have the same 29 fingerprints,
also identical to the cut before the disk incident.

Preparation built all three native packages and precompiled the complete Rust
test workspace before the unchanged runtime gates. The final executions used
`CARGO_INCREMENTAL=0` to avoid rebuilding discarded incremental caches.

| Check | macOS arm64 | Linux aarch64 |
| --- | ---: | ---: |
| Composed gates passed | 31/31 | 31/31 |
| Python passed | 15731 | 15731 |
| Historical expected failures | 10 | 10 |
| New failures/skips/missing baseline IDs | 0 | 0 |
| Rust tests passed | 171 | 171 |
| Rust sections | 39 | 39 |
| Rust failures/ignored tests | 0 | 0 |
| Real process tests passed | 90 | 90 |
| New typing errors | 0 | 0 |
| Original files changed | 0/1066 | 0/1066 |
| Storage histories | 23 compatibility + 9 corrections | 23 compatibility + 9 corrections |
| Interrupted/recovered histories | 5 | 5 |

macOS retains exactly the two recorded missing-`transformers` typing errors;
its typing command exits 1 and the baseline comparison passes. Linux has zero
typing errors and exits 0. Neither result is represented as a clean macOS mypy
run. All prior baseline failures covered by these executions passed, with no
baseline IDs removed. The 10 historical xfails remain explicitly recorded.

The storage reference runtime is Python 3.12.9, SQLite 3.47.1 and NumPy 2.4.4,
with the five frozen source owners checked. The policy-only Python patch
relaxation was not generalized to storage. Native storage reports Rust,
`ken-store` 0.18.0, bundled SQLite 3.53.2, float32/little-endian format 1 and no
inference runtime requirement.

| Measured storage endpoint | macOS | Linux |
| --- | ---: | ---: |
| Own-process peak RSS, bytes | 15024128 | 9498624 |
| Own elapsed time, ns | 1038379375 | 1651223459 |
| Copied-native process wall time, ns | 1389140042 | 1705879917 |
| Original process wall time, ns | 2688027459 | 2526993334 |

RSS and own elapsed time end after observations and before JSON transport.
The separate wall times include process/transport overhead. These observations
do not establish an improvement or a new resource budget.

Each copied native probe ran outside its checkout with a sentinel PATH without
Python. Linux traces require exactly one exec for storage parity and for every
recovery role. The controller kills only its newly created process group.
Native dependency audits identify `ken-store`; original Python processes are
independent reference seed/read operations, not native runtime children.

## Complete retained proof

- [macOS root receipt](macos/summary.json),
  [execution manifest](macos/execution-artifacts.json),
  [byte inventory](macos/artifact-manifest.json),
  [measurements](macos/measurements.json): 176 required raw files.
- [Linux root receipt](linux/summary.json),
  [execution manifest](linux/execution-artifacts.json),
  [byte inventory](linux/artifact-manifest.json),
  [measurements](linux/measurements.json): 200 required raw files.

The 376 files include root receipt/manifest pairs, nested policy/model receipts,
full Python/Rust/type/process logs and XML, benchmarks, requests, original and
native outputs, dependency audits, original recovery readbacks and Linux exec
traces. Validation authenticates and re-compares their contents. Disposable
`environment` trees are deliberately excluded, not required proof omitted from
the publication. Additional measurement/inventory documents identify the cut.

The two captured `rust_tests.log` files retain Cargo's final blank line exactly.
Consequently the unrestricted Git whitespace check reports two raw-log EOF
notices. They are preserved rather than changing authenticated machine output;
the whitespace check for all other files, including authored documentation,
passes. No product lint/test threshold or source assertion was suppressed.

## Rejected attempts and disk recovery

An initial Linux launch used an incorrect baseline path; only that owned job
was stopped and its partial output preserved outside the acceptance tree.
Later the host filesystem reached 100% with about 140 MiB free. Linux returned
disk I/O errors and Docker lost its engine socket; macOS also reported SQLite
disk I/O errors. Those attempts were not accepted.

The user authorized project temporary cleanup. Narrow checks preserved source
and evidence manifests, persistent notes and active jobs. Cleanup removed
183052 temporary files across this project and its dedicated container, about
24.15 GiB of allocated data, plus safe SQLite WAL checkpoints. Original hashes,
critical frozen sources and prior authenticated proof were reverified. A broad
mixed cleanup was rejected by automatic review and was not executed; narrower
actions proceeded only after concrete ownership/manifest checks.

Official Docker Desktop stop/start recovered the stuck backend; no unrelated
container, image or volume was deleted. The owned container's original Python
and all candidate hashes were verified before fresh full executions. Final
macOS session 49793 and Linux session 98762 both closed 0. The system later
reported approximately 32 GiB free. Old failed outputs remain private and are
excluded from this matrix. Runtime limits, fixtures and baselines were unchanged.
