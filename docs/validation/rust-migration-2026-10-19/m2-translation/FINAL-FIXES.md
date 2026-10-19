# Single final-review correction pass

Review: REVIEW.md, committed range1ae4bb97..14da4bcc. One fresh reviewer; no
second review. Both Important findings were retained by user effect and first
reproduced in failing tests. Two Minors are deferred in EXECUTION.md.

The5KB underscore/Unicode query caused Onig's retry-limit panic in both the
public query planner and normal expand_attempt path. The corrected pattern
factors at the first eligible underscore: the suffix already admits all later
underscores, preserving the longest match without repartitioning that run.
Remaining engine errors use the fallible API and become ModelError; retry
limits and input acceptance were not increased or capped. The frozen original
finds no protected span at5000/20000underscores+é. A separate299593-string
Python-only factorization experiment found no span differences; it is not
native acceptance. All2438 existing native policy histories remain unchanged.

The BLAS regression replaces the archive path after authentication, then runs
real harmless tiny Makefiles. The former helper reached the replacement source
and failed only at late publication. The correction opens a regular file
nonblocking, reads at most registered size+1, authenticates immutable owned
bytes, then extracts and publishes those same bytes. A fresh actual Linux
OpenBLAS0.3.26 build completed17.823907758s and produced the same1051378-byte
archive/SHA as the earlier numeric core. Synthetic fixtures establish ownership;
the real build establishes that the pinned source still works.

Targeted verification:7 expansion tests,5 policy tests,97 tooling tests,
workspace formatting and all-target Clippy pass. final-fixes/ retains RED/GREEN
logs and measured identities with hashes. All1066 original hashes remain intact.

The corrected T4b candidate is29de2b391b082f914256712abe24f73ac04a34f6836e5bf809073ee683aa0b1d.
Its fresh macOS26gate proof passes, with134 Rust passes/0failed/0ignored and
15671 Python passes/the same10 historical xfails. Linux also passes all26 gates,134 Rust tests and15671 Python tests with the same
10 historical xfails. Both platforms pass82 process tests with zero skips/errors.
Current MATRIX.json binds the corrected source on both platforms and reports
Translation_accepted=true,M2_accepted=false. The one correction pass is complete;
this query-expansion profile is accepted and all-M2 remains open.
