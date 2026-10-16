# Why the CORE text-corpus pilot scored poorly

The pilot's low score is reproducible. It is **not a compact-output matching
failure**. It measures Ken against opaque document chunks, with important code
structure missing, and exposes genuine selection and ordering errors in that
condition. It does not establish native repository search accuracy.

The frozen V214 engine, original outputs, qrels and acceptance criteria are
unchanged. The private acceptance reserve remains closed. These are diagnostics
on an already exposed public pilot, not a new acceptance set or a release.

## Scope and unchanged result

The pilot contains 18 level-specific cases representing 11 unique issues in
Flask, Requests and Seaborn. Level 2 and Level 3 can ask about the same issue
with different relevant document sets. This is not the complete CORE benchmark.

| Measure | Closed original pilot |
|---|---:|
| Any relevant document at rank 1 | 3/18 = 16.67% |
| Any relevant document within 10 | 9/18 = 50.00% |
| Relevant-document Recall@10 | 0.202882 |
| Binary-qrel NDCG@10 | 0.192942 |
| Query errors, retained in denominator | 2/18 |

Hit@10 is an any-hit measure; Recall@10 measures the fraction of all relevant
documents returned. They are different, especially for Level 3 queries with many
positive context chunks. These scores are not interchangeable with the local
development benchmark's correct-code-piece Top1 or Top10.

## The output format hypothesis was checked directly

The scorer joins `results[].path` through a fixed reversible map to original
CORE UUIDs. It never scores the CLI/MCP compact string or compares displayed
snippets as exact strings. All 160 returned document mappings, their original
bytes and source hashes match. All 250 visible evidence fragments are faithful
slices of the mapped originals.

The pinned official `calculate_metrics` function produces the same Hit@10,
Recall@10 and NDCG@10 for every one of the 18 actual cases. Direct UUID membership
also reproduces Hit@1. There are zero metric discrepancies.

Allowing an identical complete document under a different UUID recovers no extra
hits. Normalizing CRLF and surrounding whitespace also leaves Hit@1 at 3/18 and
Hit@10 at 9/18. A diagnostic search for identical complete callable ASTs does not
recover another Top1 either. AST overlap is not a substitute official metric.

An independent manual review of every negative Top1 found 8 documentation or
changelog documents, 3 tests, 2 wrappers for HTTP OPTIONS, and 2 errors with no
response. It did not demonstrate a complete equivalent implementation hidden
under another UUID. Related documentation or a test can help investigation;
that does not establish identity with the edit location sought by the issue.
The review does not certify that qrels exhaust every useful context document.

## What the input adapter removed

The shipped corpus supplies UUID and text, without original file paths. Our
adapter wrote each eligible original text verbatim to `documents/<UUID>.txt`.
All 19,275 materialized files across the 18 snapshots were indexed. However,
every snapshot has **zero symbols**, every passage is classified as
`documentation`, and every structured signature and documentation field is
empty. The actual prose and code remain in the body field; empty documentation
fields do not mean docstrings were erased from that body.

This disables or flattens important ranking inputs: function/class identity,
constructor recognition, signature matching, docstring-specific matching,
definition/test/example role discrimination, original path semantics, and
member ownership. A code chunk, a test and a changelog all arrive as an opaque
text module. The file route also does not use the V214 symbol-specific ranking
policy. This is a different representation from normal source repository search.

Some fragmentation predates our adapter. CORE already separates certain method
signatures, docstrings and bodies into different documents, and may omit the
enclosing class. Renaming `.txt` cannot recreate those relationships. The loss
of metadata is confirmed; how much of the aggregate deficit it causes requires
controlled measurement, rather than attributing every failure to the adapter.

## Where candidates are lost

I replayed all 18 unchanged queries through the frozen engine, recording the
broad proposals, numeric owner scores, native ten-piece pool, piece scores,
neural scores and final fusion. Every original final order or error reproduces.

| Stage | Cases with at least one reference still available |
|---|---:|
| Broad retrieval, 382–515 proposed owners per query | 17/18 |
| Native pool of ten pieces, after numeric owner selection | 10/18 |
| Final response, including the two query errors | 9/18 |

The first row is **not Top10 recall**: it is coverage in several hundred
proposals. Among the 16 queries returning a response, 3 have the correct Top1,
6 have a reference at ranks 2–10, and 7 have none in Top10. Of those seven,
six had a reference in broad retrieval and lost it before reranking; one did
not retrieve any reference even in the broad proposals. A reranker limited to
the native ten cannot repair those seven misses.

Representative best reference ranks before the cutoff are 15 for Seaborn
nominal axes, 25 for the Flask Blueprint constructor, 43 for Requests session
headers, 139 for Requests method conversion, and 11 for Requests dotted-host
validation. These are selection/ranking failures under this representation,
not formatting mismatches. The per-case receipt retains all 18 rank lists.

## A demonstrated fusion error

For Requests issue 1766, the request concerns quoting Digest authentication
`qop` options. Top1 instead sends the unrelated HTTP OPTIONS method. In both
levels the neural reranker gives the correct Digest implementation its highest
score. The final equal-weight reciprocal-rank fusion still prefers OPTIONS.

For Level 2:

