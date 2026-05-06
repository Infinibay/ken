# ken

> *Goes beyond your ken* — the memory layer your coding agent didn't have.

`ken` is a Rust engine that pre-populates context for coding agents (Claude
Code, etc.) so they don't start every turn from a blank slate. It indexes your
code, docs, PDFs, web pages, and git history into a Postgres + pgvector +
knowledge graph store, then exposes that store as MCP tools the agent can call:
semantic search, symbol lookup, file ranking, structural file maps, git
history, and more. As you work, the engine learns from session behavior
(co-access, productivity patterns) so future retrievals are sharper.

Status: alpha, single-developer use today.

---

## Table of contents

- [Quick start](#quick-start)
- [1. Build](#1-build)
- [2. Install](#2-install)
- [3. Run the server](#3-run-the-server-ken-serve---with-pg)
- [4. Wire a project into Claude Code](#4-wire-a-project-into-claude-code-ken-install)
- [5. Use it inside Claude Code](#5-use-it-inside-claude-code)
- [Re-indexing](#re-indexing)
- [Troubleshooting](#troubleshooting)
- [Architecture & design docs](#architecture--design-docs)

---

## Quick start

```bash
# clone + install (~3 min on a fresh box; pulls Rust deps + builds release)
git clone https://github.com/Infinibay/ken.git && cd ken
./install.sh

# start the server with the bundled Postgres (docker or podman required)
ken serve --with-pg

# wire your project (in another terminal)
cd /path/to/your/project
ken install --workspace my-project
ken ingest-codebase --root . --workspace my-project
ken ingest-git --repo . --workspace my-project

# restart Claude Code in that directory; the new MCP tools (`query_context`,
# `list_files`, `search_symbols`, `list_symbols`, `git_history`, `ingest_file`,
# `ingest_url`) are now available.
```

Each subsequent project gets a **new workspace id** for isolation — see
[§4](#4-wire-a-project-into-claude-code-ken-install).

---

## 1. Build

Requires Rust via [rustup](https://rustup.rs) and a C toolchain
(`build-essential` / `base-devel` — needed by `ort` / onnxruntime that
fastembed pulls in). Postgres and Docker/Podman are runtime deps, not build
deps.

```bash
./build.sh
# → target/release/ken (~45 MB)
```

The script wraps `cargo build --release -p ken` with the default features
(`postgres`, `fastembed`, `code`, `pdf`, `git`). Use it from a fresh shell on
any machine — it sources `~/.cargo/env` if `cargo` isn't on `PATH` yet.

---

## 2. Install

```bash
./install.sh
```

What it does:

- Runs `cargo install --path crates/ken --force`, which puts the binary at
  `~/.cargo/bin/ken`. **No `sudo`** — everything stays under your user.
- Removes any stale binaries from earlier project names (`cae-claude`,
  `context-engine`).
- Verifies `ken` is on `PATH`; if not, prints the right line for your shell
  (fish / bash / zsh).

If you don't have `~/.cargo/bin` on `PATH`, add it once:

```fish
# fish
set -gx PATH $HOME/.cargo/bin $PATH
```
```bash
# bash / zsh
echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.bashrc   # or ~/.zshrc
```

---

## 3. Run the server (`ken serve --with-pg`)

```bash
ken serve --with-pg
```

`--with-pg` makes `ken` auto-manage the Postgres container for you:

- Detects `docker` (or `podman` as fallback).
- If a container named `cae-postgres` doesn't exist, creates it from
  `pgvector/pgvector:pg16` with the bundled credentials and a named volume
  (`cae-pg-data`) so data survives restarts.
- If it exists but is stopped, starts it.
- If it's already running, leaves it alone.
- Polls the healthcheck (`pg_isready`) for up to 60s, then connects.
- If `DATABASE_URL` isn't set, defaults to
  `postgres://cae:cae_dev@localhost:5432/context_engine` — matching the
  bundled container.

The server listens on `0.0.0.0:8080` by default. Override with `BIND=…`.

### Without `--with-pg`

If you'd rather manage Postgres yourself:

```bash
docker-compose up -d            # one-time
export DATABASE_URL=postgres://cae:cae_dev@localhost:5432/context_engine
ken serve
```

The repo ships a `docker-compose.yml` using the same container name +
volume, so you can mix both approaches without losing data.

---

## 4. Wire a project into Claude Code (`ken install`)

`ken` doesn't auto-detect projects — you opt each one in explicitly. The unit
of isolation is a **workspace**: every query (semantic search, symbol lookup,
git history…) is filtered by `workspace_id` at the SQL level, so projects in
different workspaces never bleed into each other's results.

### Why workspaces matter

The DB can hold many projects. If you run `ken install --workspace foo` in
project A *and* project B, both share workspace `foo` → MCP queries return
mixed results from both. **Use a different workspace name (or id) per
project.**

`--workspace VALUE` accepts either a numeric id (`--workspace 1`) or a name
(`--workspace my-project`). Names are find-or-created automatically under a
shared tenant (`"local"`), so you don't need to manually create the
workspace via HTTP first — the first `ken install` (or any `ken ingest-*`)
that references the name will mint it.

If you prefer explicit creation (e.g. for a non-default tenant), the HTTP
routes are still available:

```bash
TENANT_ID=$(curl -s -XPOST http://localhost:8080/tenants \
  -H 'Content-Type: application/json' \
  -d '{"name":"andres"}' | jq -r .id)
WS_ID=$(curl -s -XPOST http://localhost:8080/workspaces \
  -H 'Content-Type: application/json' \
  -d "{\"tenant_id\":\"$TENANT_ID\",\"name\":\"my-project\"}" | jq -r .id)
```

### Install the hooks

```bash
cd /path/to/your/project
ken install --workspace my-project
```

This writes two files under `<project>/.claude/`:

- **`ken-state.json`** — a sentinel with `workspace_id`, a freshly-minted
  `session_id`, and the engine URL. Hooks and the MCP read this on every
  invocation so they know which workspace to talk to.
- **`settings.local.json`** — Claude Code config. Adds:
  - **PostToolUse hooks** for `Edit | Write | MultiEdit | Read`, so every
    file the agent touches becomes a `/events` interaction the ranker uses to
    boost related chunks in the next query.
  - **An `mcpServers.ken` entry** pointing at this binary so Claude Code
    spawns `ken mcp` over stdio when you open the project.

Re-running `ken install` is idempotent — it overwrites the prior entries for
its own matchers and leaves any other hooks/MCP servers in your settings
untouched.

### First-time index

Hooks fire on **future** edits/reads but the KG starts empty. Seed it with
the codebase + git history:

```bash
ken ingest-codebase --root . --workspace my-project
ken ingest-git --repo . --workspace my-project
```

`ingest-codebase` walks the working tree (respecting `.gitignore`), picks the
right adapter per file (Rust / Python / TS / Go / Java / C / C++ / Ruby /
Markdown / HTML / PDF / plain text), chunks intelligently (per-symbol for
code, per-section for docs, per-page for PDFs), embeds, and stores.
`ingest-git` walks commit history, recording who changed which files / which
symbols (via tree-sitter on each commit) so the agent can answer "who last
touched `User::validate`?".

Both are idempotent (content-hash skip): re-run anytime to pick up new files
without re-embedding unchanged ones.

---

## 5. Use it inside Claude Code

Restart Claude Code in the project directory. The `ken` MCP server is
auto-spawned on first use. The agent now has these tools:

| Tool | What it does | When the agent picks it |
|------|--------------|-------------------------|
| `query_context` | Semantic search across all indexed content. Returns ranked citations with `path:line` + qualified name. | "find me JWT validation middleware", "where do we handle vowels in linting" |
| `list_files` | Files ranked by relevance to a query (concentration of relevant chunks). | "which files implement the linter?" |
| `search_symbols` | Substring + last-segment match on qualified symbol names. | "jump to `validate`", "find `AnA::*`" |
| `list_symbols` | Structural map of one file (functions, methods, classes) with optional docstrings. | Cheaper than `Read` for orientation. |
| `git_history` | Commits that touched a file or symbol. | "what's the recent churn around `User::validate`?" |
| `ingest_file` | Index a file (base64 bytes) into the workspace's KG mid-session. | User drops a PDF or doc and says "use this for context." |
| `ingest_url` | Fetch + index a URL (single page or shallow crawl, capped). | "go read the React docs on memo, then answer." |

The reactive ranker also runs continuously: every time you `Read` or `Edit` a
file, the hook fires a `/events` interaction that boosts that chunk's
co-occurrences in the next `query_context` call. Over time, repeated
co-access between two resources earns a `CoAccessed` edge in the KG
(producer-only today; future ranker versions will use it for 1-hop
expansion).

---

## Re-indexing

You don't need to re-install hooks or rebuild — just re-run the ingest verbs.
They're content-hash idempotent: unchanged files / unchanged commits are
skipped on the storage side.

```bash
cd /path/to/project
ken ingest-codebase --root . --workspace my-project
ken ingest-git --repo . --workspace my-project
```

Add new sources (PDFs, web pages):

```bash
ken ingest-file --path ./design-doc.pdf --workspace my-project
ken ingest-url --url https://docs.example.com --workspace my-project --depth 1 --max-pages 10
```

Or let the agent do it via `ingest_file` / `ingest_url` MCP tools.

---

## Troubleshooting

**`DATABASE_URL is required`** — pass `--with-pg` or set the env var.

**`--with-pg` fails: neither docker nor podman found** — install one. On
Arch / CachyOS: `pacman -S podman podman-compose`. On Ubuntu:
`apt install docker.io docker-compose-plugin`. Both rootless work.

**Port 8080 already taken** — set `BIND=127.0.0.1:9000 ken serve --with-pg`.
The MCP / hook clients pick up the engine URL from `.claude/ken-state.json`
written by `ken install --engine-url http://127.0.0.1:9000 …`.

**Mixed results from multiple projects** — they share the same workspace.
Pass a different name to `ken install --workspace OTHER_NAME` in the
second project (it'll be auto-created on first reference).

**MCP not appearing in Claude Code** — restart Claude Code in the project
dir; it reads `.claude/settings.local.json` at startup. `cat
.claude/settings.local.json` should show `mcpServers.ken`.

**Hook activity log** — `tail -f /tmp/ken-mcp.log` to see every MCP tool call
the agent issues, with arguments and result counts.

---

## Architecture & design docs

Deep dives in [`docs/`](./docs/):

- [00 — Vision](./docs/00-vision.md)
- [01 — Architecture](./docs/01-architecture.md) — adapter pattern, ranking pipeline
- [02 — Data model](./docs/02-data-model.md) — Document/Chunk/Entity/Edge schema
- [03 — Ranking](./docs/03-ranking.md) — reactive / predictive / semantic channels, alpha blending
- [04 — Storage](./docs/04-storage.md) — Postgres + pgvector decisions
- [05 — Roadmap](./docs/05-roadmap.md)
- [06 — Decisions](./docs/06-decisions.md) — ADR-style log
- [10 — Git history](./docs/10-git-history.md) — synthetic sessions from commits
- [11 — Git history plan](./docs/11-git-history-plan.md) — phase-by-phase

License: Apache-2.0.
