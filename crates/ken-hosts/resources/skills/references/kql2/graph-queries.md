# Query explicit semantic relationships

Use this profile for facts that already have a semantic relation, such as a
known hazard. Start with [source selectors](README.md) when declarations and
bodies express the question naturally. Source selectors can compose with
resolved targets and explicit graph relationships; the compiler chooses the
execution plan internally.

An open bug hunt usually starts by formulating a hypothesis from the code's
contracts. The [relationship walkthrough](relationships.md) demonstrates that
process. `scope="bugs"` uses predefined risk signatures; a project-specific
query can instead describe the exact identity, ownership or order you need.
Catalog precision and the expressiveness of those queries are separate matters.

## Find a supported bug signature

Use `--backend indexed`. `HAS_HAZARD` retrieves a predefined hazard fact emitted
by the analyzer, with its source evidence. It is not an open-ended bug reasoner
and does not prove a runtime failure. For example, the mutable-default rule
recognizes Python list/dictionary/set literals in parameter defaults, not every
possible expression that could return a mutable object.

```kql
language "kql/2";
module lesson.hazards;
query mutable_defaults {
  edge HAS_HAZARD($site, "mutable-default-argument");
  select $site;
}
```

On the [sample source](sample.py.txt), this selects the hazard in `bad_default`,
whose `items=[]` default is allocated once. `fresh_default(items=None)` does not
match. The row contains a graph identifier locating that hazard, not necessarily
a callable-shaped object. Read the corresponding source before diagnosing a
runtime failure; shared mutable state may not yet have been mutated in a test.

Positive queries consisting exclusively of `HAS_HAZARD` edges acquire local
hazard evidence without constructing the project's semantic graph. Their full
result reports `analysis.source_profile: "local_hazards"`. Other graph queries,
including a hazard joined to other relations, retain full preparation. A timeout
there is incomplete analysis, not evidence that no hazard exists.

## Join a method to its resolved call target

```kql
language "kql/2";
module lesson.graph;
query method_targets {
  edge HAS_METHOD($type, $method);
  edge HAS_CALL($method, $site) { execution: "possible"; };
  edge TARGET($site, $target);
  select $type, $method, $target;
}
```

On the sample, one row connects `Writer`, `Writer.write`, and `save` (returned as
graph IDs). The repeated `$method` joins ownership to calls, and the repeated
`$site` joins that **same call occurrence** to its target. A global call to save
cannot accidentally satisfy Writer's method relation.

`edge RELATION(subject, object);` queries a fact, not a call in the analyzed
program. Endpoints can be captures, supported literals, `_` for an ignored
endpoint, or finite literal alternatives where accepted. Braces filter attributes
of that fact: here `execution: "possible"` accepts operations not established as
unreachable, rather than proving the call executes. Unknown target resolution
is not established by a similar name.

Fact filters accept strings, numbers, booleans, regexes, and finite lists, such
as `language: ["python", "typescript"];` where that fact actually publishes a
language attribute. A missing attribute does not satisfy the filter. Relation
names are validated; not every relation's attribute names have a static schema.
A positive fixture is essential to distinguish “no bug” from a misspelled or
unavailable attribute. The current graph profile rejects list elements containing
`|`; express such alternatives with separate branches.

## Combine a resolved target with scoped absence

```kql
language "kql/2";
module lesson.composition;
query save_without_close {
  callable $target { name: "save"; }
  callable $owner {
    call $site { target: $target; }
    not exists { call $cleanup { name: /^(close|closing)$/; } }
  }
  select $owner;
}
```

The sample's `Writer.write` matches. A close in another function cannot exclude
it. The query establishes a resolved call to `save` and absence of those call
spellings in the same callable. It does not establish a resource leak: a return
may transfer the value, and a `close` may refer to another object. `optional`
also composes here; witnesses introduced inside either block remain private.

Negated semantic relationships still need a closed inventory. For example,
absence of a resolved target is uncertain if dispatch could not be resolved.
Put relational `not exists` inside a source selector to define its scope;
unscoped relational negation produces an actionable compilation error.
Source `order`/`limit` clauses are not supported in graph plans; use execution
budgets to limit graph results and preserve uncertainty.

To examine an acquired value, capture it in BODY and query `usages of $value
as $use { kind: receiver; }`. This reports witnessed receiver uses of that
same result, including supported local aliases. A reassignment changes the
origin; a similarly named close on another result is not a match. Receiver
origin tracking is conservative for unsupported control flow. The usage
inventory remains open, so no receiver rows cannot prove a leak.

For additional relations, inspect the installed engine's relation vocabulary
and existing validated examples, then test a minimal positive and negative
source. This short guide does not claim to enumerate all IR relations or
language-specific facts. A parsed program alone is not an executed query.
