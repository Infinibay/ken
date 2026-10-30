# Call order and returned values on modeled paths

Read this reference when the question asks about **every modeled normal path**
of a Python function. For structural inventories, ownership, scoped absence or
other relationships, use the KQL2 recipe for that relation instead. These
interfaces combine KQL2 candidates with a separate source-path analysis.

When the function is unknown and the requested contract fits the vocabulary, use
`ken_code_find(contract="os.fsync -> os.replace",
search_path="src/ken/vectors.py")`. It uses KQL2 to find functions with a
direct `replace` call, then checks each candidate's modeled normal paths for
the requested order. In Ken, `_atomic_write` has a witnessed contract;
`compact` has a direct `replace` candidate but remains unknown because its
loops are not modeled. Read `direct_call_locations` beside `analysis.status`
and `analysis.blockers`; neither a direct call nor complete direct-search
coverage proves the all-path contract. The search can miss callers and helpers
without a direct KQL2 candidate. Use the returned `selector` in
`ken_code_check` to inspect one candidate with branch assumptions or an
explicit callee prior. In a shell, run
`ken code-find 'os.fsync -> os.replace' --in src/ken/vectors.py`; add `--full`
for traces and the query.

For one already known Python function, `ken_code_check` is a short interface
for two specific questions: “does every modeled normal path call this target,
with these arguments, after that call?” and “does every modeled normal return
forward this call's value?” For example,
`ken_code_check(selector="src/ken/vectors.py::_atomic_write",
contract="os.fsync -> os.replace(_, path)")` combines a scoped KQL2 candidate
with source-path reasoning. It reports `all_paths_called`, `missing_path`, or
`unknown` and names the calls that prevent a conclusion. To check value
forwarding, use `contract="return save(user)"`; this accepts a direct return,
local assignment aliases, or an undecorated project-local helper with a unique
binding. A constrained same-class `self.__private(...)` method can also be
followed, with a visible `binding_assumptions` entry. Public methods remain
dynamic: `method_candidates` gives their declaration and call locations to
inspect, not a proof that the local body ran. It does not accept a discarded
or overwritten result. It
reports `all_paths_return_value`, `missing_path`, or `unknown` and shows the
producer and return lines. The KQL2 `candidate_return` can remain unknown
while source-path evidence witnesses the return through a helper; inspect the
two separately. An absent KQL2 candidate is not exhaustive across helpers or
unsupported control flow; the result says `absence_exhaustive: false`.
`dependencies` identifies any imported source followed.
For an unknown,
`next_checks` identifies calls to inspect and shows conditional probability
bounds for their possible effects; it does not invent a prior. A unique short
name such as `selector="_atomic_write"` searches `src/` by default; use an
exact file selector or `search_path` when the name is ambiguous. Use custom
KQL2 for relationships beyond that contract vocabulary or patterns that a
direct `ken_code_find` candidate query cannot express.
In a shell, run `ken code-check Class.method 'A -> B(_, value)'` or
`ken code-check Class.method 'return B(value)'`;
`--full` adds the source traces. A prior such as `--effect-prior helper=0.6`
models a helper's chance of satisfying the requested contract. It does not
prove that `A` happened first, and it is not a learned probability of a bug. Each
unresolved call site has its own effect key; repeated callee names need full
keys from `unresolved_effects` before assigning distinct priors. The analysis
covers modeled normal-completion paths, not runtime success or exception exits.
Priors assigned to different call sites are treated as independent; that is
also an investigator assumption, not evidence that their effects are independent.


## Follow the unresolved boundary

For a helper that remains unresolved, inspect `uncertain_calls`, `next_checks`,
and `order_uncertainty`. For `self.method(...)`, `method_candidates` provides
possible declarations; a local method body does not prove runtime dispatch.
A source-stable private method can be followed only with the binding premise
reported by the analyzer. `--full` retains effects and traces omitted by the
compact answer. Read the implicated path and reproduce behavior before calling
it a bug.

## Keep the original quantifier

A KQL2 returned-value witness can coexist with another path that discards the
result. If a negated BODY relationship is unsupported or yields unknowns, the
absence of rows is inconclusive. For one known required wrapper, a scoped
`some_match` rule can preserve an existential source obligation. Record that
narrower domain explicitly and validate a good neighbor beside the broken
wrapper; it does not certify every wrapper or every return path. Use path
analysis and behavioral tests for the stronger obligation.
