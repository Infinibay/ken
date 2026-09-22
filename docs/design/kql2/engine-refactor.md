# KQL 2 engine: layer map, duplication audit and staged refactor plan

Status: **read-only mapping**. This document was produced without touching
production code; every claim carries `file:line` evidence read in the session
that wrote it. It is the working map for a later, staged refactor.

Scope: `src/ken/kql2/**` plus the layer it stands on, `src/ken/structural/**`
and `src/ken/structural_store/**`. Note on naming: there is **no**
`src/ken/kql2/relational.py`. The relational IR the KQL 2 graph path lowers to
is `src/ken/structural/relational.py` (`Node`, `Query`, `RELATIONS`), imported
at `src/ken/kql2/graph.py:16`.

## 1. One front door, two engines

The only public entry point is `ken.kql2.service.search`
(`src/ken/kql2/service.py:36`). Its docstring says "Explicit KQL2 entry point,
isolated from the existing KQL1 catalogue" (`service.py:1`).

`search()` runs these phases in order:

| # | Phase | Code |
|---|---|---|
| 1 | Argument/budget validation | `service.py:42-43` (`invalid execution budget`) |
| 2 | Packaged libraries overlay | `service.py:45-46` -> `catalog.with_packaged_libraries` (`catalog.py:65-83`) |
| 3 | Compile (cached) | `service.py:48-50` -> `compilation.compile_query` (`compilation.py:48`) |
| 4 | Target/path resolution | `service.py:52-56` |
| 5 | Frontend fingerprint | `service.py:57` -> `frontend_fingerprint` (`service.py:26-33`) |
| 6 | Store acquisition | `service.py:58-62` (`AcquisitionLock`, `Store`) |
| 7 | Project walk + per-unit IR reuse | `service.py:82-120` (`iter_files`, `store.find_unit`/`put_unit`, `lower_source`) |
| 8 | Evaluation | `service.py:23` imports `.execution.execute`; result shaping later in `search` |
| 9 | Artifact retention | `compilation.py:43-45` `artifact_key`, `cache.ArtifactCache` (`cache.py:43`) |

Phase 3 is where the architecture forks. `compiler.compile`
(`compiler.py:627-662`) does:

* a structural depth guard over the AST plus libraries (`compiler.py:638-647`,
  `compiled AST depth limit exceeded` at `:643`);
* `libraries.resolve` + `models.specialize` (`compiler.py:649-650`);
* the routing decision at `compiler.py:653-655`:

```python
from .graph import has_graph, compile_graph
if relational or has_graph(tree, query):
    return compile_graph(tree, query)
```

* otherwise `_expand_file` (`compiler.py:665-721`) distributes top-level
  alternatives and each branch goes through `_compile`
  (`compiler.py:101-596`), producing `Program(steps=...)`
  (`compiler.py:80-94`).

`has_graph` (`graph.py:89-114`) is therefore the **planner**, and its test list
is the effective definition of "this query needs the relational engine". It
returns `True` for: `source_usages`, `source_require`,
`declaration_initializer`, an ownerless `initializer`, `gap` with an `exit`
flag, the `macro`/`type_parameter` selectors, any `edge`/`walk`/`tally` clause
(recursively), a `type` property whose value is `nominal(...)`/`parameter(...)`,
the property names listed at `graph.py:105`
(`reassigned escapes initial writes effective exported target result_family
captures discarded derive unreplaced completes`), and a `use` of a local
pattern that either declares an `out Call` parameter or transitively contains
any of the above (`graph.py:107-112`).

### 1.1 Path A — graph/relational engine

* `graph.compile_graph` (`graph.py:518-528`) validates that exactly one
  `query` declaration is selected (`choose exactly one query`, `:522`), calls
  `lower` for its side effect of validation (`:525`) and returns a `Program`
  whose `graph=` carries the raw declarations.
