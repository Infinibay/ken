---
name: ken-prevent-regressions
description: Preserve a demonstrated source-level invariant with a validated KQL2 rule and before/after checks. Use to prevent a known structural defect from returning, not to claim runtime correctness from a code pattern.
---

# Build a contract that rejects the actual regression

Begin with the failure and the property that would expose it. Compare the broken
source with its corrected form: which relationship changed? It may be ownership,
the returned value, a resolved target, supported operation order or scoped absence.
The [relationship investigation](references/kql2/relationships.md) shows how to
build such a query from source examples. A custom project invariant does not
need a matching entry in the built-in bug catalog.

Use a behavioral test when correctness depends on execution, effects, or paths the static query
cannot establish. Check for an existing contract with
`ken_related(target=path, relation="checks")` before creating another.

Read [the KQL2 guide](references/kql2/README.md) before writing queries; the
[values chapter](references/kql2/values-and-patterns.md) explains return flow and
[graph chapter](references/kql2/graph-queries.md) explains hazards. Examples below
use MCP-call notation and illustrative project paths.

The hazard and BODY examples use indexed. For syntax-only obligations, read
[the syntax chapter](references/kql2/syntax.md) and check the backend explicitly.
Inspect authoring `diagnostics` before adopting a query. Include a mixed fixture
where one candidate satisfies the condition and another does not; this catches
global witnesses accidentally satisfying every candidate.

## Work through: “Do not reintroduce shared mutable defaults”

This example adopts an existing hazard signature. The same contract lifecycle
can adopt a tested custom KQL2 relationship; preserve the actual invariant and
its counterexamples rather than substituting a broader catalog rule.

A demonstrated regression uses `def collect(items=[]): ...`, accidentally
sharing state between calls. The source obligation is narrow: no recognized
mutable-default-argument hazards under `src`. Search for **violations**:

```kql
language "kql/2";
module contracts.defaults;
query mutable_defaults {
  edge HAS_HAZARD($site, "mutable-default-argument");
  select $site;
}
```

Choose `expectation: "no_matches"`. The complete, editable definition is in
[mutable-default-contract.json](references/mutable-default-contract.json).
It includes this query, `id`, `description`, `path`, and isolated source examples:

| Example | Expected contract result | Why |
| --- | --- | --- |
| `items=None`, allocate a new list inside the function | `pass` | No mutable default |
| `items=[]` | `fail` | The prohibited hazard is present |
| A local `items=[]` with no default | `pass` | A similar literal in a different role |
| Safe function alongside an unsafe function | `fail` | One good function must not hide a violation |

Each example has `name`, `files` (relative path -> source text), and `expect`.
Validation parses these programs in isolated projects; it does not execute them.
Start with a positive, the regression, and the closest misleading case; add
examples for distinct uncertainties rather than generating a large catalog.
Ken accepts at most 12 examples, with 1..20 files per example and a 1 MB limit
for the rule and examples together. Adapt them to the real regression.

## Validate, adopt, and compare

Run rule tools in a Ken-initialized project. For a disposable fixture with no
`.ken` project yet, `ken install --no-wire /path/to/fixture` initializes the index
without wiring assistant hosts. Direct `ken kql2` searches do not require this
initialization, but the persistent rule tools do.

Pass the **entire JSON object**, not its filename, as `definition`:

```python
ken_rule(action="create", definition=definition)
ken_rule(action="validate", rule_id="python.no-mutable-defaults", full=True)
```

Read each example's outcome. A validation failure means the query or the
claimed property needs work; add the case that fooled it. Validation requires
both passing and failing examples. When it succeeds and adopting the contract
is within the requested work:

```python
ken_rule(action="enable", rule_id="python.no-mutable-defaults")
before = ken_check(rules=["python.no-mutable-defaults"])
# After the requested source change:
after = ken_check(rules=["python.no-mutable-defaults"], compare=before["run_id"])
```

A passing baseline followed by a violation should yield `status="fail"` and a
comparison change of `regression`. Read its location and fix the actual source.
A later passing comparable run can report resolution. Keep the explicit run ID;
`compare="last"` can refer to concurrent work. An already-failing baseline is
existing debt, not proof that your change introduced it.

CLI, from the project root (set `definition_file` to the installed JSON path):

```sh
ken tools rule --action create --definition "$(cat "$definition_file")"
ken tools rule --action validate --rule-id python.no-mutable-defaults
ken tools rule --action enable --rule-id python.no-mutable-defaults
ken tools check --rules python.no-mutable-defaults
# Substitute the run_id returned above:
ken tools check --rules python.no-mutable-defaults --compare RUN_ID
```

## Avoid a contract that passes for the wrong reason

The [return example](references/return-contract.json) uses `some_match`: at least
one `save_user` returns a `save` result. Its readable query is the
[return-flow recipe](references/kql2/values-and-patterns.md). It intentionally
includes a mixed example that still passes with a broken wrapper elsewhere.
One witness satisfies this expectation. Do not use it for “every wrapper must
forward” without expressing and validating that stronger property.

`unknown` or `not_applicable` is not success; comparisons can be `inconclusive`
or `not_comparable`. `path` and `scope="changes"` select relevant rules, not a
smaller proof domain. Updating a rule invalidates its validation and adoption;
validate and enable the new definition again. CLI exit zero means a valid tool
response, so automation must inspect the JSON contract status.

Enable `automatic=True` only when ongoing checking is requested. Supported
hooks can run adopted automatic rules; installing a skill does not opt rules
into automation or add CI. Finish with the invariant, domain, adversarial cases,
observed check results, and the behavior that still needs runtime tests.
