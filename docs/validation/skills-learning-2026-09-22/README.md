# Skills rewrite and learning validation

Validated September 22, 2026, on macOS arm64 with Python 3.12.9. This implements
the [September 21 review](../../design/assistant-skills-review-2026-09-21.md).
All skill instructions and supporting resources are in English.

## What changed

The eight skills now teach an investigation from question to supported outcome,
including a worked source example, a decision based on the evidence, a branch
for an ambiguous or incomplete result, and a stopping condition:

| Skill | Investigation taught |
| --- | --- |
| Locate code | Follow a manifest writer from a coordinating wrapper to the actual effect |
| Investigate a bug | Find the boundary that drops a returned identifier and test the repair |
| Plan a change | Trace an integer-to-Record return change to an API compatibility obligation |
| Understand architecture | Explain the decisions and data on a command-to-file path |
| Reuse code | Separate a compatible atomic writer from a similarly named helper, then resolve caller access |
| Find patterns | Distinguish a returned call value from a discarded or overwritten one |
| Prevent regressions | Build a violation query, validate counterexamples, and compare explicit receipts |
| Resume work | Reuse a supported conclusion or revisit only changed inputs and assumptions |

The two query-authoring skills carry the same installed KQL2 manual, maintained
once at `src/ken/skills/references/kql2`. It explains complete programs, source
scope versus query namespaces, captures and identity, containment, properties,
regexes, context-specific lists, predicates, alternatives, correlated absence,
optional evidence, BODY values, callable targets, reusable patterns and imports,
graph relations, execution, and uncertainty. It explicitly describes a tested
subset rather than promising the entire design grammar.

The regression skill ships both `some_match` and `no_matches` definitions. The
existential example deliberately includes a mixed good/bad case that passes;
the violation example rejects a defect even alongside a good implementation.
This makes the difference observable rather than merely warning about it.

## What happened to the old skills

Names and destinations were retained. The project's existing `.agents/skills`
contained exactly the eight Ken skills; no second DeepSeek skill copy existed.
The installer updated all eight in place, with **zero new bundles, duplicates,
or preserved local conflicts**. The two clarifications found during the CLI
probe then updated the contract skill once more. DeepSeek continues to use the
shared `.agents/skills` installation.

The previous return-contract resource was extended rather than removed because
it now demonstrates a useful contrast with violation checking. Obsolete owned
resources are removed by the existing reconciliation logic. Edited or unowned
bundles remain protected; no custom files were deleted. The before/after
ownership manifests had the same eight target names. See [installation.json](installation.json).

This rewrite does not rename or retire any whole skill. A future catalog-wide
rename/removal would need an explicit migration; it is not implicitly handled
by adding a new folder. The project's 1,000 MB cache setting remains unchanged.

## Executable verification

- **123 tests passed** across bundled examples, installation/update/removal,
  host selection, DeepSeek MCP integration, source exclusion, contracts, and
  justified memory. After the final prose clarification, the 16 bundled-example
  tests were rerun and passed.
- **12 complete KQL programs copied directly from the Markdown resources** ran
  against the supplied positive and near-miss source fixture. A separate library
  block was loaded by its declared module. Assertions cover rows, completion,
  coverage, unknown candidates, truncation, and optional-evidence distinctions.
- Both shipped contracts validated their eight combined examples through the
  public CLI; before/after runs detected actual source regressions.
- All eight skills passed the skill-creator validator. Local Markdown links
  resolved inside each installed bundle; all Python example blocks parsed.
- Ruff passed for the changed catalog and example tests; mypy passed for the
  catalog. A newly built wheel was extracted and imported outside the checkout:
  it installed eight skills and **18 resources** with matching bytes. See
  [packaging.json](packaging.json).
- Final project-installed bytes matched the catalog assembly exactly.

One source-authoring trap was caught before publication: declaration selectors
reject `method { name: ["write", "read"]; }`, even though BODY call names accept
lists. The guide teaches a regex or alternatives for that selector and does not
infer executable support from parsing alone.

Run the relevant suite:

```sh
.venv/bin/python -m pytest tests/test_install_skills.py tests/test_install_deepseek.py tests/test_bundled_skill_examples.py tests/test_install_codex.py tests/test_install_opencode.py tests/test_cli_reinstall.py tests/test_gitignore_filter.py tests/test_check_tools.py tests/test_justified_memory.py
```

## Model-driven learning probes

Two separate `codex exec` runs received fresh temporary Python projects, the
installed eight skills, and novel task prompts. They used the configured default
model without an override. Instructions allowed the installed references and
CLI help, prohibited reading Ken implementation/tests as teaching material, and
required actual execution. They used the public CLI with explicit project roots,
not this repository's MCP connection. No solution query was supplied.

| Probe | Observed outcome |
| --- | --- |
| Find classes owning `load` without their own `clear` | The agent selected the pattern skill, wrote correlated negation, executed it, found only `StreamingReader`, and reported scope/coverage and inherited/dynamic-method limitations |
| Preserve “own `commit` requires own `rollback`” | The agent selected the regression skill, authored a violation query and 12 examples, validated and enabled on-demand checking, observed `pass -> fail (regression) -> pass (resolved)`, and restored the source |

The second probe was **not frictionless**. It first encountered an uninitialized
fixture and initialized it with `--no-wire`. It also attempted more than 12
examples, hit the actual rule limit, reduced the set, and succeeded. The final
skill now explains initialization and the example limits, and recommends
starting with a positive, regression, and relevant near miss. The model probe
was not rerun after that small prose clarification; executable/package checks
were rerun. No claim is made that the updated wording eliminates every such
mistake.

An independent execution of the generated queries then used additional source:

- Find: two offending classes alongside a valid class, a cleanup-only class,
  and an unrelated class. Exactly both offenders matched.
- Contract: five cases covering a valid class, unrelated-owner rollback, equal
  class names in different files, inherited rollback, and no obligated class.
  All results matched the declared direct-ownership property.

Evidence: [prompts, command traces and outcomes](learning-probes.json),
[generated find query](find-answer.kql), [find holdout](find-heldout.json),
[generated contract](contract-answer.json), [contract query](contract-answer.kql),
and [contract holdouts](contract-heldout.json).

These are two bounded transfer demonstrations, not a comparative study or proof
that all eight skills teach every programming task. The six higher-level skills
were reviewed for problem/evidence/decision flow and API accuracy, but did not
each receive a fresh model-driven trial in this run. The tests do not establish
runtime correctness of code merely because its structural contract passes.

To repeat a learning probe, materialize its `fixture` field as `src/sample.py`
in a fresh directory, install skills there, and supply its `prompt` to:

```sh
codex exec --skip-git-repo-check --ephemeral --sandbox workspace-write \
  -C /path/to/fixture --json -o /tmp/skill-probe-answer.md - < /tmp/skill-probe-prompt.txt
```

Adjust the CLI executable path in the prompt to the local Ken installation. The
recorded contract example is evidence from the probe, not an adopted contract
for this repository. No automatic rule was enabled here.
