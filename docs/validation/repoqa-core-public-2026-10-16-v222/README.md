# Public retrieval evaluations: frozen registration (V222–V226)

**Status: execution in progress; no new accuracy claim.** This change saves the
protocol and reviewed scorer, not a completed benchmark result. The search engine
is unchanged from V214 / commit `8ce6b00c3a653e2effa46ec02b7acedd4c100501`.
There is no release and the acceptance reserve remains closed.

| Track | Fixed inputs | Reported measures |
|---|---|---|
| RepoQA retrieval variant | All600 original descriptions,60 shipped repository snapshots,6 code languages | Correct file+function identity Top1/Top10, MRR@10 and single-target NDCG@10; file-only hits separately |
| CORE exploratory pilot | All18 level-specific cases from the three smallest SWE-bench Verified corpus unions: Flask, Requests, Seaborn; Level2 and Level3 | Original binary-qrel NDCG@10, relevant-document Recall@10, any-relevant Hit@1/10 |

RepoQA release `2024-06-23` contains600 cases, despite the evaluator README's
500-case description. Its gzip SHA256 is
`c050a2ad90a7df89d9dc1f1c3b3b20683edd20a56293b35fcaae43dec115d681`.
The retrieval variant searches all shipped content and is **not** the official
generative SNF/BLEU leaderboard task or its restricted constructed context.

CORE dataset revision is `23da5d97a8a4495d4bd6d5616aa86d5a12a60699`.
The pilot is **not a complete CORE benchmark or complete official group**.
Several relevant chunks per query make any-hit, recall and NDCG different measures.
The two levels can repeat an issue;18 level-specific cases are not necessarily
18 independent issues. Ten returned slots do not measure Recall@100.

CORE's shipped documents have text+UUID without original source paths. This
adapter preserves exact text under reversible opaque `.txt` filenames, retaining
all documents permitted by the original public `filtered_corpus_id`. It does not
use positive qrels to choose candidates. It loses original path/language/ownership
signals. Building eligible snapshots before retrieval also differs from the
original evaluator's corpus-wide scoring followed by a filter. Scores must be
labelled **Ken text-corpus adapter pilot**, not native original-repository function
localization or directly equivalent official leaderboard results.

The frozen source manifest SHA is
`b9e86b7fe4e7a405f94c47a1f157b97765eed97f3581f356f927d738e0f79079`.
All captures use the unmodified production configuration, CPUExecutionProvider,
1024 reranker tokens,10 native slots and12,000-character output budget. Preparation
is measured separately. Wall times and process peak RSS are observations while
other benchmark jobs can run; they do not certify isolated latency or speedup.

Requests/references are separate. Workers never load labels. Every full track
must close and verify all response pins/IDs before scoring; errors retain their
denominator. RepoQA references are reconstructed from the pinned official gzip
before grading. The reviewed identity proxy has a unique (repo,path,function leaf,
definition end) key for all46,152 official functions and all600 needles; it is not
a universal authenticator for arbitrary DTOs. See the independent review.

A first capture failed solely on a tuple/list provider assertion. A second
preparation collided with its lingering child for WasmEdge. Both logs were kept;
one infrastructure-only retry was preregistered before grading. It uses identical
requests, source and engine. No retry selection uses accuracy or labels.

The scorer passed14 focused tests. Removing its null-identity guard in a private
copy causes the three regression fixtures to fail. The independent reviewer also
checked1,000 binary metric fixtures against the official CORE collector and
rejected two synthetic unclosed tracks before label access. The product source,
model weights and public defaults were not changed by this evaluation harness.

The scripts in `experiments/search-engine/` retain the local frozen run's versioned
names. They require the pinned frozen source, prepared model cache, official data
files and metadata declared in their registration; they refuse to overwrite a run.
They do not install a new runtime dependency or enter the shipped package. Large
corpora, rebuilt indexes, raw queries and qrels are not vendored here. The local
run directory is `output/development/repoqa-core-v222` in the research workspace.
Its finalizer writes `core-report-v224.json` / `repoqa-report-v224.json` only when
those tracks close. This document must not be cited as a completed score.

Sources: [RepoQA evaluator](https://github.com/evalplus/repoqa/tree/ae876deb1365dbf5a15b0533723c8ed123eee586),
[RepoQA data](https://github.com/evalplus/repoqa_release/releases/tag/2024-06-23),
[CORE evaluator](https://github.com/zhangfw123/CORE-Bench-Eval/tree/5d00cdcaade77796fa6e5ac4852404002029c00a),
[CORE data](https://huggingface.co/datasets/zhangfw123/CORE-Bench/tree/23da5d97a8a4495d4bd6d5616aa86d5a12a60699).