* `graph.relational_plan` (`graph.py:531-532`) re-runs `lower(program.graph,
  program.name, program.fingerprint)`.
* `graph.lower` (`graph.py:172-515`) is the validator **and** the lowering
  pass: it resolves pattern dependencies with hygienic namespaces
  (`declaration`, `:183-197`), and `block` (`:201-515`) walks clauses turning
  them into `Node`s.
* `execution.execute` (`execution.py:85-501`) evaluates the plan: "Streaming
  indexed structural joins with explicit unknown/incomplete outcomes"
  (`execution.py:1`). `prepare` (`execution.py:45-63`) orders scans
  bound-owner-first. Results accumulate in `Outcome`
  (`execution.py:31-42`), which is also where the user-visible
  `states`, `elapsed_ms`, `plan`, `reason` fields live.
* `graph_execution.execute_graph` (`graph_execution.py:48-78`) is the
  cached-plan variant used against a `graph_index` (`graph_execution.py:21-45`).

### 1.2 Path B — body/source engine

* `_compile` (`compiler.py:101-596`) builds `Scan`/`Action`/`BodyPattern`
  steps; the `body` clause is compiled by `compile_body`
  (`compiler.py:302-308`).
* `compile_body` (`body.py:120-597`) validates a BODY and returns a
  `BodyPattern` (`body.py:38-46`).
* `execution.SourceExecutor.match` (`source_execution.py:110-196`) matches a
  body against the **current immutable graph**, not the SQLite store:
  "Run the existing CFG BODY matcher against the current immutable graph.
  Adapters expose stable source IDs, without SQLite copies, reparsing, or a
  second project analysis" (`source_execution.py:1-4`).
* `SourceView` (`source_execution.py:18-63`) builds per-owner indexes
  (`owned`, `operations`, `entities`) so a BODY never scans the project.
* `BodyEngine` (`body.py:600-2270`) is the matcher itself.

## 2. Layer map: one module, one responsibility

Sizes are source lines; line anchors are the symbol ranges read this session.

