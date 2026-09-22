# Problem-oriented assistant skills

`ken install` distributes English instructions organized around programming
problems. A skill can combine several tools; tool documentation remains the
authority for individual parameters. The assistant loads the relevant skill
on demand. Installing instructions does not adopt contracts or enable automation.

## Public use

```sh
ken install --codex .
ken install --deepseek .
dsh --profile web --patch .dsh/ken.cordis.json
```

Without flags, installation detects the project's host markers; a fresh project
retains the Claude default. Explicit flags select only those hosts. `--no-wire`
skips skills and all host wiring. `ken reinstall` forwards `--deepseek` along
with the existing host flags.

| Host | Project skill directory | Integration |
| --- | --- | --- |
| Claude Code | `.claude/skills` | Existing hooks and MCP configuration |
| Codex | `.agents/skills` | Existing hooks and MCP configuration |
| OpenCode | `.opencode/skills` | MCP registration; reuses a selected Claude/Codex skill destination |
| DeepSeek Harness | `.dsh/skills` | Explicit Cordis MCP overlay; reuses `.agents/skills` when Codex is selected |

Discovery locations were checked against the [Codex skill guide](https://learn.chatgpt.com/docs/build-skills),
[Claude skill guide](https://code.claude.com/docs/en/skills),
[OpenCode skill guide](https://opencode.ai/docs/skills/), and the
[DeepSeek filesystem skill provider](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md).
The installed official Harness package also documents and implements its
`.dsh/skills` and `.agents/skills` roots.

DeepSeek uses its documented [MCP overlay mechanism](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/mcp-memory.md).
Ken creates `.dsh/ken.cordis.json`, a JSON representation of a Cordis patch list,
with one `@deepseek-ai/dsh-mcp-client` insertion. `cwd` and the MCP root argument
bind the server to the installed project; the command uses the installing
Python executable. This avoids selecting an unrelated `ken` executable from
PATH. Reinstall after moving either the environment or project.

The official launcher requires `--patch`: no project overlay is silently
discovered, and no global profile is modified. Web and headless profiles can
use the same overlay. Custom profiles must provide the normal tool and skill
services. OpenCode and DeepSeek integration currently provides on-demand MCP
and skills; it does not install native prompt/edit/session hooks.

## Responsibility boundaries

- `skills/catalog.py` reads complete package bundles with `importlib.resources`.
  Adding an ordinary skill requires adding its folder, without an installer
  registry edit. The two KQL-authoring skills additionally receive the shared
  `skills/references/kql2` tree under their own `references/kql2` directory.
  This small, explicit catalog composition keeps one maintained manual and
  self-contained installed bundles; it does not add another skill.
- `skills/ownership.py` records hashes and decides whether a bundle is still
  Ken-owned and unchanged. Paths stay within the supported project skill roots.
- `skills/installation.py` selects destinations and reconciles resources.
- `deepseek_template.py` owns the official Harness overlay format and launch hint.
- `install.py`, `install_uninstall.py`, and the CLI coordinate these components.

The ownership manifest lives in `.ken/installed-skills.json`. Fresh installs
never claim an existing directory, even if its content happens to match Ken's
bundle. Reinstall updates owned, unchanged resources and removes retired
resources from an updated bundle. Any edited owned resource preserves the
whole bundle, including its references, with a visible diagnostic. Unknown
extra files remain untouched. Symlink destinations and invalid manifests are
not followed. Uninstall removes unchanged owned resources and prunes only empty
directories inside each skill; edited bundles survive.

Keeping `.ken` preserves ownership metadata. If `.ken` is removed during
uninstall, customized bundles remain as unowned files, so future installs still
preserve them. Renaming or removing an entire bundled skill is a separate
catalog migration: unchanged old installed bundles remain until uninstall.

The September 22 rewrite retains all eight existing skill names and destinations.
Reinstallation replaces their owned content in place, rather than introducing
new names or leaving old and new generations active together. The previous
return-contract resource remains as a deliberately existential example, now with
an overwritten value and a mixed good/bad case. A violation-based contract and
the language references are added to that same bundle. Locally customized old
bundles are reported and preserved as a unit; they are not partially upgraded.

The source folders under `bundled` are inputs to catalog assembly. To preview
their complete relative-link tree, use `bundled_skills()` or install into a
temporary project. Shared reference links resolve inside the assembled bundle,
and tests follow every local Markdown link after installation. Packaging tests
also assemble from an extracted wheel, outside the checkout.

Each skill now follows a concrete investigation through source evidence and
decisions, with an uncertain-result branch and a completion condition. Only
query-authoring skills need the language manual. Its literal KQL blocks are
executed against positive and near-miss source, including result overwrite,
correlated absence, and optional evidence. Validation also exercises both rule
expectations through the CLI. See the
[rewrite validation](../validation/skills-learning-2026-09-22/README.md) for the
separate limits of executable examples and model-driven learning probes.

Assistant skill roots are excluded from indexing and text searches; this
prevents their illustrative snippets from outranking actual project code.
Other `.agents` content, such as project notes, remains searchable, and the
canonical resources in `src/ken/skills/bundled` remain product source.

The skills deliberately distinguish documentation scores from probabilities,
observed call chains from business responsibility, and incomplete analysis from
absence. Source-contract examples state the difference between existential
`some_match` and absence-of-violations `no_matches`. Saved knowledge retains
assumptions and declared input validity instead of promising truth from hashes.
