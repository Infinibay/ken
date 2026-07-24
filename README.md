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

## Install ken in a project

Run this once from the project you want ken to index:

```sh
ken install .
```

By default, ken detects the assistant setup you use and wires itself into the supported local agent config. The install creates `.ken/`, adds it to `.gitignore`, installs hooks/MCP config where applicable, and performs the initial structural code index.

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

You can pass both when a project uses both assistants:

```sh
ken install --claude --codex .
```

### Eagerly build embeddings

For better first-run semantic ranking, especially on projects where initial context quality matters, force the initial embedding pass:

```sh
ken install --embed .
```

This is recommended when you can afford the extra install time. The cost depends on repository size. On very large projects, cap the eager pass while still structurally indexing the whole repo:

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

## Embedding models & GPU

New projects use a **multilingual** default (`paraphrase-multilingual-MiniLM-L12-v2`, 384-dim), so prompts written in any language retrieve code named in English. It is a drop-in for the older English-only default: same dimensions, same footprint, faster.

A project's model is **pinned to its index**. Upgrading ken never re-encodes an existing project behind your back — cosine similarity across two models is meaningless, so switching always requires a deliberate re-encode. When a project is still on the old English-only model, the session-start brief points it out and tells you how to move:

```sh
# Re-encode every stored embedding with a new model (no re-index; uses the
# source text ken already keeps). Records the model so it stays pinned.
ken reembed --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

Any [fastembed](https://github.com/qdrant/fastembed) model works out of the box.

To choose the default for **future** projects (leaving existing ones untouched), set a user-level default:

```sh
ken default-model                     # show the current default for new projects
ken default-model BAAI/bge-m3         # every project installed from now on uses this
ken default-model --clear             # back to ken's built-in default
```

This only affects projects created afterwards; switch an existing one with `ken reembed --model <name>`.

### GPU acceleration

The embedder auto-detects a GPU and uses it, falling back to CPU when none is usable — no configuration. What counts as a GPU depends on the backend:

| Backend | Accelerators | How to get it |
| --- | --- | --- |
| fastembed / ONNX (default) | CUDA, ROCm — Linux/Windows only | `pip install 'ken-rank[gpu]'` |
| torch / sentence-transformers | CUDA, **Apple Silicon (MPS)** | `pip install 'ken-rank[torch]'` |

Override detection with `KEN_EMBED_DEVICE=auto|cpu|gpu|cuda|mps` (and `KEN_EMBED_DEVICE_ID=0` to pick a CUDA index). `auto` and `gpu` prefer CUDA, then MPS, then CPU; naming one accelerator restricts the choice to that one, so `cuda` on a Mac lands on the CPU rather than quietly substituting the other GPU.

**On Apple Silicon**, only the torch backend reaches the GPU — ONNX Runtime has no MPS provider, and `[gpu]` is not installable on macOS at all (onnxruntime-gpu ships no Mac wheels), so the default models stay on the CPU where they are already fast. `[torch]` alone is enough: the stock PyPI `torch` wheel for macOS arm64 carries MPS.

MPS is used more defensively than CUDA, because it fails in ways CUDA doesn't:

- **It can lie quietly.** A batch can come back as `NaN`, or as rows the GPU never filled in — which survive normalisation as all-zero vectors that are perfectly finite and score 0.0 against every query forever. ken checks that each batch is finite *and* unit-norm; if it isn't, or the GPU raises, it re-encodes on the CPU and stays there for the rest of the process. One reload, versus unusable vectors in `ken.db` that nobody notices until retrieval has quietly degraded.
- **It won't tell you it's out of memory.** torch's MPS allocator ceiling is set from a fraction of RAM and lands *above* the RAM that exists, so instead of an out-of-memory error macOS just swaps. ken caps it (`KEN_MPS_MEMORY_FRACTION`, default `0.7`) so an oversized batch raises and hits the fallback above.
- **torch 2.9+ is required** to use the GPU (macOS 14+). Below that, a PyTorch bug could return embeddings that are finite, unit-norm and *wrong* — the one failure no runtime check can catch — so ken refuses MPS on older torch and says so in the log rather than trusting an index it can't verify. The `[torch]` extra pins this for you on Apple Silicon.

**Is the GPU worth it?** For most people, not much — and that's fine. The device only affects how fast a *query* is embedded; the rest of a rank (loading the stored vectors, the cosine sweep, the lexical/import channels) is CPU work either way. With the default fastembed model, embedding a query is already ~30–40 ms on CPU, so the GPU barely moves the needle for inline ranking. Even with the heavy `Qwen/Qwen3-Embedding-0.6B` on a large repo, a full rank was ~1.1 s of which the query embed is ~250 ms on CPU vs ~50 ms on GPU (measured on CUDA — Apple Silicon is unmeasured) — the GPU saves ~200 ms of a second-plus that's dominated by device-independent work. So CPU-only is perfectly usable, including with Qwen3.

Where the GPU genuinely pays off: **bulk work** — a full `ken reembed` or the first index of a big repo re-encodes thousands of texts at once, and there the GPU is several times faster. And if you simply want to shave every last millisecond off inline ranking, turn it on. Otherwise, don't sweat it.

### Stronger models (torch backend)

Some of the best open-source embedding models are not shipped by fastembed. The optional `torch` extra adds a [sentence-transformers](https://www.sbert.net/) backend so you can use them — most notably **`Qwen/Qwen3-Embedding-0.6B`**, the top scorer in ken's own retrieval benchmark, and `BAAI/bge-m3`:

```sh
pip install 'ken-rank[torch]'
ken reembed --model Qwen/Qwen3-Embedding-0.6B
```

ken selects the backend automatically from the model name — just point `ken reembed --model` at it.

**How good is Qwen3?** On ken's benchmark (100 labeled prompt→file queries over a real project with Spanish prompts and English code), Qwen3-0.6B was clearly the strongest model tested:

| Model | Recall@5 | MRR | Spanish Recall@5 |
| --- | --- | --- | --- |
| Qwen3-Embedding-0.6B (`[torch]`) | **0.77** | **0.68** | **0.75** |
| multilingual-MiniLM (default) | 0.59 | 0.47 | 0.59 |
| all-MiniLM (old English-only default) | 0.54 | 0.36 | 0.33 |

That is roughly **+40% Recall@5 and +87% MRR** over the old default, and it more than doubles retrieval quality on non-English prompts.

**The costs.** Qwen3 is not free to run:

- **Heavier install.** The `[torch]` extra pulls PyTorch + sentence-transformers — hundreds of MB, versus the small ONNX-only default. The model itself is ~1.2 GB.
- **Bigger index.** It is 1024-dimensional; stored vectors are ~2.7× the size of the 384-dim default, so `ken.db` grows accordingly.
- **Slower on CPU.** It shines on a GPU — the torch backend picks up CUDA or Apple Silicon's MPS on its own (the `[gpu]` extra is for the fastembed path, not this one). On CPU the per-prompt embedding is noticeably slower than the fastembed default, which matters because the daemon embeds inline on every prompt. On a Mac, `[torch]` alone is enough: the stock PyPI `torch` wheel for macOS arm64 ships MPS support, no extra index or extra to install.

So it is worth it when you have a GPU (or don't mind the CPU latency) and want the best retrieval; otherwise the lightweight multilingual default is the better trade-off. The fastembed default always stays the no-torch path.

## Tell the assistant to use ken

ken works through hooks automatically, but assistants behave better when your project instructions tell them *when* to reach for ken and, just as importantly, to write back what they learn. The MCP server already describes all 30 tools to the assistant, so the block below deliberately carries only what a tool description cannot: where to start, when to stop, and what to record. Add it to the agent instruction file for the tool you use: `AGENTS.md` for Codex, `CLAUDE.md` for Claude Code, or both.

```md
## Code intelligence: ken