| Module (lines) | Single responsibility | Depends on |
|---|---|---|
| `syntax/lexer.py` (166) | source text -> tokens with spans; `Lexer` `29-165`, `Token` `18-21`, `ParseError` `11-14` | - |
| `syntax/parser.py` (908) | tokens -> immutable syntax tree; `Parser` `18-898`, keyword tables `SELECTORS`/`RESERVED`/`QUERY_BP`/`SOURCE_BP` `10-14`, `parse` `901-907` | `syntax/lexer.py`, `syntax/ast.py` |
| `syntax/ast.py` (84) | frozen syntax vocabulary: `Expr` `29`, `SourceExpr` `39`, `Clause` `51`, `Declaration` `64`, `File` `78` | - |
| `libraries.py` (3843 B) | `resolve(tree, libraries)` import/include overlay, called at `compiler.py:649` | `syntax` |
| `models.py` (84) | `specialize` `9-83`: generic parameter instantiation, called at `compiler.py:650` | `syntax` |
| `compiler.py` (722) | capability schema (`KINDS` `16`, `TYPES` `23`, `PROPERTIES` `25`) + `Program` IR (`80-94`) + clause validation/build (`_compile` `101-596`) + **engine routing** (`compile` `627-662`) | `syntax`, `logic`, `semantic`, `source_types`, `body`, `graph`, `models`, `libraries`, `catalog` |
| `graph.py` (533) | the planner (`has_graph` `89-114`) and the relational path: validation + lowering to `structural.relational.Query` (`lower` `172-515`, `compile_graph` `518-528`, `relational_plan` `531-532`) | `structural.query`, `structural.relational` `:16`, `source_patterns`, `source_quantifiers`, `source_usages`, `body`, `semantic` |
| `body.py` (2271) | the BODY language: validation/compilation (`compile_body` `120-597`) and matching (`BodyEngine.match` `615-2270`) | `syntax`, `values`, `source_*` helpers |
| `semantic.py` (231) | predicate -> published relation mapping (`RELATIONS` `20-45`, `UNARY_RELATIONS` `51-54`) and demanded fact linking over an immutable snapshot (`SemanticRelations` `57-230`) | `structural.semantic`, `structural_store`, `values` |
| `execution.py` (527) | relational plan evaluation ("streaming indexed structural joins", `:1`); `Outcome` `31-42`, scan ordering `prepare` `45-63`, `execute` `85-501` | `compiler`, `logic`, `semantic`, `expressions`, `values`, `source_ast`, `body`, `structural_store` |
| `source_execution.py` (197) | source-path adapter: per-owner indexes (`SourceView` `18-63`), `SourceSemantics` `66-94`, `IndexedBodyEngine` `97-107`, `SourceExecutor.match` `110-196` | `body`, `semantic`, `values`, `structural_store` |
| `graph_execution.py` (79) | cached-graph variant of the same join: `graph_index` `21-45`, `execute_graph` `48-78` | `codec`, `execution` |
| `compilation.py` (95) | per-project compilation retention; `Prepared` `18-21`, `artifact_key` `43-45`, `compile_query` `48-87`, `implementation_fingerprint` `32-40` | `cache`, `compiler`, `execution`, `syntax` |
| `cache.py` (124) | byte-bounded LRU with single-flight for immutable artifacts; `retained_size` `19-40`, `ArtifactCache` `43-123` | stdlib only |
| `service.py` (230) | the public `search()` orchestration and result serialization (`36-204`), fingerprinting (`26-33`) | `compilation`, `codec`, `execution`, `catalog`, `structural_store`, `structural.service`, `structural.frontend` |
| `catalog.py` (88) | packaged pattern libraries for `ken.catalog.*` imports (`libraries` `38-39`, `with_packaged_libraries` `65-83`) | `compilation` |
| `logic.py` (141) | user predicates: components `25-80`, recursive `PredicateRuntime` `83-140` | `compiler` |
| `expressions.py` (169) | scalar/attribute expression evaluation, `EvaluationError` `14-17` | `values` |
| `values.py` (101) | value algebra: `Unknown`, `UNKNOWN`, `conjunction`/`disjunction`/`negation` (`62-100`) | - |
| `source_patterns.py` (296) | selector clause -> graph clauses (`KINDS` `13`, `DOMAINS` `25`, `selector` `33`) | `syntax`, `semantic` |
| feature modules | one published relation family each, invoked from `graph.lower`: `source_quantifiers.py` (`require`), `source_usages.py` (`usages`), `constructor_initializers.py`, `declaration_initializers.py`, `effective_fields.py`, `receiver_effects.py`, `source_type_filter.py`, `source_assignment_candidates.py`, `source_storage_contracts.py`, `source_types.py`, `source_expressions.py`, `source_ast.py`, `source_callable_values.py`, `boolean_results.py` | `graph`/`execution` |
| `codec.py` / `cli.py` | artifact encode/decode; CLI wrapper | `compilation`, `service` |

## 3. Duplicated validation

A scan of every `fail(...)`/`raise ...Error(...)` message literal in
`src/ken/kql2` and `src/ken/structural` (338 distinct messages) found 24
messages raised from more than one site. Five of them cross the
`compiler.py` <-> `graph.py` boundary, which is the real hazard: the two
engines validate the *same* language with different code. Prefer the
`validate_matcher` pattern, which is imported once (`compiler.py:13`) and
called from both paths (`graph.py:244`).

