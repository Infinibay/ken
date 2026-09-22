# English skills and DeepSeek installation validation

Validated on 2026-09-21, macOS arm64, Python 3.12.9. The official local
DeepSeek Harness package was `@deepseek-ai/dsh` **0.1.5-rc.1**.

## Results

- **108 tests passed** across installation, uninstallation, host selection,
  MCP, source-contract CLI, justified memory, and source exclusion.
- All eight English bundles passed the skill-creator frontmatter validator.
- Ruff passed for the new skill installer, DeepSeek adapter, and their tests;
  mypy passed for the seven new or changed installer modules checked.
- A wheel built from the checkout contained all eight `SKILL.md` files and
  the contract reference. A subprocess imported the extracted wheel outside
  the checkout and installed all eight skills successfully.
- The official `dsh --dump-config` composed the generated JSON overlay with
  an isolated headless profile and retained the expected MCP command and root.
- The actual official Cordis MCP plugin discovered **12 Ken tools**, called
  `ken_find` over stdio, and returned the fixture source location. The official
  filesystem skill provider discovered **all eight skills**, loaded the
  regression skill body, and retained its reference location.

The DeepSeek probe uses the official installed tool runtime, skill registry,
filesystem skill provider, and MCP bridge. It does not call a language model,
use an API key, or evaluate autonomous model choices. Native Harness prompt,
edit, and session hooks are outside this integration.

The final project installation also completed with `--codex --deepseek`: all
eight files and their reference matched the packaged resources in
`.agents/skills`, and `.dsh/ken.cordis.json` pointed to this project.
The local cache setting was verified as 1,000 MB while a fresh project still
resolved to the unchanged 500 MB default.

## Behavior exercised

| Problem | Observed result |
| --- | --- |
| Locate responsibility | `who` ranked `write_manifest` first from its docstring, while retaining an ambiguous result and heuristic score semantics. |
| Read evidence | `read` returned the exact `write_manifest` source body. |
| Reuse a callable | `available` found the explicit import alias `persist` in the caller. |
| Understand collaboration | `roles` returned candidate roles from the observed call chain. |
| Follow a result | `impact` identified `create_user` and `save_user` as consumers. |
| Find a pattern | The documented KQL2 `chmod` query completed with one matching callable/call pair. |
| Prevent a regression | The shipped JSON rule validated both examples, passed on the wrapper returning its call result, and reported `regression` after that result was discarded. |
| Resume work | A justified memory returned `unchanged`, then `stale` when a declared source changed. |

The first native DeepSeek run found the illustrative `CACHE_DIR` string in an
installed skill as well as the actual Python file. The integration now excludes
assistant skill roots from traversal, and a real stdio regression test asserts
that only the project source is returned. Other project notes and bundled
product resources remain visible.

Reinstall tests cover unchanged bundles, updated resources, removal of retired
references, unowned collisions, and edits to either a skill or a reference.
Uninstall preserves complete edited bundles and extra user files. Tests also
cover symlink destinations, malformed ownership, path traversal, `--no-wire`,
DeepSeek's explicit launch hint, and preservation of unrelated Cordis patches.

## Evidence and reproduction

- `probe.json`: official Harness plugin discovery and live MCP response.
- `deepseek-probe.mjs`: executable probe; accepts the installed DSH package
  directory and an already installed fixture project.
- `examples.json`: raw tool results and before/after contract receipts.
- `memory.json`: justified-memory responses before and after an input change.
- `packaging.json`: wheel resource inventory and isolated import/install result.

Run the automated regression suite:

```sh
.venv/bin/python -m pytest tests/test_install_skills.py tests/test_install_deepseek.py tests/test_bundled_skill_examples.py tests/test_install_codex.py tests/test_install_opencode.py tests/test_cli_reinstall.py tests/test_gitignore_filter.py tests/test_check_tools.py tests/test_justified_memory.py
```

For the native Harness probe, create an isolated fixture with
`src/storage.py` containing `CACHE_DIR = "cache"`, run
`ken install --deepseek /path/to/fixture`, then:

```sh
node docs/validation/skills-install-2026-09-21/deepseek-probe.mjs /path/to/node_modules/@deepseek-ai/dsh /path/to/fixture
```

For configuration composition without a model call, use a temporary
`DSH_HOME` and `dsh --profile headless --patch /path/to/fixture/.dsh/ken.cordis.json --dump-config`.
No existing global Harness profile needs to be read or changed.

The implementation follows the official [MCP overlay guide](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/mcp-memory.md)
and the installed official filesystem provider. See
[the installation design](../../design/assistant-skills.md) for ownership and
host discovery behavior. The separate [KQL2 latency report](../kql2-find-latency-2026-09-21/README.md)
records the cache experiment; no product cache default was changed.