**When a prompt arrives with a `<context-rank>` block**, that is ken's ranked guess
for this request: `Files:` best first, `Symbols:`, and `Notes:` — finding *topics*
from past sessions, so `ken_recall` one to read its body. If it names what you need,
open that file and skip searching. If a listed file was irrelevant, `ken_dismiss(path,
reason)` — the ranker's only negative signal, and only useful while you can still see
it. Thin or missing? `ken_rank(verbose=2)`, or `ken_intent_history("<task>")` for the
files past tasks like this one actually touched.

**Before the first search**, don't reach for `rg`, `find`, or open files you are
guessing at. One ken call, matched to the question:
- exact string or identifier (`MY_ENV_VAR`, `os.path`) → `ken_grep`, not `rg`
- which file implements X → `ken_search_files`
- where is the function/class that does X → `ken_search_symbols`
- how a route / CLI command / env var reaches its handler → `ken_wiring`

Then read what ken named: it narrows the search space, it doesn't replace reading
code. Two ken calls is normal, five means you should have opened the file already;
trivial or in-context questions need none. Use `rg` when ken comes back empty — it
searches indexed files, so something created moments ago may be missing.

**Before editing an unfamiliar file**, `ken_file_findings(path)` — what past sessions
learned here. If the change isn't local: `ken_blast_radius` (what it breaks),
`ken_cochange` (what changes with it that imports don't show), `ken_find_tests`.

**Before finishing, write back — the step agents skip, and the reason ken stops
improving.** Learned something non-obvious that cost real effort (a root cause, a
constraint, where a subsystem actually lives)? `ken_remember(topic, content)`, so the
next session starts where this one ended. Durable facts, not a session log; same
topic overwrites.
```

The shell commands (`ken rank`, `ken search-files`, `ken search-symbols`, and `ken explain`) expose the same ideas for humans or agents without MCP, and `ken tools <name>` runs any MCP tool directly (see [Run MCP tools from the shell](#run-mcp-tools-from-the-shell)). For assistants with MCP available, the MCP tools are the preferred path because they return structured results and feed ken's local task memory.

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

## Run MCP tools from the shell

Every tool the ken MCP server exposes is also runnable directly with `ken tools`, so you can use the structured code-intelligence tools (call graph, blast radius, co-change, wiring, clones, …) without an assistant in the loop. The list, descriptions, and parameters are read live from the same MCP surface, so `ken tools` never drifts from what the agent sees.

```sh
ken tools                                   # list every tool with a one-line summary
ken tools grep --help                       # show one tool's parameters
ken tools grep "MY_ENV_VAR" --mode bm25     # required params are positional, options are --flags
ken tools blast_radius src/ken/cli.py
ken tools file_symbols src/ken/search.py --no-include-docstrings
```

The tool name may be given with or without the `ken_` prefix (`grep` or `ken_grep`). Results print as JSON (`--compact` for a single line). Point at another checkout with `ken tools --path /repo <name> ...` (the flag comes before the tool name).

## Codex hook setup

After `ken install --codex .`, start Codex in the project and run `/hooks` to enable the project hooks. Codex only loads project-local hooks after the project is trusted, so also approve the trust prompt when Codex asks.

You can mark the project as trusted manually in `~/.codex/config.toml`:

```toml
[projects."/abs/path/to/my-project"]
trust_level = "trusted"
```

## Uninstall

```sh
ken uninstall .
ken uninstall --keep-db .
```

`ken uninstall .` removes hooks, MCP entries, and the local `.ken/` index. Use `--keep-db` if you want to keep `.ken/ken.db` for later.

## License

ken is released under the MIT License. See [LICENSE](LICENSE).