| Message | Sites | Consequence |
|---|---|---|
| `BODY requires a callable owner` | `compiler.py:303-304`, `graph.py:297-298` | **the two owner sets differ**: `compiler.py:303` accepts `callable/method/function/constructor/module_decl/module`; `graph.py:297` accepts `callable/method/constructor/module_decl`. `function $f { body {...} }` compiles on the body path and is rejected once the query is routed to the relational path (e.g. as soon as it also contains `writes`/`target`), so the same file can compile or not depending on an unrelated clause. |
| `duplicate declaration` | `compiler.py:107`, `compiler.py:668`, `graph.py:176`, `models.py:12` | four independent owner checks; the same input can be rejected with a different span/reason per path. |
| `choose exactly one query` | `compiler.py:130`, `compiler.py:671`, `graph.py:522` | three sites, same rule. |
| `pattern input must already be bound` | `compiler.py:347`, `graph.py:352` | `use` argument validation implemented twice (`compiler.py:321-349` vs the alias/parameter mapping in `lower`, `graph.py:183-197`). |
| `invalid execution budget` | `service.py:43`, `execution.py:91` | same invariant, two spellings. |

Intra-module duplication inside the BODY language is heavier and is the reason
`compile_body` and `match_step` must be changed together (see §4):

| Message | Sites in `body.py` |
|---|---|
| `call requires a bound Callable target or a retained callable` | `478`, `525` |
| `let capture requires a Value role` | `410`, `458`, `507` |
| `operation evidence capture must be fresh` | `419`, `465`, `586` |
| `receiver requires a bound storage role` | `489`, `542` |
| `argument for requires a bound Parameter` | `482`, `529` |
| `unreplaced requires the receiver place of the same call` | `503`, `572` |
| `unsupported call constraint` | `505`, `574` |
| `source operand requires a bound storage, parameter or captured value` | `358`, `367` |
| `index key requires a bound operand` | `342`, `347`, `349` |
| `iterate key requires a bound operand` | `233`, `235` |
| `condition requires a bound source binding or captured value` | `199`, `206` |

## 4. The `body.py` matcher: shape and separability

`body.py` is 2271 lines. `compile_body` (`120-597`, 478 lines) plus
`BodyEngine.match` (`615-2270`, 1656 lines) are 2134 lines, i.e. **94 % of the
module**. `BodyEngine` has only three methods: `__init__` `601-609`,
`source_unit` `611-613`, `match` `615-2270`. There is no dispatch table: a scan
for 4-space `elif` inside `match` returns **0**, so the whole clause language is
handled by an if/return chain inside `match_step` and its 20 helpers.

### 4.1 Clause families and where they are dispatched

`compile_body` branches on **13 distinct clause kinds** in the order it
enforces (macro must anchor first):

| Kind | Validation site (`compile_body`) |
|---|---|
| `macro` | `143` |
| `where` | `148` |
| `initializer` | `157` |
| `gap` (terminal / interior) | `170`, `177` |
| `adjacent` | `188` |
| `if` | `193` |
| `iterate` | `223` |
| `selector` (nested `method`/`callable`/`field`/...) | `286`, `288` |
| `assign` | `375`, `577` |
| `insert` | `376` |
| `clear` | `385` |
| `let` | `399` |
| `call` | `512` |

Helper closures: `expression` `126-133`, `remap` `134-137`, `free` `149-153`,
`condition` `194-208`, `source` `308-370` (the origin resolver that produces the
`source operand requires ...` errors of §3).

`match_step` branches on **16 distinct clause kinds** (union of both lists plus
`construct`, `yield`, `return`):

| Kind | Sites in `match`/`match_step` |
|---|---|
| `let` | `1052`, `1373`, `1441`, `1850`, `1982`, `2064` |
| `call` | `1070`, `1449` |
| `insert` | `1101`, `2062` |
| `clear` | `1190` |
| `if` | `1213`, `2252` |
| `macro` | `1247` |
| `iterate` | `1252`, `1261`, `2252` |
| `construct` | `1374` |
| `yield` | `1875` |
| `return` | `1888`, `2156` |
| `assign` | `1948` |
| `selector` | `2033` |
| `where` | `2216` |
| `gap` | `2223`, `2228` |
| `adjacent` | `2231` |

