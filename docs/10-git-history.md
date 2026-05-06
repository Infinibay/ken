# 10 — Git history as a source

**Status:** design — not implemented. The single highest-leverage source
for any code workspace; trumps the GitHub API path (`09-github-source.md`)
in raw signal density. The GitHub path adds structured metadata
(issues, reviews) on top.

## Why git history is special

The predictive ranker is designed around the input *"past sessions where
context resembled the current query, weighted by what targets ended up
being productive"*. Git history is **already that data, retroactively**:

| Predictive ranker expects… | Git provides… |
|---|---|
| `SessionContext` (NL description of intent) | commit message |
| `SessionInteraction`s (which targets the agent touched) | files touched in the commit |
| `EventType` (read / edited / cited / dismissed) | derived from `files[].status` (added/modified/removed) |
| `productivity` (did this lead anywhere?) | merged-into-mainline = high; reverted = negative |
| `was_edited` flag | true for any commit that modified the file |
| `agent_id` for partitioning | commit author |
| Time-decay over `lookback_days` | natural — `git log --since=` |

A 5-year-old active codebase has tens of thousands of commits, each one
a labeled training example for the ranker. **Replaying it is free
training data for the predictive channel** — no agent ever has to run
against the workspace before the engine starts producing useful results.

The reactive channel still kicks in once a real session starts. The KG
edges from the diff-resolution step give the semantic+KG channels a head
start too. Three of the four ranker channels benefit from git replay; the
fourth (FTS) doesn't change.

## What git gives that the GitHub API doesn't

* **No API auth, no rate limits, no network**. `libgit2` reads the
  `.git/` directly. A 30M-LoC kernel clone reads in ~minutes.
* **Symbol-level diffs**. The diff says exactly which byte ranges
  changed. Crossed against the existing `CodeAdapter`'s symbol byte
  ranges, every commit becomes a `Commit → ChangesSymbol` edge — far
  more precise than file-level.
* **Universal**. Works on the kernel (LKML patches, no GitHub Issues),
  on internal monorepos, on private gists, on any git repo.
* **Co-edit signal**. Two files in the same commit = directly related,
  by definition. This is the same signal task #31 was reaching for via
  session-close inference, but observable on day zero from history.
