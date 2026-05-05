# 11 — Git history ingest: implementation plan

**Status:**
- **Phase 0** shipped — libgit2 walker, mode A Documents, mode B synthetic
  sessions with backdated timestamps, idempotency, CLI.
- **Phase 1** shipped — commit-message linkage parsing
  (Fixes/Reverts/CherryPickedFrom/Co-authored-by) (#60), file-rename
  tracking with `RenamedFrom` edges (#61), squash-merge detection
  metadata flag (#62), **branch-as-session aggregation**: merges are
  the session anchor and aggregate file changes across all commits
  unique to the branch via `P1..P2` revwalk; branch members get
  Documents but no individual synthetic session (#63), and
  **symbol-level diff resolution** (#64): `Patch::from_diff` extracts
  hunk ranges per file, a blob-OID-keyed `SymbolCache` parses each blob
  once via `extract_symbols`, and per-commit `ChangesSymbol` edges target
  `External("git+symbol:<ws>:<path>:<qualified_name>")`. Default
  `branch_as_session = true`.
- **Decisions taken**: D1=2y, D2=current bot list, D3=`repo.head()`,
  D4=both modes, **D5=`sessions.kind` column shipped** (migration
  `0004_session_kind.sql`), D6=deferred to Phase 2.
**Companion to:** `10-git-history.md` (architecture/why).
**Origin:** the user pointed out that a `change-then-revert` pair within
a single branch is *negative* evidence about the change, not neutral.
This plan systematizes every signal git carries and assigns each one a
phase of implementation.

---

## 1. Full signal taxonomy

Each row is a piece of information git makes available, what it tells
us, and where it shows up in our model.

| # | Signal | What it means | Manifestation in our DB |
|---|---|---|---|
| 1 | Files changed together in commit C | Direct relatedness (co-edit) | `Edge` between docs (`CoEdited`, weight = co-occurrence strength via PMI) |
| 2 | Commit message text | Natural-language intent of the work | `SessionContext.content` for synthetic session |
| 3 | File status (added/modified/removed) | What kind of operation | `EventType::{Cited, Edited, Dismissed}` per `SessionInteraction` |
| 4 | Author identity + email | Subsystem ownership pattern | `agent_id = git:<email>` on synthetic session |
| 5 | Committer time | Recency for time decay | `Session.created_at` |
| 6 | Whether commit reached default branch | Productivity (merged ≈ accepted) | `SessionScore.productivity` (1.0 vs 0.3) |
| 7 | Commit landed on stable / release branch | Higher confidence (vetted) | productivity multiplier ×1.5 |
| 8 | `Reverts: <sha>` in message | Explicit retraction of past work | Negative `productivity` on reverted target; `Reverts` edge between commits |
| 9 | `Fixes: <sha>` / `Fixes: #N` | This commit corrects a past one | `FixedBy` edge; reduces past productivity (was incomplete) |
| 10 | `Cherry-picked from <sha>` | Same change applied in two contexts | `CherryPickedFrom` edge; double-counts the underlying signal |
| 11 | `Co-authored-by: <person>` | Pair work | Multi-author session (multiple agent_ids) |
| 12 | `Signed-off-by:` chain | Review/maintenance trail | Lower signal weight than author; not modeled in v1 |
| 13 | Hunk-level: line X changed A→B then B→A within branch | **Local revert; the change was tried and abandoned** | `dampening_weight` < 1.0 on the file's interaction; `ExploredAndAbandoned` edge to the chunk |
| 14 | Hunk-level: line X changed across N commits over time | "Hot line", load-bearing | metadata flag on chunk: `volatility_score` |
| 15 | Hunk fast oscillation X→Y→X→Y in same branch | Uncertainty / exploration | dampening of the file's edited-weight in that synthetic session |
| 16 | Branch lifetime (fork → merge) | Complexity proxy | metadata on synthetic merge-session |
| 17 | Squash-merge collapsed message | Canonical description (vs WIP intermediates) | use squashed message for `SessionContext`, drop intermediates |
| 18 | File rename detected via `--follow` | Same logical entity | rewrite history: same `external_id`, single Document |
| 19 | Code + test changed together | Productivity boost (test-driven work) | `productivity ×= 1.3` |
| 20 | Code + docs changed together | Thorough work | `productivity ×= 1.15` |
| 21 | Pure refactor (large diff, no test changes, no behavior keywords) | Lower confidence about user intent | `productivity ×= 0.6` |
| 22 | TODO/FIXME line removed | Debt resolution | `Resolves` edge to the TODO chunk; small `productivity` boost |
| 23 | Commit body mentions a `CVE-XXXX-NNNN` | Security severity | metadata flag; rank weight bump in `Pattern::Cited` direction |
| 24 | Tag/release boundary | Stability checkpoint | metadata on commits AT the tag |
| 25 | Bot author (`*[bot]@*`) | Mechanical change | skip entirely (already in doc 10) |
| 26 | Whitespace-only commit | No semantic content | skip (already in doc 10) |
| 27 | Merge commit | Bookkeeping | skip the commit, but use its message if it summarizes a squash (signal 17) |
| 28 | Backport (same diff in stable branch later) | Importance signal | `BackportedTo` edge; productivity boost on original |

This is the full surface. Phase plan below decides what to extract when.

---

## 2. Worked example: the revert-within-branch case

User's example: in a feature branch,

```
commit 1: a.c line 14:  if (x > 0)   →   if (x >= 0)
commit 2: a.c line 14:  if (x >= 0)  →   if (x > 0)    # rolled back
commit N: <merge into main with the original "x > 0" intact>
```

Naïve replay (signal #3 only) emits two `Edited` events on `a.c`,
giving the file a **higher** weight than it deserves. Two events,
neutral pattern → `pattern.multiplier() = 1.0` → no penalty.

The revert-aware path (signal #13):

1. **Hunk-level diff tracking during walk**. For each commit, we
   record the *new* lines it introduced per file, keyed by `(file,
   line_text_normalized, post_state_byte_offset)`.
2. **Within-branch oscillation detection**. As we walk a branch from
   fork to merge, we track per-file an in-memory map
   `last_set_lines: HashMap<Line, NewContent>`. When a later commit
   *changes that same line back* to a previous state seen in the
   same branch, we mark both the original change and the revert as
   "explored-and-abandoned".
3. **Effect on the synthetic session**:
   - The `SessionInteraction` for the branch-merge session **excludes
     the file from the productive set** if every change to it was
     reverted before merge.
   - If only some hunks were reverted, the file gets a
     `dampening_factor = 1 - (reverted_lines / total_lines)`.
4. **Effect on the KG**: emit `ExploredAndAbandoned` edge from the
   synthetic session's `Document` (the merge commit) to the chunks
   that were touched-then-untouched. Future ranker can use this as
   *anti-hint*: "if the user is currently on a similar query and
   considering a similar change, the past session abandoned it —
   don't surface it as a primary suggestion."

This requires:
- The walker to know branch boundaries (fork point, merge commit). We
  derive these via `git merge-base` between the branch tip and the
  default branch.
- An in-process hunk-tracker that lives for the duration of one
  branch-walk.
- Branch identity recorded on the synthetic session
  (`metadata.branch = "feat/foo"`).

Branch boundary detection is its own subproblem — see signal #16
implementation below.

---

## 3. Architecture decisions

### 3.1 Branch-as-session vs commit-as-session

**Decision: support both, prefer branch-as-session for merged feature
branches; fall back to commit-as-session for direct-to-main commits.**

Rationale: a feature branch is *one logical session* — the developer
had one goal, made N commits to reach it, the merge commit is the
canonical summary. Replaying each commit as its own session over-
weights file presence (a file touched in 5 commits during the branch
counts 5×) and *hides* the revert signal (signals #13, #15).

A direct-to-main commit *is* its own session — no branch context.

Detection:
- Walk the default branch (typically `main`/`master`) commit by
  commit.
- For each merge commit M with two parents (P1 = previous mainline,
  P2 = branch tip), the synthetic session is everything reachable
  from P2 not reachable from P1, i.e. `git rev-list P1..P2`.
- For non-merge commits on the default branch, single-commit session.

GitHub's "squash and merge" appears as a single non-merge commit on
the default branch. Heuristic: if the commit message has multiple
paragraphs and references PR numbers, assume squash-merge → still
single-session, but the body contains the full WIP rationale.

### 3.2 Hunk tracker representation

Per file, during a single branch-walk, we keep:

```rust
struct LineState {
    pub current_content: String,
    pub history: Vec<(CommitSha, /* prev_content */ String)>,
    pub revert_count: u32,
}

struct BranchHunkTracker {
    files: AHashMap<PathBuf, AHashMap<u32 /* line */, LineState>>,
}
```

When commit C edits file F line L from A→B:
- If `files[F][L]` exists with `current_content == B` from an earlier
  commit in this branch, this is a revert. Record `revert_count += 1`,
  push current state back into history, set `current_content = A`'s
  predecessor.
- Otherwise, append to history, set `current_content = B`.

After the branch walk, files where every line ended up
`current_content == initial` (i.e., net-zero change) are excluded
from the productive set.

Memory: bounded by `(distinct_lines_touched_in_branch × avg_history)`.
For typical feature branches (10s of commits, 100s of lines) this is
trivial. For massive refactor branches we cap history depth at 8 per
line (drop oldest).

### 3.3 Storage shape

**No schema migration needed.** Everything fits the existing tables:

- `sessions` row per synthetic session, with `agent_id =
  "git:<author_email>"` and a metadata flag distinguishing synthetic
  from real (so we can filter them out in dashboards if needed).
  Add a new `agent_kind TEXT` column? — No: prefix the agent_id with
  `git:` and the predictive ranker already keys on `agent_id` opaquely.
- `session_contexts` carries the commit message body.
- `session_interactions` carries one row per (file, event_type)
  derived from the diff.
- `session_scores` snapshot is computed at session-close, using the
  per-file dampening, productivity multipliers from signals #19/#20/#21,
  and revert deductions.
- `documents` for mode-A: one Document per commit
  (`ContentKind::Commit`), `external_id = "git+sha:<sha>"`.
- New `EdgeKind` variants (no schema change, JSONB column):
  `Reverts`, `FixedBy`, `CherryPickedFrom`, `BackportedTo`,
  `CoEdited`, `ExploredAndAbandoned`, `ChangesFile`, `ChangesSymbol`,
  `Authored`, `Resolves` (for TODO removal).

### 3.4 Idempotency & resync

- Per-commit external_id `git+sha:<full_sha>` makes upsert a no-op
  when the same commit is re-ingested.
- Sync state per source: `last_walked_sha` in `config_json`. Resync
  walks `<last>..HEAD` only.
- Force-pushes / rewritten history: detected by the previously-known
  `HEAD` commit no longer being reachable. Recovery: invalidate the
  branch's synthetic session and re-ingest from the new fork point.
  Phase-2 problem.

### 3.5 Performance budget

For a 50k-commit repo (typical large project, not kernel):
- libgit2 walk: ~30 seconds (mostly diff reads).
- Embedding generation: bottleneck. Commit messages avg ~200 tokens
  → 50k passages → ~25 minutes CPU-only fastembed.
- DB writes: with the batched ingest path, ~10 minutes.
- Total: ~40 minutes initial sync, ~seconds for incremental.

Linux kernel (1.2M commits): scale linearly. Smart default:
phase-0 caps at `--since="2 years ago"` (≈200k commits) and offers a
`--full-history` flag for deeper work.

---

## 4. Phased delivery

### Phase 0 — Foundation (the slice that earns its keep) — ✅ shipped

Ship the minimum that delivers the predictive-channel head start. Skips
all the second-order signals.

**In scope:**
- `crates/engine/src/ingest_git/` module using `git2` crate.
- Walker traverses default branch (configurable), HEAD-newest-first.
- Per non-merge, non-bot, non-whitespace-only commit:
  - Mode A: `Document` with `ContentKind::Commit`, message body
    chunked, `Authored` edge to `External(git:<email>)`.
  - Mode B: synthetic `Session` keyed by author + commit time;
    `SessionContext` = commit message; `SessionInteraction`s per
    `(file, status)`:
      - `added` → `EventType::Cited` weight 1.5
      - `modified` → `EventType::Edited` weight 1.0
      - `removed` → `EventType::Dismissed` weight 1.0
  - File-level edges only (`ChangesFile`).
  - `productivity = 1.0` if commit reached default branch, else 0.3.
- Cap walk at `--since` (default 2 years).
- Idempotency via `git+sha:<sha>` external IDs.

**Out of scope:**
- Symbol-level resolution (Phase 1).
- Branch-as-session aggregation (Phase 1).
- Revert detection (Phase 2).
- All commit-message linkage signals (Fixes:, Reverts:, etc) (Phase 1).

**Success criterion:** running phase-0 against a real repo
produces a `predictive_scores` rank that surfaces commits whose
messages are semantically similar to the live query, with reasonable
target sets.

**Tasks:**
1. `tree-sitter-git` is not a thing — wire `git2 = "0.20"` (libgit2
   binding). Optional engine feature `git`.
2. `IngestGitConfig`, walker, mode-A persistence.
3. Mode-B: synthetic session creation + `snapshot_session_scores`
   per-commit.
4. CLI subcommand on `cae-server`: `cae-engine ingest-git --repo
   PATH --workspace WS --since "2 years ago"`.
5. Integration test against a fixture repo (ship a 20-commit
   tarball under `tests/fixtures/`).

### Phase 1 — Correctness — ✅ shipped

Get the model true to git's actual semantics — renames, branches,
explicit linkages — before adding speculative signals.

**In scope:**
- **Branch-as-session aggregation.** Walk the default branch; for
  each merge commit, replace the chain of intermediate commits with a
  single synthetic session whose `SessionContext` = merge message and
  whose interactions are aggregated over the branch.
- **Squash-merge detection.** Single non-merge commit with multi-
  paragraph message → still single session, body becomes context.
- **File-rename tracking** via `git2::DiffOptions::similarity()`. A
  rename keeps the same Document `external_id` (the file path *as
  of the most recent commit*).
- **Symbol-level diff resolution.** For every diff hunk in a file the
  `CodeAdapter` accepts, find the smallest enclosing symbol via
  tree-sitter, emit `ChangesSymbol` edge.
- **Commit-message linkage parsing:**
  - `Fixes: <sha>` → `FixedBy` edge from new commit to fixed commit.
  - `Fixes: #N` → defer (needs GitHub source for issue ids).
  - `Reverts: <sha>` → `Reverts` edge.
  - `Cherry-picked from <sha>` → `CherryPickedFrom`.
  - `Co-authored-by:` → multi-author session (multiple agent_ids
    via additional rows or comma-separated).

**Tasks:**
6. Branch-as-session aggregator (the merge-base rev-list logic).
7. Squash-merge detection heuristic (multi-paragraph + `#NNN` ref).
8. File-rename tracking — DiffOptions + `external_id` rewrite.
9. Symbol-level diff resolution against `CodeAdapter`'s symbol tree.
10. Commit-message linkage parser + new edge persistence.

### Phase 2 — The revert-aware mode (the user's request)

The bulk of the value-add over naïve replay.

**In scope:**
- **In-branch hunk tracker** (struct `BranchHunkTracker` above).
- **Local revert detection** within branch walks. Files with net-zero
  change are excluded from the productive set; partially-reverted
  files get a `dampening_factor`.
- **Oscillation detection** (signal #15): line X→Y→X→Y within a
  branch → mark file as "exploratory" → `productivity ×= 0.5` for
  that synthetic session.
- **Cross-merge revert detection** (signal #8 outside the same
  branch): commit M reverts a hunk introduced by historical commit C
  on main → emit `Reverts` edge + lower C's productivity for the
  affected target retroactively (re-snapshot the affected synthetic
  session).
- **TODO/FIXME resolution** (signal #22). Diff a deleted line — if
  the line text matches `^.*\b(TODO|FIXME|XXX|HACK)\b.*$`, emit
  `Resolves` edge from the commit's session to the original chunk
  containing the TODO + small productivity boost.
- **`ExploredAndAbandoned` edge** emission for partially-reverted
  files.

**Tasks:**
11. `BranchHunkTracker` impl + unit tests for the revert/oscillation
    detection on synthetic diff sequences (no DB needed).
12. Wire tracker into Phase-1's branch aggregator. Compute net change
    per file before snapshotting scores.
13. Cross-merge revert detection — triggered when a `Reverts: <sha>`
    is parsed; re-snapshot the affected past session.
14. TODO/FIXME tracker.
15. Integration test: known fixture repo with deliberate
    revert/oscillation patterns; assert dampening + edges.

### Phase 3 — Productivity refinement

Refines `productivity` with co-edit-pattern signals. Pure post-
processing; doesn't change ingest mechanics.

**In scope:**
- **Test-edit boost** (signal #19). Detect test files via path
  heuristics (`*_test.rs`, `tests/`, `test_*.py`, `*.spec.ts`) per
  language. If a synthetic session edits both code and tests for the
  *same target subsystem* (= sibling paths), `productivity ×= 1.3`.
- **Docs-edit boost** (signal #20). Detect docs (`*.md` outside of
  `tests/`, files under `docs/`). Code+docs co-edit ⇒ `× 1.15`.
- **Refactor detection** (signal #21). Diff size > N lines, no test
  edits, message lacks behavior keywords (`fix|feat|add|implement`)
  → `× 0.6`.
- **Hot-line / volatility score** (signal #14). Per chunk, count of
  commits that touched this exact symbol over the lookback window.
  Stored in `chunk.metadata.extra.volatility_score`. Future ranker
  weight (out of scope).
- **CVE / security** (signal #23). Regex on commit body; flag in
  metadata; multiplier for `Pattern::Cited` of affected targets.

**Tasks:**
16. Test/docs co-edit detection (per-language path heuristics).
17. Refactor heuristic.
18. Volatility score computation pass over ingested commits.
19. CVE detection.

### Phase 4 — Co-edit strength via PMI

Replaces naïve "files A and B were in 5 commits together" with
proper pointwise mutual information / lift. This is the foundation
for high-quality `CoEdited` edges.

**In scope:**
- After ingest, sweep all synthetic sessions. For every file pair
  `(A, B)` co-edited at least 3 times:
  - `pmi(A, B) = log( P(A ∧ B) / (P(A) × P(B)) )` over sessions.
  - Emit `CoEdited` edge weighted by PMI, only when PMI > threshold
    (filters out random co-occurrence).
- Score the predictive channel against this: PMI-weighted `CoEdited`
  edges feed into the same KG-expansion step we'll use for task #31.
- This is what closes task #31's loop on day zero — co-edit edges
  exist before any live session runs.

**Tasks:**
20. Sweep job to compute PMI over ingested synthetic sessions.
21. Persist `CoEdited` edges with PMI weight.
22. Update predictive channel to optionally consume `CoEdited` edges
    (1-hop expansion from current candidates). Composes with task #31.

---

## 5. Open decisions (need user input before phase 1)

| # | Decision | Default | Reason to overrule |
|---|---|---|---|
| D1 | Default lookback window | 2 years | Short repos: shrink. Kernel-scale: stay 2y; offer `--full` flag for those who want it. |
| D2 | Bot author allowlist | `*[bot]@*`, `noreply@github.com`, named bots | If your repo has a useful bot (e.g. release automation), allowlist its emails. |
| D3 | Default branch detection | `git symbolic-ref refs/remotes/origin/HEAD` | Some repos pin `master` while default is `main` — fall back to first of `[main, master, default, trunk]` that exists. |
| D4 | Whether mode A and mode B are independent | Both run in parallel by default | Mode A is heavier (per-commit Document + embedding). Some users may only want mode B. |
| D5 | Synthetic-session storage marker | `agent_id = "git:<email>"` | If we want hard separation later we can add `Session.kind` enum (`Real | Synthetic`) — defer. |
| D6 | Phase 2's `dampening_factor` formula | `1 - (reverted_lines / total_lines)` clamped to `[0.1, 1.0]` | Empirical — adjust after first benchmark run. |

---

## 6. Risk register

- **Embedding throughput is the binding constraint** for large repos.
  CPU-only fastembed at ~50ms per passage means 200k commits = 2.7h.
  Mitigations: parallelize via `embed_passages` batching (already
  done), GPU when available, smaller embedder model (BGE-small).
- **libgit2 memory footprint** on huge repos. `git2::Revwalk`
  iterators are streaming; the diff materialization isn't. Mitigate
  by processing one commit at a time and dropping the diff promptly.
- **Force-pushes invalidate cached synthetic sessions.** Phase 0
  ignores this. Phase 1 onward needs a re-walk strategy: detect
  missing commits → invalidate downstream sessions → re-ingest.
- **Synthetic sessions could outweigh real ones** in the predictive
  channel. Mitigation: scale synthetic-session productivity down by
  a factor (e.g. 0.7) so real sessions retain higher confidence.
  Tune empirically.
- **Phase-2 hunk tracker correctness** is the trickiest piece of
  this entire plan. Plan: heavy unit testing on synthetic diff
  sequences before wiring to real branches.

---

## 7. Why this plan and not "just ingest commits"

Every phase past 0 is a signal that competitors don't extract. The
defensible position for this engine isn't "we have embeddings" — it's
"we extract every signal from history that the file-level retrieval
crowd ignores." The revert-within-branch detection (signal #13) alone
is something I haven't seen in any commercial RAG-on-code product.
Phases 1–3 stack the moat.

Phase 0 is shippable in a few days; phases 1–4 are 1–2 weeks each.
The kernel benchmark only meaningfully discriminates between
"retrieval-augmented agent" and "bare agent" if at least Phase 2 is
in — without revert-aware replay, the engine surfaces dead-end
exploration as if it were productive, and the benchmark looks worse
than it should.