### 4.2 The helpers `match` is actually made of

| Helper | Lines | Lines of code |
|---|---|---|
| `unit_operation` | `693-697` | 5 |
| `rows` / `rows_to` | `731-742` | 12 |
| `successors` | `743-767` | 25 |
| `parts` | `770-786` | 17 |
| `reference` | `787-788` | 2 |
| `declaration_group` | `789-798` | 10 |
| `captured_reaches` | `799-810` | 12 |
| `member_place` | `812-857` | 46 |
| `source_matches` | `859-1013` | 155 |
| `boolean_rows` | `975-978` | 4 |
| `consumes_value` | `999-1002` | 4 |
| `value_node` | `1014-1017` | 4 |
| `iteration_value_at` | `1021-1044` | 24 |
| `constructs` | `1046-1049` | 4 |
| `inserted_rows` | `1107-1108` | 2 |
| **`match_step`** | **`1051-2072`** | **1022** |
| `connectors` | `2074-2104` | 31 |
| `interval_ok` | `2105-2154` | 50 |
| `completed_linear_arm` | `2155-2169` | 15 |
| `terminal_ok` | `2171-2200` | 30 |

### 4.3 Verdict on separability

* The infrastructure helpers (`rows`, `rows_to`, `successors`, `parts`,
  `member_place`, `value_node`, `connectors`, `interval_ok`) are already pure
  functions of `(state, place)`; they can move to a `body_matching.py` without
  touching semantics.
* `source_matches` (155 lines) is the single origin/role resolver shared by all
  call-like clauses, so a per-kind module can take it as a parameter instead of
  a closure.
* The blocker for a clause registry is that `match_step` mutates loop state
  (`bound`, `outputs`, `roles`, `pending_gap`, `anchored`) that `compile_body`
  also maintains; a `kind -> {validate, plan, match}` registry is therefore
  reachable only *after* §5's validation unification, and each entry must be
  handed a state object rather than a closure over locals.
* Evidence that the two halves already agree by construction: `BodyPattern`
  (`body.py:38-46`) keeps the compiled clause tree
  (`owner`, `clauses`, `adjacent`, `outputs`, `nested`, `controls`, `linear`,
  `call_aliases`), and `match` re-reads it, so clause identity survives
  compilation (`source_execution.py:150-164` still walks `pattern.clauses`);
  the missing piece is only the *shared* validator.

## 5. Traceability: where a per-clause reason can come from

User-visible uncertainty is today a set of free-form strings produced at the
point of failure, with no link back to the clause that raised it.

| Producer | String |
|---|---|
| `source_execution.py:182` and `:189` | `source_body:unknown` (a whole-BODY verdict; `@unknown:<role>` is also written as a *value* at `:188`) |
| `source_type_filter.py:22`, `:32`, `:39`, `:52`, `:65` | `receiver_escape:unknown`, `source_storage:unknown`, `parameter_writes:unknown`, `normal_completion:unknown`, `source_type:unknown` |
| `effective_fields.py:49`, `:54`, `:60`, `:85`, `:105` | `effective_field:descriptor_or_method_shadow`, `effective_field:private_inherited_field`, `effective_field:<reason>`, `effective_field:type_unknown` |
| `execution.py:101`, `:118`, `:181`, `:184`, `:472`, `:483`, `:488` | `max_states`, `max_rows`, `snapshot_expired`, `cancelled`, `timeout`, `regex_timeout`, `evaluation_depth` |
| `graph_execution.py:66` | `reason=str(exc)` (raw exception text) |

Structured traces that do exist, and the seams they show:

* `Outcome.plan` and `Outcome.optional_evidence` (`execution.py:40-41`), filled
  by `graph_execution.py:75` as
  `plan=[{'operator': 'relational_graph', 'optimized': ..., 'graph_disk_hit': ...}]`.
