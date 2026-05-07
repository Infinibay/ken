# ken

Per-project context-rank index for [Claude Code](https://claude.com/claude-code)
and [Codex CLI](https://developers.openai.com/codex/cli). Local SQLite, local
daemon, no network. Indexes your codebase, watches it for changes, and feeds
the model a ranked `<context-rank>` block on every prompt — based on what
you've been touching this session, what was useful in past similar sessions,
and what looks semantically relevant to the current request.
Saved findings from `ken remember` / `ken_remember` can also appear in the
ranked block when they match the current prompt.

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
./install.sh
```

This puts `ken` on your `PATH`. Verify:

```fish
ken --version
```

If you already have `uv` and prefer the direct command:

```fish
uv tool install --from . ken --force
```

## Wire it into a project

Run once per project:

```fish
cd my-project
ken install .
```

`ken install .` wires Claude Code and Codex CLI by default. `--claude`
exists as an explicit no-op-for-now flag for symmetry with `--codex`:

```fish
ken install . --claude
ken install . --codex
ken install . --claude --codex
```

If a project already has a locked-down `.codex/` directory or an invalid
`.codex/hooks.json`, rerun with `ken install . --codex` to force Codex hook
and MCP config wiring while still preserving valid existing user entries.
By default install does structural indexing and leaves embeddings to the
daemon's lazy warm path. For large cold-start experiments where semantic
ranking quality matters immediately, run `ken install . --embed` (or
`ken install . --claude --codex --embed`) to compute file and symbol embeddings
up front.

On very large repos, eager full-repo embedding can take a long time. Use
`--embed-limit N` to eagerly embed only the N highest-priority source files
while still structurally indexing the whole project:

```fish
ken install . --embed --embed-limit 5000
```

This:

- Creates `.ken/{meta.json,ken.db}` (the local index + auth token).
- Adds `.ken/` to `.gitignore` (if you have one).
- Writes hooks into `.claude/settings.json` (Claude Code) and
  `.codex/hooks.json` (Codex CLI), covering `UserPromptSubmit`,
  `PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`, and
  `SessionEnd` (Claude only — Codex relies on the daemon's idle timeout).
- Registers ken's MCP server in `.mcp.json` (Claude Code) and
  `.codex/config.toml` (Codex CLI). Exposes `ken_rank`,
  `ken_search_files`, `ken_search_symbols`, `ken_recall`, `ken_remember`,
  `ken_dismiss`, `ken_explain_rank`.
- Runs the initial code index. Embeddings are lazy by default, or eager
  when `--embed` is passed.

**Codex trust note**: Codex won't load project-local hooks until you
mark the project as trusted. Either run `codex` once in the project
and approve the prompt, or add this to `~/.codex/config.toml`:

```toml
[projects."/abs/path/to/my-project"]
trust_level = "trusted"
```

Idempotent — re-running on an installed project re-applies the schema (noop),
re-merges hooks (dedup), and incrementally re-indexes (unchanged files
short-circuit on hash).

## Use it

Open either CLI in the project:

```fish
cd my-project
claude       # Claude Code
# or
codex        # Codex CLI
```

The hooks fire automatically:

1. **Session start** → ken daemon spawns in the background (logs to
   `.ken/daemon.log`).
2. **Each user prompt** → daemon runs the ranker, prepends a compact
   `<context-rank>` block listing top-relevant files, symbols,
   docstring-derived intent matches, and matching saved findings.
3. **Each tool call** (Read, Edit, etc.) → recorded as a reactive signal so
   the ranker learns what *this* session is touching.
4. **Stop / SessionEnd** → snapshots productivity scores so future similar
   sessions get a predictive boost. Daemon idles down after 10 min.

The model can also call `ken_rank(verbose=1|2)` to expand the block, or
`ken_explain_rank(query)` to debug why a particular file is/isn't surfaced.

You can ask the daemon directly from a shell too:

```fish
ken rank "where is codex install wiring handled"
ken rank --verbose 2 "how does predictive ranking work"
ken rank --max-chars 1200 "give me only the strongest hints"
ken rank --stats "how much context would this add"
ken explain "why did src/ken/cli.py appear"
ken search-files "semantic file retrieval"
ken search-symbols "merge codex hooks"
ken bench .ken/bench.jsonl
ken bench examples/bench/ken-dogfood.jsonl --fail-under-case-recall 0.7
ken remember "codex wiring" "Use ken install . --codex to repair invalid hooks."
ken recall "codex hook repair"
```

Benchmark datasets are JSONL, one prompt per line:

```json
{"prompt":"fix src/ken/status.py diagnostics","expected_files":["src/ken/status.py","tests/test_status.py"]}
```

`ken bench` reports recall@N and average injected context size, so ranker
changes can be judged against labeled prompts instead of intuition alone. Add
`--fail-under-case-recall 0.8` or `--fail-under-expected-file-recall 0.7` to
make the benchmark a CI gate.

### Inspect what's happening

```fish
ken status .                                # daemon + DB summary
ken status --json                          # same health report for agents/scripts
tail -f .ken/daemon.log                     # live hook traffic
sqlite3 .ken/ken.db ".tables"               # explore the index
sqlite3 .ken/ken.db "SELECT path FROM ci_files LIMIT 10"
```

`ken status` also reports embedding coverage and stale indexed files. If a repo
was installed with `--embed-limit` or warmed lazily, partial coverage is
expected; the status recommendation tells you when to warm more files for better
semantic recall. If files disappeared after a branch switch, status recommends a
resync before stale paths can pollute ranker context.

### Probe the ranker without hooks

```fish
# What would ken inject for this query?
ken rank "how does cost tracking work"

# Why did those files win?
ken explain "how does cost tracking work"
```

## Uninstall

```fish
ken uninstall .              # removes hooks, MCP entry, and the .ken/ index
ken uninstall . --keep-db    # keep .ken/ken.db for later
```

## What's inside

```
src/ken/
  cli.py              # `ken install / rank / explain / search-* / remember / recall / serve / status / hook / mcp / uninstall`
  daemon/
    server.py         # HTTP daemon: hooks → DB writes, ranker, MCP backend
    index_queue.py    # Coalesced batch reindex on file changes
    watcher.py        # watchfiles wrapper
    client.py         # Hook-side HTTP client (spawns daemon if needed)
  ranker/
    channels.py       # Reactive, predictive, fuzzy, doc-intent, lexical, explicit, findings
    boosts.py         # Freshness, co-occurrence, symbol-file/test/import affinity, dismissal penalty
    merge.py          # Per-target dedup + synergy bonus
    output.py         # `<context-rank>` rendering at verbose 0/1/2
    explain.py        # Per-channel breakdown for ken_explain_rank
  parsers/            # Tree-sitter extractors (py, rs, js, ts, go, java)
  embedder/           # ONNX MiniLM-L6-v2 (384d) via fastembed
  indexer.py          # File hashing, parsing, persistence
  mcp/server.py       # MCP stdio server with 7 tools
  hook.py             # `ken hook ...` shim invoked by Claude Code / Codex
  hooks_template.py   # `.claude/settings.json` merge logic
  codex_hooks_template.py  # `.codex/hooks.json` + `[mcp_servers.ken]` merge
  schema.sql          # SQLite schema (cr_*, ci_*)
tests/                # 291 tests, ~0.8s suite
```

## Architecture in one paragraph

ken stores everything in a per-project SQLite DB at `.ken/ken.db`. A long-lived
daemon (one process per project, idle-shutdown after 10 min) holds a single
write connection. Claude Code hooks POST events to the daemon over localhost
HTTP with a Bearer token from `.ken/meta.json`. On `UserPromptSubmit` the
daemon runs the ranker — reactive, predictive, fuzzy, doc-intent, lexical,
traceback/explicit-mention, and finding channels merged with synergy-bonus
dedup, then post-boosts (symbol-file affinity, freshness, co-occurrence,
source/test/import-affinity, dismissal-penalty) — and returns the formatted
block via stdout so Claude Code prepends it to the prompt. Doc-intent stores
module and symbol docstrings as separate purpose embeddings, so a prompt can
find files by what they are for, not only by names or content. Embeddings are
MiniLM-L6-v2 384-dim
floats stored as BLOBs; cosine sweeps in numpy run in single-digit ms even at
~50k symbols.

## Status

Phase 6 complete and validated on real projects:

- ✅ Project install + uninstall
- ✅ HTTP daemon with auth + idle shutdown
- ✅ File watcher + incremental reindex
- ✅ Parsers for Python, Rust, JS, TS, Go, Java, and C/C headers
- ✅ ONNX embedder (fastembed)
- ✅ Ranker (files, symbols, doc-intent, findings + 6 boosts + confidence gate)
- ✅ Verbose-level rendering + hook context budget/stats + per-turn decay
- ✅ Status diagnostics/JSON with recommendations for embedding coverage, findings, scores, daemon health
- ✅ MCP server (7 tools)
- ✅ Claude Code + Codex CLI integration (hooks + MCP)
- ✅ Test suite (run `uv run pytest`; ranker math + agent install/template fully covered)
- ✅ End-to-end benchmark: 24-35% token cost reduction on realistic tasks

The Rust+Postgres prototype lives at the [`legacy-rust`](https://github.com/Infinibay/ken/tree/legacy-rust) tag.

## License

MIT.
