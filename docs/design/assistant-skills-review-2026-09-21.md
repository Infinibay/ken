# Review: do the installed Ken skills teach their workflows?

Reviewed the eight canonical bundles, confirmed they match their installed
copies, read the KQL2 implementation documentation and syntax vocabulary, and
reran the bundled contract example test. This is a content and coverage review,
not an independent model evaluation. The existing example test passed.

## Verdict

The bundles provide useful tool-selection guidance and important interpretation
constraints. They are not yet sufficient instruction for all the problems their
descriptions promise. In particular, neither KQL2-authoring skill teaches the
language needed to create a new query. The other skills generally identify the
tools but omit a worked sequence connecting a result to the next decision.

### High: KQL2 authoring has no language reference

`ken-find-code-patterns/SKILL.md:13` introduces one nested callable/call query,
then a graph-edge fragment. It never explains capture declaration and reuse,
identity, scope, containment, property filters, joins, alternatives, negation,
projection, or BODY matching. "Bind a concrete target" is advice without the
syntax needed to follow it. The bundle has no supporting reference files.

Consequently, an agent can imitate the named-call example but is not equipped
by this skill to formulate a materially different structural question.

Required correction: ship an English, executable-subset reference and guide the
agent to read the relevant chapter before authoring. Each concept needs source
code, a complete query, expected matches, and an explanation of why a similar
negative example does not match. A grammar alone does not teach these semantics.

### High: contract adoption is taught before contract construction

`ken-prevent-regressions/SKILL.md:12` asks the agent to adapt a JSON example.
That example embeds its query on one escaped line, without explaining the value
capture, call target, or return relation. The lifecycle and existential warning
are useful, but there is no worked `no_matches` contract, nor a method for
turning a requested invariant into the appropriate query and test cases.

Required correction: show a complete violation-finding example and an
existential example, including a distractor that exposes a weaker property.
Walk through construction, isolated validation, adoption, baseline, changed
source, and interpretation of the comparison. Keep limitations specific to
what each example actually establishes.

### Medium: examples omit the result-to-decision step

Most skills list calls over illustrative `src/storage.py::save` paths. They do
not show the tool response, explain which fields justify the next action, or
demonstrate the final answer. "Inspect uncertainty" is incomplete instruction
without an example of a partial response and the appropriate next step.

Required correction: at least one worked problem per skill, with the initial
symptom/question, minimal source, calls, relevant response excerpts, subsequent
decisions, and a supported conclusion. Add one failure/ambiguity case where it
changes the workflow. Avoid teaching generic programming knowledge the agent
already has; focus on Ken-specific interpretation and choices.

### Medium: several descriptions promise broader workflows than their examples

The bug skill starts with a database-lock error but its only example follows a
`save` result, without connecting the two. The change-planning skill lists five
relationships without showing how a concrete change selects among them. The
architecture skill describes roles without showing a map or explaining a real
ambiguous boundary. These are useful entry points, not complete worked guides.

## Assessment by skill

| Skill | Present value | Missing instruction | Suitable acceptance exercise |
| --- | --- | --- | --- |
| `ken-locate-code` | Strongest routing guide; distinguishes text, symbols, files, wiring, and documentation. | A discovery-to-read sequence, competing candidates, and actual result interpretation. | Locate a behavior where a documented wrapper and executor have similar names. |
| `ken-investigate-bug` | Connects recall, implementation, consumers, tests, and contracts. | A coherent bug, reproducible symptom, evidence, root cause, and repair verification. | Trace an identifier discarded by a wrapper to a failing caller. |
| `ken-plan-change` | Distinguishes impact, import dependents, and historical cochange. | A concrete change with tool-selection decisions and a resulting verification plan. | Change a return contract across an imported caller and relevant tests. |
| `ken-understand-architecture` | Preserves the hypothetical status of structural roles. | A complete call map, source-backed explanation, and an unresolved-boundary example. | Explain entry, coordination, and effect across three modules. |
| `ken-reuse-code` | Useful import-alias example and availability obligations. | A complete caller/candidate example, response fields, and a rejected candidate. | Resolve a callable imported under an alias while rejecting an incompatible candidate. |
| `ken-find-code-patterns` | One working query shape and honest budget caveats. | Language instruction, query construction, relational examples, and diagnostics. | Author an unseen query requiring captures to be shared across relationships. |
| `ken-prevent-regressions` | Rule lifecycle, isolated examples, and comparison semantics. | Query derivation, a violation rule, counterexamples, and complete adoption sequence. | Construct a new rule that rejects both a real regression and a misleading success case. |
| `ken-resume-work` | Most complete state semantics and a concrete justification object. | A two-session walkthrough, stale-input repair, no-memory fallback, and supported final answer. | Reuse an unchanged conclusion, then revisit only the evidence invalidated by a source edit. |

## Design from a person's investigation

Start each skill with the person's uncertainty and the evidence needed to
resolve it. Choose a tool because it answers the next question. A worked
example must connect question, observation, interpretation, and next action;
the result determines the path rather than a mandatory sequence of API calls.

### Locate code

**Question:** "Where is the manifest actually written?"
Find plausible owners from the responsibility or a known identifier, read the
best candidate, and check whether it performs the effect or delegates it. When
it delegates, follow the concrete target only as far as needed. When candidates
compete, compare the evidence for the requested responsibility. Finish with a
source-backed location and a short explanation of the entry/executor distinction
if it matters. `who`, `find`, `read`, and sometimes `roles` serve these questions.