* `Row.evidence` — the BODY path already attaches
  `{'body_owner': local_id}` per match (`source_execution.py:192`), and
  `source_usages.py:218` attaches `{'value': value, 'usage_inventory': 'open'}`.
* `service.py:181` surfaces `unknown_candidates` and `reason`;
  `service.valid_cached_result` (`service.py:217-229`) whitelists the result
  keys, so any new trace field must be added there or it will be silently
  dropped for cached results.

Feasibility of naming the clause: `BodyPattern` keeps the clause tree
(`body.py:40`, `nested` `43`, `controls` `44`), the executor re-derives the
input roles from `pattern.clauses` (`source_execution.py:150-164`), and the
failure is known inside `match_step` (`body.py:1051-2072`) where `bound`,
`outputs` and the current `item` are all in scope. So the change is: return the
offending clause identity instead of the boolean `uncertain` that
`engine.match` yields (`source_execution.py:173-175`), and render it as
`body:<kind>@<span>` rather than `source_body:unknown`.

Two constraints measured in the code: `source_execution.py:177` and `:193-196`
memoize at most 16 outcomes per `(pattern, inputs)` key in a 1024-entry LRU, so
per-clause detail is dropped for large matches; and `SourceView`
(`source_execution.py:18-63`) is built per execution, so a trace must not store
`Node` objects beyond the execution.

## 6. Measured baselines

All numbers below were produced in this session from
`/Users/andres/Projects/ken` with `.venv/bin/python`. They are the guard rails a
refactor has to reproduce.

**A. `tests/structural/test_dispatch_table.py::test_dispatch_table_avoids_unrelated_method_parameter_cross_product`**
budget `QueryBudget(max_states=2000)` (`:63`), fixture = python `Registry` plus
150 extra `def method{i}(self, a, b, c, d, e, f): self.field{i} = a`
(`:55-59`).

* pytest `--durations`: **0.93 s**, test green.
* direct probe through `execute_rules`: `complete=True`, `matches == 1`,
  **494.6 ms** wall.
* instrumentation gap: the `execute_rules` result exposes only
  `complete`/`matches`/`outcomes` (the keys printed by the probe), so this
  fixture's *state count* is not observable through the catalogue API - only the
  budget verdict is. Closing that is a prerequisite for being able to say "the
  refactor did not regress this" instead of "it still fits".

**B. `tests/structural/test_catalog_adversarial_matrix.py`** - 2430 collected
cases (`--collect-only -q`), budget
`QueryBudget(max_matches=200, max_rows=500000, max_states=100000, timeout_ms=3000)`
(`:43-44`), 1 xfail (ledger), rest green.

* worst case by states: `template-method#composed-skeleton/noise-20` -
  csharp **15636**, go 14394, cpp 14340, java 13899, python/javascript/typescript
  13152, rust 10884 states; 133 rows examined; 33-46 ms each.
* worst case by rows examined: `command#command-closure/go/noise-20` -
  10262 states, **2639 rows**, 55.9 ms.
* headroom: 15636 / 100000 = **15.6 %** of the budget, i.e. a 6.4x state
  regression turns this suite red. It is the most sensitive gate in the tree.

**C. kql2 BODY-path sweep** - probe over 433 `(entry, language)` executions
through `Executor` with `QueryBudget(timeout_ms=3000, max_states=100_000)`, the
same API the frozen-parity test uses
(`tests/structural/test_catalog_kql2_migration.py:40-41`).

* worst by states: `mediator/python` 2359 states / 698 rows / 8.9 ms;
  `mediator#registered-colleagues/python` 1923 / 650 / 6.1 ms;
  `abstract-factory/java` 753 / 162 / 3.1 ms.
* slowest by wall time: `strategy/java` 15.9 ms at only 253 states - at this
  size the cost is fixed per-case overhead (lowering + executor setup), not
  state growth. Headroom is 42x against the 100 000 budget.

