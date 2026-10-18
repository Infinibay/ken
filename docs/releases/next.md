# Next release — draft

Status: preparation only. No version bump, tag or publication. The current
package version remains 0.17.0 while the candidate is validated.

## What changes for users

- Search files, functions, classes and modules through the complete local search
  pipeline by default: Potion static embeddings, CodeRankEmbed INT8 context,
  structural and lexical signals, learned ranking and Ettin 68M reranking.
  The pipeline runs on CPU; no embedding API key is required.
- CLI and MCP return compact text by default: source path, line ranges, symbol
  identity and selected, numbered code. Use CLI `--json` or MCP
  `output_format="json"` for structured responses. Scripts that parsed the old
  default output should select JSON explicitly.
- Tool descriptions recommend English queries for the strongest current
  results. Installation can offer project instructions in `AGENTS.md`;
  `--agents-md` and `--no-agents-md` make the choice explicit.
- C++ and Rust source extraction covers additional declaration forms. Invalid
  UTF-8 fixtures are excluded from source passages; preparation rebuilds stale
  extraction projections instead of using an obsolete index.

## Updating an existing project

After installing the eventual release, restart the assistant so it launches the
new MCP process. Re-run `ken install .` to refresh project integration. Prepare
the complete search index explicitly with:

```sh
ken retrieval prepare --path .
```

Existing project model pins and saved findings must survive the upgrade. The
complete search pipeline maintains its own retrieval representations. Preparing
it can download models and rebuild source views; first-use setup is separate
from ready-index query latency.

## Measured search quality

The last complete public comparison used the benchmark created by
[Semble](https://github.com/MinishLab/semble#benchmarks): **1,251 queries in 63
repositories**, with the original annotations and evaluator. The measured Ken
snapshot obtained **73.78% Top1**, **97.60% Hit@10** and **0.8480 macro NDCG@10**.
CPU median/p95 search time was **1.97 / 4.22 seconds**, with a maximum of 14.71
seconds and a highest worker peak of 1.76 GiB.

These annotations mainly identify files. This is not proof of 90% strict
requested-piece accuracy or a new benchmark run on this release candidate.
See the [full pinned report](../validation/semble-embedding-comparison-2026-10-17-v323/README.md)
for the measured recipe, costs and limitations. The private reserve remains
closed.

## Dependency and build policy

Project resolutions through uv exclude registry artifacts uploaded within the
last 14 days, including transitive dependencies. pip and other installers do not
inherit uv project policy. CTranslate2 is pinned to 4.8.2 to satisfy that window;
the historical benchmark used 4.8.3. No benchmark numbers were relabeled.

Tensor-level regression tests declare their development dependencies explicitly.
The development group uses official PyTorch CPU wheels, without CUDA packages;
Torch is not required by a normal Ken installation.

Publication requires successful Linux/macOS CI and clean-install/0.17-upgrade
checks on the selected candidate. See [the release procedure](../../RELEASING.md).