### Investigate a bug

**Question:** "Saving succeeds, but the caller receives no identifier. Where
does the expected value disappear?"
Use or obtain a reproduction. Locate the producer and inspect its contract,
then inspect the relevant wrapper/caller and observed result flow. If the value
is returned unchanged there, continue to the next relevant consumer; if a wrapper
discards it, test that explanation. A fix should make the failing example pass
while preserving the intended behavior. `impact` supplies a partial map, source
reading explains the defect, and a test distinguishes the diagnosis from a guess.
Relevant saved knowledge can remove work at any point.

### Plan a change

**Question:** "If save returns a record instead of an integer, what must change?"
State the compatibility obligation first. Inspect consumers that use the result
as an identifier, then relevant tests and contracts. Historical cochange is useful
when imports miss an associated responsibility; it need not be queried for every
edit. Produce a concrete list of affected interfaces and verification tasks.
Compare compatible existing contract receipts after the edit, and explicitly
identify obligations that need runtime tests or direct inspection.

### Understand architecture

**Question:** "What happens between this command and a file being written?"
Start at the entry point and follow one representative request through its
collaborators. At each boundary ask who owns the next decision, what data crosses
it, and who performs the effect. Inspect code to support a role hypothesis.
Finish with the bounded flow and its important responsibilities; identify an
unresolved external or dynamic boundary instead of inventing the missing link.
The output is an explanation of the observed system, not a list of graph nodes.

### Reuse code

**Question:** "Does the project already have a writer with the guarantees this
caller needs?"
Describe the required behavior, inspect candidate contracts and implementations,
and reject incompatible candidates before choosing a spelling for the call.
For a compatible Python candidate, inspect availability from the actual caller
file: an existing alias may be enough, an instance may be needed, or an import
may be missing. Resolve the reported obligations and validate the integration.
Availability helps access a candidate; source evidence establishes why to use it.

### Find code patterns

**Question:** "Where are there more instances of this suspicious structure?"
Write a minimal example that should match and a nearby example that should not.
Identify the relationship that separates them. Learn the corresponding KQL2
construct, build the smallest query, and execute it on those examples before
searching the relevant code scope. Read representative hits to distinguish a
structural match from a confirmed bug. If the query is unsupported or incomplete,
change the inspection method or scope while retaining that limitation.

### Prevent regressions

**Question:** "How will we notice if this specific mistake returns?"
Start from a demonstrated bug or adopted invariant. Decide whether a source
contract expresses a useful part of it, and identify the positive witness or
forbidden violation. Test valid code, the regression, and a misleading lookalike
that defeats a weaker rule. Then validate and adopt the contract within the task's
scope. Demonstrate its before/after result and state exactly what it guards.
Automation is an optional subsequent choice, not the starting point.

### Resume work

**Question:** "What did we already establish, and can I still rely on it?"
Retrieve the relevant conclusion, inspect its sources, assumptions, and validity,
and decide whether it answers today's question. Reuse sufficient unchanged
evidence with attribution. If inputs changed, inspect those inputs and revisit
the affected inference, expanding only when needed. If no useful memory exists,
investigate normally. Save the revised conclusion and support once there is a
meaningful learning to preserve.

Each rewritten skill should include one concrete successful investigation and
one important branch, such as competing candidates, a missing import, an
incomplete query, or changed evidence. State what evidence makes the requested
answer adequate; do not force every task through every Ken tool.

## KQL2 reference requirements

Organize the installed reference around executable tasks:

1. A complete program: `language`, `module`, `query`, clauses, and `select`.
   Explain that the query module is a namespace, not the searched filesystem path.
2. Captures and selectors: declarations, containment, repeated identities,
   properties, literals, regex/list filters, and scope.
3. Combining constraints: joins, `where`, alternatives, correlated absence,
   optional evidence, and the coverage required for negative claims.
4. Calls and values: call occurrence versus callable target, `body`, `let`,
   `return`, usages, ordering, and relevant unsupported cases.
5. Reuse: named patterns, parameters, imports/libraries, and their actual API.
6. Running and interpreting: MCP and CLI, source scope, compact versus full
   results, completion, coverage, unknown candidates, truncation, and errors.

Not every skill needs to load this reference: `who`, `impact`, `roles`, and
`available` users can rely on those tool interfaces without authoring KQL2.
The two authoring skills must have direct access to the relevant chapters.

The design documents are not ready to copy wholesale. `docs/design/kql2/README.md`
explicitly distinguishes a normative target from the implemented subset, and
implementation notes contain dated capability descriptions. Derive the guide
from current compiler/executor behavior and execution tests. Preserve one
maintained source for shared language material while ensuring installation in
another repository includes everything the skill links to.

## Why the prior validation was insufficient

The 108 passing tests covered installer behavior and existing tool contracts.
The native Harness probe explicitly used no model. The bundled example test
loads a query already authored by us and checks its provided positive/negative
fixtures. These establish operability of the package and example, but do not
measure whether an unfamiliar agent can learn to solve a new problem from it.

Keep those checks, and add a separate learning evaluation: an unfamiliar agent
receives only the installed skill, its references, and a small project with an
unseen task. Check whether it chooses suitable tools, constructs valid queries,
distinguishes the distractors, interprets incomplete results, and supports its
answer. A successful tool call alone is not the acceptance criterion.