| Candidate | Piece forest rank | Neural rank | Neural score | Fused score |
|---|---:|---:|---:|---:|
| HTTP `options()` wrapper, wrong | 2 | 2 | 9.317745 | 0.0161290323 |
| Digest `qop` implementation, relevant | 4 | 1 | 9.933258 | 0.0160092213 |

The current formula is `0.5/(60+piece_rank) + 0.5/(60+neural_rank)`. The large
neural score gap supplies only an ordinal advantage; it does not outweigh the
piece forest's ordering. This is direct evidence for this failure, without
assuming that any neural score is a calibrated relevance probability.

Disabling fusion is not justified by this pilot. On the same 16 completed
queries and fixed native pools, numeric owner Top1 is correct twice, the piece
forest once, raw neural order three times, and final fusion three times. Raw
neural order and final fusion succeed on different cases: fusion also recovers
correct results. These are diagnostic rank-only views of an exposed sample.

## Query handling and task mismatch

The two errors are the same Requests issue 1724 at the two levels. Its unchanged
7,476-character report exceeds the configured reranker's query-side token
budget. The engine raises `query is too long for reranking` instead of returning
the existing candidate pool. It is an input-budget handling failure. Even if
both became correct Top1, that alone could raise the pilot only to 5/18.

Ten reports are interpreted as `usage` because they contain the word `example`,
often inside a bug reproduction. This is a suspicious intent heuristic, but it
does **not** explain this pilot's owner-score difference by itself: every
passage is `documentation`, so both `usage -> example` and
`implementation -> definition` give `role_match=0`. Their test/documentation
request flags are also identical in the piece scorer. Restoring real roles
would make that intent distinction meaningful and require its own control.

CORE's task differs from finding an existing described behavior: a bug report
may ask for validation that does not exist yet. The
Blueprint issue asks for rejecting an empty name; the constructor currently
checks a dot in the name. A test rejecting `app.ui` matches Blueprint and
ValueError vocabulary but tests another rule. The relevant result is the
implementation to change, not the superficially similar condition.

## Paired representation control

I fixed a diagnostic intervention before executing it: use the same 1,000
eligible Flask Level 2 texts, UUIDs, original query, engine, file-search scope,
ten slots, output budget and CPU models. Change only the filename extension to
`.py` when the unchanged text parses with Python's AST and contains a function
or class definition; leave everything else `.txt`. No dedenting, synthetic
classes, original-path guesses, candidate removal or qrels-based classification
is allowed. The query was already exposed: this is not blind acceptance.

This syntax-only rule recognizes 603 Python documents, leaving 397 as text.
All 1,000 documents remain byte-identical and indexed. It restores 1,474
symbols and distinct definition, test and documentation roles.

The correct Blueprint constructor moves from **absent in the original Top10
to final rank 6**. Top1 remains the same incorrect dotted-name test. Thus this
minimal representation intervention demonstrably improves candidate selection
on this case, but does not resolve its final ranking or quantify the aggregate
18-case deficit. It does not restore missing enclosing classes or original
source paths, and the original 3/18 pilot score is not replaced.

The CPU-only control query took 2.62 seconds, after 204 seconds of preparation.
Observed query-process peak RSS was 1.15 GB (1.07 GiB), and preparation-child
peak was 1.26 GB. Concurrent benchmarks were running; these are observations,
not an isolated performance comparison. See [control receipt](representation-control.json).

## Implications

The original pilot score stands as a text-corpus adapter result. It should not
be marketed as native Ken repository accuracy, corrected by hand, or replaced
by a more convenient score. Conversely, the local development score near 90%
does not establish 90% on this external task.

For a native repository evaluation, retain original file/language/owner context
and bind official references to source identities without answer-dependent
candidate filtering. For direct CORE document retrieval, make a deliberate
document ingestion route that preserves available code structure. Then test
candidate selection, intent handling, long-query behavior and ranking fusion
separately on fresh data. This investigation changes none of those policies.

## Evidence and reproduction

The local run directory is `output/development/repoqa-core-v222` inside the
research workspace. This report vendors small receipts and diagnostic scripts,
not corpora, model weights or rebuilt indexes. The scripts expect that pinned
local run and refuse to overwrite an experiment. Source-only input workers do
not open qrels; labels are joined after their respective captures close.

- [Mechanical audit](audit.json), [stage analysis](stage-analysis.json), and
  [independent review](case-review.md) / [machine-readable review](case-review.json).
- The stage capture closure pins all 18 larger local trace files; their full
  feature vectors and source cards remain local for debugging.
- Frozen engine manifest:
  `b9e86b7fe4e7a405f94c47a1f157b97765eed97f3581f356f927d738e0f79079`.
- Original report SHA256:
  `b46ae4aa7ded74ace5c35e51e98df6f42c0d444bdff8cfa27c4ac24bdbc145c0`.
- [Original protocol](../repoqa-core-public-2026-10-16-v222/README.md) explains
  snapshot eligibility, pipeline differences and the separate RepoQA variant.
- [Pinned official CORE evaluator](https://github.com/zhangfw123/CORE-Bench-Eval/tree/5d00cdcaade77796fa6e5ac4852404002029c00a)
  and [dataset](https://huggingface.co/datasets/zhangfw123/CORE-Bench/tree/23da5d97a8a4495d4bd6d5616aa86d5a12a60699).
