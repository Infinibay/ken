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

From this checkout, run:

```sh
./install.sh
```

The installer uses `uv` to install the `ken` command into your user-local tool directory. If `uv` is not present, the script bootstraps it with Astral's official installer unless you pass `--no-bootstrap-uv`.

Verify the install:

```sh
ken --version
```

You can also install directly with `uv`:

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

## Tell the assistant to use ken

ken works through hooks automatically, but assistants behave better when your project instructions explicitly tell them how to use the ken MCP tools. Add the same guidance to the agent instruction file for the tool you use: `AGENTS.md` for Codex, `CLAUDE.md` for Claude Code, or both.

```md
## Code Search

Use ken as the first attempt for codebase questions. Prefer ken MCP tools before
broad text search or reading many files:

- Start with `ken_rank` for the current task, or pass a query when the question
  needs a focused search.
- Use `ken_search_files` to find files by intent, feature, behavior, or concept.
- Use `ken_search_symbols` to find functions, classes, methods, APIs, and other
  named code objects.
- Use `ken_file_outline`, `ken_file_symbols`, and `ken_file_snippets` to inspect
  surfaced files precisely before opening larger chunks of code.
- Use `ken_file_neighbors`, `ken_module_graph`, and `ken_find_tests` to follow
  imports, related modules, and source/test pairs.
- Use `ken_changed_context` when working from an existing diff or local edits.
- Use `ken_project_overview` for a compact map of an unfamiliar project area.
- Use `ken_grep` for exact-literal or BM25-ranked text search (preserves
  identifiers like `MY_ENV_VAR` and `os.path`) instead of falling back to `rg`.
- Use `ken_recall` and `ken_findings` for saved project knowledge, and
  `ken_remember` when a durable finding should help future sessions.
- Use `ken_explain_rank` when rankings look surprising or an expected file is
  missing.
- Use `ken_dismiss` when ken surfaces a file that is clearly not relevant, so
  future similar tasks get better results.

To understand *how something works* — answered by local algorithms, not an LLM,
so the output is fast, deterministic, and evidence-cited:

- Use `ken_architecture` for subsystems, layers, dependency cycles, and
  load-bearing hub files (graph algorithms over the import graph, with honest
  edge-coverage).
- Use `ken_callgraph` to find who calls a symbol and what it calls
  (precision-tiered T1/T2; Python).
- Use `ken_type_hierarchy` for subclasses, ancestors, and method overrides
  (Python).
- Use `ken_wiring` to map routes / CLI commands / env vars to their handler
  symbols (Python).
- Use `ken_profile` to learn what a file or package is *for* and what
  distinguishes it from its siblings (distinctive-term statistics).
- Use `ken_cochange` to see what historically changes together with a file —
  including hidden coupling imports can't show (schema↔migration, code↔config).
- Use `ken_blast_radius` before an edit to estimate what it might affect, with
  per-channel evidence (imports, tests, co-change).
- Use `ken_clones` to find copy-pasted / near-duplicate code.
- Use `ken_intent_history` to see which files requests *like the current one*
  have historically touched.

After ken narrows the search space, read the relevant files directly. Fall back
to `rg` only when ken is insufficient.
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