* **Authorship + blame** as ACL/ownership signal — useful for
  multi-tenant routing later (e.g., "weight scores higher when the
  current agent is touching code historically owned by the same author
  cluster").

## Two ingest modes

### Mode A: Documents (commits as searchable artifacts)

Each commit is a `Document` (`ContentKind::Commit`) with:

* `title` = first line of the commit message
* body chunked: full message + per-file diff hunks as `Chunk`s
* `path_or_url` = `git+sha:<repo>@<sha>`
* edges:
  - `Commit → Document` (`ChangesFile`) per touched file
  - `Commit → Chunk` (`ChangesSymbol`) per resolved symbol (fast-follow)
  - `Commit → External(github:user)` (`Authored`)
  - `Commit → Commit` (`References`) for "Fixes: <sha>" / "Reverts: <sha>"
    parsed from the message body

This makes commits *retrievable*: "what was the rationale for the
spinlock in `tcp_v4_rcv`?" → ranks the commit that introduced it.

### Mode B: Replay as synthetic sessions (the killer)

The predictive ranker consumes `(SessionContext, SessionInteraction[],
SessionScore[])` triples. Git replay produces them directly:

```
For each commit C in the history (newest first, capped at lookback):
  ctx     = SessionContext { content: C.message, kind: Query }
  events  = [
    SessionInteraction { target: file F, event_type: Edited, weight: change_size(F, C) }
    for F in C.files_modified
  ] + [
    SessionInteraction { target: file F, event_type: Cited /* added */, weight: 1.0 }
    for F in C.files_added
  ] + [
    SessionInteraction { target: file F, event_type: Dismissed, weight: 1.0 }
    for F in C.files_removed
  ]
  scores  = [
    SessionScore {
      target: F,
      score: derived_from(events_for_F),
      productivity: 1.0 if C is on default branch (got merged) else 0.3,
      pattern: classify_pattern(events_for_F),
      was_edited: true,
    }
    for F in C.files_modified ∪ C.files_added ∪ C.files_removed
  ]
  Persist as a synthetic Session with agent_id = "git:<author_email>",
                                created_at = C.committer_time
```

After replay, the predictive channel sees thousands of past "sessions"
the moment a live one starts. The query *"how does the slab allocator
handle NUMA?"* finds high-similarity past commits whose messages
discussed slab+NUMA, and surfaces the symbols those commits touched.

The mode-B replay also produces co-edit data (multiple files in the
same synthetic session) — which is task #31's source of truth. The
session-close job from #31 can run against synthetic sessions exactly
the same way it would against real ones.

## Filtering — what to skip

Replaying every commit verbatim adds noise. The defaults:

* **Merge commits**: skip. Their diff is mechanical; the message is
  usually `Merge branch 'foo'`. No signal.
* **Bot commits**: skip authors matching `*[bot]@*`, `dependabot[bot]`,
  `renovate-bot`, `github-actions`. Mass-edits without intent.
* **Formatting / whitespace-only commits**: skip when ratio of code
  lines to whitespace lines crosses a threshold. Detected by parsing
  the diff.
* **Reverts**: keep, but emit a `Reverts` edge to the original commit
  and treat the original's `productivity` as negative for that target
  (the change *didn't* end up being right).
* **Squashed PRs vs individual commits**: prefer the merge-commit's
  collapsed view if available — captures the PR's intent better than
  the WIP intermediate commits.
* **Lookback window**: default 2 years. Older history is fine to
  retain as Documents (mode A) but contributes diminishing returns to
  the predictive channel after the `session_decay` math eats it.

## Implementation sketch

* New module `crates/engine/src/ingest_git/` — uses `git2` (libgit2
  binding) for read-only repo traversal. Pure read, no remote ops.
* `IngestGitConfig { repo_path, lookback_days, branches, mode: A|B|Both }`.
* Walk via `git2::Revwalk`. For each commit, read the diff via
  `git2::Diff`, classify hunks against the file's tree-sitter tree (when
  the file is a code file the `CodeAdapter` understands), emit either
  Documents (mode A) or synthetic Sessions (mode B) accordingly.
* Embedding: same path as everything else. Mode A passes commit message
  + diff text through `embed_passages`. Mode B passes commit message
  through as the `SessionContext` content.
* Idempotency: keyed by `(workspace_id, "git+sha:<sha>")`. Re-ingesting
  the same repo is a no-op for already-seen commits.
* Incremental: the last-ingested commit sha is the cursor. Next sync
  walks from `HEAD` until that sha.

## Symbol-level resolution

For each diff hunk over a file the `CodeAdapter` accepts:

1. Re-tokenize the file at that commit (or the parent commit, depending
   on whether you want pre-state or post-state symbols) via the
   appropriate tree-sitter grammar.
2. For each modified byte range in the hunk, find the smallest
   enclosing symbol (`function_item` / `method_definition` / etc).
3. Emit `Commit → Chunk` (`ChangesSymbol`) edges, with the chunk being
   the *current* version of that symbol in our index. Stale (deleted)
   symbols just don't get an edge — fine, the file-level edge still
   exists.

This is what makes "find PRs that touched `User::validate`" → "here's
the 3-year history of who edited this exact function and what their
commit messages said."

## Volume / cost estimates (Linux kernel as worst case)

* ~1.2M commits, ~600 active contributors, ~30M LoC.
* Mode A only: 1.2M Documents = ~1.8GB embeddings (384d × 4 bytes ×
  avg 1 chunk per commit message). HNSW handles it at our tuned
  `m=24, ef_construction=128` — tested in pgvector at 5–10M vectors.
* Mode B replay: ~1.2M synthetic sessions, ~50M synthetic
  interactions. Sessions table grows linearly; the scores table after
  snapshot is the dense one.
* Smart default: cap mode-B replay at the last 2 years (~200k commits)
  *and* sample 1-of-N for older history if the user wants long memory.
* Embedding throughput is the bottleneck. 200k commits at 50ms/commit
  CPU-only fastembed = ~2.7 hours. With batched `embed_passages` and
  the new ingest write path, the DB side is no longer the limiter.

## Alignment with task #31

Task #31 ("Learned co-access edges") was scheduled for post-MVP and
designed to *infer* co-access edges from session-close events. Git
replay produces the same edges from history on day zero. Once #31
lands, its session-close job runs unchanged on synthetic Sessions
produced by replay — the two mechanisms compose.

## What this enables for the kernel benchmark

The user's proposed benchmark — "agent-only on Linux kernel" vs
"agent + engine on Linux kernel" — only works if the engine has been
populated with something better than just the bare code embeddings.
Mode B replay over 2 years of kernel commits is what closes that gap:
the predictive channel surfaces *the actual fix* for similar past
problems, not just code that lexically matches. Without replay the
benchmark is essentially testing "embedding-based grep vs ripgrep" —
informative, but underestimates the system.
