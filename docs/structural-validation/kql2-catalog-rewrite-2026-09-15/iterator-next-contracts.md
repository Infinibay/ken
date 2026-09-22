# Iterator: bounded source-language migration plan

Read-only review while the integration suite runs. No production or tests changed.
The TOML contains eight variants and two named operations. Completing this file
requires implementing source semantics, not renaming its graph relations.

## Contracts and migration decisions

| Entry | Algorithm and honest claim | Work needed |
|---|---|---|
| generator | A non-context-manager callable suspends and emits a value. No claim of progress. | BODY `yield _;`; retain generator/context-manager selector properties. |
| delegated-generator | Same callable delegates emission to an iterable. | BODY `yield from _;`; distinguish delegation from ordinary yield, including JS `yield*`. |
| explicit-cursor | Python `__iter__` returns its own receiver; `__next__` changes and reads stored state. | BODY receiver return is available. Existing public reads/writes restrictions can preserve the modest state signature. Do not claim finite traversal. |
| paired-cursor | `next` changes stored state inspected by `hasNext`. | Existing source declarations and reads/writes already express the signature. Add BODY only for stronger advancing-element refinement; arbitrary updates must not be described as numeric progress. |
| external-cursor | C++ next/isDone/currentItem share state, next updates it. | Already source authored; preserve conservative signature and do not infer overloaded increment semantics. |
| delegated-cursor | Python self-returning iterable advances the retained iterator and returns that result. | Generic accredited builtin-call selector plus BODY argument and returned-value correlation. A function merely named next is insufficient. |
| callback-iterator | Go loop invokes callback on the actual element; false causes exit from that loop/function. | Captured iteration source, inline call predicate or captured result in if, scoped break; exact exit target and branch reachability. |
| async-iterator | Async consumer advances an async loop over the result of an async yielding producer. | Yield matcher, iterate accepting captured Value, async loop property and source-result identity. |
| iterate_over | Expose source, item binding, body region and iteration occurrence for composition. | Iteration selector captures these source-level roles without requiring an already-bound collection. Distinguish item Binding from per-iteration Value. |
| advancing_element | Read items at current index, advance same index by one, return read value. | Indexed expression result capture in let; arithmetic assignment support with actual origin; same-path subsequence already provides sequencing. |

## Proposed source contracts (new parts explicitly proposed)

Yield instructions are already parsed but rejected by BODY compilation. Implement
those existing clauses instead of introducing a new public detector function:

```graphql
callable $iterator {
  generator: true; context_manager: false;
  body { yield _ as $suspend; }
}
// Delegation variant uses: yield from _ as $suspend;
```

Select yielded operand with the usual binding/value semantics; alias captures the
Operation. Check the current callable owner, exclude nested lambda/function yields,
and follow the owner's CFG. A dead yield following return must not become a certain
reachable match. Yield delegates must retain the distinct source kind. Do not turn
async yields into thread operations.

For async consumption, use the following target syntax; `iterate` currently rejects
captured Value collections and properties, so this is an extension:

```graphql
callable $producer { async: true; body { yield _ as $suspend; } }
callable $iterator {
  async: true;
  body {
    let $source = call $producer {};
    iterate $source as $item as $loop {
      async: true;
      body {}
    }
  }
}
where $producer != $iterator;
```

The implementation must correlate the iterable with the call's produced Value,
including a stored alias, not confuse a call occurrence with its result. Synchronous
iteration over the same expression, an awaited unrelated call, an unrelated async
producer, and overwritten aliases are negatives. Empty nested BODY means identify
the loop without requiring a particular instruction in its body.

For Go callbacks:

```graphql
callable $iterator {
  language: "go";
  parameters { param $callback {} param $items {} }
  body {
    iterate $items as $element as $loop {
      body {
        let $accepted = call $callback { argument $element; };
        if (!$accepted) { return; }
      }
    }
  }
}
```

This shape covers callback calls inline in the branch condition only if the call
operation/result is correctly part of that condition's execution trace. Explicit
saved bool should work too. Add the positive-test/else alternative. Add `break;`
only with proof it exits the matched loop; a break of an inner switch/loop does not
satisfy cancellation. Return must leave the iterator callable, not a nested closure.
No `while` implementation is required to complete current variants: it is a useful
independent language extension, not a prerequisite that should block this migration.

For advancing-element, target a value capture rather than a write-count surrogate:

```graphql
type $unit {
  field $index {} field $items {}
  method $next {
    name: ["next", "__next__"];
    body {
      let $value = $items[$index];
      $index = $index + 1;
      return $value;
    }
  }
}
```

Verify the let syntax/compiler first: current let execution is call/construction
oriented. Add generic indexed-expression matching and origin capture, not an
`advancing_element()` primitive. Noise is allowed, overwriting the returned local
with another value must fail, saving an alias before overwriting should pass.
`+= 1` and native ++ require accredited normalized arithmetic semantics. Step zero,
wrong index, wrong collection and reversed advance/read order are negatives.

Delegated cursor requires an accredited callable selection such as proposed
`callable $advance { builtin: "python.next"; }`, then ordinary BODY call with the
cursor field argument followed by returning the captured result. The builtin
property must use lexical resolution: local next definitions, parameters and imports
shadow Python's builtin. This is generic source API identity, not a renamed
ADVANCES_ITERATOR relationship. If no builtin declaration model exists, implement
that model first; name equality is not an acceptable substitute.

## Parallel implementation boundaries

1. **BODY owner**: implement yield/yield-from, returned indexed-expression capture,
   and targeted break; unit tests per primitive. All touch body.py, so one owner
   should serialize patches. Existing parser yield and break ASTs should be reused.
2. **Iteration owner**: add source iteration selector/properties and Binding/Value
   output roles in an isolated module; coordinate one small BODY hook with owner1.
   Add async loop filtering and captured iterable origin resolution.
3. **Protocol-model owner**: Python builtin next identity with shadowing negatives;
   does not modify BODY. After its API is stable, author delegated cursor.
4. **Catalog/test owner**: migrate variants after respective primitives land;
   preserve all valid source fixtures and run focused Iterator family tests. Add
   source-only authoring guard; leave public modest read/write contracts intact.

Do not let all owners edit body.py concurrently. Benchmark each new primitive on
many unrelated methods and repeated source patterns. Index operation kinds and loop
sources per callable; reuse existing per-pattern BODY memo. Include every captured
output and async/protocol condition in memo keys and serialized-query fingerprints.
Do not traverse arbitrary graph neighborhoods for each candidate loop.

## Validation and completion gate

Start with existing `test_iterator_async_iterator.py`, callback, augmented-state,
C++ iterator, iteration-values and algorithm-iterator suites. Add per-language
positive/noise/negative cases for all currently declared languages, including
C# yield return versus yield break, Python context managers, nested/dead yields,
JS delegated yields, Go false-branch cancellation and builtin shadowing. Existing
old negative oracles must be reviewed, never silently flipped to make migration pass.

Completion means all eight variants and both operations remain executable with
source syntax, their advertised output bindings remain composable, no edge/walk in
authored queries, no loss of valid variants, and targeted tests plus integration
suite and bounded-state performance probes pass. Unsupported analysis returns
unknown rather than inventing origin, protocol identity or break destinations.
