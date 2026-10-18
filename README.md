# ken

### Find the code. Keep the context.

**Code search and project memory for coding agents.** Ken finds relevant files,
functions and classes, returns code your agent can inspect, and brings useful
project knowledge into the next session. Works with Claude Code, Codex and other
MCP clients.

**97.6% Hit@10 · 1,251 queries · 63 repositories · CPU only**

*Measured on development main; [methodology and reproducible results](docs/validation/semble-embedding-comparison-2026-10-17-v323/README.md).*

We evaluated Ken using the same public code-search benchmark created by
[Semble](https://github.com/MinishLab/semble#benchmarks). Ken returned a matching
target in its first ten results for **1,221 of 1,251 queries**. The measured engine
runs locally, with no embedding API key or powerful GPU required.
[Results and methodology ↓](#measured-on-real-repositories)

## Start here

Requires Python 3.11+. Install the CLI, then connect a project:

```sh
uv tool install ken-rank
cd your-project
ken install .
```

Prefer pipx? Use `pipx install ken-rank`. The package is `ken-rank`; the command
is `ken`.

Ken detects supported assistant setups and installs local MCP configuration,
skills and hooks where available. Restart your assistant after installation.
Choose a host explicitly with `ken install --claude .` or `ken install --codex .`.
OpenCode uses `ken install --opencode .`.

**The benchmark below measures development main, not a new PyPI release.**
To try that engine now, install from Git instead:

```sh
uv tool install --reinstall 'git+https://github.com/Infinibay/ken'
```

Models download on first use; indexing and inference run on your machine. Prepare
the search models and source index ahead of the first query with:

```sh
ken retrieval prepare --path .
```

## Ask about behavior, get code

```sh
ken search-files "Where are application settings loaded?"
ken search-symbols "Read a stored setting by key"
ken search-symbols "Reader.read_value"
```

Use English queries for the strongest current results. Choose the kind of piece
when it matters:

```sh
ken search-symbols "Read stored settings" --piece-kind class
ken search-files "Load configuration" --piece-kind module
```

Compact text is the default in the CLI and MCP: a path, source range, symbol and
numbered code. For example, this real response from the small demo project gives
the agent something concrete to verify:

```text
reader.py:6-8 :: Reader.read_value
6 |     def read_value(self, key):
7 |         """Return the stored value for a setting key."""
8 |         return get_value(key)
```

Need structured output? Add `--json`, or use MCP `output_format="json"`.
[More actual CLI and MCP responses](docs/validation/compact-output-2026-10-16-best-default/EXAMPLES.md).

## More than a search box

- **Give the agent a starting point.** Claude Code and Codex hooks can inject
  ranked project context before each prompt. MCP tools support explicit searches
  in other clients.
- **Find by meaning or by structure.** Search behavior, exact names and text;
  inspect symbols, imports, callers, related tests and change impact.
- **Keep the useful discoveries.** Save findings with source references and
  anchors so the next session can recover them. Dependency checks expose when
  their declared inputs have changed.
- **Keep context focused.** Results include source locations and selected code;
  full diagnostics and JSON are available when needed.
- **Run locally.** The index, embeddings and project memory stay on your machine.
  Ken needs no hosted search service or embedding API. Your coding assistant's
  own connection and data policies still apply.

The default search combines lexical and static retrieval, structural information,
CodeRankEmbed INT8 context and Ettin 68M reranking. You can use the complete
pipeline on CPU. No model selection is needed to get the measured default.

## Measured on real repositories

The benchmark was created by [Semble](https://github.com/MinishLab/semble) and
covers **1,251 queries across 63 repositories**. Ken used the original queries,
source revisions, annotations and NDCG evaluator, with every query retained.
Results for the current CodeRank default:

| Metric | Result |
|---|---:|
| Matching target at Top1 | **73.78%** — 923/1,251 |
| Matching target within Top10 | **97.60%** — 1,221/1,251 |
| NDCG@10, averaged by repository | **0.8480** |
| Ready-index search, median / p95 | **1.97 s / 4.22 s** |
| Highest worker peak RAM | **1.76 GiB** |

CPU measurements: Apple M1 Pro, 10 cores, 32 GiB RAM. Search timing includes the
API, compact rendering and serialization with the index and models prepared;
initial setup is separate. The slowest query took 14.71 s. RAM is the whole-worker
high-water mark, including preparation and model loading.

The annotations mainly identify **files**: 1,462 of 1,496 targets have no line
span. These figures measure matching the published targets, not exact-function
accuracy or a blind acceptance test. The same evaluator gives the saved Semble
0.7.0 reference 74.02% Top1, 98.64% Hit@10 and 0.8512 NDCG@10; its historical
timings are not a matched comparison.

The [full reproducible report](docs/validation/semble-embedding-comparison-2026-10-17-v323/README.md)
includes all three tested contextual encoders, per-query scores, CPU/RAM costs,
source/model hashes, limitations and a model-free recheck script. The private
acceptance reserve was not used.

## Let your agent use it

With MCP connected, the core workflow is:

```python
ken_find(query="Where are stored settings read?", scope="symbols")
ken_read(path="reader.py", include=["source"], qualname="Reader.read_value")
```

Save a discovery for the next session:

```sh
ken remember "settings lookup" "Reader.read_value delegates to settings.get_value."
ken recall "settings lookup"
```

These paths and names belong to the demo project; use your repository's results.
`ken status .` shows index health. `ken tools` lists the MCP tools from the shell.

## Go deeper

- [Full CLI, installation and integration reference](docs/reference.md)
- [Actual output examples](docs/validation/compact-output-2026-10-16-best-default/EXAMPLES.md)
- [Memory with evidence and dependency validity](docs/design/justified-memory.md)
- [Structural code queries](docs/design/kql2/README.md)
- [Source contracts and regression checks](docs/design/source-contract-tools.md)

Ken is open source under the [MIT license](LICENSE).
