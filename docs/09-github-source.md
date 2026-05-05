# 09 — GitHub source

**Status:** design — not implemented. Layers structured GitHub metadata
(issues, PRs, reviews, comments) on top of the local git-history path
described in `10-git-history.md`. **For code-only signal, git history
alone is sufficient and superior** (no API rate limits, byte-level
diff resolution, universal across hosting). This doc is about what the
GitHub API adds that git itself doesn't — primarily Issues and the
human conversation around them.

## Why

The engine's predictive ranker is built around the premise *"past sessions
are signal for present queries"*. A GitHub repo's history is exactly that,
retroactively: every issue is a question, every PR is the answer, every
commit is the diff that bridged them. Pulling that data in gives the
ranker a productivity-weighted KG before any agent has run a single
session against the workspace.

The killer query: *"this issue looks similar to a 2-year-old one — these
are the symbols the previous fix touched, plus the discussion that led to
choosing that approach over alternatives."*  Our existing model already
supports this shape — we just need the adapter and the edge vocabulary.

## Mapping to the existing data model

### SourceKind

Already present: `SourceKind::GitHub` (`types.rs:98`). The `sources.config_json`
column carries the per-source config:

```json
{
  "owner": "torvalds",
  "repo": "linux",
  "auth": "github_pat_…",          // or "app_install_id": 12345
  "include_issues": true,
  "include_pull_requests": true,
  "include_commits": true,
  "include_comments": true,         // separate Documents per comment
  "branches": ["master"],           // commit history scope
  "since_cursor": "2024-01-01T..."  // updated each successful sync
}
```

### ContentKind variants to add

```rust
ContentKind::Issue           // GitHub issue (body + metadata)
ContentKind::PullRequest     // PR (body + status + merge metadata)
ContentKind::Commit          // commit (message; the diff is captured via edges)
ContentKind::Comment         // single comment on issue/PR/commit
```

Each becomes a `Document`. The body is chunked the usual way (text or
Markdown adapter). Comments are **separate Documents**, not sub-chunks of
the parent — this lets retrieval surface a single useful comment without
dragging in 100 unrelated ones, at the cost of inflating the corpus
~5–10× per active issue.

### EdgeKind additions

```rust
EdgeKind::Resolves        // PullRequest → Issue   (PR closed/fixed an Issue)
EdgeKind::Mentions        // any → Issue/PR/Commit (text references via #N or sha)
EdgeKind::CommentOn       // Comment → Issue/PR/Commit
EdgeKind::Authored        // Commit → External(github:user)  (git author)
EdgeKind::ChangesFile     // Commit → Document    (file modified by this commit)
EdgeKind::ChangesSymbol   // Commit → Chunk       (symbol-level resolution; fast-follow)
EdgeKind::CreatesFile     // Commit → Document    (file created)
EdgeKind::DeletesFile     // Commit → Document    (file removed)
```

`ChangesFile/CreatesFile/DeletesFile` are derived from the GitHub
`files[].status` field on a PR or commit (`modified` / `added` /
`removed`). The mapping to our `EventType` vocabulary is direct:

| GitHub status | EventType (when replayed as historical session) |
|---|---|
| `added`    | `Edited` (a creation is a positive edit) |
| `modified` | `Edited` |
| `removed`  | `Dismissed` (the file was retired) |
| `renamed`  | `Edited` on the new path |

### EdgeOrigin

Add `EdgeOrigin::GitHub` so the ranker can later weigh GitHub-derived
edges differently from live-session edges (probably should — historical
edges are more confident but also more diluted by time).

## Sync semantics

### Initial pull

Linear paginated fetch via the GitHub REST API (or GraphQL — fewer round
trips, more code). Order:

1. All issues (open + closed) → Documents
2. All PRs → Documents + `Resolves` edges from the PR's "fixes #N" body
   parse + the linked-issue API field
3. Comments per issue/PR → Documents + `CommentOn` edges
4. Commit log per branch → Documents + `Authored` + `ChangesFile/...`
   edges (one per file in the commit's diff)

Embeddings are generated on the fly via the existing `Embedder` trait
(no GitHub-specific path).

### Incremental sync

GitHub provides cursor-based pagination via `since` (ISO timestamp). We
record the high-water-mark in `sources.config_json.since_cursor` after
each successful sync. Webhooks would be fast-follow once we have an
HTTP webhook receiver.

### Rate limits

5000 req/hr authenticated. A 5-year repo with 10k issues + 5k PRs +
50k commits ≈ 65k objects. Each is ~1 request (or 100/page batched), so
initial sync is ~10 minutes of API calls plus the embedding pipeline.
Token-bucket throttle to stay under limits + retries with backoff on
HTTP 403 abuse-detection responses.

## What we get for the ranker (predictive channel)

After ingest, an issue text query produces a `session_contexts` style
match against past Issues/PRs (`recent_session_max_sims`). For each
matching past session:

* `session_scores` snapshots are seeded from the historical PR closing
  the issue: targets are the files/symbols changed, productivity is `1.0`
  if the PR was merged (else `0.3`), `was_edited = true` if the PR was
  merged.
* The predictive channel then scores: *"this issue sim 0.78 to closed
  PR #421 → suggests `User::validate` (changed by that PR) for the
  current session"*.

This is the path that justifies the ranker's design.

## Symbol-level resolution (fast-follow)

A PR's diff lists files; the existing `CodeAdapter` can resolve byte
ranges within those files to symbols. For each `(file, hunk_byte_range)`
in the diff, find the symbol whose `position.byte_range` overlaps and
emit `ChangesSymbol` instead of `ChangesFile`. Doubles ranking precision
for code workloads at the cost of one diff-pass per commit during
ingest.

## What's *not* in scope

- Full clone of the git repo for blame/log queries — out of scope; we
  use the GitHub API.
- Cross-repo edges (e.g., a PR in repo A referencing an issue in repo B).
  The model supports it via `External` URIs but the sync layer doesn't.
- Workflow runs / CI status / reviews-as-first-class. They're useful but
  bloat the model and aren't load-bearing for retrieval.

## Decisions taken so far

| # | Decision | Why |
|---|---|---|
| 1 | Comments are separate Documents | Granular retrieval; cost is corpus inflation |
| 2 | One `Commit` Document per commit, edges to files | Diff is too large to chunk inline; symbol-level fast-follow |
| 3 | `since_cursor` per source row | Re-sync is cheap, no separate sync-state table |
| 4 | GitHub PAT for v1, App for multi-tenant | Multi-tenant needs App; PAT is faster to ship |
