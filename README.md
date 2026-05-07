# ken

Per-project context-rank index for [Claude Code](https://claude.com/claude-code).
Local SQLite, local daemon, no network. Indexes your codebase, watches it for
changes, and feeds Claude a ranked `<context-rank>` block on every prompt —
based on what you've been touching this session, what was useful in past
similar sessions, and what looks semantically relevant to the current request.

## Why

Cold-start exploration burns tokens. Without ken, Claude reaches for `Glob` /
`Grep` to figure out which files matter for your task. With ken, the relevant
files are surfaced upfront via embedding similarity + reactive scoring, so
Claude reads them directly instead of grepping around.

Measured on real-world tasks against [BerriAI/litellm](https://github.com/BerriAI/litellm)
(7,772 files, 5,050 of them parsed code) using `claude -p` with opus 4.7:

| Task | Cost (no ken) | Cost (with ken) | Δ | Wall time Δ |
|---|---:|---:|---:|---:|
| Plan an implementation (read-only) | $0.83 | $0.63 | **−24%** | −39% |
| Implement `litellm.estimate_cost` (write) | $1.43 | $0.93 | **−35%** | −33% |

Same prompt, same model, same project state. The win comes from the model
reading fewer files and reusing the cached `<context-rank>` injection across
turns instead of re-grepping.

## Install

ken is a Python CLI installed via `uv tool`:

```fish
uv tool install --from git+https://github.com/Infinibay/ken.git ken
```

Or from a local checkout:

```fish
git clone https://github.com/Infinibay/ken.git
cd ken
uv tool install --from . ken
```

This puts `ken` on your `PATH`. Verify:

```fish
ken --version
```

## Wire it into a project

Run once per project:

```fish
cd my-project
ken install .
```

This:

- Creates `.ken/{meta.json,ken.db}` (the local index + auth token).
- Adds `.ken/` to `.gitignore` (if you have one).
- Writes hooks into `.claude/settings.json` (`UserPromptSubmit`, `PreToolUse`,
  `PostToolUse`, `SessionStart`, `SessionEnd`, `Stop`).
- Registers ken's MCP server in `.mcp.json` (exposes `ken_rank`,
  `ken_search_files`, `ken_search_symbols`, `ken_recall`, `ken_remember`,
  `ken_dismiss`, `ken_explain_rank`).
- Runs the initial code index (parser-only, ~10s for medium projects;
  embeddings are computed lazily by the daemon on first prompt).

Idempotent — re-running on an installed project re-applies the schema (noop),
re-merges hooks (dedup), and incrementally re-indexes (unchanged files
short-circuit on hash).

## Use it

Just open Claude Code in the project:

```fish
cd my-project
claude
```

The hooks fire automatically:

1. **Session start** → ken daemon spawns in the background (logs to
   `.ken/daemon.log`).
2. **Each user prompt** → daemon runs the ranker, prepends a
   `<context-rank verbose=0>` block listing top-relevant files + symbols.
3. **Each tool call** (Read, Edit, etc.) → recorded as a reactive signal so
   the ranker learns what *this* session is touching.
4. **Stop / SessionEnd** → snapshots productivity scores so future similar
   sessions get a predictive boost. Daemon idles down after 10 min.

The model can also call `ken_rank(verbose=1|2)` to expand the block, or
`ken_explain_rank(query)` to debug why a particular file is/isn't surfaced.

### Inspect what's happening

```fish
ken status .                                # daemon + DB summary
tail -f .ken/daemon.log                     # live hook traffic
sqlite3 .ken/ken.db ".tables"               # explore the index
sqlite3 .ken/ken.db "SELECT path FROM ci_files LIMIT 10"
```

### Probe the ranker without claude

```fish
# What would ken inject for this query?
set TOKEN (jq -r .auth_token .ken/meta.json)
set PORT (cat .ken/daemon.port)
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"session_id":"smoke","prompt":"how does cost tracking work"}' \
    http://127.0.0.1:$PORT/sessions/start

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"session_id":"smoke","prompt":"how does cost tracking work"}' \
    http://127.0.0.1:$PORT/prompts | jq -r .context_block
```

## Uninstall

```fish
ken uninstall .              # removes hooks, MCP entry, and the .ken/ index
ken uninstall . --keep-db    # keep .ken/ken.db for later
```

## What's inside

```
src/ken/
  cli.py              # `ken install / serve / status / hook / mcp / uninstall`
  daemon/
    server.py         # HTTP daemon: hooks → DB writes, ranker, MCP backend
    index_queue.py    # Coalesced batch reindex on file changes
    watcher.py        # watchfiles wrapper
    client.py         # Hook-side HTTP client (spawns daemon if needed)
  ranker/
    channels.py       # Reactive, predictive, fuzzy, explicit-mention
    boosts.py         # Freshness, co-occurrence, dismissal penalty
    merge.py          # Per-target dedup + synergy bonus
    output.py         # `<context-rank>` rendering at verbose 0/1/2
    explain.py        # Per-channel breakdown for ken_explain_rank
  parsers/            # Tree-sitter extractors (py, rs, js, ts, go, java)
  embedder/           # ONNX MiniLM-L6-v2 (384d) via fastembed
  indexer.py          # File hashing, parsing, persistence
  mcp/server.py       # MCP stdio server with 7 tools
  hook.py             # `ken hook ...` shim invoked by Claude Code
  schema.sql          # SQLite schema (cr_*, ci_*)
tests/                # 171 tests, ~0.5s suite
```

## Architecture in one paragraph

ken stores everything in a per-project SQLite DB at `.ken/ken.db`. A long-lived
daemon (one process per project, idle-shutdown after 10 min) holds a single
write connection. Claude Code hooks POST events to the daemon over localhost
HTTP with a Bearer token from `.ken/meta.json`. On `UserPromptSubmit` the
daemon runs the ranker — four scoring channels (reactive, predictive, fuzzy,
explicit-mention) merged with synergy-bonus dedup, then post-boosts (freshness,
co-occurrence, dismissal-penalty) — and returns the formatted block via stdout
so Claude Code prepends it to the prompt. Embeddings are MiniLM-L6-v2 384-dim
floats stored as BLOBs; cosine sweeps in numpy run in single-digit ms even at
~50k symbols.

## Status

Phase 6 complete and validated on real projects:

- ✅ Project install + uninstall
- ✅ HTTP daemon with auth + idle shutdown
- ✅ File watcher + incremental reindex
- ✅ Tree-sitter parsers for Python, Rust, JS, TS, Go, Java
- ✅ ONNX embedder (fastembed)
- ✅ Ranker (4 channels + 3 boosts + confidence gate)
- ✅ Verbose-level rendering + per-turn decay
- ✅ MCP server (7 tools)
- ✅ Test suite (171 tests, ranker math fully covered)
- ✅ End-to-end benchmark: 24-35% token cost reduction on realistic tasks

The Rust+Postgres prototype lives at the [`legacy-rust`](https://github.com/Infinibay/ken/tree/legacy-rust) tag.

## License

MIT.