**D. Whole-suite reference** (recorded in a previous session on a frozen tree,
*not* re-measured here): `tests/structural tests/kql2 tests/common_ast` =
12566 passed, 10 xfailed, 0 failed, 358.70 s. Re-run it before and after any
stage of section 7 that touches `body.py` or `compiler.py`.

## 7. Staged refactor plan

Each stage is independently reversible and names the command that gates it.
Order matters: stages 1-3 remove the duplication that stages 4-5 would otherwise
have to preserve twice.

**Stage 0 - this map.** No code. Gate: this file exists and every claim cites a
range read in the same session.

**Stage 1 - one clause-entry validator.** Add `src/ken/kql2/validation.py`
owning the owner-kind sets and the rules duplicated in section 3
(`duplicate declaration`, `choose exactly one query`,
`pattern input must already be bound`, `invalid execution budget`), then call it
from `compiler.compile`/`_compile`, `graph.lower`/`compile_graph`,
`models.specialize`, `service.search` and `execution.execute`.
Gate: `.venv/bin/python -m pytest tests/kql2 -q` and
`.venv/bin/python -m pytest tests/structural/test_catalog_kql2_migration.py -q`.

**Stage 2 - reconcile the BODY owner set.** `compiler.py:303` and
`graph.py:297` accept different owners for the same clause; derive both from
Stage 1's table and decide once whether `function`/`module` are legal BODY
owners and whether `module_decl` is. This makes "same file compiles or not"
independent of which engine the planner picked.
Gate: `tests/kql2/test_source_body_memo.py`,
`tests/kql2/test_saved_source_patterns.py`, and the migration parity file.

**Stage 3 - unify the intra-BODY per-kind checks.** The 11 duplicated messages
of section 3 become one `validate_<kind>` per clause family, called by both
`compile_body` and `match_step`.
Gate: `tests/kql2` plus the migration suites
(`test_command_actions.py`, `test_stored_command.py`, `test_queued_commands.py`,
`test_memento_accessors.py`, `test_iterator_async_iterator.py`).

**Stage 4 - decompose `body.py`.** Move the pure helpers of section 4.2 into
`kql2/body_matching.py`, then express clause handling as a
`kind -> entry` registry that receives an explicit state object instead of
closing over `match_step`'s locals. No semantic change in this stage.
Gate: `.venv/bin/python -m pytest tests/kql2 tests/common_ast -q`, then the
whole frozen catalogue:
`.venv/bin/python -m pytest tests/structural tests/kql2 tests/common_ast -q`.

**Stage 5 - per-clause trace.** Return the offending clause identity from
`match`/`match_step` (section 5), render it as `body:<kind>@<span>`, and extend
`service.valid_cached_result` so cached results keep the new field.
Gate: `tests/kql2/test_source_body_memo.py tests/kql2/test_usages.py
tests/kql2/test_insert_effect.py tests/kql2/test_disk_artifacts.py
tests/kql2/test_unlimited_execution.py`.

**Stage 6 - performance proof.** Re-run the section 6 probes and require:
(A) the dispatch-table budget fixture still green with exactly 1 match and
elapsed within 1.5x of 494.6 ms; (B) the adversarial worst case at or below
15636 states with the `max_states=100000` budget untouched; (C) the BODY sweep
worst case at or below 2359 states.
Gate: `tests/structural/test_dispatch_table.py::test_dispatch_table_avoids_unrelated_method_parameter_cross_product`
and `tests/structural/test_catalog_adversarial_matrix.py`.

**Standing constraint while running any wide suite:** freeze production Python
first. `compilation.implementation_fingerprint` is `lru_cache(maxsize=1)`
(`compilation.py:32-40`), so editing a module while a run is in flight can leave
the parent process with the pre-edit fingerprint and a subprocess with the new
one, which surfaces as a spurious `disk_hit` miss in
`tests/kql2/test_disk_artifacts.py`.
