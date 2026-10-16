# ken

ken is a local context-rank index for coding agents such as [Claude Code](https://claude.com/claude-code) and [Codex CLI](https://developers.openai.com/codex/cli). It indexes each project into a local SQLite database, watches for changes, and gives the assistant a ranked `<context-rank>` block before each prompt so it can start from the most relevant files instead of exploring from scratch.

Everything runs locally: project metadata, embeddings, the daemon, and the SQLite index stay on your machine.

## Why it works

ken is not only a code embedding index. It builds several local signals and ranks files by combining them:

- **Structural code index**: each file is hashed and parsed when possible. The AST parser extracts symbols, line ranges, imports, module docstrings, and symbol docstrings. Files that cannot be parsed are still tracked by path, mtime, and lightweight text intent when useful.
- **Semantic index**: ken embeds files, symbols, and explicit purpose text. File embeddings are based on language, filename, and top symbol names. Symbol embeddings include kind, name, and docstring. Docstrings are also stored as separate intent sources, so a prompt can find code by what it is for, not only by what it is named.
- **Live task memory**: hooks record local interactions in the project SQLite DB: prompts, reads, edits, writes, dismissals, and the files touched in each turn. Recent interactions are weighted more heavily, and useful patterns such as read-then-edit score higher than repeated reads with no follow-through.
- **Predictive memory**: at the end of a session, ken snapshots which files were productive for that task. Later, when a new prompt is semantically similar to a previous one, those files get a predictive boost.
- **Relationship boosts**: after the main channels rank candidates, ken applies conservative boosts for things like recently modified files, symbols pointing to their containing file, source/test counterparts, imports, and files that often co-occurred in past similar sessions.

The result is closer to a local project memory than a plain search tool. Raw text search can find exact strings. Embeddings can find semantic neighbors. AST indexing can find named symbols. ken combines all of that with how the assistant actually used the project over time. That is why results are often better after a few real sessions: the database accumulates project-specific evidence about which files matter for which kinds of tasks.

All of these signals stay local in `.ken/ken.db`. They are not sent to a any server.

## Install the CLI

ken is published on PyPI as [`ken-rank`](https://pypi.org/project/ken-rank/). The
distribution name is `ken-rank`, but it installs the `ken` command. Install it
with `pipx` (recommended, isolates the tool) or `uv`:

```sh
pipx install ken-rank
# or
uv tool install ken-rank
# or
pip install ken-rank
```

Verify the install:

```sh
ken --version
```

The MCP Python SDK is a required runtime dependency and is installed with
`ken-rank`; there is no separate MCP extra to enable. Current releases require
MCP 2.x (`mcp>=2.0,<3`) because the server uses the 2.x `MCPServer` API.

### From a checkout

To install from a local clone (for development or an unreleased build):

```sh
./install.sh
```

The installer uses `uv` to install the `ken` command into your user-local tool
directory. If `uv` is not present, the script bootstraps it with Astral's
official installer unless you pass `--no-bootstrap-uv`. You can also install the
checkout directly with `uv`:

```sh
uv tool install --editable . --force --reinstall --refresh
```

For development, create or refresh the locked environment and run the same
quality checks as CI:

```sh
uv sync --locked --dev
uv run pytest
uv run mypy
```

The mypy gate is incremental: it checks all of `src/ken`, while modules with
known historical annotation debt are listed explicitly in `pyproject.toml` as
temporary per-module overrides. New modules and modules outside that list must
remain clean.

### Troubleshooting MCP startup

If the host assistant (Claude Code, Codex, OpenCode, …) lists the `ken`
MCP server as `failed` or `disconnected` while the project itself looks
fine, the most common cause is a stale install of ken-rank 0.10.0 from
PyPI — that release shipped with the wrong `mcp>=1.0` pin, and depending
on what `mcp` was already on the system, the SDK version that got
resolved could be incompatible with the MCP server. `ken mcp` exits with
a clear remediation message in that case; if you see one, reinstall:

```sh
uv tool install --reinstall ken-rank
# or
pipx reinstall ken-rank
# or
pip install --upgrade --force-reinstall ken-rank
```

Then restart the assistant so it respawns the `ken mcp` process. 0.11.0
and later pin `mcp>=2.0,<3` and refuse to start against older SDKs.

## Install ken in a project

Run this once from the project you want ken to index:

```sh
ken install .
```

By default, ken detects the assistant setup you use and wires itself into the supported local agent config. The install creates `.ken/`, adds it to `.gitignore`, installs hooks/MCP config and problem-oriented skills where applicable, and performs the initial structural code index.

Embeddings are lazy by default. That means `ken install .` does not eagerly embed the whole repository; the daemon warms embeddings as they are needed. This keeps install fast and avoids doing expensive work before the project needs it.

ken also gets better with use. The first run starts from the project index, names, symbols, docstrings, and any available embeddings. As you and the assistant read files, edit code, dismiss weak context, and save findings, ken records those interactions as local ranking signals. Results should improve after real sessions because the system learns which files were useful for similar work in this project.

### Force a target assistant

Use `--claude` when you specifically want Claude Code wiring:

```sh
ken install --claude .
```

Use `--codex` when you specifically want Codex CLI wiring:

```sh
ken install --codex .
```

Use `--opencode` when you specifically want [OpenCode](https://opencode.ai)
wiring — it registers ken as a local MCP server in the project's
`opencode.json` (or `opencode.jsonc`):

```sh
ken install --opencode .
```

For the official [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
(`dsh`), install its project overlay and launch with that overlay:

```sh
ken install --deepseek .
dsh --profile web --patch .dsh/ken.cordis.json
# Or run a task from the CLI:
dsh --profile headless --patch .dsh/ken.cordis.json "Use Ken to locate the storage implementation"
```

DeepSeek requires the explicit `--patch` argument. Ken prints the launch command,
including in quiet mode, and detects `.dsh/` on subsequent installs. The overlay
pins the MCP process to this project and the Python installation that ran
`ken install`. Reinstall after moving the project or replacing that environment.
It composes with existing profile patches; no global Harness profile is edited.

You can pass several when a project uses several assistants:

```sh
ken install --claude --codex .
ken install --claude --opencode .
ken install --codex --opencode .
ken install --claude --codex --opencode .
```

OpenCode and DeepSeek receive MCP tools and skills. Ken does not currently
install native lifecycle hooks for these two hosts: recall, ranking, and
contract checks are available on demand. Automatic context injection and edit
checks require a host hook integration; merely connecting MCP does not run them.

### Skills organized by problem

All eight bundled skills are in English. Each works through a programming
problem: the question, evidence to collect, how to interpret the result, and
what to do when it is ambiguous or incomplete:

| Skill | When to use it |
| --- | --- |
| `ken-locate-code` | Find who implements a behavior or handles an entry point. |
| `ken-investigate-bug` | Connect a failure to its cause, consumers, and tests. |
| `ken-plan-change` | Scope a refactor or migration and compare existing contracts. |
| `ken-understand-architecture` | Explain responsibilities and observed collaboration. |
| `ken-reuse-code` | Find reusable code and a candidate access expression in Python. |
| `ken-find-code-patterns` | Search structural properties and bug signatures with KQL2. |
| `ken-prevent-regressions` | Author and validate an explicit source contract. |
| `ken-resume-work` | Reuse conclusions with their sources, assumptions, and validity. |

The two query-authoring skills include a self-contained KQL2 guide with
executable examples: captures and ownership, filters, correlated absence,
returned values, target identity, reusable patterns, libraries, and graph
hazards. The contract skill includes both witness (`some_match`) and violation
(`no_matches`) examples with cases that expose misleading success.

`ken install` follows the selected/detected hosts: `.claude/skills` for Claude,
`.agents/skills` for Codex, `.opencode/skills` for OpenCode, and `.dsh/skills`
for DeepSeek. OpenCode can reuse Claude/Codex copies; DeepSeek can reuse the
Codex copy. Skills are loaded on demand by the assistant. Installed skill
directories are excluded from Ken's code index and text search so their example
code does not compete with the project implementation.

Reinstall replaces older content under the same eight skill names; it does not
install a second generation alongside them. It updates unchanged Ken-owned
bundles, removes obsolete owned references, and reports local customizations
without overwriting them. Uninstall removes unchanged owned files and preserves
edited bundles and extra user files. Ownership is tracked in
`.ken/installed-skills.json`; existing unowned skills are never adopted.
`ken install --no-wire` skips skills as well as hooks and MCP wiring. Installing
skills does not enable source contracts or automatic checks.

See [installation design and verified host contracts](docs/design/assistant-skills.md)
and the [skill rewrite and validation report](docs/validation/skills-learning-2026-09-22/README.md).

### Eagerly build embeddings

For better first-run semantic ranking, especially on projects where initial context quality matters, force the initial embedding pass:

```sh
ken install --embed .
```

This is recommended when you can afford the extra install time. The cost scales with the repository, and the ceiling is lower than you would expect: the **Linux kernel 7.1-rc2** — 101 084 files walked, 65 907 parsed, 771 563 symbols extracted — indexes in **219 s on a Ryzen 9 8945HS laptop**. On very large projects, cap the eager pass while still structurally indexing the whole repo:

```sh
ken install --embed --embed-limit 5000 .
```

You can combine assistant selection and eager embeddings:

```sh
ken install --codex --embed .
ken install --claude --embed .
```

### Install CLI and wire a project in one step

From a ken checkout, `install.sh` can install the CLI and then run `ken install` for a project:

```sh
./install.sh --project /path/to/my-project
./install.sh --project /path/to/my-project --codex --embed
```

## Search defaults and embedding models

New projects use **`minishlab/potion-code-16M-v2`**, a 256-dimensional static
Model2Vec code embedding (about 32 MB of weights). Normal `search-files`,
`search-symbols` and MCP `ken_find` semantic requests use the complete measured
configuration: static and lexical retrieval, CodeRankEmbed INT8 source context,
local Spanish expansion, numeric owner/piece ranking and Ettin 68M reranking.
Everything runs locally on CPU, without PyTorch or a GPU requirement.

The first semantic request prepares missing public pinned models and source
indexes. To perform setup explicitly before searching:

```sh
ken retrieval prepare --path /path/to/project
ken search-symbols 'Where is a value validated before storage?' --path /path/to/project
ken search-files 'Which module handles configuration?' --piece-kind module --path /path/to/project
```

CLI and MCP return compact text by default: the requested piece, path, source
ranges and numbered code. `--piece-kind class|module|symbol|file` makes the
requested unit explicit; `auto` infers it. `--json` or MCP
`output_format="json"` changes presentation while keeping the same search engine.
See [actual CLI and MCP output examples](docs/validation/compact-output-2026-10-16-best-default/EXAMPLES.md).

Current observations on 200 queries per cohort:

| Cohort | Correct requested piece at top1 | Recall@10 |
| --- | ---: | ---: |
| Exposed development | 191/200 (95.5%) | 197/200 (98.5%) |
| Independent additional queries | 177/200 (88.5%) | 198/200 (99%) |

The independent result **does not meet the 90% goal**. Development tuning continues
and another untouched reserve is required for validation. The cohorts use the
same eight repositories and do not demonstrate new-repository generalization.
The independent prepared CPU run measured p50 2.54 s, p95 3.74 s and peak 1.81 GiB RSS;
model preparation/indexing is separate. Full methodology, per-type results and
receipts are in the [search validation journal](docs/validation/search-engine-top1-2026-10-14/scoring-internals/PUBLIC-DEFAULT-V140-V145.md).

Existing project embedding pins and explicit user choices remain available.
Semantic search prepares its registered passage/context representations separately
so it never compares incompatible vector dimensions. To control the embedding
used by future project indexes, or explicitly reembed an existing index:

```sh
ken default-model
ken default-model --clear
ken default-model BAAI/bge-m3
ken reembed --model minishlab/potion-code-16M-v2
```

### Optional model backends and accelerators

The complete measured search pipeline currently uses CPU execution. Automatic
selection of a validated faster accelerator for that pipeline is still pending.
The dynamic Ettin graph failed a source-free CoreML compilation probe on this Mac;
no CoreML speedup is claimed.

Explicit fastembed and sentence-transformers index backends retain their existing
GPU detection and CPU fallback. `ken-rank[gpu]` supports compatible CUDA/ROCm ONNX
installations on Linux/Windows; `ken-rank[torch]` supports CUDA or Apple Silicon
MPS. These optional backends do not change the measured complete search profile.
Their device control is `KEN_EMBED_DEVICE=auto|cpu|gpu|cuda|mps`.

Earlier static-Qwen, multilingual and heavy-transformer comparisons are preserved
in [historical embedding controls](docs/validation/embedding-history-before-best-default.md).
Their metrics use different tasks and cannot be compared directly with the
requested-piece benchmark above.

## Where the vectors live

Since 0.9.0 the vectors are **not** in `ken.db`. They live in `.ken/vectors/` as memory-mapped, fixed-size segment files, and each row in SQLite carries a `vec_slot` pointing at one. The relational half — paths, symbols, imports, sessions, findings — stays where it was.

This is not cosmetic. On a Linux 7.1-rc2 index (101 083 files, 771 563 symbols), `ken rank` took **21.3 s**, of which the actual arithmetic was 0.138 s. The rest was deserialising 771 563 Python row objects and 2.9 GB of blobs to feed one matrix-vector product. Mapping them instead:

| | before | after |
| --- | --- | --- |
| `ken rank`, end to end | 21.3 s | **1.82 s** |
| fuzzy channel | 20.4 s | 0.374 s |
| lexical channel | 22.6 s | 0.126 s |
| `ken.db` | 4.10 GB | **214 MB** |

Ranked output is unchanged: top-k overlap 1.000 across a 12-query set, with scores drifting 5.1e-03 on ~7 from float32 rounding.

Worth saying plainly, because the obvious suspect was wrong: **SQLite was never the bottleneck.** Measured over the same 2.9 GB, it handed over the vector column at 906 MB/s against 1.5 GB/s for a raw flat file — within 1.7×. Swapping the database engine would have bought 3%.

### Migrating an existing project

An index built before 0.9.0 keeps working untouched — every read falls back to the inline column for rows without a slot, so it is correct, just slow. Convert it when convenient:

```sh
ken vectors migrate      # move the vectors out, then VACUUM the freed pages
ken vectors verify       # expect 0 leaked / 0 out-of-range / 0 double-booked
```

Stop the daemon first (`ken serve --stop`): the migration takes SQLite's write lock in batches, and a running daemon can hit its 5 s busy timeout. It is idempotent and resumable — an interrupted run leaves a partly-converted index that still answers correctly, and re-running finishes it.

`ken install --embed .` and `ken reembed` also migrate, so if you were going to run either anyway there is nothing extra to do.

Timing: 2 m 21 s for the kernel's 872 000 vectors. A normal project is seconds.

### The rest of `ken vectors`

```sh
ken vectors              # sizes and how many vectors are still inline
ken vectors verify       # cross-check slots against rows
ken vectors compact      # renumber live vectors densely, reclaim leaked slots
```

`compact` is for maintenance, not migration: it rebuilds the store into a dense prefix and drops the tail, reclaiming slots stranded by a crash between a vector's write and its commit. `verify` tells you whether there are any — usually zero.

Segment files are preallocated and sparse, so a space holding a few thousand vectors reports 256 MB of apparent size against ~17 MB of real blocks; `ken vectors` reports the blocks.

## Tell the assistant to use ken

ken works through hooks automatically, but assistants behave better when your project instructions tell them *when* to reach for ken and, just as importantly, to write back what they learn. The MCP server already describes all six tools to the assistant, so the block below deliberately carries only what a tool description cannot: where to start, when to stop, and what to record. Add it to the agent instruction file for the tool you use: `AGENTS.md` for Codex, `CLAUDE.md` for Claude Code, or both. OpenCode reads the same `AGENTS.md` from the project root.

```md
## Code intelligence: ken

**A `<context-rank>` block in the prompt is ken's ranked guess for this
request**: `Files:` best first, then `Symbols:`, then `Notes:` — finding
*topics*, which `ken_recall(topic="…")` reads. If it names what you need,
open that and skip searching. If a listed file turns out to be irrelevant,
`ken_remember(path, action="dismiss", reason=…)` — the ranker's only
negative signal, and only while the block is still in front of you. Thin or
missing? `ken_rank(verbose=2)`, or `ken_find(task, scope="intent")` for the
files that work like this one actually landed in.

**Start with one `ken_find`, not with `rg` or a guessed path.** The scope is
the whole decision:

- an exact string or identifier (`MY_ENV_VAR`, `os.path`) → `scope="text", literal=true`
- which file does X → `scope="files"`
- which function or class does X → `scope="symbols"`
- how a route, CLI command or env var reaches its handler → `scope="wiring"`

Then read what it named — `ken_read(path)` for the outline, plus
`include=["source"]` and a *qualname* for one symbol's body. ken narrows
where to look; it does not replace reading the code.

**Stop rules.** If two ken calls have not narrowed it, open the likeliest
file and read — a third will not help. If ken returns nothing, use `rg`: it
searches the index, so a file created minutes ago may not be in it yet. A
question you can already answer from context needs no call at all.

**Before editing a file you have not read this session**, `ken_recall(path=…)`
— what earlier sessions learned there. If the change is not local:
`ken_related(path, relation="blast_radius")` for what it breaks,
`relation="cochange"` for what moves with it that imports do not show, and
`ken_find(path, scope="tests")` for its tests.

**Write back what cost you real effort** — a root cause, a constraint the
code does not state, a trap you fell into: `ken_remember(topic, content)`.
Not what the code already says plainly. Re-using a topic overwrites it.

**Anchor it, or it only fires if someone searches.** An anchored memory is
handed to whoever next touches the same thing — no query needed:
`ken_remember(topic, content, anchor_file="src/db/service.py")`, or
`anchor_symbol` for one function, `anchor_tool="pytest"` for a command,
`anchor_error="database is locked"` for a message (matched as a substring of
whatever the tool reports). Set as many as apply; the memory fires on any.
```

The shell commands (`ken rank`, `ken search-files`, `ken search-symbols`, and `ken explain`) expose the same ideas for humans or agents without MCP, and `ken tools <name>` runs any MCP tool directly (see [Run MCP tools from the shell](#run-mcp-tools-from-the-shell)). For assistants with MCP available, the MCP tools are the preferred path because they return compact, actionable text by default and feed ken's local task memory. Use `output_format="json"` for native structured results.

## Use ken directly

The hooks run automatically when the assistant is active, but the CLI is useful for checking what ken sees:

```sh
ken status .
ken rank "where is codex install wiring handled"
ken rank --verbose 2 "how does predictive ranking work"
ken explain "why did src/ken/cli.py appear"
ken search-files "semantic file retrieval"
ken search-symbols "merge codex hooks"
```

You can save and recall project-specific findings:

```sh
ken remember "codex wiring" "Use ken install --codex . to repair invalid hooks."
ken recall "codex hook repair"
```

Findings can also carry a justification, evidence files and file/tree dependencies
through `ken_remember(..., justification={...})` or `ken tools remember`.
The existing session and prompt hooks surface compact dependency validity, and
`ken_recall(topic="…", detail="answer", max_chars=1800)` starts with a whole
conclusion, source references, assumptions and input validity. Expand with
`detail="full"` or read the relevant symbol when evidence is missing or stale;
`summary` adds a short rationale. See
[justified programming memory](docs/design/justified-memory.md) for the contract,
examples and limits. Unchanged dependencies do not establish that a conclusion
is true or that its assumptions still apply.

## Run MCP tools from the shell

Every tool the ken MCP server exposes is also runnable directly with `ken tools`, so you can use the structured code-intelligence tools (call graph, blast radius, co-change, wiring, clones, …) without an assistant in the loop. The list, descriptions, and parameters are read live from the same MCP surface, so `ken tools` never drifts from what the agent sees.

```sh
ken tools                                       # list every tool with a one-line summary
ken tools find --help                           # show one tool's parameters
ken tools find "MY_ENV_VAR" --scope text --literal   # required params are positional, options are --flags
ken tools related src/ken/cli.py blast_radius
ken tools read src/ken/search.py --include symbols imports
ken tools who "Who stores reusable findings?" --path src/ken
```

The tool name may be given with or without the `ken_` prefix (`find` or `ken_find`). Required parameters are positional in schema order — `ken_related` takes `target` then `relation`. Results print as compact text with locations and numbered source by default. `ken tools --json read ...` or `--output-format json` after the tool name requests native JSON. The older global `--compact` keeps its single-line JSON meaning. `--path /repo` before the tool name selects another checkout. See [all output examples](docs/validation/compact-output-2026-10-16/EXAMPLES.md).

`ken_who` answers responsibility questions with ranked symbol hypotheses, current
documentation, evidence from names and call expressions, and explicit assumptions.
Its confidence score is a heuristic, not a calibrated probability. Optional
`--hypotheses "Store reusable findings"` supplies an alternative formulation,
useful when the question and documentation use different terminology or languages.
See [responsibility questions and confidence](docs/design/responsibility.md).

`ken_rule` registers KQL2 source contracts with passing/failing examples;
`ken_check` validates the current code, keeps evidence receipts, and compares
regressions or resolutions. `ken_related(..., relation="checks")` finds applicable
contracts; `ken_remember(..., check_run="...")` binds a memory to a check.
Validated rules can opt into bounded background edit checks through Ken's
existing hooks. See [source contracts, MCP/CLI examples and limits](docs/design/source-contract-tools.md).

`ken_related` also exposes `impact` (result consumers and related tests), `roles`
(call chains and structural role hypotheses), and `available` (explicit Python
access expressions with outstanding compatibility obligations). For example:

```sh
ken tools related 'src/ken/checks/report.py::query_view' impact --path src/ken/checks --depth 3
```

Inspections follow explicit imports; same-named functions in unrelated files do
not establish a dependency. Memories retain per-rule freshness, including imported
dependencies. Compact recall preserves whole conclusions or offers an explicit
expansion when the character budget is too small. See [program inspection and
coding workflows](docs/design/code-inspection.md).

File-path arguments handled by these tools are confined to that selected
project root. Relative paths are resolved from the root; absolute paths are
accepted only when they remain inside it. Traversal such as `../outside.py` and
symbolic links that resolve outside the project are rejected. This applies to
the shared tool surface used by both MCP clients and `ken tools`.

## Codex hook setup

After `ken install --codex .`, start Codex in the project and run `/hooks` to enable the project hooks. Codex only loads project-local hooks after the project is trusted, so also approve the trust prompt when Codex asks.

You can mark the project as trusted manually in `~/.codex/config.toml`:

```toml
[projects."/abs/path/to/my-project"]
trust_level = "trusted"
```

## OpenCode setup

After `ken install --opencode .`, OpenCode picks up the `ken` MCP server automatically the next time it starts in the project — no extra step on your side. OpenCode reads `opencode.json` / `opencode.jsonc` straight from the project root and merges `ken`'s block with whatever you already have (model, providers, commands, sibling MCP servers, all preserved). Run `opencode mcp list` to confirm the server is registered.

If you wired multiple assistants into the same project, the OpenCode MCP entry lives alongside the Claude and Codex hooks with no interaction between them.

## Uninstall

```sh
ken uninstall .
ken uninstall --keep-db .
```

`ken uninstall .` removes hooks, MCP entries, and the local `.ken/` index. Use `--keep-db` if you want to keep `.ken/ken.db` for later.

## License

ken is released under the MIT License. See [LICENSE](LICENSE).

## Structural code analysis

Ken can query a tree-sitter IR graph, scan 23 GoF pattern signatures, summarize
patterns by directory, and check a catalogue of source-level bug signatures:

```sh
ken structural patterns --path .
ken structural bugs --path .
ken structural search --path . --query-file search.kenq
ken structural catalog
```

Queries support typed selectors, regex, named roles, graph paths, cardinalities,
variants and evidence-based ranking. Results distinguish structural matches,
missing semantic evidence and exhausted query budgets. The content-addressed
cache defaults to 500 MB; use `--cache-mb 0` to disable it. MCP clients use
`ken_find` with `scope="structure"`, `"patterns"` or `"bugs"`.

See [the current query guide](docs/structural-queries.md) for syntax, examples,
language coverage, precision limits, cache configuration and tests. All 23 GoF
concepts have canonical queries tested against Python, Java and TypeScript source;
[the coverage matrix](docs/gof-coverage.md) distinguishes executable variants from
planned ones. Matches remain structural candidates, not proof of design intent.

Structural searches support [KenQL and named queries](docs/structural-queries.md),
with [declarative pattern files](src/ken/structural/patterns).
