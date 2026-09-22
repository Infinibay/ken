# KQL 2 catalog extensions

Design note for the remaining structural-catalog migration: the entries that
still express themselves with the legacy relational clauses (`edge`, `walk`,
`tally`) instead of selectors, body instructions and public predicates.

Measured inventory at the time of writing (scripted over
`src/ken/structural/**/*.toml`): **25 TOMLs, 69 entries, 1602 legacy clause
lines**, of which 18 entries still carry a `legacy_query` string next to the
KQL 2 `query`. Of the families below only **F1 is implemented** (2026-09-15);
every other section names the legacy relations involved, the KQL 2 surface
proposed for them, and the pending entry ids it unblocks.

## 1. What KQL 2 already offers (baseline)

Verified in source, not from the old queries:

- **Selectors** (`src/ken/kql2/compiler.py:16-22`): `class`, `interface`,
  `trait`, `type`, `module_decl`, `callable`, `method`, `function`,
  `constructor`, `field`, `param`, `receiver`, `var`, `value`, `operation`,
  `macro`, `call`, `node`, `expression`, `statement`. Ownership is immediate:
  `type $t { method $m {} field $f {} }`, `callable $c { param $p {} }`.
- **Properties** (`compiler.py:24-48`, `graph.py:105`): `name`, `path`,
  `language`, `native_kind`, `visibility`, `static`, `constructor`, `arity`,
  `reassigned`, `escapes`, `initial`, `writes`, `effective`, `exported`,
  `target`, `result_family`, `captures`, `type: nominal($x)`,
  `type_status: known|unknown`, `return_type`, `execution`, `kind`, `line`.
- **Body instructions** (`src/ken/kql2/body.py:245-320`): `call $c { ... }`,
  `let $v = call ... as $inv;`, `let $x = construct $t { ... } as $op;`,
  `$place = $source as $write;`, `insert $value into $collection at $key;`,
  `return $v;`, `var $b { ... }`.
- **Source operands** (`body.py:267-301`): a bound `role` (`var`, `param`,
  `receiver`, `field`, and `value`/`callable` where values are allowed),
  `literal`, `binary`, `unary`, `wildcard`, `$place.name` member access and
  `read($x)`. Anything else — notably an **indexed element of a container** —
  raises `unsupported source expression` / `source operand requires a bound
  storage, parameter or captured value`.
- **Public predicates** (`src/ken/kql2/semantic.py:20-46`): `subtype`,
  `implements`, `nominal_root`, `overrides`, `possible_call`, `returns_new`,
  `returns_self`, `returns_type`, `returns_value`, `reads`, `writes`,
  `writes_element`, `iterates_calls`, `delegates_to`, `forwards_slot`,
  `final_member_input`, plus the unary `linear_members`, `linear_bindings`.

- **Receiver-only invocation** (`parser.py:605-613`, `body.py:1089-1099`,
  `parser.py:703`): `call on $place { ... }` states *something invoked on* that
  place with no named callee — the form for a call whose target is unresolved
  (a Java functional-interface method, a dynamic dispatch). The `on` flag is
  preserved when `body_clause` rebuilds the clause, and the matcher treats the
  receiver as the whole evidence: the call alias and the argument positions
  bind, and no callee resolution is required.

Everything the legacy clause set uses and that is absent from that baseline is
a gap family below.

## 2. Gap families

### F1 — Element origin: a value read out of a container

Legacy relations: `VALUE`, `INDEX`, `CONTAINER`, `CONTAINER`/`INSTANCE_SLOT`,
`MEMBER_OF`, `MEMBERSHIP_CONTAINER`, `MEMBERSHIP_KEY`, `LOOKS_UP`,
`ELEMENT_TYPE`, `LOADED_FROM`.

**Implemented.** A source operand may now be an *element of a bound container*,
spelled with the subscript the languages themselves use:

```kql
call $forward {
  argument $request[_] at any;     # an element of $request, at any key
  argument $table[$key] at any;    # the element at the key the pattern bound
  argument $table["id"] at any;    # the element at a literal key
}
```

Grammar surface: `$container[$key]`, where

- the **container** must be a place the pattern bound — a `var`, `param`,
  `receiver`, `field`, `value` or `callable` role;
- the **key** is an ordinary source operand — a bound place, a literal, a member
  read, the anonymous `_` (any element of the container will do), or an unbound
  role, which is then captured as a produced value the way an assignment's
  right-hand side captures one.

No grammar change was needed: `parser.py:570-575` already builds an `index`
expression and `parser.py:707-716` already accepts an index place in an
assignment. The change is in the body compiler
(`src/ken/kql2/body.py`): `source()` accepts an `index` operand and registers its
container/key roles, and the call matcher resolves it against the access
occurrence's own `CONTAINER`/`INDEX` facts — the same facts
`src/ken/structural/frontend.py:1819-1836` emits for a subscript. `_` or an
unbound key accepts any key, because the element *origin* — not the key — is what
the pattern claims; a bound key correlates exactly like an argument position.

Because the operand is only validated where source operands are already allowed,
the same spelling works for `argument ...`, `return $...`, the right-hand side of
an assignment and an `if` condition. Contract tests:
`tests/kql2/test_body_index_origin.py` (matches the fixture, rejects an unrelated
container, correlates a bound key, rejects an unbound container).

Still pending in this family: the **named capture** spelling
`value $entry from $table at $lookup;`, which would bind the element as a place a
later clause can consume, and `ELEMENT_TYPE` (the container's element type).

Unblocks: `adapter.functional-adapter`, `dispatch-table.direct`,
`dispatch-table.adapted`, `flyweight.explicit-interning`,
`unit-of-work.keyed-change-set`, `iterator.iterate_over`,
`composite.additive_aggregate`, `cache-aside.java-optional`.

**Landed for `adapter.functional-adapter`** (2026-09-15): the wrapper is a
`callable` that captures the factory's parameter, is returned by the factory,
and invokes the captured callable with two distinct elements of its own input
parameter:

```kql
callable $factory { parameters { param $inner {} } }
callable $wrapped { constructor: false; captures: $inner; parameters { param $request {} } }
callable $factory { body { return $wrapped; } }
either {
  callable $wrapped { body { call $inner { argument $request[_] at 0; argument $request[_] at 1; } as $delegation; } }
} or {
  callable $wrapped { body { call on $inner { argument $request[_] at 0; argument $request[_] at 1; } as $delegation; } }
}
```

Two details are load-bearing: the argument positions must be *stated* (`at 0`
and `at 1`), because two `at any` clauses can bind the same occurrence and the
variant is about splitting one input into two parameters; and the second arm is
the receiver-only call, which is what the Java functional-interface case needs
(the first arm covers Python, JavaScript, TypeScript, C#, C++, Go and Rust).

**Landed: the same operand in callee position** (2026-09-15). The element spelling
also names *what gets invoked*, with the container role unchanged (so `select`/`bind`
still name the table, not the element):

```kql
call $table[$requested] { } as $lookup;   # invokes the element that key selects
```

The parser accepts `$container[$key]` after `call`; the call matcher resolves it
against the call's `CALLEE_VALUE` object together with that object's own
`CONTAINER`/`INDEX` facts, and the container stays the bound role. `_` or an unbound
key accepts any key, exactly as in argument position.

One frontend gap had to close for Go: the Go grammar parses an indexed
`table[key](arg)` as a *type conversion*, so the call handler never attributed the
occurrence to its callable and the operation was not filed as a call. The Go
frontend now attributes that call occurrence (`src/ken/structural/frontend.py`) and
the body matcher also considers an operation whose byte span a published CALL
occurrence covers, even when its operation kind came out of the grammar differently.
Contract tests: `tests/kql2/test_body_callee_index_origin.py`.

**Measured cost — why `dispatch-table#direct` stays on the legacy signature**
(2026-09-15). With F1 in callee position the variant *is* authorable in pure KQL 2:

```kql
pattern detect(out GraphTerm $unit, out GraphTerm $register, out GraphTerm $dispatch, out GraphTerm $table) {
  type $unit {
    field $table { }
    method $dispatch { arity: 2; param $requested { } body { call $table[$requested] { } as $call; } }
    method $register { arity: 2; param $key { } param $handler { } body { insert $handler into $table at $key; } }
  }
  where $key != $handler;
  where $register != $dispatch;
}
```

It matches the registry in every language of `tests/structural/test_dispatch_table.py`,
Go included (26 of 27 cases). It does not fit that file's adversarial case: on the
150-method registry (`test_dispatch_table_avoids_unrelated_method_parameter_cross_product`,
`QueryBudget(max_states=2000)`) the pattern reaches **13 414** states in 11 ms of real
work, against 42 for the legacy signature. The pattern matcher charges a state per
region×clause and the extra methods multiply that even after `arity: 2` prunes them
at the selector (`field`+`method` alone is 917 states; adding the two parameters 3 701;
adding the registration body 28 989). The entry therefore keeps its `edge` spelling,
and its `query_claim` records the reason. When the callee/matcher accounting gets
cheaper, the block above is the migration to land.

### F2 — Call occurrences as first-class evidence

Legacy relations: `HAS_CALL`, `ENTITY`(CALL) with `name`/`resolution`,
`CALLEE_VALUE`, `CALLEE_NAME`, `TARGET`, `DECLARED_TARGET`, `RESULT`,
`RETURNS_CALL`, `RETURNS_VALUE`, `DISCARDS_RESULT`, `RECEIVER_UNREPLACED`,
`RECEIVER_BINDING_VERSION`, `INVOKES_RESULT_OF`, `PASSES_SELF_TO`,
`ARGUMENT_VALUE_ORIGIN`, `RETURN_OPERAND`.

`call $c { receiver: ...; target: $x; }` already covers the common case, and
`possible_call` / `forwards_slot` cover delegation. Six things were missing; the first
four are landed, the last two are still open:

1. **Resolution status.** *Landed* (2026-09-15): `call $c { resolution: resolved |
   unresolved | ambiguous; }`, mirroring `type_status: known|unknown`. A clause that
   states `resolution:` binds the **occurrence itself** when no declared callable
   accredits the callee, which is what "an unresolved clone call" means
   (`body.py`, the callee-binding branch: `target = Node(...,'CALL',...)`). Any other
   clause keeps requiring an accredited target, so existing catalogues are unaffected.
2. **Discarded result.** *Landed* (2026-09-15): `call $c { discarded: true; }`. The
   model publishes `DISCARDS_RESULT(statement, call)`, so the claim is read from the
   call side (a reverse lookup; `semantic.facts_to` / `SourceSemantics.facts_to`) and
   the statement that drops the value is never named. `command.retained-contract` still
   needs F4's initializer clause (`CONSTRUCTOR_FIELD_INPUT`) and
   `batch-work-queue.drain` needs F7's loop block, so neither moved with this item.
3. **Callee spelling.** *Landed* (2026-09-15): `call $c { name: "clone"; }` states the
   occurrence's own name, which is evidence even when nothing resolved. It is the
   attribute the entity publishes, not the bound node's field.
4. **Derivations.** *Landed* (2026-09-15): `type $unit { language: "rust"; derive:
   "Clone"; }` states a language-accredited derivation (`DERIVE_NAME`), which is what
   a `#[derive(Clone)]` type is. `prototype.derived_copy` is migrated with it.
5. **Call through a result.** `dispatch-table.adapted` invokes the value
   returned by an adapter. Propose the composition of the existing `let`
   capture with an invoke form:
   `let $entry = call $adapter { argument $key; } as $lookup;`
   followed by `call $entry { argument $request; }` — i.e. allow a captured
   call result (`$lookup`) as the callee place of a `call`. This is the single
   most valuable addition after F1.
6. **Receiver identity/version.** `builder.director` and
   `chain-of-responsibility.*` distinguish "receiver replaced by the same
   method" from "receiver rebound": propose a public predicate
   `same_receiver(call, receiver)` and `rebinds_receiver(call)`.

Unblocks (still open): `command.retained-contract`,
`command.command-object`, `command.stored-closure`, `builder.director`,
`dispatch-table.adapted`, `proxy.lazy-subject`, `proxy.remote-subject`,
`observer.event_delivery`, `mediator.event_delivery`. Migrated here:
`prototype.derived_copy`.

**The call surface as landed.** Two spellings exist and they are not the same code:

- a `call` clause inside `body { ... }` (`body.py`) accepts `argument`, `dispatch`,
  `receiver`, and now `name`, `resolution`, `discarded`;
- a `call` **selector** at pattern level (`source_patterns.py`) accepts `target`,
  `result_family`, `receiver`, and now `name`, `resolution`, `discarded`. There
  `resolution` takes a bare name (`resolution: unresolved`), which is lowered to the
  occurrence attribute, and `discarded: true` becomes `DISCARDS_RESULT(_, $call)`
  because a pattern-level claim has no statement role to name.

A receiver role is any bound place (field, parameter, receiver, local, value), which is
why an entry that correlates a receiver with a call must not pin the place's kind: the
`prototype.derived_copy` migration states it as
`either { param $receiver { type: nominal($unit); } } or { var $receiver { ... } }`.

### F3 — Statement containment: handlers, loops and statement kinds

Legacy relations: `OPERATION` with `native_kind`/`role`/`kind`, `SYNTAX_PARENT`,
`SYNTAX_NODE`, `IN_TRY_BODY`, `IN_HANDLER`, `HANDLER_OF`, `TRY_EXIT_STATUS`,
`CONTINUE_TARGET`, `HANDLER_FALLTHROUGH`, `LOOP_BODY_TAIL`, `ENCLOSING_LOOP`,
`NORMAL_COMPLETION`, `GUARDS_WRITE`, `CFG_NEXT`, `BRANCH_TRUE`, `BRANCH_FALSE`.

The `operation` selector already exists and carries `kind`, `line`,
`execution` and the common `native_kind`. What the retry and guard entries need
is **nesting stated declaratively** rather than via a `walk SYNTAX_PARENT`:

```kql
operation $retry { native_kind: "continue_statement"; }
inside $retry -> $handler;            # containment, replaces walk SYNTAX_PARENT
enclosing $handler -> $attempt;       # nearest enclosing loop / protected region
exits $handler without override;      # TRY_EXIT_STATUS "no-explicit-override"
completes $body normally;             # NORMAL_COMPLETION
```

Two small predicates instead of three relations: `inside($x, $y)` for
`IN_TRY_BODY`/`IN_HANDLER` (the named ancestor is what the pattern bound),
`enclosing_loop($x, $loop)` for `ENCLOSING_LOOP` + `CONTINUE_TARGET`.

Unblocks: `exception-retry.explicit-continue`,
`exception-retry.handler-fallthrough`, `flyweight.explicit-interning`,
`singleton.once-primitive`, `chain-of-responsibility.linked-handlers`,
`composite.algebraic-tree`, `memento.serialized-snapshot`.

### F4 — Instance state, writes and initialization

Legacy relations: `ASSIGNMENT_TARGET`, `ASSIGNMENT_VALUE`, `ASSIGNED_FROM`,
`BINDING_WRITE_STATUS`, `BINDING_WRITE_COUNT`, `UNIQUE_BINDING_WRITE`,
`UNREASSIGNED_BINDING`, `FINAL_FIELD_INPUT`, `CONSTRUCTOR_FIELD_INPUT`,
`INITIALIZES_FIELD`, `HAS_INITIALIZER`, `STORAGE_WRITE_COUNT`,
`STORAGE_WRITE_STATUS`, `RETURNS_STORAGE`, `FINAL_MEMBER_INPUT`.

`$field = $value as $write;` already states an assignment, `final_member_input`
already exists, and `writes: exactly($b, 1)` already constrains write
inventory. The missing half is the **initializer** form and the uniqueness
status:

```kql
field $state { }
call $initialize {
  argument $input for $param;
  initializes $state from $param;   # INITIALIZES_FIELD + HAS_INITIALIZER
}
where unassigned($state);           # UNREASSIGNED_BINDING / *_WRITE_STATUS
```

**Landed — the initializer step.** The spelling the language already had is
`body { initializer { $state = $param; } }`: the first step of a constructor's body
whose assignments go from the constructor's parameters to the fields that retain them
(`parser.py` `body_clause`, `body.py:140`, matched by
`src/ken/kql2/constructor_initializers.py`). What was missing was the evidence path for
languages whose constructors are ordinary assignments rather than declaration-phase
initializers (Python, JavaScript, Java, C#): they publish
`CONSTRUCTOR_FIELD_INPUT(field, parameter)` — the linear field analysis — instead of
`PARAMETER_INITIALIZES_FIELD`/`INITIALIZES_FIELD`, so the clause found nothing and
matched nothing. The matcher now accepts that evidence, and it no longer accepts an
initializer that the same constructor body overwrites (the executed write the body
publishes, `WRITES` with `execution: possible`), because `CONSTRUCTOR_FIELD_INPUT` is
withheld exactly there. Both evidence paths ask that question through one helper
(`src/ken/kql2/constructor_initializers.py` `_body_overwrites`): the parameter-property
path (`PARAMETER_INITIALIZES_FIELD`) is checked too, because TypeScript publishes no
`CONSTRUCTOR_FIELD_INPUT` for it — a parameter property the constructor later assigns
over still satisfied the declaration phase, and the clause used to accept it
(`tests/kql2/test_constructor_initializer_finality.py`, `command#queued-object`).
Authoring rule of thumb:

- `initializer { $field = $param; }` states *the field's retained input*: which field,
  which constructor parameter, and that nothing later writes the field.
- `writes: exactly($field, N)` states the same claim as a write inventory, but the
  inventory counts body assignments only: a C++ constructor initializer list is not one
  of the writes, so `exactly($field, 0)` is the C++ spelling and `exactly($field, 1)`
  the Python one. Prefer the `initializer` step where the entry must read the same for
  every language.

Migrated with it: `command#retained-contract` (was `HAS_FIELD` +
`CONSTRUCTOR_FIELD_INPUT` + `HAS_METHOD`/`HAS_PARAMETER` on the constructor, now
`field $receiver {}` plus `constructor $constructor { parameters { param $input {} }
body { initializer { $receiver = $input; } } }`), and `command#queued-object` (a batch
invoker whose stored actions are drained and each invoked): the retained action keeps a
constructor-supplied receiver, its parameterless operation dispatches on that receiver
through the **method-level** `call` clause — a `body { call ... }` clause requires an
anchored callee resolution, which JavaScript's `this.receiver.write(...)` does not
publish — and registration is either nominal or evidence of an observed caller:

```kql
param $input { type: nominal($contract); }        # nominal registration
type $contract { method $slot { constructor: false; arity: 0; } }
where subtype($unit, $contract);
where $dispatch.name == $slot.name;
where overrides($execute, $slot);
```
```kql
callable $caller {                                # untyped registration
  body {
    let $made = construct $unit {} as $creation;
    call $registration { argument $made at any; } as $use;
  }
}
where $registration.name == $register.name;
where $dispatch.name == $execute.name;
```

Unblocks: `builder.stored-product`, `prototype.field-copy`,
`prototype.language-copy`, `cache-aside.null-miss`,
`proxy.guarded-access`, `memento.snapshot-object`, `singleton.eager-shared`,
`unit-of-work.keyed_flush`.

**Landed — the retained dispatch step (`command.retained_dispatch`).** The legacy entry
was the last one that stated four facts KQL 2 could not spell. Three of them already had
a surface; one is new.

```kql
pattern detect(out GraphTerm $invoker, out GraphTerm $storage, out GraphTerm $invoke,
               out Call $dispatch, out GraphTerm $contract, out GraphTerm $slot, ...) {
  type $contract {
    method $slot { constructor: false; }
  }
  type $invoker {
    field $storage { }
    method $invoke {
      constructor: false;
      # the role after `call` is the target method, and `as` names the occurrence
      body { call $slot { receiver: $storage; unreplaced: true; } as $dispatch; }
    }
    either {
      method $setter {
        constructor: false;
        param $input { type: nominal($contract); reassigned: false; }
        body { $storage = $input as $write; }
      }
      where final_member_input($write, $input);
    } or {
      constructor $setter {
        param $input { type: nominal($contract); reassigned: false; }
        body { initializer { $storage = $input; } }
      }
    }
  }
  where $setter != $invoke;
  where $dispatch.explicit_arguments == $slot.arity;
}
```

New property — `unreplaced: true;` on a call clause. It states that the place the
occurrence is dispatched on was not rebound before it, which is the lexical prefix
inventory the graph publishes as `RECEIVER_UNREPLACED(call, place)`
(`src/ken/structural/write_inventory.py:117-130`). A later write cannot invalidate an
earlier occurrence, so only the prefix counts. It requires the same clause to name
`receiver:`; without it the compiler rejects the clause. Implemented in
`src/ken/kql2/body.py` (both call-clause whitelists and the runtime check),
declared in `src/ken/kql2/compiler.py` (`PROPERTIES['call']`) and routed through the
relational plan in `src/ken/kql2/graph.py` (`has_graph`). Replaces the legacy
`edge RECEIVER_UNREPLACED($call, $place)`.

The other three, now known to be already available — recorded here because each cost a
measured experiment:

- **The target method and the call occurrence are different roles.** A bare
  `call $role { … };` binds `$role` to the *target callable*. To bind the *occurrence*,
  declare the role with the `Call` domain and alias the clause: `call $slot { … } as
  $dispatch;`. That pair is what the legacy `HAS_CALL($invoke, $dispatch)` (occurrence)
  plus `TARGET($dispatch, $slot)` (resolution) state together; `target: $slot;` is
  accepted by the parser but rejected by the body matcher, so do not use it.
- **`$dispatch.arity` is the target's arity, not the call's argument count.** The count is
  `$dispatch.explicit_arguments` (`semantic.py`), so the legacy "matching explicit arity"
  is spelled `where $dispatch.explicit_arguments == $slot.arity;`. Writing
  `where $dispatch.arity == $slot.arity;` compiles and is trivially true, which silently
  admits calls that pass the wrong number of arguments.
- **`param $input { reassigned: false; }`** is the existing spelling for the legacy
  "the retained input is not rebound" (`UNREASSIGNED_BINDING`); it is what rejects the
  `input = null; this.saved = input` contrast in every language.

Authoring rule of thumb, learned the hard way: **a `where` with a semantic predicate is
not evaluated inside an `either` branch's body.** `method $setter { body { $storage =
$input as $write; where final_member_input($write, $input); } }` silently matches nothing
once it is one alternative of an `either`; the same `where` one level up, at the branch
level (after the `method` selector, inside the branch), matches. A `where` at pattern
level needs every role it names to be bound in *all* alternatives, so the branch level is
the right home for a predicate that belongs to one alternative.

Unblocks: `command.retained_dispatch` and everything built on it
(`command#retained-contract`, `command.captured_payload`).

Four more authoring rules, measured while migrating `command#command-object` (they apply
to every remaining entry that reads a call's result or a state write):

- **A returned call is spelled `let` + `return`.** `return $call;` where `$call` is a
  call-occurrence alias is rejected at compile time — `source()` accepts only
  `var/param/receiver/field/value/callable` as a return operand (`body.py:306`), and a call
  alias is a `call` role. The equivalent that compiles, binds the occurrence and matches is
  `let $result = call $target { receiver: $place; } as $call; return $result;`, which reads
  `HAS_CALL` + `RECEIVER` + `RETURN_ORIGIN` in three lines.
- **A discarded result is `discarded: true;`** on the call clause; it reads
  `DISCARDS_RESULT(statement, call)` (`body.py:1319-1323`). Legacy
  `HAS_OPERATION($method, $statement)` needs no clause: containment is what puts the
  occurrence inside the method body in the first place.
- **A legacy `either { WRITES } or { WRITES_ELEMENT }` becomes a *nested* `either`.**
  A graph-level `where writes($a, $s) or writes_element($a, $s);` is rejected
  (`graph where currently requires comparisons joined by and`, `graph.py:429`), but
  `either { where writes($action, $state); } or { where writes_element($action, $state); }`
  compiles and keeps both alternatives live (verified: an element-writing receiver matches).
- **Optional constraints belong inside the branch, not above it.** Declaring the receiver's
  field at pattern level (`field $local_state {}`) makes *every* alternative require it, so
  the `discarded` alternative silently stopped matching the fixture whose receiver exposes
  no state. Move each clause that only one alternative needs into that alternative.

Also measured, and worth not rediscovering: a bare `method $role { … }` selector is legal at
pattern level (no enclosing `type` is needed), which is how a legacy role that binds a
*method* (`HAS_CALL($method, $call)`) is spelled; and both `call` and `return` body clauses
need their trailing `;`.

### F5 — Type parameters and the type an operation speaks for

Legacy relations: `BINDS_TYPE_PARAMETER`, `TYPE_PARAMETER`,
`TYPE_PARAMETER_OWNER`, `TYPE_PARAMETER_RECEIVER`, `TYPE_NAME`,
`RETURN_TYPE_ARGUMENT`, `TYPE`, `IN_TYPE`, `IS`, `INSTANCE_OF`,
`ALLOCATES_TYPE`, `RESOLVED_ALLOCATION_COUNT`.

Generic bridge, typestate builder and generic visitor all bind a type
parameter in one place and use it in another. Proposed surface keeps the
declaration form flat and readable:

```kql
type $abstraction<param $t> { method $slot { param $value { type: nominal($t); } } }
callable $bridge { type_parameter $t for $abstraction; }
where return_type_of($method) == $t;   # RETURN_TYPE_ARGUMENT
```

`IS`/`INSTANCE_OF` map to the existing selector kind notation
(`type $x { }` already spans `CLASS|INTERFACE|TRAIT|STRUCT`, and a literal list
endpoint already exists in `graph.py:132-135`), so only the "which type did this
operation allocate / speak for" predicates are new: `allocates($call, $type)`
and `allocation_count($call, exactly(1))`.

Unblocks: `bridge.generic-composition`, `bridge.injected_returned_primitive`,
`builder.consuming-typestate`, `visitor.generic-visitor`,
`composite.algebraic-tree`, `flyweight.stable_intrinsic`,
`singleton.module-shared`, `state.context-transition`.

### F6 — Value tests, casts and language protocols

Legacy relations: `NULL_TEST`, `UNDEFINED_TEST`, `TRUTH_TEST`,
`PARAMETER_TEST`, `OPTIONAL_VALUE`, `OPTIONAL_PRESENT`, `OPTIONAL_FALLBACK`,
`OPTIONAL_OR`, `CAST_VALUE`, `RETURN_FLOW_STATUS`, `BODY_VALUE`, `FLOWS_TO`,
`EXPRESSION_OPERAND`.

`either { where ... } or { ... }` already expresses the branch; what is missing
is a test vocabulary that reads like the language being described:

```kql
where present($optional);          # OPTIONAL_PRESENT
where absent($optional);           # NULL_TEST / UNDEFINED_TEST
where truthy($flag);               # TRUTH_TEST
return $cast;                      # cast($v, $cast) for CAST_VALUE
where flows($write, $load);        # FLOWS_TO, explicit one-hop value flow
```

A cast needs its own operand form because the legacy `CAST_VALUE` walk relates
a cast expression to its inner call: propose `cast $inner to $target as $cast;`
in BODY, lowering to `edge CAST_VALUE($cast, $inner); edge CAST_TARGET($cast,
$target);`.

Unblocks: `cache-aside.null-miss`, `cache-aside.java-optional`,
`read-through-cache.read_fill`, `subclass-factory.returned-subclass`,
`composite.higher-order-traversal`, `prototype.language-copy`,
`visitor.result_forwarding`, `builder.consuming-typestate`.

### F7 — Iteration over collections

Legacy relations: `ITERATION_SOURCE`, `ITERATION_BINDING`, `ITERATION_ORIGIN`,
`ITERATION_INVOKES_VALUE`, `ITERATED_CALL`, `ITERATION_ENTRY_SOURCE`,
`ITERATION_PASSES_VALUE`, `ITERATION_SNAPSHOT`, `COLLECTION_SNAPSHOT_OF`,
`CLEARS_COLLECTION`, `AFTER_ITERATION`, `INSERTS_INTO`, `INSERTED_INPUT`,
`INSERTED_VALUE`, `DISCARDS_RESULT`.

`iterates_calls` exists as a predicate but the batch-drain, command-closure and
iterator entries all need to say *what each iteration passes* to the call.
Propose one block that states the whole loop and drops the tally/walk pairing:

```kql
iterate $item over $collection {
  call $worker { argument $item for $input; }
}
after { clears($collection); }      # CLEARS_COLLECTION + AFTER_ITERATION
```

Unblocks: `batch-work-queue.drain`, `command.command-closure`,
`composite.higher-order-traversal`, `iterator.callback-iterator`,
`iterator.delegated-cursor`, `iterator.advancing_element`,
`unit-of-work.keyed_flush`.

**Landed: the loop body is a role.** The `iterate` clause gained one optional
property, `body: $role;`, which binds the walk's body region, so a pattern can hand
the loop body on instead of only constraining what happens inside it:

```kql
pattern detect(out Parameter $source, out Binding $item, out Operation $body, out Operation $iteration) {
  callable $unit {
    parameters { param $source {} }
    body {
      iterate $source as $item as $iteration { body: $body; body {} }
    }
  }
}
```

The role publishes the `ITERATION_BODY` operation the same way the `as $iteration`
capture publishes the loop (`reference(operation)`), so the body can be selected,
compared or passed to another pattern. The walked collection may stay a bound place
(`var`/`field`/`param`/`receiver`/`value`/`call`) *or be introduced by the clause
itself*: when the source role is unbound the walk supplies it, and the clause binds
the entity the loop reads (`ITERATION_SOURCE`), so one clause covers a parameter, a
field and a call result alike — hence `out GraphTerm $source` in the migrated entry
rather than a `parameters { param $source {} }` wrapper. Compared to the sketch
above the clause keeps its `as $item as $iteration` shape (two captures were already
legal) and gains only the body capture; `after { clears($collection); }` is *not*
implemented — the lifecycle predicates are read by the existing
`clear $collection after $iteration;` clause. Implemented in
`src/ken/kql2/body.py` (compile side: property split, role/output registration and
an unbound source role; matcher side: only `async` constrains the loop, the body
role binds `reference(body_region)` and an unbound source binds the loop's single
`ITERATION_SOURCE` place), no grammar change: `body: $x;` was already parseable —
`body $x {}` and a third `as` are `ParseError`s. Migrated entry:
`iterator.iterate_over`, verified against all eight `test_pattern_operations`
languages plus its negatives (Go index-only range, Python destructuring, two
disjoint loops), the operational IR guide's field-sourced loop, and the
frozen-parity roundtrip (one reviewed evidence-only delta: on the generator fixture
the authored BODY discloses `source_body:unknown` where the frozen edge query stayed
silent, with no match gained or lost).

Measured, still open in this family:

- ~~`let $value = $container[$key];` is rejected.~~ **Landed: an indexed read is a
  value capture.** The clause the migration needed is exactly the spelling that was
  refused:

  ```kql
  pattern detect(out TypeDecl $unit) {
    use ken.catalog.iterator.detect(iterator: $unit);
    type $unit {
      field $index {}
      field $items {}
      method $next {
        name: ["next", "__next__"]; constructor: false;
        body {
          let $value = $items[$index];
          $index = $index + 1;
          return $value;
        }
      }
    }
  }
  ```

  What the role binds, measured on the cursor fixtures: **the place the read wrote**,
  not the lookup expression. `value = self.values[self.index]` publishes
  `ASSIGNMENT_TARGET(read, STORAGE:value)` next to
  `ASSIGNMENT_VALUE(read, VALUE:194:217)` with `CONTAINER`/`INDEX` on that value, and
  the `return` publishes `RETURN_OPERAND(return, STORAGE:value)`. Binding the element
  *expression* instead leaves `return $value` at `value_provenance_incomplete`, because
  an evaluated origin is not the binding the return names. The clause also requires
  the place to have exactly one supported write (`STORAGE_WRITE_COUNT` = 1), which is
  the `STORAGE_WRITE_COUNT($value, "1")` the legacy query spelled out: it is what
  refuses a cursor that reads the element and then overwrites the place before
  returning it.

  Implementation, all in `src/ken/kql2/body.py`, no grammar change (the parser already
  produced a `let` whose `expressions` held the index and whose `blocks` were empty):

  - compile side: the `let` branch accepts a single `index` expression, registers the
    named role as a `Value` output and binds its `as $alias` like every other
    statement (a branch that `continue`s before the generic alias handling must do it
    itself, or the alias is unbound and the pattern fails
    `graph output is not bound in every alternative`).
  - matcher side: a `let` whose expression is an index is offered the `ASSIGN`/`UPDATE`
    operations of the group, is not unwrapped into the call clause it does not have,
    and resolves `CONTAINER`/`INDEX` exactly as an indexed argument does — including
    the `_` key and the unbound key role, which binds the key the read used.
  - CFG gate: a body over a callable whose `CFG_STATUS` is `partial` was refused with
    `control_flow_incomplete`. An **abrupt exit** (`raise`/`throw`) now joins the
    suspension shapes as an accepted reason: the walk still publishes the entry and
    every statement of the body, so a pattern that states the *order* of those
    statements stays reliable — which is what the legacy `execution: "possible"`
    clauses asserted. The canonical cursor (`if …: raise StopIteration` before the
    read) needs it.

  Migrated entry: `iterator.advancing_element`, verified against
  `tests/structural/test_algorithm_iterator.py` (Python/Java/TypeScript positives,
  injected work between read and advance, and the `no-progress` / `unrelated-result`
  mutation families) plus the frozen-parity roundtrip.
- ~~A method body cannot name the call it returns.~~ **Landed: the returned call is
  a declared `Call` role and `advances` is a predicate.** The migration of
  `iterator.delegated-cursor` needed exactly two facts the body language could not
  read: `RETURNS_CALL(callable, call)` and `ADVANCES_ITERATOR(call, place)`. Neither
  needs a new clause — the pieces were the *role domain* of the call and one new
  relation:

  ```kql
  pattern detect(out TypeDecl $iterator, out Call $local_advance) {
    type $iterator {
      field $cursor { }
      method $iter { name: "__iter__"; constructor: false; }
      method $next {
        name: "__next__"; constructor: false;
        body {
          let $local_result = call $advance { argument $cursor at any; } as $local_advance;
          return $local_result;
        }
      }
    }
    where returns_self($iter, $iterator);
    where advances($local_advance, $cursor);
  }
  ```

  What made it work, measured on the seed fixture
  (`def __next__(self): return next(self.values)`):

  - `let $local_result = call ... as $op;` is the part that *returns* the call: with
    the result bound, `return $local_result` joins the `RETURN` operation, so a
    `__next__` that calls and discards (`next(self.values); return 0`) is refused.
    A bare `return $op;` does not compile — `$op` is not a source role.
  - The `as` alias needs a **declared domain** to be usable outside the body:
    `out Call $local_advance` puts the alias in `expected_types`, so the alias binds
    the `CALL` *entity* (`.../CALL:129@129:146`) instead of an operation reference.
    That identity is what `ADVANCES_ITERATOR` names as its subject; with an
    undeclared alias the body still matches, but `where advances(...)` fails the
    "positively bound roles" rule and, once declared, the join is an exact-id join.
  - `advances($call, $place)` is a public predicate —
    `('ADVANCES_ITERATOR','Call','Field')` in `src/ken/kql2/semantic.py`. No
    `execution: possible` attribute is required: the frontend publishes the
    delegation as `ADVANCES_ITERATOR(call, storage)` with a model attribute
    (`python-next`), not an execution budget.
  - The call occurrence is the `next(...)` free function, so the clause needs
    `argument $cursor at any` (or `resolution:`) to bind the unresolved occurrence
    as the call itself; a bare `call $advance { }` matches nothing for an unresolved
    callee.
  - The variant's own query keeps `use detect(iterator: $iterator); select
    $iterator;`: an extra `out` role is internal evidence and does not appear in the
    published bindings, so the frozen contract is reproduced byte for byte.

  Verdict: `iterator.delegated-cursor` migrated with no grammar change
  (`tests/structural/test_iterator_delegated_cursor.py`, frozen parity on
  python/java/typescript plus the adversarial matrix).
- A branch cannot be captured as a role, so the Go push-iterator protocol — a `bool`
  parameter whose result governs a `return`/`break` — is not expressible yet. Blocks
  `iterator.callback-iterator` (`TRUTH_TEST`, `CFG_NEXT` kinds).

### F8 — Registration, notification and coordination

Legacy relations: `DECLARES_EVENT`, `ADDS_HANDLER`, `REMOVES_HANDLER`,
`RAISES_EVENT`, `CONDITIONAL_DELEGATION`, `ADD`/`REMOVE` collections,
`INSTANCE_SLOT`, `PASSES_SELF_TO`, `DELEGATES_TO`.

Observer and mediator are the last name-based families: they read as
"registers a supplied callable under a key" and "notifies the registered
handlers". `writes_element` and `insert` already cover the registration half
(`insert $handler into $registry at $topic;`), so the additions are the
notification verbs:

```kql
notifies $unit through $registry;           # ADDS/REMOVES + RAISES_EVENT
delegates $handle to $next conditionally;   # CONDITIONAL_DELEGATION
```

Unblocks: `observer.snapshot-registry`, `observer.language-event`,
`observer.event_delivery`, `mediator.message-coordination`,
`mediator.tag-dispatch`, `mediator.event_delivery`,
`chain-of-responsibility.middleware-closures`,
`chain-of-responsibility.single_exclusive_handler`, `strategy.static-policy`,
`proxy.single_guarded_dispatch`, `visitor.named-dispatch`.

### F9 — Value-origin chains and allocation identity

Legacy relations: `VALUE_DEPENDS_ON`, `ARGUMENT_VALUE_ORIGIN`,
`ARGUMENT_VALUE_ORIGIN`/`RETURN_ORIGIN`, `LOADED_FROM`, `RETURNS_FIELD`,
`RETURN_FIELD_STATE`, `FIELD_STATE_ORIGIN`, `FIELD_STATE_WRITE`,
`RETURNS_NEW`, `RETURNS_SELF`, `ALLOCATES_TYPE`, `RESOLVED_ALLOCATION_COUNT`,
`RETURNS_STORAGE`, `RESULT`.

`returns_new`, `returns_self`, `returns_type` and `final_member_input` already
exist. The gap is the **origin chain**: adapter's input/output conversion and
prototype's field-copy need "this returned value is computed from that
argument" without naming every intermediate.

```kql
return from($input) as $converted;    # ARGUMENT_VALUE_ORIGIN / VALUE_DEPENDS_ON
return $state of $replica;            # RETURN_FIELD_STATE + FIELD_STATE_ORIGIN
where allocation_count($call, 1);     # RESOLVED_ALLOCATION_COUNT (same call site)
```

Unblocks: `adapter.input_conversion`, `adapter.output_conversion`,
`prototype.field-copy`, `builder.stored-product`, `command.captured_payload`,
`command.retained_dispatch`, `mediator.tag-dispatch`,
`singleton.eager-shared`, `singleton.once-primitive`.

**Measured blocker** (2026-09-15, so the next round starts from facts): both
`adapter` conversions were attempted and reverted; none of the four hypotheses
below survives.

- `let $x = <expression>;` is rejected — `let requires a call or a
  construction`. Only `let $x = call ...` and `let $x = construct ...` parse, so
  a pattern cannot bind "a value computed from a place".
- An `argument` operand must already be bound: an unbound role raises `source
  operand requires a bound storage, parameter or captured value`. Unlike an
  assignment's right-hand side, `argument $converted at 0;` does **not** capture
  the produced value.
- `argument binary(left: $input, operator: _, right: _) at 0;` compiles but does
  not match a forwarded `perform(converted)`: the operand test is identity, not
  dependence.
- `return binary(left: $result, operator: _, right: _);` after `let $result =
  call $delegate { receiver: $place; };` matches `return result + 1;` but misses
  `return 1 + (result * 2);` (`tests/structural/test_ir178_contracts.py`),
  because the call result is consumed two levels down.

So the two entries keep their `edge`/`walk` spelling until an origin clause
lands: the planned `return from($input) as $converted;` for the input side and a
depth-agnostic consumer form for the output side (the legacy walked
`VALUE_DEPENDS_ON` to depth 8).

**Implementation site for the next round** (recorded 2026-09-15). The two halves
are not the same change, and only the first is a `source()` change:

- *Input side* (`argument $converted from $input at 0;`): a new clause in the
  body parser (`src/ken/kql2/syntax/parser.py`, `body_clause`, beside the
  existing `argument`/`let`) that lowers to
  `ARGUMENT_VALUE_ORIGIN($argument, $place)` + `VALUE_DEPENDS_ON($argument,
  $place)` — the relation the operand loop already reads at `body.py:797-801`
  (`basis: "evaluated-expression-inputs/1"`, correlated by `position`). The
  operand side must stop raising *source operand requires a bound storage,
  parameter or captured value* (`src/ken/kql2/body.py`, `source()`, the bound
  check, `body.py:289/298`) when the operand names the produced value the clause
  declares: that capture is the primitive, not an extra property.
- *Output side* (depth-agnostic consumer): this is **not** the per-operand loop.
  `1 + (result * 2)` does not align operand-by-operand with the pattern's
  `binary(left: $result, ...)`, so a whole-expression claim belongs to the body
  `where` handler in `src/ken/kql2/body.py` (a `where derived($result);` over the
  transitive `VALUE_DEPENDS_ON` closure), not to `source_matches`.
- Status after this round: neither half is implemented; `read_file` and shell
  inspection of `src/ken/kql2/body.py` were frozen for the editing window, so the
  `source()` body could not be read before editing. Unblock = a window that can
  read `body.py` `source()` (≈lines 250–320) and `parser.py` `body_clause`
  (≈lines 660–740).

**Landed: the derived-value operand.** Both halves are in, as one primitive -- `argument
from $place` for the input side and `return from $place` for the output side (depth-agnostic
over the `VALUE_DEPENDS_ON` closure, continued through a call that stands in the chain).
The spelling differs from the sketch above in one respect: the operand is *omitted* rather
than named, because an unbound operand role is refused by `source()` for exactly the reason
recorded here. `adapter.toml` now holds no `edge`/`walk`/`tally` clause. See §5.44 for the
grammar, the semantics and the verification.

**Round status: the `command` catalogue** (2026-09-15). Landed in pure KQL 2 and verified
against the frozen catalogue: `command.retained_dispatch` (needs only `unreplaced: true;`,
which this round added to the `call` clause), `command#retained-contract` (F4
`initializer { $field = $param; }`), `command.retained_object`,
`command.captured_payload` (`argument $payload at any;` — an F9 origin operand naming a
*field* place, so no new syntax was needed). **Update: the whole `command` catalogue is
migrated.** `command#command-object`, `command#stored-closure`, `command#command-closure`
and `command#queued-object` are pure KQL 2 and `command.toml` holds no `edge`/`walk`/`tally`
clause; the last entry needed exactly two primitives, sections 5.4 and 5.5 below.

**Measured blocker: a field storing an inline closure** (`command#stored-closure`).
The legacy entry needs `ASSIGNED_FROM(field, closure)` where the closure is written
inline. The only spelling that lowers to the assignment operand is
`body { $action = $closure as $write; }` with the callee role bound by
`callable $closure { constructor: false; captures: $bound; }`. Measured with
`tests/structural/test_stored_command.py` fixtures (`frozen -> migrated` matches):

| fixture | frozen | migrated |
|---|---:|---:|
| python nested `def action(): …` + `self.action = action` | 1 | **1** |
| python `self.action = lambda: work(data)` | 1 | 0 |
| javascript `this.action = () => work(data)` | 1 | 0 |
| typescript / csharp arrow assigned to the field | 1 | 0 |
| go `&Task{action: func(){…}}` (`INITIALIZES_FIELD` + `STORES_VALUE`) | 1 | 0 |

The two python fixtures publish the *same* graph facts for the link
(`ASSIGNMENT_TARGET` → the storage, `ASSIGNMENT_VALUE` → the closure, `ASSIGNED_FROM`);
only the right-hand operand node differs (identifier versus `lambda`). The matcher is
`src/ken/kql2/body.py:1493-1516` (the body `assign` statement) and the bound-role branch it
calls is `src/ken/kql2/body.py:701-751`; the instruction that drops the inline case was not
isolated this round, so treat the cause as unproven and start from the two fixtures above.
The go composite literal additionally needs an `INITIALIZES_FIELD` + `STORES_VALUE`
spelling (`field { initial: … }`, or the `construct $type { initializer $field; }` form that
`builder.toml:71` already uses for a stored value).

Spellings that do **not** compile, so a future round does not retry them:
`$unit.$action = $closure as $write;` (`expected IDENT, got '$action'`),
`$action = read $closure as $write;` (`source expressions require a role or application`),
and an unbound right-hand role (`source operand requires a bound storage, parameter or
captured value` — the declaration must precede the `assign` clause in the pattern).

Two F2 findings from the same round: a `call` clause inside a closure body that must match an
*unresolved* function needs `call $work { resolution: unresolved; } as $invocation;` — the
plain `call $work {}` reports `source_body:unknown` — and `call on $role` is not the
callee-value spelling: `call $field {}` (the bare role) is, while `on` is for
receiver-position role invocation.

### F10 — Unresolved and name-dispatched calls

Legacy relations: `CALLEE_NAME`, `ENTITY`(CALL) `resolution`,
`RETURNS_CALL`, `INVOKES_RESULT_OF`, `ENTITY`(CALLABLE) for interpreter
fragments, `SINGLETON`/`once` primitives.

Interpreter, proxy and lazy variants route through calls whose target is not
resolvable, or whose spelling *is* the evidence (a recognised primitive name).
Both are already expressible if F2.1 lands, plus one explicit escape hatch:

```kql
call $dispatch { resolution: unresolved; }        # no resolved target required
call $primitive { name: "once"; target: unknown; } # name is the evidence
```

Unblocks: `prototype.derived_copy`, `proxy.remote-subject`,
`proxy.lazy-subject`, `interpreter.expression-sum`,
`interpreter.context-free-binary`, `interpreter.binary_result`,
`visitor.overloaded-dispatch`, `singleton.once-primitive`,
`visitor.generic-visitor`, `visitor.result_forwarding`.

## 3. Coverage of the 69 pending entries

Entry ids below are `<pattern-id>.<entry-id>`; the collection prefix
(`architecture.`, `persistence.`, `resilience.`) is omitted, and
`read-through-cache` (main) is the entry whose query is the TOML's top-level
`query`. Every row is an entry that today contains at least one `edge`, `walk`
or `tally` clause.

| Entry | Family |
|---|---|
| `batch-work-queue.drain` | F7 (with F2 discard) |
| `cache-aside.java-optional` | F1, F6 |
| `cache-aside.null-miss` | F4, F6 |
| `dispatch-table.direct` | F1, F3 |
| `dispatch-table.adapted` | F1, F2.3 |
| `exception-retry.explicit-continue` | F3 |
| `exception-retry.handler-fallthrough` | F3 |
| `read-through-cache` (main) + `read_fill` | F4, F6, F9 |
| `subclass-factory.returned-subclass` | F5, F6 |
| `unit-of-work.keyed-change-set` | F1, F4 |
| `unit-of-work.keyed_flush` | F7, F9 |
| `adapter.functional-adapter` | F1 (blocking), F2 |
| `adapter.input_conversion` | F9 |
| `adapter.output_conversion` | F9 |
| `bridge.generic-composition` | F5 |
| `bridge.injected_returned_primitive` | F5, F9 |
| `builder.consuming-typestate` | F5, F6 |
| `builder.director` | F2.4, F9 |
| `builder.stored-product` | F4, F9 |
| `chain-of-responsibility.linked-handlers` | F3, F8 |
| `chain-of-responsibility.middleware-closures` | F2, F8 |
| `chain-of-responsibility.single_exclusive_handler` | F3, F8 |
| `command.retained-contract` | F2.2 |
| `command.command-object` | F2.2, F4 |
| `command.stored-closure` | F2, F4 |
| `command.command-closure` | F2.2, F7 |
| `command.queued-object` | F4, F5 |
| `command.retained_dispatch` | F4, F9 |
| `command.captured_payload` | F9 |
| `composite.algebraic-tree` | F3, F5 |
| `composite.higher-order-traversal` | F6, F7 |
| `composite.additive_aggregate` | F1, F9 |
| `flyweight.explicit-interning` | F1, F3, F6 |
| `flyweight.entry-api` | F1, F3 |
| `flyweight.stable_intrinsic` | F5 |
| `interpreter.expression-sum` | F10 |
| `interpreter.context-free-binary` | F5, F10 |
| `interpreter.binary_result` | F9, F10 |
| `iterator.callback-iterator` | F7 |
| `iterator.delegated-cursor` | F7, F9 |
| `iterator.iterate_over` | F1, F7 |
| `iterator.advancing_element` | F7, F9 |
| `mediator.message-coordination` | F8 |
| `mediator.tag-dispatch` | F8, F9 |
| `mediator.event_delivery` | F2.3, F8 |
| `memento.accessor-snapshot` | F4 |
| `memento.snapshot-object` | F4, F9 |
| `memento.serialized-snapshot` | F3, F9 |
| `observer.snapshot-registry` | F8 |
| `observer.language-event` | F8, F10 |
| `observer.event_delivery` | F2.3, F8 |
| `prototype.field-copy` | F4, F9 |
| `prototype.language-copy` | F4, F6, F10 |
| `prototype.derived_copy` | **migrated** (was F2.1, F10) |
| `proxy.guarded-access` | F4, F6 |
| `proxy.lazy-subject` | F2, F6, F10 |
| `proxy.remote-subject` | F2, F10 |
| `proxy.single_guarded_dispatch` | F6, F8 |
| `singleton.eager-shared` | F4, F9 |
| `singleton.module-shared` | F5 |
| `singleton.once-primitive` | F3, F9, F10 |
| `state.context-transition` | F5, F9 |
| `state.event_transition` | F3, F8 |
| `strategy.static-policy` | F8 |
| `visitor.overloaded-dispatch` | F5, F10 |
| `visitor.named-dispatch` | F8, F10 |
| `visitor.generic-visitor` | F5, F10 |
| `visitor.result_forwarding` | F6, F10 |

## 4. Implementation order and verification

1. **F1** (element origin) — **landed**. It unblocks the one entry that was
   impossible to author (`adapter.functional-adapter`) and the two dispatch
   table variants; those migrations are the next work item, not another language
   extension.
2. **F2.1/F2.2/F2.3** (resolution, discarded result, callee spelling, derivations) —
   **landed** (2026-09-15). `prototype.derived_copy` is migrated to pure KQL 2 with
   them; `command.retained-contract` and `batch-work-queue.drain` were re-checked and
   stay listed, because they also need F4's initializer clause and F7's loop block.
3. **F3, F4, F9** — the largest group; keep them declarative and reject
   anything that would need a `walk`.
4. **F5–F8, F10** — last, because their entries are already authored in
   selector-heavy KQL 2 with only a handful of relational leftovers.

Each migration lands only when `tests/structural/test_catalog_kql2_migration.py`
(the frozen pre-KQL 2 parity matrix), `test_catalog_adversarial_matrix.py`
and `test_negative_corpus.py` pass for the touched pattern. A primitive that
cannot keep parity is reverted and stays listed here.

## 5. Extensions landed with the `command` rewrite

`command#stored-closure` needed three primitives at once. The same claim — an
object stores a closure that captures an outer binding, and that same field is
what another method invokes — is published through an assignment in Python,
JavaScript, TypeScript and C#, and through a keyed literal in Go; and the
closure's own body is where the capture is used.

### 5.1 `initializer $field from $value;` — the value a construction stores

```
callable $producer {
  constructor: false;
  body { let $made = construct $unit { initializer $action from $closure; } as $new; }
}
```

`initializer $place;` alone states that the construction stores *that place*.
A keyed literal (`&Task{action: func(){ ... }}`) instead initializes a field with
a value that never passes through a parameter: the frontend publishes
`INITIALIZES_FIELD(keyed_element, field)` **and** `STORES_VALUE(keyed_element, closure)`,
so the place the pattern binds (the field) is not the value that is stored. The
new operand names both — the field the literal fills and the value it carries —
and demands both facts.

- Parser: `src/ken/kql2/syntax/parser.py` `construct()` accepts an optional
  `from <sourceExpr>` after the place. The block form
  (`initializer $place { transfer: [identity]; }`) is unchanged, so every
  already-migrated query parses exactly as before.
- Body: `src/ken/kql2/body.py` validates the operand with the same
  `source(..., allow_value=True)` every other clause uses — it must already be a
  bound place — and matches it against
  `INITIALIZES_FIELD(initializer, $field)` and `STORES_VALUE(initializer, $value)`.
- Without `from` the clause keeps its previous meaning untouched.

### 5.2 `captures: $x` binds the captured binding as a value

```
callable $closure {
  constructor: false;
  captures: $bound;
  body { call $inner { argument $bound at any; } as $use; }
}
```

The property was the only place the captured binding was declared, and it bound
nothing: the role could not be named anywhere else, so a clause could say *that*
a closure captures something but never *what it does with it*. Now
`captures: $x` binds `$x` as a value for the owner's own clauses — including its
`body` — while the `CAPTURES` edge it publishes keeps pinning it to the binding
the language reports.

- `src/ken/kql2/source_patterns.py` `selector()` emits a `source_capture`
  clause next to the `CAPTURES` relation it already emitted.
- `src/ken/kql2/graph.py` `declaration().block()` lowers it: the role is bound
  with domain `value`, so a later `body` sees it in `body_roles`.

### 5.3 A `call` clause that names an argument is anchored by the occurrence

```
body { call $inner { argument $bound at any; } as $use; }
```

A `call $c { ... }` clause whose role is unbound previously had to accredit its
callee (`TARGET`/`DECLARED_TARGET`, a `name:`, a `resolution:` or a receiver) or
it stayed uncertain — yet `work(data)` in a fixture is a call the project never
declares, and the claim being made is about the *argument*. The clause now binds
the call occurrence whenever it names one, exactly as `resolution: ...;` already
did for the same reason (see the comment at that branch in `body.py`).

- `src/ken/kql2/body.py`, `BodyEngine.match()`, the callee-resolution branch:
  a clause carrying an `argument` constraint is evidence about the occurrence
  itself, so the occurrence binds and the argument constraints decide truth.

### 5.4 What an insertion carries: the local alias and the wrapper

```
callable $action { constructor: false; captures: $local_payload; }
method $submit { body { insert $action into $queue as $local_insertion; } }
```

`insert $value into $collection;` matched the node stored verbatim. Languages rarely
store the closure itself: JavaScript, TypeScript, Java, C#, C++ and Go bind it to a
local name first (`const action = ...; this.pending.push(action)`), and Rust wraps it
(`self.pending.push(Box::new(action))`), so `INSERTED_VALUE` names the local storage or
the wrapper call. The operand now resolves what the insertion *carries*: from the stored
node it follows `ASSIGNED_FROM` (a local name and the value bound to it), `ARGUMENT`
(a wrapper call and the place it passes) and `FLOWS_TO` (the value that flows into the
stored node), to a bounded depth of three hops. The legacy spelling needed three
`either` arms plus `walk FLOWS_TO {0,2}` for the same claim; one clause now covers all
eight languages.

- `src/ken/kql2/body.py`, `BodyEngine.match_step()`, the `insert` branch: the
  insertion's `INSERTED_VALUE`/`STORES_VALUE`/`ASSIGNMENT_VALUE` set is expanded
  transitively before the operand is matched. The collection, the key and the
  bound-place requirement of the operand are unchanged.
- `tests/kql2/test_body_insert_carries.py`: the alias hop (JavaScript), the wrapper hop
  (Rust) and a stored value that carries no callable (negative).

### 5.5 The iterated element is the receiver of the operation it offers

```
method $run {
  body {
    iterate $queue as $local_element {
      body { call on $local_element { argument $local_execution at any; } as $local_dispatch; }
    }
  }
}
```

`iterate $queue as $item { body { call $item { ... } } }` covers a language that invokes
the element itself. Java, C# and C++ elements are interface values whose *operation* is
invoked (`action.applyAsInt(context)`), and `call on $item` already said "the receiver is
the evidence" — but the receiver check compared the bound place's identity against
`RECEIVER`, and the loop binds a synthetic iteration value, not the element's storage.
The clause now resolves that identity through the iteration fact, exactly as the
iterated-element-as-callee rule four lines above it already did.

- `src/ken/kql2/body.py`, `BodyEngine.match_step()`, the `'on' in item.flags` branch:
  a place bound by the enclosing `iterate` resolves to the element id the loop reports,
  and that id must be the call's `RECEIVER`. Without a receiver the verdict stays
  `Unknown`, never a definite absence.
- `tests/kql2/test_insert_effect.py`:
  `test_iterated_element_is_the_receiver_of_the_operation_it_offers` — the Java fixture
  matches `call on` and does not match the element in callee position.

### 5.6 The walk must enter with the collection it drains

A loop that starts *after* the same field was replaced or emptied walks a different
value, and `ITERATION_SOURCE` cannot say so on its own: both walks name the same field.
The IR separates them by publishing `ITERATION_ENTRY_SOURCE` (basis
`no-prior-explicit-replacement-or-clear/1`) only while the collection was neither
replaced nor cleared before the loop, so `iterate` now *requires* the entry source to be
the bound collection (`src/ken/kql2/body.py`, `BodyEngine.match_step()`, the
`item.kind == 'iterate'` branch). That is the legacy `require $iteration
ITERATION_ENTRY_SOURCE $queue;` spelled as part of the clause instead of as a separate
line. The requirement applies to a walk over a storage place, which is what the entry
analysis follows: a walk over a call result (`for await (const x of produce())`) has no
place to track, publishes no entry source, and keeps the `ITERATION_SOURCE` test alone.
A bucketed walk (`iterate $map[$key]`) binds a container element instead and is exempt.

### 5.7 An insertion names the caller's input only while it is unwritten

`insert $input into $queue` is the legacy `require $insert INSERTS_INTO $queue; require
$insert INSERTED_INPUT $input;`, and two details are load-bearing:

- `INSERTED_VALUE` is published even when the input has been rebound
  (`task = None; self.tasks.append(task)`), while `INSERTED_INPUT` is not, so the clause
  intersects with the input relation whenever the IR has one.
- When it has none, the insertion is an API insertion (it published `INSERTED_VALUE`) and
  the operand *is* an input place, the insertion carries something else and the clause
  rejects it. The alias/wrapper widening of §5.4 still applies to operands that are not
  input places (`const action = …; queue.push(action)`).
- A keyed write (`insert $handler into $handlers at $key`) publishes the element write
  instead of an API insertion, so that guard does not apply to it.

### 5.8 The element is invoked by the loop, not merely read

`call on $item { … }` resolves the receiver through the iteration fact (§5.5). It now
also requires the loop to be the walk that *invokes* that call: `ITERATION_INVOKES_VALUE`
is published only while the binding still names the element at that occurrence, so an
element rebound before the call (`item = None; item.perform()`) is not the element the
loop invokes and the clause no longer matches it.

### 5.9 A suspension point does not invalidate the statement walk

An `async def consume` publishes `CFG_STATUS partial` with reason `await`, so any body
pattern with more than one clause was refused outright — and the batch-work queue's walk
whose body invokes the element is exactly such a pattern. The allowance the single-`call`
and single-`yield` shapes already had is now stated once, generally: when the only
incompleteness reasons are suspension points (`await`, `await_expression`, `yield`,
`yield_expression`, `yield_statement`) the IR still publishes the entry, the loop edges
and every statement of the body, so the statement walk a pattern asks for stays reliable.

### 5.10 Verification

`tests/structural/test_stored_command.py` — 24 tests, five languages, including
the package/cross-file, duplicate-type, map-key and package-reference negatives
— and `tests/structural/test_catalog_kql2_migration.py` for the frozen pre-KQL 2
parity matrix. This is what separates 5.1–5.3 from a spelling that merely parses:
the Go negative `func(){ _ = data }` captures the binding without passing it to
any call, and it must not match.

Sections 5.6–5.9 carry their own contract in `tests/kql2/test_body_lifecycle.py`
(six cases: the insertion with and without a rebound input, the walk with and
without a reset before it, the element rebound before the call, and the awaited
invocation), while the catalogue side is pinned by
`tests/structural/test_queued_commands.py` (17 mutations × 5 languages),
`tests/structural/test_modern_catalog_precision.py::test_batch_must_drain_entry_collection`
and `tests/structural/test_modern_catalog_review.py`.

### 5.11 `singleton#module-shared`: two additions landed with the rewrite

The variant has two shapes and neither could be spelled with the selectors alone,
so the rewrite landed two additions. It is now pure KQL 2:

```text
pattern detect(out GraphTerm $unit, out GraphTerm $module, out GraphTerm $storage,
               out GraphTerm $accessor, out GraphTerm $creation, out GraphTerm $type) {
  either {
    type $unit {}
    module_decl $module {
      field $storage { static: false; initializer { construct $unit {} as $creation; } }
      callable $accessor { exported: true; body { return $storage; } }
    }
  } or {
    module_decl $module {
      callable $accessor {
        var $storage { static: true; }
        body { let $initialized = construct $unit {} as $creation; $storage = $initialized; return $storage; }
      }
    }
  }
  bind $type = $unit;
}
```

The eager `type $unit {}` is nested inside the first arm on purpose — 5.46 measures
what the other placement costs.

**`var $storage { static: … }` is an accepted callable child.** C++ keeps the
singleton in a function-local `static`, so the IR declares the storage *from the
callable* (`DECLARES CALLABLE:current/STORAGE:shared {static: true}`). A `field`
cannot be a callable child (the compiler answers `callable cannot immediately own
field`), but a `var` can, and `static` is now an accepted `var` property
(`src/ken/kql2/compiler.py`, `PROPERTIES['var'].update(static='Bool')`). It lowers
to `DECLARES(callable, storage)` plus `ENTITY(storage, STORAGE){static:true}` —
which is exactly the storage class that separates the C++ singleton from a fresh
local per call (`test_the_storage_class_is_what_admits_the_function_local_shape`).

**A declaration-shaped initializer wrapper is unwrapped.** Go publishes
`var shared = Config{value: 1}` as
`var_declaration > var_spec > expression_list > composite_literal`, and the
`var_spec` carries no `value`/`right` role of its own, so `Initializers.regions`
reported `initializer_expression_missing` and the module-scope branch could not
match Go. `src/ken/kql2/declaration_initializers.py` now unwraps a lone
`var_spec` / `short_var_declaration` / `const_spec` child and treats an
`expression_list` as transparent. The unwrap only runs when no `value`/`right`
child is present, so every other initializer match keeps its previous shape.

**Re-anchored test.** `tests/structural/test_singleton_module_shared.py:148`
asserted the legacy spelling (`'edge IS($module, "MODULE")' in row['query']`);
it now asserts the KQL 2 selectors (`module_decl $module`, `exported: true`,
`body { return $storage; }`) — the same move `adapter#functional-adapter`
already required.

Verification: `tests/structural/test_singleton_module_shared.py` (six languages
plus the fresh / non-public / uninitialized / plain-local negatives),
`tests/structural/test_catalog_kql2_migration.py` (frozen pre-KQL 2 parity),
`tests/structural/test_catalog_adversarial_matrix.py -k singleton` and
`tests/kql2` — all green.

### 5.12 F5 lands: `type_parameter $t;` and `type: parameter($t)`

The generic `bridge#generic-composition` entry needed the two halves of F5, so both landed
with its rewrite (2026-09-15):

```kql
type $unit {
  type_parameter $implementation_parameter;                 # BINDS_TYPE_PARAMETER($unit, "I")
  field $implementation { type: parameter($implementation_parameter); }   # TYPE_NAME(field, "I")
  ...
}
```

- `type_parameter $t;` is a new clause in `src/ken/kql2/syntax/parser.py` (`_clause`, before the
  selector branch). It is deliberately a *standalone* clause: the parameter is a **name**, not an
  entity, and the optional block is currently empty. The name is reserved to the enclosing block.
- `src/ken/kql2/source_patterns.py` lowers it to `BINDS_TYPE_PARAMETER(declaration, $t)`
  (`selector()`, early branch) and adds the `parameter(...)` arm beside `nominal(...)`, which
  lowers `type: parameter($t)` to `TYPE_NAME(place, $t)`.
- Both roles bind the *spelling* the IR publishes, so writing the same role in both places states
  "the field's declared type is the parameter this type binds" without comparing strings in the
  query. A refinement may rename its parameter, which is what the entry's tests assert.
- `src/ken/kql2/graph.py` (`has_graph`) routes a pattern that uses either form through the
  relational planner.

**The call that has no callee.** `this.impl.run()` publishes `HAS_CALL` + `RECEIVER` and no
`TARGET`/`CALLEE_VALUE` (`resolution: unresolved`). The spelling that matches is
`body { call on $implementation { }; }` — receiver-position invocation, where the receiver is the
evidence. Measured: `call $local_delegate { receiver: $implementation; }` and a bare
`call $local_delegate { };` both report `source_body:unknown`, because the clause's role is the
*callee*, and a fresh unbound role has no target. This is the same `call on $role` rule recorded in
F9 above, now confirmed from the other direction.

**Re-anchored test.** `tests/structural/test_bridge_generic_composition.py:339` asserted
`'edge ENTITY(' in row['query'] and 'SUBTYPE_OF' in row['query']`; it now asserts
`type_parameter $implementation_parameter;`, `type: parameter($implementation_parameter);` and
`where subtype($local_variant, $unit);`.

Verification: `tests/structural -k bridge` (dedicated six-language suite, the renaming fixture, the
non-generic Go receiver negative), `tests/structural/test_catalog_kql2_migration.py` (frozen pre-KQL 2
parity for both `bridge` entries) and `tests/structural/test_catalog_adversarial_matrix.py -k bridge`
— all green. The bridge catalogue now carries no `edge`/`walk`/`tally` clause.

### 5.13 `call qualify $t { }` — an operation the type parameter itself selects

`strategy#static-policy` has two forms, and its own `query_claim` names both: a field typed by
the type parameter, or — in C++ — a call qualified by the parameter itself (`P::apply(x)`) with
nothing stored. The second form is what the frozen query stated as
`TYPE_PARAMETER_RECEIVER($call, $policy)` + `TYPE_PARAMETER_OWNER($call, $unit)` +
`where $policy == $parameter`. The parser already reserved the clause
(`src/ken/kql2/syntax/parser.py`, `call()`: `call qualify $parameter { … }`, `flags=("qualify",)`);
the compile-time and match-time halves were missing.

```kql
pattern detect(out GraphTerm $unit, out GraphTerm $policy, out GraphTerm $parameter,
               out GraphTerm $algorithm, out GraphTerm $call) {
  type $unit {
    type_parameter $parameter;
    method $algorithm { constructor: false; }
  }
  either {
    type $unit {
      field $policy { type: parameter($parameter); }      # form 1: field typed by the parameter
      method $algorithm { body { call on $policy { } as $call; } }
    }
  } or {
    type $unit {
      type_parameter $policy;
      method $algorithm { body { call qualify $parameter { } as $call; } }   # form 2: P::operation
    }
    where $policy == $parameter;
  }
}
```

- `src/ken/kql2/body.py` (`compile_body`): the accepted role shapes for a `call` clause now depend
  on the flag — a `qualify` clause takes a `type_parameter` role instead of a callable or storage
  place, and a fresh role defaults to `type_parameter` rather than `callable`.
- `src/ken/kql2/body.py` (`match_step`): the new `qualify` arm matches
  `TYPE_PARAMETER_RECEIVER(call, name)` and `TYPE_PARAMETER_OWNER(call, declaration)`
  (`src/ken/structural/frontend.py:1661-1663`), both published only for a C++ qualifier that is a
  parameter the enclosing template declares. Because the branch also binds `$policy` to a name the
  unit binds (`BINDS_TYPE_PARAMETER`) and equates it with `$parameter`, a homonymous parameter of
  another scope contributes nothing — the legacy `where $policy == $parameter` holds.

Two authoring traps, both measured:

- `bind $policy = $parameter;` is rejected (`graph bind requires a fresh top-level alias of a
  bound role`, `graph.py:394`), so the second form re-selects the parameter into `$policy` and
  equates the two names with `where` instead of aliasing them.
- BODY bindings are keyed by *bare* role names (`owner = bindings[pattern.owner]`), so a BODY clause
  cannot reach an outer role as `$unit`; the declaring unit is `unit`.

Verification: `tests/structural/test_strategy_static_policy.py` (18), the frozen pre-KQL 2 parity of
`tests/structural/test_catalog_kql2_migration.py -k strategy` and every strategy case of
`tests/structural/test_catalog_adversarial_matrix.py` (including `directed/strategy-static-no-field`)
— all green, and `strategy.toml` carries no `edge`/`walk`/`tally` clause.

### 5.14 `return $replica copies $field;` — the returned object kept a field

`prototype#field-copy` asks for the *correlated* copy: a method returns a fresh instance of its own
type, and the field on that instance is the receiver's field of the same name. The legacy entry
stated four relations the flow analysis (`src/ken/structural/return_flow.py:471-478`) publishes:
`RETURN_FIELD_STATE(return, state)` (with `field=` the member spelling), `FIELD_STATE_ORIGIN(state,
allocation)`, `FIELD_STATE_WRITE(state, write)` and the write's `ASSIGNMENT_VALUE` equal to the
field declaration. Reconstructing that correlation inside the query is impossible — it is a
last-write-wins, alias- and branch-aware result — so the query names the claim and the engine reads
the analysis.

Landed surface (parser.py:772-785, body.py:1766-1790):

```
method $clone {
  constructor: false;
  body {
    let $replica = construct $unit {};
    return $replica copies $state;
  }
}
```

`copies $field` is a modifier of the `return` clause; `$field` must be a *field role* the pattern
bound (a bare `field $state { static: false; }` on the type suffices). It is satisfied when the
returned operation has a `RETURN_FIELD_STATE` whose `field` spelling equals that role's name and
whose `FIELD_STATE_WRITE` write has the bound field declaration among its `ASSIGNMENT_VALUE`
objects. Consequences the fixtures pin:

- a plain `return $replica;` still claims only "a fresh allocation is returned" — the modifier is
  load-bearing, not decorative (`tests/kql2/test_body_copies_field.py`);
- a write of a constant, of a *different* receiver field, of the same field on *another* instance,
  or a write superseded before the return, all fail;
- the copy follows aliases (`let q = p`) because the flow analysis, not the query, decides which
  write survives;
- an undeclared field role yields no match rather than an error.

Two traps, both measured while landing it:

- `ir.entities` (the graph the body executor reads) is keyed by *module-local* ids
  (`CLASS:Product/STORAGE:count`) while the fact objects *and* bound `Node.local_id` carry the
  qualified id (`copy::module/CLASS:Product/STORAGE:count`), so the copied slot's name has to come
  from the bound role's `Node.name`, not from an entity lookup.
- `os` is shadowed by a local name inside `match_step`; debug output there must reach the module
  through `__import__('os')`.

Verification: `tests/structural/test_prototype_field_copy.py` (199 cases, including the
alias/branch/escape/annotation matrices), `tests/kql2/test_body_copies_field.py` (9),
`tests/structural/test_catalog_kql2_migration.py -k prototype` and
`tests/structural/test_prototype_language_copy.py` — all green, and `prototype#field-copy` carries
no `edge`/`walk`/`tally` clause.

### 5.15 `prototype#language-copy`: four matchers landed with the rewrite

The variant states that the copy comes from the language's own mechanism, in three
shapes: a copy constructor, a delegation to a copy primitive, and the Clone trait's
method whose result is built from a field. Migrating it from `edge`/`walk` needed four
matchers, each of which already had facts and only lacked vocabulary.

1. **`param $p { reference_kind: "lvalue"; }`** (and on `receiver`). The C++ copy
   constructor differs from the move and by-value spellings only in its declarator,
   which IR 1.60 records as `lvalue`/`rvalue`. Lowered to the `PARAMETER` entity
   attribute; `compiler.py` `PROPERTIES['param']`.
   `tests/kql2/test_body_param_reference_kind.py`.
2. **`call $c { name: ["copy", "deepcopy", "clone", "MemberwiseClone"]; }`.** A
   protocol spelled differently per library needs the alternatives the occurrence
   itself publishes; a list is only accepted where a name is stated, and a single
   literal behaves exactly as before. `body.py` `name_spellings`.
   `tests/kql2/test_body_call_name_list.py`.
3. **`call $c { ...; returned: true; }`.** The delegation must be what the method
   hands over: the returned operand *is* the occurrence (Python's `return
   copy.deepcopy(self)`), or it is the runtime cast of it (Java's `(Config)
   super.clone()`, C#'s `(Config) this.MemberwiseClone()`, published as
   `RETURN_OPERAND` + `CAST_VALUE`). `RETURNS_CALL` states the same for the first
   shape. Without it, `directed/prototype-discarded-copy` (`copy.copy(self)` with the
   result dropped) matched — a resolved adversarial case the migration must not
   reopen. `tests/kql2/test_body_call_returned.py`.
4. **`method $m { completes: true; }`.** A constructor identified by signature must
   still have a body that reaches a normal exit; `prototype#language-copy/cpp/algorithm-removed`
   (`Config(const Config& other) : value(other.value) { throw 0; }`) is exactly a
   declaration whose body never completes, and it is the other resolved case.
   Evaluation reads `HAS_OPERATION` + the body-role `OPERATION` + `NORMAL_COMPLETION`;
   a callable with no body operation, or a body with no completion fact, discloses
   `normal_completion:unknown` rather than a negative. `source_type_filter.py`,
   routed through `source_patterns.py` like `reassigned`.
   `tests/kql2/test_body_callable_completes.py`.

5. **`body { initializer { $state = $source; } }`** — the clause F4 landed — now also
   reads the declaration phase's *member* spelling: an initializer of the field whose
   argument belongs to a parameter of the constructor, which is how
   ``Config(const Config& other) : value(other.value)`` publishes its copy. The analysis
   reports that argument as `INITIALIZER_ARGUMENT` + `MEMBER_OF(parameter)` and leaves
   the initializer's status `unsupported` (`non-direct-value`), so this evidence is
   evaluated before the status inventory; a constant initializer (``: value(0)``) has no
   such argument and still fails.
   `tests/kql2/test_body_initializer_member_copy.py`, and the signature-vs-state case
   `tests/structural/test_creational_catalog_precision.py::test_cpp_copy_constructor_copies_state_instead_of_only_matching_a_signature`.

**Not added.** An `instance $self {}` selector was prototyped to name the implicit
instance and withdrawn: in the catalogue engine the existing `receiver $self {}`
already lowers to `source_receiver`, which binds the type's `INSTANCE_RECEIVER`
(`relational.py:521`), so `receiver: $self` matches a delegation on `this`/`super` in
Java and C# while the same clause keeps rejecting a delegation on a field
(`this.items.clone()`). The logic-plan engine binds the receiver *parameter* instead,
which only the languages that spell one publish; the catalogues run on the catalogue
engine. Also withdrawn: a `cast` modifier on `return`, superseded by `returned: true`
on the call clause, which needs no extra role in the pattern signature.

Verification: `tests/structural/test_prototype_language_copy.py` (21 cases, five
languages plus the alias/fresh/move/by-value/foreign-container matrix),
`tests/structural -k prototype` and the frozen-parity contracts — all green, and
`prototype.toml` carries no `edge`/`walk`/`tally` clause.

### 5.16 `return_type: applied($unit, $state)` — a generic return instantiation

`builder#consuming-typestate` states that a non-constructor step of the builder
returns *another instantiation of the builder itself*, in a different state:
`Builder<Pending> → Builder<Ready>`. The frozen query used
`RETURN_TYPE_ARGUMENT($step, $state)` plus a `tally distinct $state >= 2`.

`RETURN_TYPE_ARGUMENT` (IR 1.65, `src/ken/structural/frontend.py:571`) is
published exactly when a callable's declared return type applies its own
declaring type to arguments, and the bare type name does not carry the argument
(`native_return_type` keeps `Builder<Ready>`; the entity only says `Builder`).
So the matcher names both ends:

```kql
method $local_step { return_type: applied($builder, $state); }   # RETURN_TYPE_ARGUMENT(step, "Ready")
```

- It is a third arm of the `type`/`return_type` family in
  `src/ken/kql2/source_patterns.py` (`selector()`), beside `nominal($x)` and
  `parameter($t)`. It lowers to `RETURN_TYPE_ARGUMENT(subject, $argument)` and
  `continue`s before `source_types.validate_matcher`, which would otherwise
  reject the call form.
- The base must be the *enclosing* type role: `applied($other, $state)` inside
  `type $unit { … }` fails with "applied requires the enclosing type as its
  base". That mirrors the IR condition — the return type applies the declaring
  type — so the clause cannot spell an unrelated generic.
- No compiler schema change was needed: `return_type` is already a `SourceType`
  property of `callable`/`method`/`function`/`constructor`
  (`src/ken/kql2/compiler.py:57`), and the relational path does not consult
  `PROPERTIES`.

**The second state is a second method, not a quantifier.** The legacy
`tally distinct $state >= 2 { HAS_METHOD($builder, $transition);
RETURN_TYPE_ARGUMENT($transition, $state) }` is written as a second selector plus
two equalities:

```kql
method $local_step       { constructor: false; return_type: applied($builder, $state); }
method $local_transition { constructor: false; return_type: applied($builder, $local_state); }
where $state != $local_state;
where $local_step != $local_transition;
```

Two methods with different arguments *are* two distinct states, so the invariant
holds without a counting operator — and a builder whose steps all return the same
instantiation has no second method to bind. `require` was deliberately not
extended: it quantifies declaration inventories (`allocation`, `constructor`) and
supports neither arbitrary relations nor a count form
(`src/ken/kql2/source_quantifiers.py`, `src/ken/kql2/syntax/parser.py:267-287`).

**Re-anchored test.** `tests/structural/test_builder_consuming_typestate.py:185`
asserted `'RETURN_TYPE_ARGUMENT' in row['query'] and 'tally distinct' in
row['query']`; it now asserts `type_parameter $local_state_parameter;` and
`return_type: applied($builder, $state);`.

Verification: `tests/structural/test_builder_consuming_typestate.py` (16 cases —
three languages, the renamed builder, and the fluent / non-generic /
finish-without-slot negatives) and `tests/kql2/test_body_applied_return_type.py`
(4 cases — both arguments bound, a primitive return excluded, the parameter-name
comparison, and the foreign base rejected) — all green.

### 5.17 `$place._` — a member of the bound place, at any depth

Legacy relations: `MEMBER_OF`, `MEMBER_DECLARATION`, `BINDING_REFERENCE`,
`READ_ORIGIN`.

A member operand spelled `_` claims the *path* from a bound place to one of its
members, not the member's spelling or depth:

```
method $step {
  constructor: false; static: false;
  param $input { }
  body { $stored._ = $input as $write; }
}
```

and in receiver position:

```
call $local_copy { receiver: $stored._; name: "clone"; returned: true; };
```

**Evidence.** `src/ken/kql2/body.py:810-826` — `member_place`, the
`expected.value == '_'` branch: from every candidate member it walks
`MEMBER_OF` upward (eight levels, no cycle) until it reaches the entity the bound
place denotes, and accepts the first candidate that gets there; a member that
never reaches that holder is rejected. `src/ken/kql2/body.py:531-534` accepts the
same `$place._` shape where a `call` clause names its `receiver:`. An argument
or assignment operand spelled `_` was already a wildcard
(`src/ken/kql2/body.py:1784-1785`, `1826-1827`, `1980`).

**Unblocks** `builder#stored-product`. The fixture's builder stores the product
returned by `finish` in a field whose name, and whose nesting depth, differ per
language; `$stored._` states "the member of the field the builder keeps the
product in" without naming it.

**Fixture.** `tests/structural/test_stored_product_builder.py` — 144 verdicts
(four languages × the mutation matrix × nesting).

### 5.18 `initializer $field from $value` — the stored value named by its producer

Legacy relations: `HAS_INITIALIZER`, `INITIALIZES_FIELD`, `STORES_VALUE`,
`RESULT`.

`initializer $field from $value;` inside a `construct { ... }` names which bound
place the construction stores, and `$value` may be a role bound to an earlier
construction's *result*:

```
let $created = construct $product {} as $creation;
construct $builder { initializer $stored from $created; };
```

**Evidence.** The operands must already be bound places
(`src/ken/kql2/body.py:430-437` — `source(operand, allow_value=True)`). The
matcher links a bound result to the occurrence that produced it through the
`producers` map: `src/ken/kql2/body.py:1380-1388` builds
`stored_ids = {carried.local_id, producers.get(carried.local_id)}` and accepts
when one `HAS_INITIALIZER` of the call both `INITIALIZES_FIELD`s the named field
and `STORES_VALUE`s either the bound result value or its producer occurrence.

**Unblocks** `builder#stored-product`: the builder's field is initialized with
the product whose construction the pattern bound as a role, so the query names
the construction whose result it stores instead of enumerating stores.

**Fixture.** `tests/structural/test_stored_product_builder.py` (the entity-typed
`initializer` branch) and, for the single-argument form it extends, §5.1.

### 5.19 Mixed storage kinds in `either` collapse to a usable place role

Legacy relations: the `PLACE`/`FIELD`/`PARAMETER` entity kinds the alternatives
published.

When both alternatives of an `either` block bind the *same* role to storage
kinds, but disagree on which (`field` in one, `param` in the other), the unified
role stays usable as a place:

```
call $finish { receiver: $receiver; ... };
```

**Evidence.** `src/ken/kql2/graph.py:378-387` — after the either-block kinds are
intersected, `kinds <= {'field','var','param','receiver','value'}` now sets
`role_types[role] = 'var'`. The comment states the intent: the alternatives agree
the role is storage even though they disagree on which, and "patterns correlate
places by identity -- a director drives the instance it was handed or built --
so the unified role stays usable as a storage role." Before this, such a role
reverted to `''` and any later body clause that consumed it as a place failed
its binding check.

**Unblocks** `builder#director`, whose receiver is a parameter in one fixture
and a field in another; the two branches meet at `receiver: $receiver`.

**Fixture.** `tests/structural/test_algorithm_builder.py` (python/java/
typescript positives) plus the frozen-parity entry
`builder#director`.

### 5.20 `receiver_version: $lifetime` — the binding a place is read through

Legacy relations: `RECEIVER_BINDING_VERSION`, `RECEIVER_UNREPLACED`.

```
call $finish { receiver: $receiver; receiver_version: $lifetime; returned: true; };
```

**Evidence.** Parse: `src/ken/kql2/body.py:537-545` — `receiver_version` requires
a role operand, and that role defaults to the `value` domain. Match:
`src/ken/kql2/body.py:1681-1699` — the first occurrence that names the role binds
it to the call's `RECEIVER_BINDING_VERSION`; every later occurrence must read the
same binding. A call with no such row yields the `call_receiver_version_missing`
unknown, and a role that is bound but disagrees yields a negative.

**Unblocks** `builder#director`. A `parts = other;` between the configuration
steps publishes a *different* version for the receiver, so a director cannot
configure one instance and finish another.

**Fixture.** `tests/structural/test_algorithm_builder.py` (`rebound` negative)
and `tests/structural/test_catalog_adversarial_matrix.py -k director`.

### 5.21 A callee that is a member of the bound receiver

Legacy relations: `CALLEE_VALUE`, `MEMBER_OF`.

```
call $local_copy {
  receiver: $stored;
  name: "clone";
  resolution: unresolved;
  returned: true;
};
```

**Evidence.** `src/ken/kql2/body.py:531-534` accepts a member shape where the
`call` clause names its receiver. The call matcher resolves the callee member
through the call's own `CALLEE_VALUE` rows rather than a fresh enumeration of
members: `src/ken/kql2/body.py:1535-1545` accepts a target or element when
`f.object == target.local_id` / `element_id` for some `CALLEE_VALUE` of the same
call, and `src/ken/kql2/body.py:1600` collects those rows for the indexed-callee
path.

**Unblocks** `builder#stored-product`: the `finish` method calls `clone` on the
product the builder stored, so the callee is a member of the bound receiver and
is resolved per call.

**Fixture.** `tests/structural/test_stored_product_builder.py` (the rust
`derive: "Clone"` accept and the `no-derive`/`explicit-clone`/`other-clone`
rejects).

**Verification for 5.17-5.21.**
`tests/structural/test_catalog_kql2_migration.py -k builder`
(frozen-parity per entry × language against
`catalog_matrix/pre_kql2_catalog.json`),
`tests/structural/test_stored_product_builder.py`,
`tests/structural/test_algorithm_builder.py`,
`tests/structural/test_catalog_adversarial_matrix.py -k builder`, and
`tests/structural/test_negative_corpus.py` — all green. The director
noise-20 family also fits `QueryBudget(max_states=100000)`: python dropped from
168436 to 4474 states after both receiver branches were narrowed with
`type: nominal($builder)`.

### 5.22 `$place.$field` — a member read named by the pattern's own role

Legacy relations: `MEMBER_OF`, `MEMBER_DECLARATION`, `READ_ORIGIN`,
`BINDING_REFERENCE`.

```
body { $state = $memento.$saved as $write; }
```

`$memento.saved` names a member *literally*: it reads whatever declaration the
project spells `saved`, so a fixture that names the field `state` (or a rename
mutation) cannot be covered by one authored pattern. The role form names the
declaration instead, so the query never fixes the member's spelling.

**Evidence.** Parse: `src/ken/kql2/syntax/parser.py:576-584` — after a `.` the
postfix loop accepts a declaration role and builds `member` with the role as its
second argument. Source operands: `src/ken/kql2/body.py:316-328` accepts that
shape and requires the holder to be a bound place and the named role to be a
declared field or binding. Match: `src/ken/kql2/body.py:833-838` resolves the
role form to the declaration the role bound, instead of looking the member name
up among the bound roles. Plans: `src/ken/kql2/graph.py:158-166` carries the
operand as `$place.$field`.

**Unblocks** `memento#snapshot-object`: restore reads the snapshot's retained
field, and the same pattern covers the GoF fixtures (`state`) and the algorithm
fixtures (`saved`, `rename`).

**Fixture.** `tests/structural/test_algorithm_memento.py` (positives and the
`wrong-snapshot-field` negative) and
`tests/structural/test_catalog_kql2_migration.py -k memento`.

### 5.23 `final_field_value($write, $value)` — the write that ends a field's flow

Legacy relations: `FINAL_FIELD_VALUE`.

```
$state = $memento.$saved as $write;
where final_field_value($write, $memento.$saved);
```

An assignment states *an* occurrence that stores the read value; it does not
state that this occurrence is the field's surviving value. The relation does,
which is what separates a restore from a restore followed by an overwrite.

**Evidence.** `src/ken/kql2/semantic.py:28-32` publishes `FINAL_FIELD_VALUE` as a
public relation over an operation and a value; the fact is produced by
`src/ken/structural/field_transfers.py:139`. `src/ken/kql2/body.py:826-838`
resolves the second operand, so a member read and a plain value both work.

**Unblocks** `memento#snapshot-object` (the `restore-overwrite` and
`wrong-origin-field` negatives). `final_member_input` cannot carry this check:
its second domain is a `Parameter`, so a value operand yields
`Unknown('final_member_input_unknown')` and poisons the enclosing `either`.

**Fixture.** `tests/structural/test_algorithm_memento.py`
(`test_direct_snapshot_requires_capture_and_final_restoration`).

### 5.24 A relation operand may name a member

```
where final_field_value($write, $memento.$saved);
```

**Evidence.** `src/ken/kql2/graph.py:428-441` admits an operand that is a role or
a member rooted in a bound role, and keeps the positive-binding check for the
holder. Operand rendering: `src/ken/kql2/graph.py:158-166`.

**Unblocks** `memento#snapshot-object`, whose finality check names the member the
restore read.

**Verification for 5.22-5.24.** `tests/structural/test_catalog_kql2_migration.py
-k memento`, `tests/structural/test_algorithm_memento.py`,
`tests/structural/test_memento_accessors.py`,
`tests/structural/test_memento_serialized_snapshot.py`,
`tests/structural/test_catalog_adversarial_matrix.py -k memento`, and
`tests/structural/test_negative_corpus.py -k memento` — all green.

**Measured gap (not landed).** `memento#accessor-snapshot` and
`memento#serialized-snapshot` therefore stay on their legacy clauses. Pinning a
call's *receiver input* to a method parameter is still missing: with
`param $memento {}` declared on the method and
`let $read = call $getter { receiver: $memento; };`, the
`restore-rebind` fixture (`s = Snapshot(0); self.state = s.get()`) still matches,
because an unbound receiver role is satisfied by the call's own `RECEIVER` row
(`src/ken/kql2/body.py:1627-1645`), and `CALL_RECEIVER_INPUT(call, parameter)` —
the relation the legacy accessor query required — has no KQL2 spelling.

### 5.25 `call $x` is callee position, `call on $x` is receiver position

The two ways to name the place an invocation runs on are **not** synonyms, and
after the observer rewrite the engine keeps them strictly apart:

- `call $x { ... }` — `$x` is the value that gets **invoked** (the callee). For
  an iterated element this is the `item(value)` shape: the collection supplies
  the callable, so the evidence is `CALLEE_VALUE(call, element)`.
- `call on $x { ... }` — `$x` is the **receiver** of an operation it offers (a
  dynamic dispatch with no named callee). For an iterated element this is the
  `item.next(value)` shape: the element is the receiver, and the walk must
  dispatch it (`RECEIVER(call, element)` together with
  `ITERATION_INVOKES_VALUE(loop, call)`).

**Evidence.** `src/ken/kql2/body.py:1568-1587`: the `on` branch sets
`target = None` and treats the receiver as the whole evidence, while the
callee branch requires `CALLEE_VALUE` and explicitly refuses to let a receiver
call satisfy callee position ("a receiver call must not satisfy callee
position, or the two spellings would be indistinguishable").
`tests/kql2/test_insert_effect.py:120-143`
(`test_iterated_element_is_the_receiver_of_the_operation_it_offers`) pins the
distinction: on a Java `for (IntUnaryOperator action : pending) action.applyAsInt(context)`
fixture, `call on $element { argument $context at 0; }` yields one row and
`call $element { argument $context at 0; }` yields none.

**Authoring rule.** A catalogue entry that is meant to accept *either* form
spells both arms with a **pattern-level** `either { ... } or { ... }`. The two
observer entries that need this are `observer#snapshot-registry` and the
`observer` `event_delivery` operation:

```
either {
  call $handler { argument $event at any; };
} or {
  call on $handler { argument $event at any; };
}
```

**Evidence.** `tests/structural/test_collection_snapshots.py:96-98`
(`test_direct_callable_elements`) asserts that `source(language).replace('item.next(value)', 'item(value)')`
still matches, while the unmodified fixture uses `item.next(value)` — so the
same registry entry must accept the callee form and the receiver form.

**Why pattern level, not body level.** A body-level `either` (two `call`
instructions inside one `body { }`) parses but `src/ken/kql2/graph.py:block`
rejects it — measured at 100 % failures in the observer rewrite — so the
alternative belongs at pattern level, where each arm contributes its own
whole-body match.

**Verification.** `tests/kql2/test_insert_effect.py`,
`tests/structural/test_collection_snapshots.py -k direct_callable`,
`tests/structural/test_algorithm_observer.py -k snapshot`,
`tests/structural/test_catalog_kql2_migration.py -k observer`, and
`tests/structural/test_catalog_adversarial_matrix.py -k observer` — all green.

### 5.26 The Optional protocol: `wraps:`, `empty:`, `present:`, `fallback:`

Landed 2026-09-15 with the `architecture.cache-aside#java-optional` rewrite, the
last legacy block of that catalog.

**The evidence.** `src/ken/structural/java_optional.py:41` publishes
`OPTIONAL_VALUE(call, value)` for `Optional.ofNullable(x)` and `:52` maps the
receiver methods `or`/`ifPresent`/`orElse` to `OPTIONAL_OR`,
`OPTIONAL_PRESENT` and `OPTIONAL_FALLBACK(call, operand)`. Every row hangs off
the *call occurrence* of the API method — which is why the vocabulary is a
`call`-clause property and not a selector:

```kql
callable $supplier {
  var $loaded { }
  body {
    call $load { name: ["load"]; argument $key at 0; };
    call $loaded_optional { wraps: $load; argument $load at 0; };
    call on $loaded { present: $consumer; };
    return $loaded;
  }
}
body {
  call $lookup { receiver: $cache; name: ["get", "Get"]; argument $key at 0; };
  call $boxed { wraps: $lookup; argument $lookup at 0; };
  call $choice { empty: $supplier; argument $supplier at 0; };
  call on $choice { fallback: "NULL"; returned: true; };
}
```

- `wraps: $value;` — `OPTIONAL_VALUE(call, value)`: the value the factory wraps.
- `empty: $supplier;` — `OPTIONAL_OR(call, supplier)`: the callable the empty
  case runs.
- `present: $consumer;` — `OPTIONAL_PRESENT(call, consumer)`: the callable a
  present value runs.
- `fallback: $value;` (role or literal) — `OPTIONAL_FALLBACK(call, value)`.

The four names live in `src/ken/kql2/source_optional.py:5` (`OPTIONAL_ROLES`)
and are resolved by `optional_row` (`source_optional.py:9-24`): the row's other
side binds the operand role, so `wraps: $load` leaves `$load` naming the load
call itself. They are accepted in both `call $x { ... }` and
`let $x = call $y { ... }` position (`src/ken/kql2/body.py:505-519` and
`:589-599`) and read at match time by `body.py:1783-1786`.

**Three rules make the rewrite decidable.** All three were measured on the
`test_optional_cache_aside.py` fixture:

1. *A protocol row alone is not evidence.* The callee branch accredits a
   target, and only an `argument` or `resolution` constraint lets an
   unaccredited occurrence stand for itself (`body.py:1488-1498`). Without one,
   `call $boxed { wraps: $lookup; };` reports
   `source_body:unknown` (measured) instead of matching, so every
   factory-position clause names its argument: `argument $lookup at 0;`.
2. *A receiver-only invocation is spelled `call on $place`*, where the receiver
   is the whole evidence (`body.py:1566-1593`; see §5.25). `loaded.ifPresent(c)`
   and `choice.orElse(null)` have no callee to accredit, so they are anchored on
   the place they run on: `call on $loaded { present: $consumer; };` and
   `call on $choice { fallback: "NULL"; returned: true; };`.
3. *A declared local is bound by `var $local { }`*, which matches the
   declaration the enclosing callable `DECLARES` (`src/ken/kql2/source_patterns.py:281`).
   The receiver role of rule 2 and the returned role must be that declaration:
   `callable $supplier { var $loaded { } body { ... return $loaded; } }` binds
   `$loaded` to `STORAGE:loaded` on the fixture, while `let $loaded = call ...`
   binds a produced value instead and cannot name the receiver.

**One engine fix came with it.** Naming a role as a protocol operand registered
it in the pattern's `roles` but not in its `outputs`, so a later
`call $load { ... }` clause could not register it either and the compiler
reported `graph output is not bound in every alternative`. Both validation
loops now add the operand role (`body.py:519` and `:599`).

**Verification.** `tests/structural/test_optional_cache_aside.py` — 19 passed:
one match on the Java fixture and on its renamed copy; the eight near-miss
mutations (`other.set`, `cache.set(other, ...)`, `cache.set(key, other)`,
`store.load(other)`, `return other`, `other.ifPresent`, `orElseGet`,
`cache.get(key)`) rejected; the eight shadowed/unresolved-`Optional` sources
produce no `OPTIONAL_*` fact at all; a rebound local does not propagate the
Optional type; and `architecture.cache-aside#java-optional` is selectable on its
own. Frozen parity for the root entry:
`tests/structural/test_catalog_kql2_migration.py -k cache`.

### 5.27 A `VALUE` role in argument position states the argument's origin

`architecture.cache-aside#null-miss` writes the loaded value back to the cache:

```kql
let $filled = call $load { argument $key at 0; };
call $write { receiver: $cache; name: ["put", "set", "Set"];
              argument $key at 0;
              argument $cached at 1;
              argument $filled at 1; };
```

Both clauses speak about the argument at position 1, and they mean different
things by it — which is the whole point:

- `argument $cached at 1` names a **storage** role (`var $cached { }`). The
  matcher falls to the identity branch (`src/ken/kql2/body.py:1865-1866`): the
  argument occurrence must *be* that binding. Reassigning the binding does not
  change that, so this clause alone still matches a source that rebinds
  `value = None` before `cache.set(key, value)`.
- `argument $filled at 1` names a role bound by `let $filled = call $load { }`,
  i.e. a **produced value** (`body.py:1885-1889`). The matcher then compares the
  call's `ARGUMENT_VALUE_ORIGIN` rows for that position against the role
  (`body.py:1854-1861`), passing only when the two are the same evaluated origin
  (`captured_reaches`, `body.py:826-837`). A rebound local has a different
  origin, so the clause rejects it; a `may`-modal origin degrades to
  `Unknown('argument_origin_may')` instead of a false match.

**`from` is not argument syntax.** The parser accepts `argument <srcExpr> [for
$param | at N | at any | at name("x")] [as $a];` and nothing else
(`src/ken/kql2/syntax/parser.py:652-670`) — `argument $cached at 1 from($filled)`
fails with `expected ';', got 'from'`. The only `from` forms in the language are
the top-level clause and `initializer $field from $value;`
(`parser.py:700-709`, §5.1/§5.18). The origin constraint is therefore spelled by
*naming the producing role at the position*, not by a new keyword.

**Verification.** `tests/structural/test_catalog_adversarial_matrix.py -k cache`
— 71 passed, including the three `directed/modern-cache-aside-*-negative` cases
that rebind the local before the write. `tests/structural/test_optional_cache_aside.py`
plus `tests/structural/test_catalog_kql2_migration.py -k cache` — 21 passed.
`tests/structural/test_cache_aside_flow.py` went from 25 to 20 failures: the
clause restored exactly the `value-after-load` family (5 languages) and broke
nothing. The remaining 20 are *other* lost constraints, not origin ones: a
frozen-oracle probe (`/tmp/probe_flow_legacy.py`, the pre-KQL 2 query from
`tests/structural/catalog_matrix/pre_kql2_catalog.json` run over the same
fixtures) shows 0 mismatches, so `alias-return` (returned through an alias) plus
`value-before-test`, `value-after-write` and `value-after-branch` (the tested or
returned binding reassigned away from the written value) are still open contract
losses of the `null-miss` rewrite.

### 5.28 Three lowering rules that made `null-miss` agree with the frozen oracle

`tests/structural/test_cache_aside_flow.py` pins 18 variants per language of the
same read/load/write/return contract. Three changes closed the gap between the
`null-miss` rewrite and the pre-KQL 2 query; the frozen-oracle probe
(`/tmp/probe_flow_legacy.py` runs the catalog's own query over the same fixtures;
`/tmp/probe_flow_migrated.py` runs the rewrite) reports `0 mismatches` over the
18 cases x 5 languages.

**1. A `writes:` filter may name a binding the selector declares later.** The
write inventory of a callable is published per binding —
`BINDING_WRITE_STATUS(callable)` and `BINDING_WRITE_COUNT(callable, storage)` —
so `writes: exactly($cached, 2)` belongs to the enclosing `callable $unit`, but
`$cached` is declared by the sibling `var $cached { }`. Lowering used to fail with
`writes matcher requires an already bound source binding` (`graph.py:221`); the
check is now collected during the forward pass and applied at the end of the
enclosing block (`src/ken/kql2/graph.py`, `forthcoming`). A filter that still
names an unbound role after the whole block is lowered fails with the same message.

**2. A selector's filters are lowered after its declarations and before its
body.** Needed for rule 1 to hold at *runtime*: node order is the plan's order, and
the `source_type` node resolves `bindings['$cached']`, which only exists after the
`var` declaration has been lowered (`src/ken/kql2/source_patterns.py:287-303`).
The position matters in both directions — with the filter after the body,
`test_catalog_adversarial_matrix.py::test_catalog_semantic_oracle[directed/long-noise-cache-aside]`
exhausts `max_states=100000`, while declarations-then-filters-then-body stays
inside the budget (71 passed for `-k cache`).

**3. `return $place` accepts a returned alias.** `result = value; return result`
returns the value the place holds, and the return occurrence still carries
`RETURN_ORIGIN` for the lookup and the load. The return matcher took the origin
route only for a `VALUE` role; for a place role it compared operand identity, so
the alias missed. It now falls back, for `STORAGE`/`PARAMETER`/`MEMBER`/`FIELD`
roles, to agreeing origins: the values the return yields (`RETURN_ORIGIN`) must
intersect the values the place was written from (`ASSIGNED_FROM`) —
`src/ken/kql2/body.py`, return branch. Ordering is not relaxed: the body's clause
cursor already fixes that the pattern's writes precede this return, which is why
`return-before-load`, `return-before-write`, `value-after-write` and
`value-after-branch` still reject.

**Verification.** `tests/structural/test_cache_aside_flow.py` (72 params),
`test_cache_aside.py` and `test_optional_cache_aside.py` — 178 passed;
`tests/structural/test_catalog_adversarial_matrix.py -k cache` — 71 passed;
`tests/structural/test_catalog_kql2_migration.py` (whole file) — 81 passed;
`tests/kql2` — 934 passed. The whole `tests/structural tests/kql2
tests/common_ast` suite is green except
`tests/structural/test_construction_access.py::test_many_private_overloads_keep_the_query_bounded`,
which already failed before these changes (same test id in the earlier
`/tmp/bg31_prototype_fieldcopy.log` suite).

### 5.29 `origin: $lookup;` — the walk over a batch a lookup filled

Legacy relations: `ITERATION_SOURCE`, `ITERATION_ORIGIN`, `ITERATION_ENTRY_SOURCE`.

`unit-of-work.keyed_flush` walks a local batch a map lookup filled
(`batch = changes.get("new")`, then `for item in batch: store.insert(item)`). `iterate`
*requires* the entry source of a walk over a storage place — the evidence that the place
was neither replaced nor cleared before the loop — and the frontend publishes none for a
local that was written once by a call. The walk's own origin says the same thing from the
other side, so the clause now lets the pattern state it:

```kql
let $batch = call $lookup { receiver: $changes; name: ["get", "GetValueOrDefault"]; resolution: unresolved; };
iterate $batch as $item as $iteration {
  origin: $lookup;
  body { call on $store { name: $action in [ ... ]; argument $item at 0; resolution: unresolved; } as $effect; }
}
```

With the property the matcher requires `ITERATION_ORIGIN(loop, $lookup)`, exactly one
walked source, and that the walked value is that call's result; the entry-source test is
skipped. Without it the walk of a lookup-filled local is refused — both directions are
pinned by `tests/kql2/test_iterate_origin_and_callee_name.py`
(`src/ken/kql2/body.py`, `compile_body`'s iterate branch and `match_step`'s `iterate`
branch).

### 5.30 `name: $action in [ ... ]` — the callee spelling the call used

Legacy relations: `CALLEE_NAME`, `ENTITY`(CALL) `name`.

`name: [...]` *stated* the spellings a protocol is recognised under; it could not *report*
which one a matched occurrence used, so `unit-of-work.keyed_flush` could not expose the
persistence action it saw (`insert`/`delete`). The property now takes a role, with or
without the whitelist: `name: $action;` reports the spelling, `name: $action in
["insert", "update", "modify", "delete", "save"];` reports it and keeps the alternatives.
The role must be declared by the pattern (`out Value $action`), which is the same rule the
source capture states. Helper `named_role` (`src/ken/kql2/body.py`).

### 5.31 The place a call filled — resolving `ASSIGNED_FROM`

Legacy relation: `ASSIGNED_FROM`.

A local that receives a call result is modelled twice: the role a `let` binds is the
call's *result*, while the frontend publishes the write against the *storage* the result
landed in (`ASSIGNED_FROM(storage, call)`). Helper `landed_place`
(`src/ken/kql2/body.py`) resolves the one to the other, so a pattern states provenance and
still correlates the writes it needs:

```kql
let $batch = call $lookup { receiver: $changes; name: ["get", "GetValueOrDefault"]; resolution: unresolved; };
insert $entity into $batch as $insertion;      # the place the lookup filled
```

Landed in the **insertion matcher** (the collection named by the producing call) and in the
**indexed assignment** right-hand side (`$changes[$key] = $batch;`), both pinned by
`tests/kql2/test_iterate_origin_and_callee_name.py`. In the **argument** position the
resolution was attempted and reverted: without a staleness test it accepted a local that a
later assignment had replaced (`facade#module-surface`
`test_result_overwritten_before_consumption_is_rejected[*]`,
`tests/structural/test_authored_behavioral_template.py::test_composed_steps_conserve_results[overwrite-*]`),
and the tests that would make it safe — "the place was assigned exactly once, by this
call" — reject the map-API fixtures, where the batch is initialised under a guard
(`if (batch == null) { batch = []; }`) before it is stored. That gap is what keeps
`persistence.unit-of-work#keyed-change-set` on its legacy clauses (below).

### 5.32 `$registry[$key] = $value;` — an indexed assignment target

Legacy relations: `WRITES_ELEMENT`, `INDEX`, `STORES_VALUE`, `ASSIGNMENT_TARGET`.

The parser already accepted an indexed place as an assignment target; the body compiler
rejected the place and the matcher resolved only member and role targets. An indexed
assignment now resolves through the element's own `VALUE` node, whose `CONTAINER` and
`INDEX` evidence name the registry and the key the write uses, so
`$changes[$entity] = $batch;` is refused where `$changes[$key] = $batch;` matches.

### 5.33 `entry: $place;` — the binding a call is entered with

Legacy relation: `CALL_ENTRY_BINDING`.

`unit-of-work.keyed_flush` requires the coordinator to call its worker while the changes
field still holds what the registration filled; the legacy entry said so with
`edge CALL_ENTRY_BINDING($local_delegate, $changes)`. A selector-level call clause now
states the same:

```kql
method $flush { call $delegate { target: $worker; entry: $changes; } }
```

`entry:` requires the place to be a bound storage role and matches `CALL_ENTRY_BINDING`
(`src/ken/kql2/body.py`, both constraint loops and the matcher;
`src/ken/kql2/source_patterns.py` lowers it; `src/ken/kql2/compiler.py` registers the
property). It is what makes
`tests/structural/test_catalog_adversarial_matrix.py::test_catalog_semantic_oracle[directed/uow-erases-before-commit]`
reject a coordinator that empties the changes before it delegates.

Verification for 5.29-5.33: `tests/structural/test_unit_of_work.py` (80 passed, five
languages), the frozen pre-KQL 2 parity of both `unit-of-work` entries
(`tests/structural/test_catalog_kql2_migration.py`, 81 passed),
`tests/structural/test_catalog_adversarial_matrix.py -k unit` (32 passed) and
`tests/kql2/test_iterate_origin_and_callee_name.py` (7 passed).

### 5.34 An insertion value named by the call that filled it

Legacy relation: the `VALUE`/`LOADED_FROM` chain from an insertion's stored node back to the
local the producing call filled.

`unit-of-work#keyed-change-set` states its keyed write-back with

```kql
let $batch = call $lookup { receiver: $changes; name: ["get", "GetValueOrDefault"]; resolution: unresolved; };
insert $entity into $batch;
insert $batch into $changes at $key;
```

`$batch` names the local by the *call* that filled it, while the frontend records the
insertion against the *place* that call landed in (`ASSIGNED_FROM`). The insertion matcher
already resolved that for the collection (`landed_place`); it resolves it for the value
operand too (`src/ken/kql2/body.py`, the insert branch). The place has to still hold what the
call left there: every other producer of the place must be the null-coalescing fallback
(`if batch == null: batch = []` — a collection literal, an allocating construction or a call
with `ALLOCATES_TYPE`). An unconditional overwrite stays refused, which is what
`tests/structural/test_facade_module_surface.py` and
`tests/structural/test_authored_behavioral_template.py::test_composed_steps_conserve_results`
pin.

### 5.35 A map-API insertion publishes its stored place as an argument

Legacy relation: `ARGUMENT` plus `VALUE`/`LOADED_FROM` for `changes.set(key, batch)`.

`changes.set(key, batch)` (javascript, typescript) and `changes.put(key, batch)` (java)
publish `WRITES_ELEMENT` and `INDEX` on the call and the stored place as the call's
*argument*, not as `STORES_VALUE`. The stored-value candidates of an insertion now also read
the occurrence's `ARGUMENT` objects, so one
`insert $batch into $changes at $key;` covers the indexed write, the `STORES_VALUE` call and
the map-API call (`src/ken/kql2/body.py`).

### 5.36 `at least N distinct $role { ... }` — existential cardinality

Legacy clause: `tally distinct $role >= N { ... }`.

`unit-of-work#keyed-change-set` requires the unit's flush path to perform *two different*
persistence actions. No body pattern can state that: it is a claim about how many distinct
solutions a nested block has. KQL 2 now spells it

```kql
at least 2 distinct $action {
  use ken.catalog.persistence.unit_of_work.keyed_flush.detect(unit: $unit, changes: $changes, flush: $flush, store: $store, action: $action);
};
```

`src/ken/kql2/syntax/parser.py` reads the clause (`at`, `least`, integer, `distinct`, role,
block) and `src/ken/kql2/graph.py` lowers it to the counting node the older
`tally distinct` spelling builds, selecting the relational kernel for it. The legacy spelling
keeps parsing; no migrated entry uses it.

**Measured state of `unit-of-work.toml`.** Both entries are pure KQL 2 and the file carries no
`edge`/`walk`/`tally` clause.


### 5.37 `declares_event`, `subscribes`, `unsubscribes`, `raises` — the C# event vocabulary

Legacy clauses: `edge DECLARES_EVENT(...)`, `edge ADDS_HANDLER(...)`,
`edge REMOVES_HANDLER(...)`, `edge HAS_CALL(...) { execution: "possible" }` +
`edge RAISES_EVENT(...)`.

`observer#language-event` is the only entry that needs them, and it is also the
clearest F8 case: the pattern is "a type declares an event, one method registers a
handler, another removes one, a third raises it, all over the **same storage**".
The IR already states every half; what was missing was the vocabulary to name them
at the level the sentence speaks at. KQL 2 now spells it

```kql
pattern detect(out TypeDecl $unit, out Field $event, out Callable $attach,
               out Callable $detach, out Callable $raise) {
  type $unit {
    field $event { }
    method $attach { constructor: false; }
    method $detach { constructor: false; }
    method $raise { constructor: false; }
  }
  where declares_event($unit, $event);
  where subscribes($attach, $event);
  where unsubscribes($detach, $event);
  where raises($raise, $event);
  where $attach != $detach;
}
```

Four things landed:

- `declares_event($unit, $event)` reads `DECLARES_EVENT`. A delegate-typed field
  never gets the fact, so `+=` on a plain `Action<int>` field is not a handler
  registration — the exclusion the legacy query bought with the relation is the
  relation's own semantics, not a query trick.
- `subscribes($method, $event)` reads `ADDS_HANDLER` and
  `unsubscribes($method, $event)` reads `REMOVES_HANDLER`
  (`RELATIONS` in `src/ken/kql2/semantic.py`; both facts are keyed by the callable,
  so no join is needed).
- `raises($method, $event)` needs a join the IR did not publish: `RAISES_EVENT` is
  keyed by the *call* and `HAS_CALL` by the callable that owns it. Rather than
  recompute it per evaluation, `src/ken/structural/events.py` now publishes
  `METHOD_RAISES_EVENT(method, event)` beside the call-level fact, and
  `RELATIONS['raises']` reads it. The catalog engine executes the compiled plan
  against the live IR (`src/ken/structural/rules.py:371`), so a derived fact has
  to live in the IR; materializing it in the KQL 2 store instead is measured not to
  work (the plan never reads that table).
- The relation is registered in the graph's relation set
  (`src/ken/structural/relational.py:55`); without that the plan refuses to compile
  with `unknown graph relation METHOD_RAISES_EVENT`.

The legacy `HAS_CALL(...) { execution: "possible" }` filter is not reproduced as an
attribute check: `RAISES_EVENT` is only published from a *resolved* receiver or
callee value that names the declared event, so an unresolved or shadowed member
never reaches the join. `METHOD_RAISES_EVENT` therefore carries the invocation
evidence and `basis: event-invocation`, not an execution budget. If a later
language needs to exclude unreachable calls, that belongs to the execution pass.

**Verification.** `tests/structural/test_observer_language_event.py` (7 tests: the
positive binding of all five roles, the two-handler registration fact, the
cross-class resolution, and the four exclusions — plain delegate, custom accessor,
never raised, attach/detach on different events), `tests/structural/test_catalog_kql2_migration.py`
(frozen parity for the entry), `tests/structural/test_catalog_adversarial_matrix.py -k observer`,
`tests/structural/test_negative_corpus.py -k observer`. `observer.toml` carries no
`edge`/`walk`/`tally` clause. The test's `test_variant_is_ready_for_its_single_declared_language`
used to assert the retired operator spelling in the query text; it now asserts the
KQL 2 predicates and the absence of legacy clauses.


### 5.38 `base: $parameter` — the runtime base a locally created type carries

Legacy clauses: `edge BASE_INPUT($derived, $base)`, `edge DECLARES($factory, $derived)`,
`edge HAS_PARAMETER($factory, $base)`, `edge ENTITY($base, "PARAMETER") { receiver: false; }`,
`edge ENTITY($derived, ["CLASS", "INTERFACE"])`, and the `either` arm
`{ UNREASSIGNED_BINDING + RETURN_FLOW_STATUS + RETURNS_VALUE } or
{ ENTITY(..., "CALLABLE") { native_kind: "arrow_function" } + BODY_VALUE }`.

`subclass-factory#returned-subclass` is the pattern "a factory hands back a type it
created locally, built on a base it was given": `def extend(base): class Derived(base): ...;
return Derived` — the base is a *runtime value*, not a nominal `extends Foo` spelling.
The IR already proves which parameter that base came from
(`BASE_INPUT(derived, base)` in `src/ken/structural/value_contracts.py:74`, derived from
`BASE_VALUE` through unique preceding aliases and `STORAGE_WRITE_COUNT == 0`); what was
missing was the vocabulary to say it at the level the sentence speaks at. KQL 2 now
spells it

```kql
pattern detect(out GraphTerm $factory, out GraphTerm $derived, out GraphTerm $base) {
  callable $factory {
    param $base { reassigned: false; }
    class $derived { base: $base; }
  }
  where returns_value($factory, $derived);
}
```

Three things landed:

- `base: $place` on the type-like selectors (`class`, `interface`, `trait`, `type`)
  reads `BASE_INPUT`. It is declared in `compiler.py` beside `derive:` (the other
  type-level relation) and lowered in `source_patterns.py:selector` to
  `relation('BASE_INPUT', subject, value)`; a non-role operand is rejected with
  `base requires a place role`. It deliberately does *not* read `EXTENDS`/`SUBTYPE_OF`:
  a supplied value and an inheritance spelling are different facts, and
  `test_parameter_base_is_not_a_same_spelled_nominal_class` pins that difference.
- A callable can immediately own a type declaration. The selector compiler's ownership
  map rejected `class` nested in `callable` with `callable cannot immediately own class`,
  although the frontend publishes `DECLARES(scope, declared)` for a type defined inside a
  function body. `class`/`interface`/`trait`/`type` were added to the callable-owned
  `DECLARES` branch.
- `where returns_value($factory, $derived);` reads `RETURNS_VALUE`
  (`RELATIONS['returns_value']` in `src/ken/kql2/semantic.py`), which is what separates
  "the factory returns the class" from `return Derived()` (an instance), `return base`
  (another value) and no return at all.

The legacy `either ... or` arm did not need a KQL 2 counterpart: a concise arrow whose body
is the class expression publishes `RETURNS_VALUE` like any other return, so
`const extend = (base) => class extends base { ... };` matches the same three clauses
(`tests/structural/test_subclass_factories.py::test_arrow_factory_returns_a_class_value`).
The anonymous spelling `return class extends base { }` also matches, because a selector
matches an entity by native kind, not by name; the `reassigned: false` filter on the
parameter is the accepted way to state that the binding is never overwritten, and it is
what excludes the `input-before` and parameter-write-after-definition negatives.

**Narrowing to record.** The legacy query accepted `ENTITY($derived, ["CLASS", "INTERFACE"])`.
The migrated selector says `class`, i.e. `CLASS` only: for the three languages the variant
declares (python, javascript, typescript) the fixtures publish `CLASS`, and `type $derived`
(wider: `CLASS|INTERFACE|TRAIT|STRUCT`) or an explicit `either { class ... } or { interface ... }`
remain available if a language starts publishing an interface as the returned base.

**Verification.** `tests/structural/test_subclass_factories.py` (57 tests: 7 positives × 3
languages, the 6 near misses × 3 languages, the nominal-shadow identity test, the unique
preceding alias, the arrow factory and the 150-independent-factories budget),
`tests/structural/test_catalog_kql2_migration.py` and
`tests/structural/test_catalog_adversarial_matrix.py -k subclass`. `subclass-factory.toml`
carries no `edge`/`walk`/`tally` clause.

### 5.39 `where guarded_write($field, $access);` — a write guarded by its own field

Legacy clause: `edge GUARDS_WRITE($subject, $access) { execution: "possible"; }`.

`proxy#lazy-subject` calls for "the accessor writes the storage under a guard that
references the storage". The frontend publishes that as `GUARDS_WRITE(storage, callable)`,
and the absence test may be spelled `is None`, `is_none()`, `=== null`, `== None` or a
`match`. A BODY condition cannot carry that claim without pinning one spelling: the
seeded Rust witness in `tests/structural/catalog_matrix/seeds.json` writes
`if self.subject.is_none()`, which publishes **no** `NULL_TEST` row at all, while
`if self.inner is None` does.

The relation is therefore public, beside `delegates_to`, `reads`, `writes` and
`writes_element` (`src/ken/kql2/semantic.py`, `SEMANTIC_ATTRS` in `src/ken/kql2/graph.py`):

```kql
where guarded_write($field, $access);
```

It reads as "the storage is written under a guard that names the storage". A guard on an
unrelated flag publishes no `GUARDS_WRITE` row, and an unguarded write publishes none
either, so both negatives stay rejected. `execution: possible` is required, exactly as for
`delegates_to`.

### 5.40 `require one dispatch of $method;` — one call site dispatches the operation

Legacy clause: `tally distinct $same_operation == 1 { edge HAS_CALL($local_method,
$same_operation) { execution: "possible"; } where $same_operation.name == $local_method.name; }`.

`proxy.single_guarded_dispatch` needs "the wrapper has **one** syntactic dispatch of its
operation": under the guard model the forwarding call may be spread over an arm and a
continuation, so the count is what separates a single dispatch from a guarded dispatch
followed by an unconditional bypass. The quantifier clause that already carries
`require one allocation of $unit;` now accepts a second domain:

```kql
require one dispatch of $method;
```

The owner is the callable itself (`require`'s owner check accepts a `method`, `function`,
`callable` or `constructor` selector for this domain; a type declaration stays the owner of
`allocation` and `constructor`). The inventory counts the callable's own `HAS_CALL` rows
with `execution: possible` whose callee spelling equals the declaration's own name, and it
is **closed** only by the structured-CFG witness (`CFG_STATUS` = `structured` at
`level: statement`) with every owned occurrence spelling known; without that witness the
inventory is open and the quantifier reports
`source_quantifier:dispatch:incomplete_inventory` as `unknown` instead of a match. The name
comes from the bound role or, for a foreign binding, from the published `ENTITY` row
(`src/ken/kql2/source_quantifiers.py`).

### 5.41 `argument $creation at any;` — an argument that receives a construction's result

Legacy clauses: `edge RESULT($creation, $local_created_value)`, `edge
ARGUMENT($local_container, $local_argument)`, `edge VALUE($local_argument,
$local_created_value)`.

Python, Java, C# and C++ store the subject with `self.subject = RealSubject()`; Rust wraps
it: `self.subject = Some(RealSubject { })`. The stored value is then the *wrapper call*,
and the created value reaches the field as that call's argument. Until this step the
argument operand only matched the argument object itself (`argument $x at any`, identity)
or an `ASSIGNMENT_VALUE`/`ARGUMENT_VALUE_ORIGIN` chain, so the wrapped form had no
spelling. A call-entity operand now also matches when the argument's value is *that call's
result*:

```kql
let $local = construct $created { } as $creation;
call $wrapper { argument $creation at any; };
$field = $wrapper as $write;
```

The identity comes from published rows only — `RESULT($creation, $result)` and
`VALUE($argument, $result)` — never from a name, a position or a wrapper protocol, so
`Some`, `Optional.of`, a builder call and a user-defined wrapper behave alike, and a call
that receives something else (or nothing) does not match (`src/ken/kql2/body.py`, the
argument matcher). The construction call must be declared as a `Call` role
(`out Call $creation`) for the operand to have a domain.

### 5.42 Guarded delegation in a BODY — the arm and the early-return forms

No grammar change; the two shapes below are what `proxy#guarded-access` and
`proxy.single_guarded_dispatch` state, and they reproduce the legacy arm-or-continuation
model:

```kql
body { if (_) { call $forward { receiver: $subject; }; } }
body { if (_) { return _; } call $forward { receiver: $subject; }; }
```

The first arm is "the forwarding call is what a lexical branch arm performs"; the second is
"a guard whose other arm returns, then the forwarding call on the continuation". The `if (_)`
operand is deliberately opaque: the legacy query never constrained the guard expression, and
using it keeps a call in the *guard condition* out of the arm (which the plain
`CONDITIONAL_DELEGATION` fact alone does not — it is also published for `if inner.run(x):`).
Two authoring rules matter and cost a probe each:

- `either` is **not** implemented inside a BODY (`BODY instruction is not implemented:
  either`); alternatives go around whole selectors at pattern level.
- A delegating call whose callee the frontend cannot resolve (Rust `self.subject.as_ref()`)
  matches **no** `call $forward { receiver: $subject; }` clause; the receiver-only spelling
  `call on $subject { };` is the evidence form, and it is what `proxy#lazy-subject` uses.

**Verification.** `tests/kql2/test_dispatch_and_guard.py` (10 tests: the dispatch count, its
declared owner, the open-inventory witness, `guarded_write` on `is None` and `is_none()` and
its two negatives, and the carried-construction argument with its negative),
`tests/structural/test_proxy_lazy_subject.py` (8 languages, 6 negatives),
`tests/structural/test_proxy_remote_subject.py` (8 languages, 4 negatives, renames, the
root rule), `tests/structural/test_algorithm_proxy.py` (the guard placements and the four
mutation families), plus `tests/structural/test_catalog_kql2_migration.py` and
`tests/structural/test_catalog_adversarial_matrix.py -k proxy`. `proxy.toml` carries no
`edge`/`walk`/`tally` clause.


### 5.27 Exclusivity by callee name: `require one dispatch of $callable named $call`

Landed with the `chain-of-responsibility.single_exclusive_handler` rewrite, the
last legacy block of that catalog. **No new primitive was needed**; this note
records the existing spellings the hand-authored contract depends on, because
three of them are easy to get wrong.

**What the entry states.** A linked handler — a method of a type that both
inherits the handler contract and stores a successor of it — either forwards the
request to that successor or handles it locally, and returns whichever result it
took: two distinct returns, one of the forwarding call and one of a call to a
sibling method of the same type. The forwarding call is branch guarded and
carries the handler's own request parameter.

**The three spellings it turns on.**

- **`target:` is a method-level call property, not a body one.** Writing
  `target: $processing;` inside `let $x = call $local { ... };` does not compile
  (`unsupported call constraint`, `src/ken/kql2/body.py:577`). The same property
  on a bare `call $local { receiver: $self; target: $processing; }` clause at
  *method* level compiles, so that is where the local dispatch is declared.
  Measured over five spellings directly against
  `compiler.compile(parser.parse(...))`.
- **The instance receiver is a method-scoped role.** `receiver $self { }` inside
  the method, plus `receiver: $self;` on the call, is the
  `INSTANCE_RECEIVER` / `RECEIVER` pair; `src/ken/kql2/source_patterns.py:70`
  lowers the `receiver` selector and `adapter#class-adapter` is the model.
- **Per-callee exclusivity is a counted quantifier, not a `tally`.** The legacy
  contract's two `tally distinct ... == 1` blocks count calls *by callee name*.
  `src/ken/kql2/source_quantifiers.py:69-96` shows `require one dispatch of
  $owner named $witness;` counts exactly that: the `HAS_CALL` rows of `$owner`
  whose callee spelling equals the witness call's own name. `require one
  dispatch of $handle named $local;` is what rejects a handler that processes
  twice (the `process-and-forward` mutation) while still accepting the clean
  shape.

**Verification.** `tests/structural/test_algorithm_chain_of_responsibility.py`
plus `tests/structural/test_chain_middleware_closures.py` are green (50 cases
combined, python/java/typescript and the eight closure languages);
`tests/structural/test_catalog_kql2_migration.py -k chain` and
`tests/structural/test_catalog_adversarial_matrix.py -k chain` are green; and
`grep 'edge \|walk \|tally ' src/ken/structural/patterns/chain-of-responsibility.toml`
returns nothing.

### 5.43 Polarity, the arm that stops the loop, and two authoring traps

Landed with the `iterator#callback-iterator` rewrite (the last legacy block of that
catalog). Legacy relations: `TRUTH_TEST($branch, $call) { when: false|true }` plus
`CFG_NEXT($branch, $exit) { kind: ... }`.

`callback-iterator` states a push iterator: a `func Each(values []int, yield func(int) bool)`
that calls `yield(value)` with the loop's own element and stops the loop when that boolean
says so. The branch is what makes the pattern: `if !yield(value) { return }`,
`if !yield(value) { break }` and `if yield(value) { consume(value) } else { return }` are
the same contract, and the test says so ("the polarity is not the contract; that the boolean
stops the loop is").

Three things the rewrite pinned down:

1. **The exit belongs to the arm the *false* result selects.** Of the four placements,
   only `if !yield(v) { return }`, `if !yield(v) { break }`,
   `if yield(v) { .. } else { return }` and its `break` twin are the contract; the two
   mirrored placements (exit in the arm the *true* result selects) are counterexamples,
   and `test_go_range_callback_false_must_stop` pins all four. The variant states them with
   spellings the callback suites already use:

   ```kql
   let $accepted = call $callback { argument $element at any; } as $call;
   if ($accepted == false) { return as $exit; }     # false edge, exit in the then arm
   if ($accepted == false) { break $loop as $exit; }
   if ($accepted) { } else { return as $exit; }     # false edge, exit in the else arm
   if ($accepted) { } else { break $loop as $exit; }
   ```

   No engine change was needed: `if ($accepted == false)` reads the accredited boolean the
   frontend publishes for `!callback(item)` (the same contract
   `tests/structural/test_callback_body_captures.py` pins per language), `break $loop as
   $exit;` binds the exit to the loop it stops, and `return ... as $exit;` aliases the
   return operation. The four placements are alternatives, so they sit in one pattern-level
   `either` over whole selectors.

2. **A `callable` selector declares its parameters with `param`.** `callable $iterator {
   param $callback {} }` binds the callback parameter; the `parameters { ... }` wrapper is
   *not* a source selector and is rejected (`unsupported source selector or selector
   alias`). The pattern's out-parameter must then be declared with the matching domain
   (`out Parameter $callback`), or the lowering reports
   `incompatible source selectors for $callback`.

3. **`returned: true` also accepts a member chain.** Extended for
   `flyweight#entry-api`, whose C++ fixture returns `pool.try_emplace(k, v).first->second`:
   the returned operand may be a `MEMBER_OF` chain of at most two steps below the call
   (the depth the legacy `walk MEMBER_OF($returned, $call) { min: 0; max: 2; }` allowed),
   beside the direct return and the runtime-cast spellings.

**Two authoring traps that cost a probe each.**

- **A pattern-level `body` clause has no owner** (`BODY requires a callable owner`). The
  `body { ... }` inside an `either` arm must be wrapped in its own selector, so a four-way
  disjunction repeats `callable $iterator { param $callback {} body { ... } }` once per arm.
- **`either` nested inside a BODY over `body { ... }` arms silently matches everything** —
  the arms are not applied as constraints, so the pattern degrades to "any loop, any
  branch, any return" and every negative fixture matches. Author alternatives *around whole
  selectors*, never inside a body. (The withdrawn alternative for this variant was exactly
  that: a single `callable` with `either` around three `body` arms.)
- The `if ($call) { }` spelling that names a call occurrence in a condition was prototyped
  and then withdrawn: it needs the polarity free, which is what the placement test above
  forbids, so the engine change was reverted and the catalog states `$accepted == false`
  instead.

**Verification.** `tests/structural/test_iterator_callback_iterator.py` (13 cases: the four
placements, three of them positive, plus the rename and rejection fixtures),
`tests/structural/test_behavioral_catalog_join_regressions.py::test_go_range_callback_false_must_stop`
(the four placements with their expected verdicts),
`tests/structural/test_callback_body_captures.py`,
`tests/structural/test_catalog_kql2_migration.py`, and
`grep -E '^\s*(edge|walk|tally)\b' src/ken/structural/patterns/iterator.toml` returns
nothing.

### 5.44 The derived-value operand: `argument from $place` / `return from $place`

**Need.** `adapter.input_conversion` and `adapter.output_conversion` -- the two object-adapter
operations -- each claim a *computed* origin, and said so with a dependence chain whose
intermediate value was deliberately unnamed:

```
edge ARGUMENT_VALUE_ORIGIN($local_forward, $converted);
walk VALUE_DEPENDS_ON($converted, $input) { min: 1; max: 8; } as $conversion;
...
edge RETURN_ORIGIN($return, $converted);
walk VALUE_DEPENDS_ON($converted, $local_forward) { min: 1; max: 8; } as $conversion;
```

The object adapter turns its incoming parameter into the argument it delegates (input
conversion) and consumes the delegated result in the value it returns (output conversion).
What the pattern asserts is the *derivation*, never the intermediate value's spelling.

**Spelling.**

```
call $local_forward { receiver: $local_field; argument from $input at any; };
...
call $local_forward { receiver: $local_field; } as $local_call;
return from $local_forward;
```

The operand may be given (`argument $converted from $input at any;`) or omitted; when it is
omitted the clause states only the derivation, which is what these two entries claim.

**Semantics (`src/ken/kql2/body.py`, `derived_from`).**

- The walk starts at the operand's own published origins -- `ARGUMENT_VALUE_ORIGIN` at that
  argument position inside a `call` clause, `RETURN_ORIGIN` (falling back to `RETURN_OPERAND`)
  for `return` -- and follows `VALUE_DEPENDS_ON`. A call standing in the chain continues it
  through its own `ARGUMENT_VALUE_ORIGIN` rows, so `sink(str(request))` derives from `request`
  one call further out.
- At least one hop is required: a value does not derive from itself (the legacy `min: 1`). The
  depth is capped at 8 hops (the legacy `max: 8`); a hop published with modality `may` returns
  `derivation_may` instead of a confirmed match, and a missing origin set returns
  `derivation_origin_missing` -- incomplete evidence, not a negative.
- The source place may be the *invoked callable* rather than a storage. The role of a `call`
  clause binds the resolved target when the call accredits one, so `return from $local_forward`
  reads as "a value that consumes a call of that symbol": the call occurrences that target it
  (`TARGET`, `DECLARED_TARGET`, `MAY_TARGET`) count as the chain's far end. This keeps both
  entries at their single `$unit` output, so no variant signature had to change.

**Parser (`src/ken/kql2/syntax/parser.py`).** `argument [<operand>] from $place [for $param | at POS];`
carries the place as a `from` expression on the argument clause; `return [<operand>] from $place;`
carries it as a `from` block on the return clause. The validator requires `$place` to be a role
the pattern bound (`derivation requires a bound place`), so an undeclared name stays a typo.

**A note on parity for these two entries.** The frozen `pre_kql2_catalog.json` has no rule with
the ids `adapter.input_conversion` / `adapter.output_conversion`, so
`tests/structural/test_catalog_kql2_migration.py` does not constrain them (its name filter
requires the id to exist in the frozen registry). Their evidence is the pattern-specific
suites below plus `tests/structural/test_ir178_contracts.py`, which exercises the same
snapshot-at-evaluation contracts with mutations.

**Verification.** `tests/kql2/test_body_derivation.py` (7 cases: computed argument over the
parameter, nested-call argument, an unrelated place, a constant, a derived return, a return
that never consumes the call, and the unbound-place refusal), `tests/kql2` (all),
`tests/structural/test_algorithm_adapter.py`, `tests/structural/test_ir178_contracts.py`,
`tests/structural/test_adapter_functional_adapter.py`,
`tests/structural/test_adapter_class_adapter.py`,
`tests/structural/test_catalog_kql2_migration.py`,
`tests/structural/test_catalog_adversarial_matrix.py -k adapter`,
`tests/structural/test_negative_corpus.py -k adapter`, and
`grep -E '^\s*(edge|walk|tally)\b' src/ken/structural/patterns/adapter.toml` returns nothing.

### 5.45 `resolution: any;` and the three spellings `mediator` needed

Legacy clauses replaced: `IS`, `HAS_METHOD`, `HAS_PARAMETER`, `ENTITY(PARAMETER)`,
`CONDITIONAL_DELEGATION`, `PARAMETER_TEST`, `PASSES_SELF_TO`, `INSTANCE_RECEIVER`, `IN_TYPE`,
`CALLEE_NAME`, `ARGUMENT`, `VALUE`, `LOADED_FROM`, `STORAGE_WRITE_COUNT` and a
`tally distinct $field >= 2` block.

**One new language value: `resolution: any;`.** The `resolution:` constraint accepted
`resolved`, `unresolved` and `ambiguous`, and *omitting* it means "the callee resolved to a
callable" (`src/ken/kql2/body.py`, the call matcher). The legacy relations never constrained
resolution, and the mediator fixture resolves differently per language: `self.first.apply(tag)`
is `unresolved` in Python and JavaScript but `resolved` in Go, Rust, Java and C++ (the callee
name matches a declared method). `resolution: any;` says "this occurrence is what the clause is
about, without constraining how it resolved": it still accredits the occurrence as evidence
(so a call clause may bind its role from it), but it filters nothing. Implemented in the call
validator (two sites, `call` and `let ... call`) and in the matcher; `resolution: _` stays
unsupported, so the three concrete statuses plus `any` are the whole vocabulary.

**Three authoring rules that cost a probe each.**

* **Guarded delegation is `if (_) { .. } else { .. }`.** A plain `body { call; call; }` matches
  two *sequential* statements and is rejected by an if/else pair; two separate `if (_)` arms
  match two separate `if` statements, not the `then`/`else` of one test. The mediator fixtures
  spell the dispatch as `if tag == 1: ... else: ...`, so the migrated entry uses the `else`
  arm. `else if` is not accepted, and a bare `else (_) { .. }` is a parse error
  (`unknown BODY instruction 'else'`).
* **The instance receiver is a selector inside the callable:** `method $notifier_a { receiver
  $self_a {} body { call $outgoing_a { argument $self_a at 0; }; } }`. Declared at type level it
  is refused (`receiver requires a callable owner`), and it is what `INSTANCE_RECEIVER` +
  `ARGUMENT`/`VALUE` used to state.
* **Two colleagues are two type selectors**, told apart by `where $colleague_a != $colleague_b`,
  and the callee name of the notification is tied to the dispatching method with
  `where $outgoing_a.name == $operation.name and $outgoing_b.name == $operation.name` -- the
  same idiom `composite#recursive-nominal` uses, and the reason the variant works for
  JavaScript, where the injected coordinator has no recorded type. A name `where` may not
  reference a role bound **inside a branch arm** (`where requires positively bound roles`), so
  the delegated calls are not name-compared: only the notification calls are.

The tag half is `param $tag {}` plus `if ($tag == _)`, which is what `PARAMETER_TEST` said; the
tagged variant hands the tag over as `argument $tag at 0`, the sibling branches on it instead.
`param $event { reassigned: false; }` is the spelling of
`STORAGE_WRITE_COUNT($event, "0")` in `mediator.event_delivery`, and the two-target delivery
collapses the `tally distinct $field >= 2` block into one guarded `if`/`else` with
`where $first_target != $second_target`.

**Verification.** `tests/structural/test_mediator_tag_dispatch.py`,
`tests/structural/test_mediator_message_coordination.py` (8 languages x the 4-5 negatives each,
plus the two re-anchored authoring-shape tests),
`tests/structural/test_algorithm_mediator.py` (including
`test_payload_contract_rejects_discarded_event_data` for `mediator.event_delivery`),
`tests/structural/test_authored_behavioral_mediator.py`,
`tests/structural/test_catalog_kql2_migration.py -k mediator`,
`tests/structural/test_catalog_adversarial_matrix.py -k mediator`,
`tests/structural/test_negative_corpus.py`, and
`grep -E '^\s*(edge|walk|tally)\b' src/ken/structural/patterns/mediator.toml` returns nothing.

### 5.46 Where the eager `type $unit {}` sits decides the state budget

`singleton#module-shared` is what tripped `QueryBudget(max_states=25000)` on
`tests/structural/test_construction_access.py::test_many_private_overloads_keep_the_query_bounded`
(100 classes, each a `private` constructor plus a private overload, one `static` field
initialized with its own type and one `static` zero-argument accessor): the `singleton`
root rule spent **47312 states** and reported `unknown=['budget:max_states']`.

The cost is not the shape but the *placement of one clause*. The variant opened with
`type $unit {}`, which enumerates every class of the graph (100 here), and both `either`
arms were then evaluated once per class. The two arms are not comparable:

| arm | states |
|---|---:|
| `field $storage { static: false; initializer { construct $unit {} … } }` + exported accessor | 101 |
| `callable $accessor { var $storage { static: true; } body { construct $unit {} … } }` | 30203 |

The first arm is cheap because the field's own initializer *is* the anchor: a storage
whose initializer constructs `$unit` is found by walking fields, and the class follows.
The second arm multiplies — 100 classes × ~300 callables ≈ 30203 states — and every one
of those states is discarded, because a Java file has no module-scope `static` local.

**The rule.** A role a *body* statement constructs need not be enumerated up front:
`let $initialized = construct $unit {} as $creation;` binds `$unit` from the
construction, so the clause order becomes
`module_decl → callable → var(storage) → construct → $unit` and the enumeration
disappears (arm 2 alone: 30203 → 303 states; root rule: 47312 → 7116). Only a
*declaration* expression needs its role bound earlier: the field-initializer form still
requires it and the compiler says so
(`initializer target must be selected before its expression`) when it is missing. So
the eager `type $unit {}` belongs **inside the arm that needs it** — see the 5.11
snippet, which now spells it that way.

Measured after the move: the root rule is `complete=True` with 100 matches in
**7116 states**, inside the 25000 budget.

Verification for this entry: `tests/structural/test_construction_access.py` (88 tests,
the budget case included), `tests/structural/test_singleton_module_shared.py`,
`tests/structural/test_creational_catalog_precision.py`,
`tests/structural/test_algorithm_singleton.py`,
`tests/structural/test_authored_singleton_initializers.py`,
`tests/structural/test_authored_singleton_storage_contracts.py`,
`tests/structural/test_eager_singleton.py`,
`tests/structural/test_singleton_once_primitive.py`,
`tests/structural/test_catalog_kql2_migration.py -k singleton` and
`tests/structural/test_catalog_adversarial_matrix.py -k "singleton or eager or lazy or module"` — all green.

### 5.47 `construct $type { argument $place at N | for $param; }` — the value a construction is built with

`state#context-transition` states that the context constructs its first concrete
state with *the context instance itself* (`self.state = Idle(self)` /
`this.state = new Idle(this)`). The construction was already expressible
(`let $initial = construct $concrete { ... }`), but there was no way to say what
the construction received: the legacy entry read
`CALL_BINDING`/`BINDING_VALUE`/`BINDING_PARAMETER` for the occurrence, and the
`construct` clause accepted only `initializer` constraints.

The clause now takes the same argument vocabulary a `call` clause takes:

```kql
let $initial = construct $concrete { argument $self for $context_input; };
```

- `argument $place at N;` selects the construction's argument at position `N`
  (`at any;` accepts any position, `at name("x");` a named one).
- `argument $place for $param;` selects the argument the constructor symbol hands
  to that parameter — the correlation the legacy arm stated with
  `BINDING_PARAMETER`.
- The operand is a place the pattern already bound, and, as in a call, a role the
  pattern declared as `Call` may stand in it: then the argument may be the result
  of that construction (`install(new Ready())`).

Implemented in `src/ken/kql2/syntax/parser.py` (`argument()` is now shared by
`call()` and `construct()`), validated in `src/ken/kql2/body.py` (`source()`
accepts the constraint) and matched in the construct branch of the BODY engine
against the occurrence's `ARGUMENT` rows (position/kind), with the same
`RESULT`/`VALUE` widening the call clause uses for a construction operand.

Unblocks: `state#context-transition`, `state.event_transition`.

### 5.48 `if (binary(left: $p, operator: _, right: _))` — a condition without naming its operator

`state.event_transition` requires the state's action to *test the request event*
the dispatch handed it (legacy `PARAMETER_TEST(condition, $action_event)`). The
fixtures test it with `event > 0`, `event > 0` and `if(event>0)`, so the
condition cannot be written as `$event == _`.

An `if` condition now accepts the source-expression form the argument
derivations already use (`binary_parts`, `src/ken/kql2/source_expressions.py`):

```kql
if (binary(left: $action_event, operator: _, right: _)) { ... }
```

`operator:` takes `_` (any operator), a string, or a list of strings, so the
pattern claims the test, not its spelling. Implemented in
`src/ken/kql2/body.py` (`condition()` inside the `if` validator; the runtime
already matched this form through `source_matches`).

### 5.49 The state catalogue: what a branch-bound occurrence costs

`src/ken/structural/patterns/state.toml` is the first catalogue where two entries
of the same pattern need *different* shapes for the same claim, for two reasons
worth recording:

1. **A role bound inside an `if` arm cannot be named at pattern level.** Both a
   pattern-level `where` (`where requires positively bound roles`) and a
   body-level one (`BODY where inputs must already be bound`, because the other
   type block has not been compiled yet) reject it. `state.event_transition`
   therefore names the setter *directly* in the arm
   (`call $setter { receiver: $backref; argument $creation for $candidate; ... }`)
   instead of binding the occurrence to an alias and correlating
   `explicit_arguments == arity` the way `state#context-transition` does.
2. **A clause after an `if` does not see the operations inside it.** The arm is a
   region: a method-level `call` clause following a guarded `construct` matched
   nothing, because the construction and the transition both live in the
   consequent region of the fixture. The transition clause must therefore sit
   inside the arm.

Also measured while migrating: `arity: 1;` on a `method` selector counts the
parameters the graph publishes with `receiver: false`
(`src/ken/structural/query_view.py:18-21`), so it is language-independent — but
it is *weaker* than `explicit_arguments == arity` (a call may pass more arguments
than the declaration and still match), which is why `state#context-transition`
keeps the occurrence correlation and only `state.event_transition`, whose call is
branch-bound, states the setter's shape at the declaration.

### 5.50 `dispatch: contract;` — an operation reached through the element's contract

Landed 2026-09-15 with the `composite#higher-order-traversal` rewrite attempt.

A composite walks its child collection and calls **its own operation** on each
element. When the frontend can resolve neither the element's type nor the call,
`call $operation { receiver: $element; }` has no target evidence, and
`dispatch: possible;` (`src/ken/kql2/body.py:1880-1899`) only accredits the
operation the *element's contract* declares under the very same name. A concrete
member that **overrides** that declaration (the standard composite shape:
`Subject.count` overrides `Component.count`) therefore missed.

```kql
let $child_call = call $operation { receiver: $element; dispatch: contract; };
```

`dispatch: contract;` adds two accreditation routes, both opt-in, so no existing
pattern changes verdict:

- **override:** when the method the element's contract declares is overridden by
  the pattern's callable (`OVERRIDES(target, declared)`), the overriding member is
  the dispatch target the occurrence accredits.
- **walk:** when the frontend publishes the occurrence as the invocation the walk
  performs on the element (`ITERATED_CALL(call, source)`), the collection names
  the operation the walk dispatches to. Unannotated collections (python's
  `self.children = children`) have no other evidence.

The callee spelling must still equal the declared operation's name
(`target.name == call.name`), which is the variant's own claim: *the same-named
operation is invoked on the element*.

Allowed values are accepted at `src/ken/kql2/body.py:566` and `:649`
(the `let`-call and bare-call constraint lists).

**Measured.** `composite#higher-order-traversal` under `dispatch: contract;`
matches all eight target languages except rust (see §5.53). Under
`dispatch: possible;` java, typescript, csharp, cpp and go match as well, but the
accreditation is *also* what `composite` reports as an unresolved-dispatch
unknown on interface-typed collections
(`tests/structural/test_catalog_kql2_migration.py:42-49`), so the new mode is
opt-in rather than a widening of `possible`.

### 5.51 `rebound: true;` — the iterated element survives a write to the loop variable

The complement of the existing `unreplaced: true;` (`src/ken/kql2/body.py:2064-2075`).

`receiver: $element;` on a call inside a walk is checked *at the occurrence*
through `iteration_value_at()` (`src/ken/kql2/body.py:1209-1213`): a loop variable
written before the call no longer names the element there, so the receiver claim
fails. A pattern whose claim is "the walk dispatched on the element it iterated,
not on whatever the variable holds at that point" states it:

```kql
let $child_call = call $operation { receiver: $element; rebound: true; };
```

```kql
$accumulator += $child_call as $write;
```

**Two traps found by measurement.**

- An assignment clause compares the *operator*: `$place = $call;` does **not**
  match `total += child.count(ctx)`; the pattern must spell `+=`. The compound
  spelling needs the frontend to publish `OPERATOR`, which rust did not (§5.53).
- `var $accumulator {}` and `iterate` must appear in the order the source
  instructions appear (java: declaration then loop). Rust still disagrees — see
  §5.53.

`rebound: true;` is accepted next to `receiver` on a call clause in both
constraint lists (`src/ken/kql2/body.py:594-608` and `:698-712`) and waived in the
receiver matcher (`src/ken/kql2/body.py:1962-1977`).

**Fixture.** `tests/structural/test_composite_higher_order_traversal.py`
`test_a_reassigned_element_is_not_yet_rejected`, whose `reassigned-element` mode
inserts `child = children.get(0);` before the accumulation.

### 5.52 An `iterate` that reaches the place through an access

```kql
iterate $children as $child { body { ... } }
```

now also accepts a walk whose source is an *access* on the place — a borrow or an
`iter()`/getter call the frontend publishes as a call whose receiver is the place
(rust `for child in self.children.iter()`). The access is an IR detail; the
pattern claims the place.

Implementation: `src/ken/kql2/body.py:1506-1520` narrows the walk sources to those
that read the bound place, and `:1560` tracks the access as the walked source.
The narrowing only applies when such an access exists, so a walk of a *different*
collection still fails the clause
(`tests/structural/test_algorithm_composite.py::test_iterating_external_collection_does_not_use_stored_place`).
An **indexed** walk (`iterate $registry[$topic]`) keeps the exact source: the key
is part of that claim, and letting an access stand in for the container would
bypass the bucket check
(`tests/structural/test_observer_event_bus.py::test_negative_shapes_are_rejected[different-topic]`).

### 5.53 Landed: rust's `var`/`iterate`/`return` interaction

Measured while attempting `composite#higher-order-traversal` (2026-09-15). The
variant was parked back on its legacy spelling; the engine gap is recorded here
so the next round starts from facts.

Reproduce (python, from a checkout with the KQL 2 rewrite of that variant):

```
.venv/bin/python -m pytest tests/structural/test_composite_higher_order_traversal.py -q
```

Facts:

- The rewritten variant matches **python, javascript, typescript, java, csharp,
  cpp and go**; rust matches once `iterate` precedes `var` and the `return`
  clause is dropped — i.e. rust needs an order the other seven reject.
- `var $accumulator {}` alone matches rust; `var $accumulator {}` +
  `return $accumulator;` does **not**, on a rust fixture whose method ends in the
  same tail expression the other languages write as `return total;`
  (`RETURNS_STORAGE(count, total)` *is* published for rust).
- With the loop removed, rust still fails `var` + `return`, so the loop and the
  `ITERATED_CALL` accreditation are not the cause: the clause order/anchoring of
  the body matcher places rust's `let mut total = 0;` declaration differently
  relative to the walk.
- **Root cause of the anchoring** (measured, 2026-09-15). A `var` clause matches
  only at the instruction whose *declaration group* contains the storage's own
  `start_byte` (`src/ken/kql2/body.py:2480-2487`,
  `props.get('declared') is not True or declaration_group(start) != group`).
  Rust records the accumulator storage at its **tail read**, not at its `let`:

  | language | `STORAGE:total` start_byte | the source line |
  |---|---:|---|
  | rust | 317 | `total` (the implicit return), declaration at 213 |
  | java | 277 | `int total = 0;` |
  | python | 189 | `total = 0` |

  So on rust the clause is anchored after the walk, which is why rust needs
  `iterate` before `var`. The frontend reaches that position because rust's `let`
  is not in the explicit-local-declaration branch of
  `src/ken/structural/frontend.py:1510-1514` (python/`assignment`,
  js/ts/java/csharp/`variable_declarator`, go); adding a rust arm there did *not*
  move the position (the entity is still re-registered at 317), which is where the
  next round should look.

Landed anyway, because they are correct on their own terms:

- **Rust compound assignments publish their operator.**
  `src/ken/structural/frontend.py:97-101` now lists `compound_assignment_expr` in
  `OPERATOR_NODES` and `:1212` treats it as an assignment, so
  `total += child.count(ctx);` publishes `OPERATOR(op, "+=")` like every other
  language. Before this, a KQL 2 write clause that spells `+=` had no operator
  evidence to compare against on rust.

**Fixture fix.** `tests/structural/test_composite_higher_order_traversal.py`'s
python template prefixed every statement with eight spaces *and* carried its own
indentation, so it emitted `for` at column 16 — invalid python that the legacy
relational query tolerated but a BODY walk cannot read. The prefix now supplies
the whole base indent.

**Position fix (landed 2026-09-15).** The misplacement had a single source:
`semantics` in `src/ken/structural/frontend.py` visits a `block` *before* its
statements, and its rust implicit-return branch (`kind == "block"` whose parent
is a callable) materialised the tail expression through `value()` → `storage()`.
The tail read therefore registered the slot first, at its own byte (rust
`total`: 317). That branch now binds the block's `let` names through the same
`declaration_parts`/`unwrap`/`storage` path the other languages use in their
declaration arm, so the slot is created at its declaration (rust 205, java 277,
python 189) and `RETURNS_STORAGE` points at the declared slot.

`tests/structural/test_composite_higher_order_traversal.py::test_rust_tail_expression_returns_the_declared_accumulator`
pins it. With that, on the traversal fixture `var $accumulator {}` +
`return $accumulator;` matches rust in the same clause order as the other seven
languages — `var` before the loop; `iterate`-before-`var` is no longer needed for
rust and now fails there, as it already did on java. `tests/structural/test_composite_*`
and the composite frozen parity are green.

### 5.54 `if (...) as $branch { ... }` — naming the branch occurrence

A tag dispatch *is* a branch, and the frozen `composite#algebraic-tree` contract
bound it: `operation(kind: branch) as $branch; $branch TRUTH_TEST $tested;`.
KQL 2 had `if ($tag == _) { ... }` for the condition but no way to name the
occurrence the condition opens.

`src/ken/kql2/syntax/parser.py` (`body_clause`, the `if`/`while` arm) now reads
`self.alias()` *before* the block, exactly where `iterate $x as $item { ... }`
reads it; `src/ken/kql2/body.py`'s `if` arm in `compile_body` exports the alias
as an `operation` output, and the match-time arm (`match_step`,
`item.kind == 'if' and op.kind == 'BRANCH'`) binds it with `reference(op)`, the
value every other aliased body clause binds.

Spelling: `if ($tested == _) as $branch { }`. A `$tag` role bound to a field of
the owner is the evidence — the `condition` walker already accepts `field`.

### 5.55 `call alongside $x { ... }` — the sibling operand of one statement

`composite#algebraic-tree`'s operation calls its own name on **both** recursive
fields — `left.evaluate() + right.evaluate()` — two calls that are siblings under
one binary expression. The walker refused that on purpose (`src/ken/kql2/body.py`,
`match_step`'s cursor guard): inside one statement it follows only *ancestors* of
the cursor, because operand evaluation order differs across languages and is not
evidence a pattern may assume.

`call alongside $second_call { receiver: $second; }` is the opt-in that states
the claim: the clause matches when the candidate's parent is the cursor's own
parent, so the two occurrences are proven peers of the same enclosing operation.
`src/ken/kql2/syntax/parser.py` (`call`) accepts the keyword and sets the
`alongside` flag; `body.py`'s cursor guard reads it. A clause without the flag
keeps the ancestor-only rule.

### 5.56 `where element_type($collection, $unit);`

`ELEMENT_TYPE(storage, type)` says a field's elements are that type. It is what
separates a traversal of the component's own children from a walk over an
unrelated payload. It is now a public predicate (`src/ken/kql2/semantic.py`,
`RELATIONS['element_type'] = ('ELEMENT_TYPE', 'Field', 'TypeDecl')`), spelled
`where element_type($children, $unit);`.

### 5.57 `composite.additive_aggregate` accumulates through a local (migrated)

The catalog's third composite row is the only one with no frozen counterpart (the
pre-KQL 2 matrix lists four composite variants and zero operations), but
`tests/structural/test_algorithm_composite.py` exercises it directly. Its
operation is:

```python
total = context
for child in self.children:
    value = child.Count(context)
    total = total + value
return total
```

Reusing `composite#higher-order-traversal`'s body gets the loop, the same-name /
receiver / argument-origin constraints and the return. The pieces without a
spelling are the **write and the operand join**:

* `ASSIGNMENT_VALUE($child_write, $child_call)` + `ASSIGNMENT_TARGET($child_write, $child_result)`
  — `value = child.Count(context)` stores the call in a local.
* `EXPRESSION_OPERAND($sum, $total) { position: 0; operator: "+"; }` and
  `EXPRESSION_OPERAND($sum, $child_result) { position: 1; operator: "+"; }`
  — the update folds *that local* into the accumulator.
* `walk SYNTAX_PARENT($child_write, $loop)` / `($update, $loop)` and the
  `STORAGE_WRITE_COUNT` pair (`$child_result` 1, `$total` 2).

Measured, not guessed: the loop, the call with its argument origin, and the
return match all three fixtures; adding any accumulate clause drops the match.
`$total += $child_call as $write;` is definite-false (the source's write value is
a *sum*, not the call); `$total = $total + $child_call as $write;` after
`let $child_call = call …;` is `source_body:unknown` (a `let` binds the call
*occurrence*, so it cannot be an operand of the sum, whose operands are the
`total` and `value` storages); and `$value = call $operation { … };` is a parse
error ("source expressions require a role or application") — an assignment's
right-hand side cannot be a call clause. Re-checked while migrating the row:
`let $child_result = $child_call;` (a `let` whose right-hand side is an
already-bound call role) does not even compile — `body.py`'s `let` arm raises
*"let requires a call or a construction"* (`src/ken/kql2/body.py:497`); and
binding the call directly, `let $child_result = call $operation { … };
$total += $child_result as $update;`, compiles but matches **nothing** on the
three positive fixtures (the other 116 cases of
`tests/structural/test_algorithm_composite.py` stay green), because the operand
of the sum is the local `value`, not the call occurrence.

The row therefore keeps its legacy clauses until a primitive states "the write
whose value is a sum whose operand is the local that holds this call".

**Landed: the primitive was already there.** `composite.additive_aggregate` is now
pure KQL 2, with no compiler change. The missing piece was not a language gap but
an *operand identity*: the sum's operand is the local **storage** that received the
call, so the pattern must bind that storage and then sum the storages.

```kql
method $operation {
  param $context { reassigned: false; }
  var $total { }
  var $value { }
  writes: exactly($total, 2);
  body {
    iterate $children as $element {
      body {
        let $child_call = call $operation { receiver: $element; dispatch: contract; rebound: true; argument $context at 0; };
        $value = $child_call;
        $total = $total + $value as $update;
      }
    }
    return $total;
  }
}
```

`$value = $child_call;` is an **assignment whose right-hand side is a bound call
occurrence**: it publishes the write the legacy `ASSIGNMENT_VALUE`/`ASSIGNMENT_TARGET`
pair read (value = the call, target = the local), and it is what makes `$value` an
operand the sum can name. `let $value = $child_call;` cannot stand in — a `let`
accepts only a call or a construction (`body.py:497`) — and `let $value = call …;`
binds the *occurrence*, which is exactly why the sum then has no storage operand and
matches nothing.

Two authoring limits measured while landing the row:

* A selector accepts **one** `writes:` filter (`graph.py` raises *"duplicate method
  property writes"*), so the legacy pair `STORAGE_WRITE_COUNT($total, 2)` /
  `STORAGE_WRITE_COUNT($value, 1)` cannot be stated together. The variant keeps the
  accumulator's count, the one its claim names.
* Inside a nested `iterate` body the argument source must carry a **concrete**
  position: `argument $context at 0;` compiles and matches, while
  `argument $context at any;` is rejected with *"source operand requires a bound
  storage, parameter or captured value"* even though `$context` is the enclosing
  method's parameter.

**Verification for the accumulated-composite row.**
`tests/structural/test_algorithm_composite.py` (34 passed: three languages x
baseline/noise/renamed positives, four broken-collaboration mutations, the
external-collection and broken-value-flow mutations, and the rebound-child case),
`test_recursive_composite.py`, `test_composite_algebraic_tree.py`,
`test_composite_higher_order_traversal.py`, `tests/structural -k composite` (354
passed) and `test_catalog_kql2_migration.py -k composite` are green; the frozen
matrix has no operation counterpart for this row, so parity is vacuous and the
operation is held by `test_catalog_ir_contracts.py`'s positive/roundtrip contract.

**Verification for 5.54-5.56.** `tests/structural/test_composite_algebraic_tree.py`
(48 passed: six languages x positive / renamed / root / four negatives / the
branch-test), `test_composite_higher_order_traversal.py`,
`test_algorithm_composite.py` and `tests/structural/test_catalog_kql2_migration.py
-k composite` are green.

### 5.58 `return $container[$key];` -- the returned value is that indexed read

Legacy clause: `require $factory RETURNS $returned [execution:possible];` with
`$returned CONTAINER $pool; $returned INDEX $return_index;` (or the same two claims on a
local the read filled). The legacy interning query bound the returned object that way and
then required `$return_index == $write_index`.

A BODY `return` already accepted a role, a `from` derivation and a `copies` clause. The
indexed operand is new, and it is **the occurrence, not the spelling, that is the
evidence**: the frontend publishes the subscript as a `VALUE` entity carrying
`CONTAINER`/`INDEX`, and the returned value is named by `RETURN_OPERAND` (or
`RETURN_ORIGIN` when the flow layer resolved it):

```kql
body { $pool[$key] = _ as $write; return $pool[$key]; }
```

The operand accepts the four key forms the other element operands accept: a bound key
role (the read's `INDEX` must be that same binding), a wildcard `_` (any key), a literal
(the read's index text), and an unbound role, which is captured as the key the read used.
The container must be a place the pattern bound; an unbound container reports
`returned_element_container_unknown` instead of silently matching.

**Measured before the change.** With the container bound and the element stored at the
same index, `return $pool[$key];` matched 0 of 3 fixtures (python membership guard, Java
`pool[key]==null`, TypeScript `!pool[key]`) while the same pattern without the return
matched all 3: the missing operand, not the guard, was what stopped the shape.

**Verification.** `tests/kql2/test_body_return_element.py` (5 tests: the read matches,
a different container is rejected, a returned constant is rejected, an unbound key role is
captured, a wildcard key is accepted), and `tests/kql2` together with the flyweight
suites: 1044 passed.

**Landed next.** The three guard spellings this shape needed are in §5.59: `not in`, an
indexed read as a condition subject, and a bound call result as a condition subject.

### 5.59 The guard vocabulary: `not in`, an indexed read, and a call result as a condition subject

Legacy clauses: the interning arms guarded their writes with the `NOT_MEMBER_OF`,
`MEMBERSHIP` and `NULL_TEST` edges over a pool role, a read role or a storage local. Three
BODY spellings landed so a pattern can state the same guard:

| Guard | KQL 2 spelling | Evidence the engine reads |
|---|---|---|
| negated membership | `if ($key not in $pool) { ... }` | the `OPERATOR` of the branch's `CONTROL_CONDITION` |
| a miss on an indexed read | `if ($pool[$key] == null) { ... }` | the element `VALUE` node's `CONTAINER`/`INDEX` facts |
| a call the pattern bound | `let $v = call $load {}; if ($v == null) { ... }` | the result's provenance (`ASSIGNED_FROM`/`READ_ORIGIN`), as §5.27 |

**Parser.** `src/ken/kql2/syntax/parser.py` (`_expr`): the lexer emits `not` and `in` as two
separate words, so `not` in infix position now folds the pair into the single operator
`not in` at the comparison precedence `in` already has (30). Prefix `not` (`if (not $flag)`)
is unchanged, and an infix `not` followed by anything but `in` is a syntax error
(`expected 'in' after 'not'`).

**Compiler.** `src/ken/kql2/body.py` (`compile_body`, the `if` condition walker): an `index`
expression is now an accepted condition subject. The container must be a place the pattern
bound (`field`/`var`/`param`/`receiver`/`value`) and the key a bound operand, a literal, a
wildcard or a fresh value role -- otherwise `condition requires a bound collection place` /
`condition key requires a bound operand`. A role bound by `let $x = call ...` is already a
`value` role, so it was always a legal subject and needs no further change.

**Matcher.** `src/ken/kql2/body.py` (`source_matches`): for an `index` subject the engine
resolves the element the read yielded -- the `VALUE` entities whose span is the condition
operand's span, plus any `VALUE` rows published under it -- and requires the bound
container's `CONTAINER` fact and the key's `INDEX` fact on that element. An unbound
container or key reports `index_container_unknown` / `index_key_unknown`; a read of another
container, or at another key, is a definite non-match.

**Measured.** On fixtures built for the interning shape:
`if ($key not in $pool) { $pool[$key] = _; }` matched the guarded write (1 row) and rejected
the unguarded write and the opposite polarity `if (key in pool)` (0 rows).
`if ($pool[$key] == null) { $pool[$key] = _; }` matched the guarded write (1 row) and rejected
a guard on another container, an unguarded write, and a guard at another key (0 rows each).
`let $v = call $load {}; if ($v == null) { return 1; } else { return 2; }` matched (1 row) and
rejected a comparison with another literal (0 rows).

**Authoring trap.** An `else { ... }` arm needs a spelled alternative region in the source: a
fallthrough `return` after the `if` does not satisfy it (pre-existing `alternative`-region
matching, measured here).

**Verification.** `tests/kql2/test_body_guard_subjects.py` (8 tests: one positive and one
negative per guard), `tests/kql2` green, and
`tests/kql2/test_body_condition_values.py` + `tests/kql2/test_body_return_element.py` green
(53 tests).

### 5.60 Landed for the flyweight interning arms: `undefined` and a storage-level `writes:` count

Legacy clauses replaced: `NULL_TEST` beside `UNDEFINED_TEST` as one "miss" family, and
`STORAGE_WRITE_STATUS`/`STORAGE_WRITE_COUNT` on the checked local.

**1. `== null` also states the JS/TS `undefined` miss.** `src/ken/kql2/body.py`
(`source_matches`, the literal branch) now reads `undefined` as the same null-ish literal
as `null`/`nil`, and the branch override that reads the guard's own rows
(`match_step`, `item.kind == 'if' and op.kind == 'BRANCH'`) accepts `UNDEFINED_TEST`
beside `NULL_TEST`. The frontend already published the TS miss as both a `TRUTH_TEST`
(`basis: comparison-syntax`) and an `UNDEFINED_TEST` (`basis: unshadowed-undefined-syntax`),
so the pattern states one claim and either spelling answers it:

```kql
body { var $read {} if ($read == null) { ... } return $read; }
```

Measured: `tests/structural/test_flyweight_local_guard.py`'s TypeScript fixture
(`let result = this.pool[key]; if (result === undefined)`) matched 0 times with the
pattern whose guard was `$read == null` before the change and 1 time after, with the
other five mutations of the same fixture still rejected.

**2. `writes: exactly($local, n)` falls back to the local's own storage contract.**
`src/ken/kql2/source_storage_contracts.py` (`evaluate`, the `writes` branch) returned
unknown whenever the callable-level `BINDING_WRITE_STATUS` was `unsupported` --
which is what the interning method produces, because the *target* of its pool write is
itself an access (`pool[key] = local`, reason `unmodeled-target`). It now falls back to
the binding's `STORAGE_WRITE_STATUS`/`STORAGE_WRITE_COUNT`, which is exactly the pair
the legacy `STORAGE_WRITE_COUNT(local, n)` clause read. No catalog changed behaviour: the
binding-level inventory, when closed, still decides first.

Measured on the same fixture family: the clean local shape matched with
`writes: exactly($read, 2);` and the four extra-write mutations
(`reset-before-guard`, `reset-and-restore`, `overwrite-before-insert`,
`overwrite-after-insert`) that the unfiltered shape accepted are now rejected.

**3. Measured blocker: an indexed read in a *declaration initializer* cannot back a
`let` capture.** `src/ken/kql2/body.py` binds ``let $value = $container[$key];`` to an
operation whose `ASSIGNMENT_VALUE` element carries `CONTAINER`/`INDEX`, and then requires
the assignment's `ASSIGNMENT_TARGET` to have `STORAGE_WRITE_COUNT == 1` (the "this read is
its only producer" rule that `iterator#advancing_element` relies on). The TypeScript
interning fixture initializes its checked local from the pool and writes it a second time
inside the miss arm, so:

* `let $looked = $pool[$key];` binds nothing (0 matches) even though the frontend
  publishes `ASSIGNMENT_VALUE(variable_declarator, VALUE:164:178)` and
  `CONTAINER(VALUE:164:178, pool)` -- the initializer publishes no `ASSIGNMENT_TARGET`
  for the declared name, and the local's write count is 2, not 1;
* the `call`-shaped lookup binding used for the Python and Java arms
  (`let $looked = call $load { receiver: $pool; argument $key at 0; };`) has no
  counterpart in the TypeScript fixture, whose lookup is a subscript expression.

So the TypeScript row of `flyweight#explicit-interning` needs one further primitive:
either a declaration initializer that publishes its declared name as the assignment
target, or an indexed capture that admits a place with more than one write and states the
correlation instead of the producer count.

**Spellings the flyweight arms did settle on** (all measured, `tests/structural/
test_flyweight_*`):

| Family | KQL 2 |
|---|---|
| local read, Python/Java/TS (`result = pool.get(key)` / `this.pool[key]`) | `param $key {} var $read {} writes: exactly($read, 2); body { if ($read == null) { let $filled = construct $product { argument $key at 0; }; $pool[$key] = $read as $write; } return $read; }` |
| the same with the map API write (Java `pool.put(k, v)`) | `call $write { receiver: $pool; name: ["put", "set"]; argument $key at 0; argument $read at 1; };` |
| a key local derived from the key parameter | `var $key {} body { let $derived = call $derive { argument $state at 0; }; $key = $derived; ... }` -- a `let` capture cannot be written into a declared `var` in one clause (`let capture requires a Value role`), so the derivation needs the pair |
| the miss guard per language | `if (not $probe)` over `let $probe = call $load { receiver: $pool; argument $key at 0; };` (Python's `not pool.get(k)`), `if (not $pool[$key])` (TypeScript's `!pool[k]`), `if ($pool[$key] == null)` (Java's `pool[k] == null`) |
| the returned element | `return $pool[$key];` with the same `$key` binding the write used (the constant-return negative is rejected by that correlation alone) |

### 5.61 Landed for the TypeScript interning arm: `let $value = $container[$key] writes: n;`

Legacy clause replaced: `STORAGE_WRITE_COUNT($local_cached, "2")` beside
`ASSIGNMENT_TARGET($local_lookup_assignment, $local_cached)`.

The indexed capture from §5.19 binds the place an element read was stored into, and it
demanded exactly one producer, because that is what `iterator#advancing_element` means:
the cursor assigned the element it read, once. An interning method is not that shape. It
reads the pool into a local and then rewrites the same local in the miss arm with the
object it stores back, so the place has two writes and the legacy query said so. The
capture now takes an optional write count, and the inventory must agree:

```kql
body {
  let $looked = $pool[$key] writes: 2;
  if ($looked == null) { let $filled = construct $unit {}; $looked = $filled; }
  insert $looked into $pool at $key;
  return $looked;
}
```

**Grammar.** `src/ken/kql2/syntax/parser.py` (`body_clause`, the `let` branch): after the
value expression, an optional `writes : <integer>` is accepted and carried on the clause
(`Clause.name`, otherwise unused for `let`). `writes:` is the property name the language
already uses for a callable's write inventory, so the spelling needs no new vocabulary.

**Rule.** `src/ken/kql2/body.py`, the `elif item.kind == 'let' and item.expressions[0]
.kind == 'index'` branch: the per-target test `counts[0].object != '1'` is now
`!= (item.name or '1')`. Omitting the count is unchanged behaviour — one producer, the
`STORAGE_WRITE_STATUS`/`supported` check kept — so the iterator rules keep their teeth.
The count is the correlation, not a relaxation: the container and the key are still
matched as before, so the wrong-pool and wrong-key shapes stay rejected.

**Correction to §5.60.3.** That paragraph said the TypeScript initializer "publishes no
`ASSIGNMENT_TARGET` for the declared name". Measured again: `src/ken/structural/
frontend.py:1582-1594` publishes `ASSIGNMENT_TARGET`, `ASSIGNMENT_VALUE`,
`ASSIGNED_FROM`, `FLOWS_TO` and `WRITES` for *every* declaration with a right-hand side,
`variable_declarator` included, so the declaration-initializer path
(`src/ken/kql2/declaration_initializers.py:42`) was never the blocker. The write count was
the whole of it: on a one-write TypeScript fixture the plain capture matched (1 row) and on
the two-write fixture it did not (0 rows).

**Verification for 5.61.** `tests/kql2/test_body_index_capture_writes.py` (6 passed): the
one-producer shape matches `let $looked = $pool[$key];`; the interning shape (declaration
read plus miss-arm rewrite plus the store) matches 0 times without the count, 1 time with
`writes: 2`, and 0 times with `writes: 3`; the wrong-pool (read from `other`, store into
`pool`) and wrong-key (read at `"other"`, store at the key parameter) fixtures stay
rejected with the count stated. `tests/kql2` green (whole suite), and
`tests/structural -k "flyweight or iterator"` green, so the eight local-guard mutations
of `test_flyweight_local_guard.py` and the cursor captures are unaffected.

### 5.62 Landed for the derived-key interning arm: `let $place = call $f { ... } writes: n;`

Legacy clauses replaced: `ASSIGNED_FROM($local_index, $local_derived)` beside
`STORAGE_WRITE_COUNT($local_index, "1")` -- the *place* a derived call's result was stored
into, not the call's result value.

`let $value = call $f { ... };` binds the value the call produced, and a value role cannot
be the index of `$pool[$key] = ...`: the element's `INDEX` fact names the *storage* the read
or write used (`INDEX(VALUE:290, STORAGE:key)`), so a pattern that only holds the call
result cannot correlate the store with the return. Stating a write count on the capture
binds the place instead, the call-shaped counterpart of §5.61:

```kql
body {
  let $key = call $derive { argument $state at 0; } writes: 1;
  if (_ == null) { let $filled = construct $product { argument $state at 0; }; $pool[$key] = $filled as $write; }
  return $pool[$key];
}
```

**Rule.** `src/ken/kql2/body.py`, the `if item.kind == 'let' and truth is not False:`
branch of the call-clause matcher: when the clause carries a count (`Clause.name`, already
used for `let`), the enclosing declaration or assignment (`ASSIGNMENT_TARGET`, walking at
most three parents up from the call operation) names the place, and
`STORAGE_WRITE_COUNT`/`STORAGE_WRITE_STATUS` must agree with it. A place whose inventory
disagrees is contradictory evidence (definite non-match); a call with no enclosing
assignment stays `Unknown('call_result_place_unknown')`. Without a count the branch is
unchanged, so no earlier catalog moves.

**Measured cost.** On the 110-statement budget fixture of
`tests/structural/test_flyweight_local_guard.py`, the same arm costs 88 440 states when the
key is a declared `var` filled by a separate assignment, and 2 222 states with the place
capture -- the difference the variant's state budget needs. `writes: exactly($key, 1);` on
the method, a `name:` list on the derivation call and a `linear` body each moved the 88k
figure by less than 10%.

**Verification.** `tests/kql2/test_body_call_capture_place.py` (5 passed: the positive, a
place with a second write, a disagreeing count, a literal index and a renamed role),
`tests/structural/test_flyweight_explicit_interning.py`,
`tests/structural/test_flyweight_local_guard.py` (both including the 40-statement budget
test) and the frozen-parity module.

### 5.63 Measured: an indexed miss guard does not resolve inside a catalog `pattern`

`if ($pool[$key] == null)` is documented and measured *inline* (§5.59, and
`tests/kql2/test_body_guard_subjects.py`, which passes): `source_matches` resolves an
`index` subject to the VALUE entities at the condition operand's span plus
`rows('VALUE', operation)`, then asks those elements' own `CONTAINER`/`INDEX` facts.

Inside a catalog `pattern` the same clause matches nothing. Measured on the java fixture of
`tests/structural/test_algorithm_flyweight.py` with temporary instrumentation in
`body.py`'s index branch: the inline query sees 12 entities in the body engine's unit IR,
including `VALUE:260:274` with its span, and resolves `elements=1`; the pattern path sees
10 entities, whose only `VALUE` rows are span-less `.../argument/0/loaded-value`
pseudo-entities, and resolves `elements=0`. The same text answers through
`ken.kql2.service.search` and not through `named_rule` + `execute_rules`, so this is a
property of the unit IR the two paths hand the body engine, not of the clause.

**Authoring rule until that is fixed.** A catalog arm states the *kind* of miss test with a
wildcard subject, and the guarded write plus the returned index carry the correlation:

| Language spelling | Catalog arm |
|---|---|
| `key not in pool` | `if ($key not in $pool)` |
| `pool[key] == null`, `=== undefined`, `!pool[key]` | `if (_ == null)`, `if (not _)` |
| `not pool.get(key)` over a derived key | `if (not _)` |

`_` is already an accepted condition subject (`body.py` `condition()` admits `wildcard`, and
`source_matches` answers `True` for it), so this needs no grammar. The precision it costs is
what the flyweight suites enforce: each arm matches its fixture family once and rejects all
seventeen mutations (`tests/structural/test_flyweight_*.py`,
`tests/structural/test_catalog_adversarial_matrix.py -k flyweight`).

### 5.64 `flyweight.stable_intrinsic`: "written once, in the constructor" without a field count

The legacy operation read `HAS_FIELD(product, intrinsic)` + `CONSTRUCTOR_FIELD_INPUT` +
`STORAGE_WRITE_COUNT($intrinsic, "1")`. `writes: exactly($field, n)` cannot state that:
`writes:` is not a `type` property (`unknown type property writes`), and on a callable it
counts what *that callable* writes (`source_storage_contracts.py` `evaluate`, first
branch), so `writes: exactly($intrinsic, 1);` on the constructor is also true of the
extrinsic-overwrite fixture (measured: 1 match, must be 0).

The claim is therefore stated as two facts that together pin the same thing:

```kql
  type $product {
    field $intrinsic {}
    constructor $ctor {
      parameters { param $input {} }
      body { initializer { $intrinsic = $input; } }
    }
    method $reader {
      constructor: false;
      writes: exactly($intrinsic, 0);
    }
  }
```

The `initializer` step (§F4) says the field retains the constructor's input and that nothing
later *in that body* overwrites it; the reader's zero-write inventory says the method the
pattern names does not write it either. Measured on
`tests/structural/test_algorithm_flyweight.py`: initializer + reader = 1 match on each of
the three positive fixtures and 0 on `captures-extrinsic`, while the initializer alone (or
with `writes: exactly($intrinsic, 1);` on the constructor) accepts the mutation. Residual
gap, stated in the operation's caveat: a third method the pattern does not name could still
write the field, which the legacy total count would have rejected.

### 5.65 The `visitor` rewrite: a generic callable, a parameter-typed type parameter, and an argument that fills a signature slot

Three rules landed with the `patterns/visitor.toml` migration.

**1. `type_parameter $t;` inside a generic callable** (`src/ken/kql2/source_patterns.py`).
The clause required a *type* owner, but a generic **method** declares its own parameter
(`template <typename V> void accept(V& visitor)`, `fn accept<V: Renderer>(&self, v: &V)`) and
the graph binds the name to that callable: `BINDS_TYPE_PARAMETER(accept, "V")`. A callable
owner is now accepted, and the clause still takes no properties.

**2. `type: parameter($t)` on a parameter joins `TYPE_PARAMETER`, not `TYPE_NAME`** (same file).
A parameter whose declared type *is* one of its callable's type parameters publishes
`TYPE_PARAMETER` with the *undecorated* name (this is the IR 1.63 capability
`tests/structural/test_visitor_generic_visitor.py` documents), while the spelling written in
the source (C++ `Visitor &`, Rust `&V`) is what a field's `TYPE_NAME` carries. A field keeps
`TYPE_NAME`, so `bridge` and `strategy` are untouched. Measured on the cpp and rust fixtures:
the two clauses contradicted each other -- 0 matches with both, 2 with either alone.

**3. `argument $value for $parameter;` no longer needs the language's binding analysis**
(`src/ken/kql2/body.py`). The clause read the positions of `CALL_BINDING`/`BINDING_PARAMETER`
and answered `Unknown('parameter_binding_incomplete')` whenever `BINDING_STATUS` was missing or
unsupported. C++ publishes `BINDING_STATUS(call, unsupported)` with `reason: language` for its
whole `explicit-arguments` analysis, so *every* cpp body call was unnameable that way. The
clause now falls back to the call's resolved or declared target: if that target *declares* this
very parameter (`HAS_PARAMETER`), the value fills the slot the parameter is declared in. An
explicit receiver counts as a slot but is never passed, so the parameters after it shift by one
-- `fn visit(&self, element)` is called with the element as its first argument. Measured: cpp
`visitor.visit(*this)` matched 0 before and 1 after, while the typed-self negative
(`visitor.audit(this)` next to `visitor.visit(null)`) stays at 0, because `audit` does not
declare the pattern's parameter.

**4. `returned: true;` also accepts the flow-analysed `RETURN_ORIGIN`** (`src/ken/kql2/body.py`).
It required the returned operand to be the call itself, or the call behind a cast or a member
chain, which rejects the ordinary `result = f(x); return result`. The graph publishes
`RETURN_ORIGIN(return_statement, call)` with `basis: flow` for exactly that shape -- the
relation the legacy contract named. Measured on `tests/structural/test_algorithm_visitor.py`:
0 matches before, 3 (python, java, typescript) after; the overwritten-result negative stays at
0 because the flow analysis resolves the *last* write (`result = 0`).

**5. A leading `*` is a spread argument only where it means expansion**
(`src/ken/structural/frontend.py`). The argument-kind table read
`spelling.startswith(("*", "..."))`, so C++'s dereference (`visitor.visit(*this)`) was published
as `spread_positional`; the body engine refuses a spread argument
(`Unknown('argument_pack_unresolved')`, and a later position is `argument_position_after_pack`),
which is right for a real pack and wrong for a dereference. `*` now counts as a pack only in
Python and Ruby; `...` still counts everywhere. Java, C#, Go and Rust were mis-tagged the same
way.

The four visitor entries are stated as:

```kql
pattern detect(out GraphTerm $unit) {          -- named-dispatch, and result_forwarding's prefix
  type $visitor_type { method $visit { param $element { type: nominal($unit); } } }
  type $unit {
    method $accept {
      receiver $self {}
      param $visitor { type: nominal($visitor_type); }
      body { call on $visitor { receiver: $visitor; argument $self for $element;
                                resolution: resolved; unreplaced: true; }; }
    }
  }
  where $visitor_type != $unit;
}
```

- `named-dispatch` states the resolved target by binding the self argument to the operation's
  parameter (`for $element`), and the received-visitor contract with
  `receiver: $visitor; unreplaced: true;` -- the lexical-prefix relation
  `RECEIVER_UNREPLACED(call, place)` the legacy named. `reassigned: false` on the parameter is
  *not* that contract: it inventories the whole body, so a write **after** the dispatch revokes
  it too (measured on `tests/structural/test_ir178_contracts.py`, `after=True`: 0 matches, must
  be 1). The element type is declared before the element only because a `for` role must already
  be bound.
- `overloaded-dispatch` drops the name link the legacy spelled
  `$overload.name == $dispatch.name` (a `where` on a call's `name` matched nothing) and keeps
  the claim in two parts: an operation of the visitor type whose slot 0 is the element, plus
  `at least 2 distinct $local_element_type { ... }` over the operations' slot-0 types. An
  overload set publishes no argument binding, so its self-passing is stated by position
  (`argument $local_self at 0;`).
- `generic-visitor` is the generic callable: `type_parameter $visitor_parameter;` next to
  `param $visitor { type: parameter($visitor_parameter); }`.
- `result_forwarding` is the named-dispatch prefix plus `returned: true;`.

### 5.66 The `interpreter` rewrite: three variants, no new syntax

`patterns/interpreter.toml` now carries no `edge`/`walk`/`tally` clause. The three entries were
authored with surface earlier rounds had already landed -- no compiler change was needed:

- `expression-sum` is the tagged grammar: `field $first { type: nominal($unit); }`,
  `field $second { type: nominal($unit); }`, `field $tested { }`, a `method $operation` whose body is
  `if ($tested == _) as $branch { }` followed by `call $local_first_call { receiver: $first;
  dispatch: possible; argument $context at 0; };` and `call alongside $local_second_call { receiver:
  $second; ... };`, plus `where $operation.name == $local_first_call.name` (the uniform-name
  recursion) and `where $first != $second`.
- `binary_result` and `context-free-binary` keep the counted claim:

  ```kql
  at least 2 distinct $child {
    type $unit {
      field $child { type: nominal($expression); }
      method $interpret {
        param $context { }
        body {
          let $stored = call $call { receiver: $child; unreplaced: true; dispatch: possible; argument $context at 0; } writes: 1;
          return from $call;
        }
      }
    }
    where subtype($unit, $expression);
    where overrides($interpret, $slot);
    where $interpret.name == $call.name;
  };
  ```

  `context-free-binary` is the same shape with a zero-argument slot
  (`method $evaluate { constructor: false; arity: 0; ... }` and no context argument).

Four authoring facts cost a probe each:

1. **A field is a valid condition subject; a member path is not.** `if ($tested == _)` compiles when
   `$tested` is a `field` of the enclosing type -- the frozen `TRUTH_TEST` relation names the *storage*,
   not a member expression -- while `$local_this.$tested` is refused
   (`unsupported condition expression`). The legacy `either` over "field of the unit / member of the
   instance receiver / member of the receiver parameter" therefore collapses into the single field
   spelling: the three arms name the same place.
2. **The second call of one statement needs `alongside`.** `return child.evaluate(ctx) +
   other.evaluate(ctx)` is one statement, so a second `call` clause without the flag looks for the
   next *statement* and matches nothing.
3. **The out-role must be bound outside the counted block.** Declaring `type $unit { ... }` only inside
   `at least 2 distinct $child { ... };` fails with `graph output is not bound in every alternative`;
   an empty `type $unit { }` before the quantifier fixes it (the counted block re-states the same role
   with its members).
4. **The result-consumption claim needs the join capture.** `return from $call;` alone accepts the
   `overwrite-result` fixture (`b = child.evaluate(ctx); b = 0; return a + b`), because the first child
   still feeds the return; `let $stored = call $call { ... } writes: 1;` beside it rejects it (the
   overwritten local carries two writes), which is what `walk VALUE_DEPENDS_ON($result, $call)
   { min: 1; max: 8; }` pinned in the frozen dialect.

**Reviewed parity delta.** `tests/structural/test_catalog_kql2_migration.py` records one evidence-only
delta for `interpreter` on the frozen multilingual fixture (one child field, one recursive call):
matches and completeness are unchanged, and the counted clause discloses `cardinality:open_world` --
the single child's inventory cannot be closed -- where the frozen edge/tally query stayed silent.

**Verification.** `tests/structural/test_interpreter_expression_sum.py`,
`tests/structural/test_algorithm_interpreter.py`, `tests/structural/test_ir178_contracts.py`,
`tests/structural/test_catalog_kql2_migration.py -k interpreter`,
`tests/structural/test_catalog_adversarial_matrix.py -k interpreter`,
`tests/structural/test_negative_corpus.py`, `tests/structural/test_catalog_ir_contracts.py`, and
`grep -E '^\s*(edge|walk|tally)\b' src/ken/structural/patterns/interpreter.toml` returns nothing.

### 5.67 The `exception-retry` rewrite: statement containment by name

The two retry variants correlate statements, not callables: a protected call returns from a loop, and
the handler either jumps back to that loop or completes at the loop's tail. The frozen dialect stated
that with `edge IN_HANDLER/HANDLER_OF/ENCLOSING_LOOP/CONTINUE_TARGET/TRY_EXIT_STATUS/LOOP_BODY_TAIL/
HANDLER_FALLTHROUGH` plus a `walk SYNTAX_PARENT` from the call to the return. KQL 2 now names the
nesting instead. Each claim reads as the sentence it checks and lowers onto the relation the frontend
already publishes for that statement (`src/ken/kql2/semantic.py`: `STATEMENT_RELATIONS`,
`STATEMENT_ATTRS`, `STATEMENT_UNARY`, `RETURN_OPERAND_HOPS`):

```kql
operation $loop { kind: "loop"; }
operation $protected { kind: "try"; }
operation $handler { }
operation $success { kind: "return"; }
operation $attempt { kind: "call"; }
operation $retry { native_kind: "continue_statement"; }

where runs($unit, $loop);                # HAS_OPERATION with execution: possible
where inside_try($success, $protected);  # IN_TRY_BODY
where inside_handler($retry, $handler);  # IN_HANDLER
where enclosed_by($protected, $loop);    # ENCLOSING_LOOP
where handles($handler, $protected);     # HANDLER_OF
where continues_to($retry, $loop);       # CONTINUE_TARGET
where ends_with($loop, $protected);      # LOOP_BODY_TAIL
where falls_through($handler, $protected);  # HANDLER_FALLTHROUGH
where exits_cleanly($protected);         # TRY_EXIT_STATUS == "no-explicit-override"
where returns_operand($success, $attempt);  # the call the return hands back
```

**Where each half is evaluated.** A selector query executes through the scan path
(`src/ken/kql2/execution.py`), whose `relation()` hook resolves these names against the facts the
linker publishes for the unit (`SemanticRelations.facts`, materialized once per snapshot); the graph
path lowers the same names to fact/path requirements (`src/ken/kql2/graph.py`), and the type checker
accepts two entity operands (`src/ken/kql2/compiler.py`). `runs` carries the `execution: possible`
attribute the public `possible_call` family uses, so an unreachable operation cannot satisfy it.

**Five measured authoring facts.**

1. **The handler needs no kind.** `operation $handler { }` is enough: `handles` + `inside_handler` /
   `falls_through` pin it, which is also language-neutral (`except_clause` in Python, `catch_clause`
   elsewhere). A property list (`native_kind: ["except_clause", "catch_clause"]`) is refused --
   `property requires a scalar literal, regex or wildcard in this capability` -- so the relation, not a
   kind spelling, carries the claim.
2. **`kind:` is the lowercase structural kind.** `operation $loop { kind: "loop"; }` and
   `operation $protected { kind: "try"; }` match `while`/`for`/`do` and `try`; the same property cannot
   select a handler, whose kind is the uninformative `native`.
3. **The claim order is the reading order.** `returns_operand($return, $call)` walks from the *call*
   up the syntax chain, so the roles read as the sentence does; the walk is bounded at four hops
   (`await`, a cast or a unary wrapper sits between a returned call and its return).
4. **Nesting is what separates the decoys.** No clause ties the call to the return beyond that walk:
   the inner-function fixture (`def g(): return work()` inside the protected region) is rejected
   because the linker publishes no `IN_TRY_BODY`/`ENCLOSING_LOOP` for the inner callable's return, and
   the second-try fixture because the handler that continues belongs to the other `try`.
5. **`exits_cleanly` is the finalizer contract.** `finally: audit()` keeps
   `TRY_EXIT_STATUS = no-explicit-override`; `finally: return/break` moves it to `may-override`, which
   is what makes an explicit retry under a returning finalizer *not* a retry.

**Verification.** `tests/kql2/test_statement_containment.py` (12 cases: each claim, the four decoys,
the finalizer pair, the await walk and the unbound-operand rejection),
`tests/structural/test_exception_retry.py`, `tests/structural/test_normal_completion.py`,
`tests/structural/test_modern_catalog_precision.py`, `tests/structural/test_modern_catalog_review.py`,
`tests/structural/test_catalog_kql2_migration.py -k retry`,
`tests/structural/test_catalog_adversarial_matrix.py -k retry`,
`tests/structural/test_negative_corpus.py`, and
`grep -E '^\s*(edge|walk|tally)\b' src/ken/structural/modern_patterns/exception-retry.toml` returns
nothing (both variants and the root are native KQL 2).

### 5.68 The `read-through-cache` rewrite: no new syntax, two authoring lessons

Legacy clauses replaced: the root rule's `HAS_METHOD`/`HAS_FIELD`/`ASSIGNED_FROM`/
`ALLOCATES_TYPE`/`HAS_CALL` block and the `read_fill` operation's 54-line block
(`CFG_STATUS`, `RETURN_FLOW_STATUS`, `BINDING_WRITE_STATUS`, `TRUTH_TEST`,
`BRANCH_TRUE`, the four `CFG_NEXT` walks, `UNREASSIGNED_BINDING`,
`UNIQUE_BINDING_WRITE`, `RETURN_ORIGIN`, `SYNTAX_PARENT`).

No compiler change was needed. The rewrite is:

```kql
pattern detect(out GraphTerm $unit, ...) {
  use ken.catalog.architecture.read_through_cache.read_fill.detect(read: $read, cache: $cache, ...);
  type $unit {
    field $cache { }
    method $read { }
    method $local_initialize {
      constructor: true;
      body {
        let $created = construct $local_storage_type {} as $local_construction;
        $cache = $created;
      }
    }
  }
}
```

and the operation states the retrieval body directly:

```kql
type $unit {
  field $cache { }
  method $read {
    param $key { reassigned: false; }
    param $source { }
    body {
      let $hit = call $presence { receiver: $cache; name: ["contains","containsKey","has","Contains","ContainsKey"]; argument $key at 0; };
      if ($hit) {
        let $looked = call $lookup { receiver: $cache; name: ["get","Get"]; argument $key at 0; };
        return $looked as $hit_return;
      }
      let $loaded = call $load { receiver: $source; name: ["load"]; argument $key at 0; };
      call $write { receiver: $cache; name: ["set","put","Set"]; argument $key at 0; argument $loaded at 1; };
      return $loaded as $miss_return;
    }
  }
}
where $source != $cache;
where $lookup != $load;
where $presence != $lookup;
where $presence.explicit_arguments == 1;
where $lookup.explicit_arguments == 1;
where $write.explicit_arguments == 2;
```

Every piece is existing surface: `type`/`field`/`method`/`param`/`constructor`, a BODY
`let ... = call ...`, an `if` whose subject is a role bound by `let ... = call ...`
(§5.59's third row), `return $place as $role`, and the public predicate
`explicit_arguments` (already used by `command`, `state` and `batch-work-queue`).

**Lesson 1: the same role must have one kind across a `use`.** The first draft declared
`param $cache { reassigned: false; }` in the operation. Validation then failed with
`ValueError: incompatible role kinds for $cache in results`: the root binds `$cache` with
`field $cache { }` (`FIELD`) while the operation's `param` bound it `PARAM`, and
`src/ken/structural/relational.py` `validate()` intersects the two empty. The retrieval
role is a field of the unit in both queries, so the operation now scopes its `method $read`
inside a `type $unit { field $cache { } ... }` block. Rule of thumb: when a role crosses a
`use`, both declarations must name the same graph kind, or neither may name a kind.

**Lesson 2: `call` is not a return operand.** `return call $lookup { ... };` is a parse
error (`source expressions require a role or application`). Bind the call to a local and
return the local, naming the return operation with `as $role` when the pattern exports it.

**Verification.** `tests/structural/test_read_through_cache.py` (147 cases:
`positive`/`renamed`/`alternate-api` match on five languages, all 18 near-miss mutations and
the five extra control/call shapes reject, the expanded-key spread rejects, and
`borrowed-cache` matches the public operation exactly once),
`tests/structural/test_catalog_kql2_migration.py -k cache` (root + operation parity against
the frozen pre-KQL2 catalog), `tests/structural/test_catalog_adversarial_matrix.py -k cache`,
`tests/structural/test_negative_corpus.py`, and
`grep -E '^\s*(edge|walk|tally)\s' src/ken/structural/modern_patterns/read-through-cache.toml`
returns nothing (root and operation are native KQL 2). The broad suite
(`tests/structural tests/kql2 tests/common_ast`) is green.

### 5.69 `singleton#once-primitive`: a callable passed directly as an argument, and the three arms that arm2/arm3 need

The variant asserts that a one-shot cell API (`sync.Once`, `std::once_flag`, `OnceLock`,
`Lazy<T>`, `AtomicReference`) retains a construction: the cell's call receives the *thunk*
that builds the type, and the accessor hands that retained value back. Its legacy query
matched the thunk with `ARGUMENT(call, arg)` + `VALUE(arg, $thunk)`, i.e. the argument's
value *is* the callable.

**Landed: identity for a callable argument operand.** `src/ken/kql2/body.py` (the call
clause's argument matcher) resolved a role bound to a `CALLABLE` node only through
`source_callable_values.reaches` -- the flow that carries a callable value through a
binding. A callable passed *directly* (`guard.Do(func(){...})`,
`std::call_once(flag, [](){...})`, `cell.get_or_init(|| ...)`) publishes
`ARGUMENT(call, CALLABLE)` with no value hop, so it matched nothing. The branch now accepts
the occurrence's own argument (`argument.object == binding.local_id`) first and falls back
to `reaches`, so:

```kql
callable $thunk { body { let $created = construct $unit {} as $construction; } }
callable $accessor { body { call on $cell { argument $thunk at 0; } as $local_call; return $retained; } }
```

**Three arms are now pure KQL 2** (verified against the variant's own fixtures -- each arm
matches `positive` and its near-misses with `search(...)`; see the fixtures in
`tests/structural/test_singleton_once_primitive.py`):

```kql
# Go / C++  ($cell and the slot are module-scope `var`s; `writes` ties the thunk to the slot)
callable $thunk { body { let $created = construct $unit {} as $construction; } }
module_decl $module {
  var $cell {}
  var $retained {}
  callable $accessor { body { call on $cell { argument $thunk at 0; } as $local_call; return $retained; } }
}
where writes($thunk, $retained);

# C++ passes the flag first: `call $local_call { argument $cell at 0; argument $thunk at 1; } as $local_call;`

# Rust / Java-like: the accessor returns the call on the cell
module_decl $module {
  var $cell {}
  callable $accessor {
    body { let $out = call $local_call { receiver: $cell; argument $thunk at 0; }; return $out; }
  }
}
```

Three authoring rules cost a probe each and are worth recording:

- A **nested lambda is not declared by the module**. `callable $thunk {...}` inside
  `module_decl` requires `DECLARES(module, thunk)`, which Go/C++/Java publish only for
  top-level functions; the lambda is declared by its enclosing callable. Put the thunk
  clause at pattern level (it may still sit inside the same `either` arm) and keep the
  module-scope `cell`/slot inside `module_decl`.
- The **clause order is load-bearing**: a `body` that names `$thunk` must be preceded by the
  clause that binds it, or the compiler reports `source operand requires a bound storage,
  parameter or captured value`.
- A module-scope variable is bound with **`var`, not `field`** (`out Binding $v`); `field`
  selects type members, and a `field` nested in `module_decl` only resolves for a storage
  the module *initializes* (that is what `singleton#module-shared` matches).

**Measured gaps (not landed).** The Java and C# arms of this variant are still blocked, and
each gap is a property of the fixture, not of the pattern:

- **A `return` clause cannot read an expression-bodied callable.** Java's thunk is
  `prev -> prev != null ? prev : new Config()`: a `return` needs a return *statement*, and the
  lambda is a single expression, so `body { return _; }` matches nothing (measured; with
  `param $previous {}` alone the clause matches 1 row). `returns_new($thunk, $unit)` /
  `returns_type($thunk, $unit)` are likewise unpublished for such a lambda. The **`construct`
  clause does read it** -- see §5.70, which lands the Java arm's construction claim.
- **A field initialized from a call with an argument.** C#'s cell is
  `private static readonly Lazy<Config> guard = new Lazy<Config>(() => new Config());`; the
  thunk reaches the cell as the *argument of the initializing call*, and `argument` inside
  `initializer { call ... }` is rejected by the parser (`unexpected constraint 'argument'`).
  The accessor then returns the cell's `Value` member, a read of a static field that the
  body matcher does not resolve as a return operand today.
- **An assignment to a module-scope (or callable-local) variable.** `$retained = _;` where
  `$retained` is bound by `var {}` matches nothing (`singleton#once-primitive` used to state
  that with `ASSIGNMENT_TARGET`/`ASSIGNMENT_VALUE`), so the Go/C++ arm above states the
  thunk-to-slot link with `where writes($thunk, $retained);` instead.

**Verification.** `tests/kql2` green after the matcher change; `tests/structural/
test_singleton_once_primitive.py`, `test_singleton_module_shared.py`,
`test_creational_catalog_precision.py`, `test_adapter_functional_adapter.py`,
`test_iterator_callback_iterator.py`, `test_callback_body_captures.py` and
`tests/structural/test_catalog_kql2_migration.py` green (270 tests) -- the widening only
accepts an occurrence that already carried the bound callable, so no entry gained or lost a
match. `singleton.toml` itself is unchanged: the rewrite waits on the two gaps above.

### 5.70 Reading an expression-bodied callable: `construct` reaches the lambda's value

§5.69 recorded that Java's `once-primitive` thunk `prev -> prev != null ? prev : new Config()`
had "no readable body": `callable $thunk { body { ... } }` matched nothing for it. That probe
used a `return` clause, and a return clause needs a return *statement* -- the lambda is one
expression, so there is none. The clause the legacy Java arm actually named is not a return:
it is `HAS_CALL($thunk, $construction)` + `ALLOCATES_TYPE($construction, $unit)`, and a
**`construct` clause reads the expression body through exactly those rows**. The frontend
publishes `HAS_CALL(lambda, call)` for the `new Config()` operand with
`ALLOCATES_TYPE(call, Config)`, and `body.py`'s `let`-construction arm resolves a callable's
construction from them:

```kql
callable $thunk {
  param $previous {}
  body { let $created = construct $unit {} as $construction; }
}
```

Measured against the five Java fixtures of `tests/structural/test_singleton_once_primitive.py`
(row counts):

| pattern | positive | local | crossed | fresh | reset |
|---|---:|---:|---:|---:|---:|
| the thunk clause alone | 1 | 1 | 1 | 1 | 1 |
| thunk clause + `field $cell {}` on the holder + `let $call = call $local_call { receiver: $cell; argument $thunk at 0; }; return $call;` on the accessor | 1 | 0 | 0 | 0 | 1 |

On the positive row `$unit` is `CLASS:Config`, `$construction` is the lambda's own
`new Config()` (the `CALL` whose span is the ternary's false arm, `301:313`) and `$cell` is
`STORAGE:guard`. So the Java arm's construction claim is now stateable, and the shared-cell part
(holder field + receiver + accessor returning that same call) is what rejects the three
near-misses; the `reset` boundary stays a match, as the variant's own test pins.

Two authoring facts: the `callable $thunk` clause must precede any body that names `$thunk`
(clause order, §5.69), and `param $previous {}` is the selector for the lambda's parameter --
what `HAS_PARAMETER($thunk, $previous)` names.

**Still unstated: the ternary guard itself.** The legacy arm additionally required
`NULL_TEST(condition, $previous) { when: false; }` with `BRANCH_FALSE →` the construction and
`BRANCH_TRUE → $previous`, i.e. "when the previous value is missing, build one; otherwise keep
it". KQL 2's guard vocabulary is statement-shaped (§5.59) and an expression body has no
statement, so the clause above says only "this lambda builds the type". A lambda that *always*
constructs satisfies it too. **Closed by §5.72**, which lands the polarity as the
`retained:` property of the construction, and by §5.71/§5.73, which closed the C# arm; the
probes recorded below were the measurements that motivated both.

**Verification.** `tests/kql2/test_expression_body_callable.py` (4 tests: the positive's
bindings, the pinned `reset` boundary, the three near-miss rejections, and the isolated thunk
clause) and `tests/kql2` green.

### 5.71 `where initialized_with($cell, $value, name: "…");` — the value a declaration initializer is entered with

Legacy relations: `ASSIGNED_FROM`, `ARGUMENT`, `VALUE`, `ENTITY{name}`.

A static cell can be *built from* a callback rather than written by it. C# declares that
relation in the field's own declaration, so there is no body to hang a `call` clause on:

```csharp
private static readonly Lazy<Config> guard = new Lazy<Config>(() => new Config());
public static Config current() { return guard.Value; }
```

The predicate states the whole tie in one clause:

```kql
where initialized_with($cell, $thunk, name: "^Lazy");
```

* `$cell` and `$value` are positively bound roles (typically a `field` selector and the
  callable the initializer receives). The evaluation lowers to three joins over fresh
  witnesses: `ASSIGNED_FROM($cell, ?call)` and `ARGUMENT(?call, ?argument)` and
  `VALUE(?argument, $value)`.
* The optional `name: "<pattern>"` operand constrains the creation call's spelling as a
  regular expression. It is spelled as a named string — not a `/…/ ` literal — because a
  call argument list goes through `arguments()` (`src/ken/kql2/syntax/parser.py:503`), and
  only a *matcher* position lexes a regex. The pattern is compiled with `_regex`
  (`src/ken/kql2/graph.py`, the `where` lowering), so a bad regex fails at compile time.

**Evidence.** The three joins are the rows the C# frontend publishes for the fixture
(`ASSIGNED_FROM(guard, CALL:140)`, `ARGUMENT(CALL:140, CALL:140/argument/0)`,
`VALUE(CALL:140/argument/0, anonymous@157)`) and `ENTITY($call, "CALL") { name: … }` carries
the spelling the call resolved to. Nothing else in KQL 2 relates a storage to a value its
own initializer received: `initializer { call $c; }` binds the creation call but rejects any
constraint inside it (`src/ken/kql2/graph.py` — *initializer expression constraints are not
yet supported*), and `argument` is a `call`-clause constraint, not a pattern-level predicate.

**Unblocks** `singleton#once-primitive` (the C# arm). Its three near-misses stay rejected:
a `Factory<…>` cell fails the `name:` pattern, a per-call `var` cell fails the `field`
selector, and a crossed cell (`other` built from the thunk while the accessor reads `guard`)
fails because the *guard* has no argument to join.

### 5.72 `construct $unit { retained: $gap; }` — a guarded construction's polarity

Legacy relations: `BODY_VALUE`, `SYNTAX_NODE`, `NULL_TEST`, `BRANCH_TRUE`, `BRANCH_FALSE`,
`VALUE`.

An expression-bodied callback can compute "build it once, otherwise keep what you have":

```java
guard.updateAndGet(prev -> prev != null ? prev : new Config())
```

A `construct` clause reads the allocation out of that lambda (§5.70), but says nothing about
the ternary. The new property states the polarity in one line:

```kql
callable $thunk {
  param $previous {}
  body { let $created = construct $unit { retained: $gap; } as $construction; }
}
```

It claims: the conditional's *other* arm hands `$gap` back, so the construction is the arm
the null test takes **when the value is missing**, and `$gap` is what the opposite arm
retains. The matcher reads the owner callable's `BODY_VALUE`, then `SYNTAX_NODE` to the
conditional, then `NULL_TEST(condition, $gap)`. Its `when` attribute names the arm that means
"the value is absent": `when: true` takes `BRANCH_TRUE` as the constructing arm, otherwise
`BRANCH_FALSE`; the opposite branch must carry `$gap` through `VALUE`.

**Evidence.** `src/ken/kql2/body.py` — the construct matcher's property loop (next to the
`argument`/`initializer` constraints) and the validation pass that accepts the property. On
the Java fixture the positive's `NULL_TEST {when: false, operator: "!="}` publishes
`BRANCH_FALSE → new Config()` (**values** `VALUE → CALL:301`) and `BRANCH_TRUE → prev`
(`VALUE → PARAMETER`), so both halves hold. The three counterexamples fail: no conditional
at all, both arms constructing (the opposite arm carries a call, not `$gap`), and the
reversed polarity (the construction is in the arm the null test does *not* take).

**Measured** (`tests/structural/test_creational_catalog_precision.py`, Java arm):

| thunk body | rows |
|---|---:|
| `prev != null ? prev : new Config()` | 1 |
| `prev == null ? new Config() : prev` | 1 |
| `new Config()` | 0 |
| `prev != null ? new Config() : new Config()` | 0 |
| `prev != null ? new Config() : prev` | 0 |

### 5.73 `singleton#once-primitive`: the five arms rewritten, and two §5.69 gaps closed

The last legacy block of `src/ken/structural/patterns/singleton.toml` (101 lines of
`edge`/`walk`) is now a `pattern` of five `either` arms, one per language. What each arm
states:

| arm | shape |
|---|---|
| Go | `module_decl $module { field $cell; field $retained; callable $accessor { body { call $local_call { name: "Do"; receiver: $cell; argument $thunk at 0; }; return $retained; } } }` + `where writes($thunk, $retained);` |
| C++ | the same, with the once flag as the call's **first argument**: `call $local_call { name: ["std::call_once", "call_once"]; argument $cell at 0; argument $thunk at 1; };` |
| Rust | `module_decl $module { field $cell; callable $accessor { body { let $out = call $local_call { name: "get_or_init"; receiver: $cell; argument $thunk at 0; }; return $out; } } }` |
| Java | `type $holder { field $cell { static: true; } … }` + the guarded construction of §5.72 + `name: "updateAndGet"` |
| C# | `type $holder { fields { field $cell { static: true; } } method $accessor { body { return $cell._; } } }` + `where initialized_with($cell, $thunk, name: "^Lazy");` |

Authoring notes that cost a probe each:

* **`either` is not a body instruction.** The two call shapes of Go and C++ had to be hoisted
  to two pattern-level alternatives (`BODY instruction is not implemented: either`); the
  accessor clause is duplicated inside each arm.
* **The thunk clause moved into each arm.** A single pattern-level `callable $thunk { … }`
  cannot serve both "builds the type" and "builds it only in the missing arm", so the Java
  arm carries its own clause with `param $previous {}` and `retained: $gap`.
* **The API name is what separates the idiom from an arbitrary callback API.** Each arm pins
  the protocol spelling (`Do`, `std::call_once`/`call_once`, `get_or_init`, `updateAndGet`,
  `^Lazy`); the precision suite swaps each one for a plausible near-miss
  (`.Repeat(`, `invoke(`, `.replace_with(`, `.map(`, `Factory<Config>`) and every swap must
  be rejected. `name:` in a `call` clause takes a literal or a list of literals, so the C++
  spelling is a two-element list (`std::call_once` is what the fixture publishes) and the C#
  prefix match lives in §5.71, where a regex is accepted.
* **§5.69 overstated one gap.** It recorded that "the body matcher does not resolve [a
  static field's member] as a return operand today". The `$place._` operand of §5.17 does:
  `body { return $cell._; }` resolves the member the accessor hands back. What the C# arm
  really needed was the initializer tie (§5.71), not a new member-read primitive.
* **The eager `type $unit {}` selector is what blows the state budget here.** The composed
  `singleton` rule must enumerate 100 private-overload classes inside
  `QueryBudget(max_states=25000)` (`tests/structural/test_construction_access.py`). With
  `type $unit {}` before the thunk clause the arm costs **340 201** states, because the type
  is bound from the 100 classes *before* the construction walks each callable's body; with
  the clause removed, so that the `construct` itself binds the constructed type, the same
  arm costs **3 401**. The composed rule dropped from **1 516 316** states (no arm could
  complete) to **20 721** — 100 matches inside the budget. This is §5.46's lesson in its
  sharpest form: a type-introducing selector multiplies by the number of candidate types.

**Verification.** `tests/structural/test_singleton_once_primitive.py`,
`test_singleton_module_shared.py`, `test_creational_catalog_precision.py`,
`test_catalog_adversarial_matrix.py -k singleton`, `test_catalog_kql2_migration.py` (frozen
parity), `test_negative_corpus.py` and `tests/kql2` green. `singleton.toml` has no
`edge`/`walk`/`tally` clause left.

### 5.74 `let $v = call $f { receiver_input: $place; };` — the capture form of the strict receiver

```
body {
  let $read = call $getter { receiver_input: $memento; } as $lookup;
  $state = $read as $write;
}
```

**Evidence.** `src/ken/kql2/body.py`, the let-capture constraint loop (the branch next to
`receiver:`) now accepts `receiver_input:` and applies the same bound-storage-role check as
the statement-call loop. The engine side already existed: the `receiver_input:` branch reads
`CALL_RECEIVER_INPUT(call, place)` — the row the linear body publishes for the receivers it
reads *directly* — which is strictly narrower than `receiver:`, satisfied by the call's own
receiver row alone. `tests/kql2` green.

**Measured on `memento#accessor-snapshot`'s fixtures.** With `receiver_input: $memento;` the
python round trip matches, and both rebind shapes are rejected: the fixture's own
`restore-rebind` (`s = Snapshot(0); self.state = s.get()`) and `s = self; self.state =
s.get()`. With plain `receiver: $memento;` both rebind shapes still match, which is the gap
5.24 recorded.

### 5.75 Measured: why `memento` and `dispatch-table` carried `edge` clauses

Both catalogues were re-measured (2026-09-16) with micro-patterns that compile a candidate
body against the live fixtures; every number below is a state count from the engine, not an
estimate.

**`dispatch-table#direct` — a state-budget wall, not an expressive gap.** The pure KQL 2 form
is authorable and semantically right (`matches == 1` on the small registry of every language
and on the 150-method registry), but as first spelled it did not fit
`tests/structural/test_dispatch_table.py::test_dispatch_table_avoids_unrelated_method_parameter_cross_product`,
whose assertion is `execute_rules(..., QueryBudget(max_states=2000))` then
`result['complete']`. Costs on that fixture:

| spelling | states |
|---|---:|
| legacy `edge` signature (as committed) | 43 |
| §F1 form (`type` + `field` + two `method`s with `arity: 2`, params, bodies) | 13 438 |
| same with `position:` pinned on all three parameters (`param $key { position: 0; }`) | 6 746 |
| `parameters { param … }` block instead of bare `param` | 6 746 |
| without the two parameter clauses and both bodies | 1 844 |

The attribution is that this first spelling binds `$table` by *enumerating the class's fields*:
the plan keeps the authored order, so `HAS_FIELD` scans all 151 fields of the fixture (the 150
noise fields plus the table) and the BODY matcher then runs once per field — ~9.7k of the 13.4k
states are body matching (`src/ken/kql2/body.py:976`, `:2878`, `:971`,
`src/ken/kql2/source_execution.py:72`, `:149`). Pinned parameter positions, `arity: 2`,
`writes: exactly($table, 1);` and a linear body do not change that (measured: `writes:` variant
7 699 and `matches == 0`). What changes it is binding the storage from the write instead of
enumerating fields: §5.77 lands that spelling and brings the entry to 260 states, inside the
budget.

**`memento#accessor-snapshot` — two arms the pure form still cannot state.** The typed arm is
authorable: `type nominal($snapshot)` on the restore parameter plus
`writes: exactly($state, 1);` and `receiver_input: $memento;` (§5.74) gives the python
positive and rejects `restore-overwrite`, `restore-rebind`, `constructor-overwrite`,
`constructor-rebind` and `getter-overwrite` once the constructor states
`writes: exactly($saved, 1);` and `param $input { reassigned: false; }`. The other two arms
are landed too (§5.76): the `contract=True` fixtures annotate the restore parameter with the
interface the snapshot implements, and the JavaScript parameter is untyped, correlated only by
an observed caller. Measured: the interface arm needs `type $contract { method $slot {} }` —
`type` binds an interface, `class` binds only a class — plus
`where subtype($snapshot, $contract);` and `where overrides($getter, $slot);` so the plain
fixtures do not match, with the getter call written `call $slot { receiver_input: $memento; }`.
The untyped arm needs the new `receives($memento, $snapshot)` predicate (§5.76): with
`receiver: $memento; resolution: unresolved;` the member call matches the JavaScript fixture
even when the caller is deleted, so the caller has to be stated and it is the only relation
that states it. The file is now pure KQL 2.

**`memento#serialized-snapshot` — migrated (§5.78).** 25 clauses of `FLOWS_TO` walks, codec
identification by name and three decoded-value shapes across eight languages. The walks became
three pattern-level arms and the codec identification a regex spelling inventory; the file is
now pure KQL 2, and this was the last catalogue entry that used an internal operator.

### 5.76 `where receives($parameter, $type);` — the value a call site hands a parameter

Legacy relations: `CALL_BINDING`, `BINDING_PARAMETER`, `BINDING_VALUE`, joined to `TYPE` or
`ALLOCATES_TYPE`.

```kql
pattern detect(out Callable $restore) {
  type $snapshot { field $saved {} method $getter { arity: 0; body { return $saved; } } }
  type $originator { field $state {} }
  callable $restore { name: "restore"; param $memento {} writes: exactly($state, 1); }
  where receives($memento, $snapshot);
}
```

The untyped Memento restore parameter (`def restore(self, s): self.state = s.get()`) names no
type, so the only evidence that `s` is a snapshot is a call site that hands one in:
`origin.restore(new Snapshot(10))` publishes `BINDING_PARAMETER`/`BINDING_VALUE` for that
occurrence, and the supplied value is either a construction of the type (`ALLOCATES_TYPE`) or
a declaration the project typed with it (`TYPE`). Stating the caller as evidence is what makes
`tests/structural/test_memento_accessors.py::test_untyped_restore_needs_observed_snapshot_input`
reject a restore whose caller was deleted: the unresolved member call alone matches either way.

**Evidence.** `src/ken/kql2/graph.py` lowers the predicate next to `initialized_with`: one
`fact` node for `BINDING_PARAMETER(binding, $parameter)` and an `any` over two branches, each
joining `BINDING_VALUE(binding, value)` to `TYPE(value, $type)` or
`ALLOCATES_TYPE(value, $type)`. The binding and the value are fresh witness roles, so the
pattern never has to name the call site. `src/ken/kql2/compiler.py` types the predicate as two
bound entity roles, which is what makes the query checker accept it.

**Unblocks** the third arm of `memento#accessor-snapshot`. It is also the spelling any pattern
needs when a parameter's type is only observed at a call site.

**Authoring note.** The predicate is a join, so it lowers on the graph-plan path only. A
pattern that uses it must be graph-capable — every catalogue pattern is; the nominal operand
(`type: nominal($x)`) or a relational property such as `writes:` is what selects that path
(`src/ken/kql2/graph.py:91`).

**Verification.** `tests/kql2/test_where_receives.py` (the construction branch, the typed-local
branch, the absent-caller and other-type negatives, the swapped-role negative and the arity
check), `tests/structural/test_memento_accessors.py`,
`tests/structural/test_algorithm_memento.py`,
`tests/structural/test_memento_serialized_snapshot.py`,
`tests/structural/test_catalog_kql2_migration.py -k memento`,
`tests/structural/test_catalog_adversarial_matrix.py -k memento` and
`tests/structural/test_negative_corpus.py -k memento` — all green.

### 5.77 `insert $value into $collection at $key writes: n;` — the insertion names its collection

```kql
pattern detect(out TypeDecl $unit, out Field $table) {
  type $unit {
    method $register {
      arity: 2;
      param $key { }
      param $handler { }
      body { insert $handler into $table at $key writes: 1; }
    }
    method $dispatch {
      arity: 2;
      param $requested { }
      body { call $table[$requested] { } as $call; }
    }
    field $table { }
  }
  where $key != $handler;
  where $register != $dispatch;
}
```

**A fresh collection role.** The collection used to have to be a place the pattern had already
bound (`insert requires a bound collection place`), which forced `field $table { }` to be
authored *before* the registration body — and that spelling enumerates every field of the class
(§5.75). An insertion now introduces the role the way `iterate $source as $item` introduces the
collection a walk reads: the write target binds it. The domain is the one the pattern declared
for that role (`out Field $table`); a pattern that declares none gets `value`. A later
`field $table { }` selector then *confirms* the storage instead of fighting it. The insertion
still refuses to guess when it names more than one collection — a keyed bucket and its
container are two — so that spelling keeps needing a bound place.

**A stated write count.** `insert … writes: n;` is the insertion's counterpart of the
`let $read = $pool[$key] writes: 2;` capture (§5.44): this insertion is the owner's only
indexed write to that collection. It is the pure KQL 2 spelling of the retired
`edge INDEXED_WRITE_COUNT($local_write, "1")` clause, and without it a registration that is
immediately overwritten (`table[key] = handler; table[key] = None`) still matches a dispatch
table (`docs/structural-validation/catalog-adversarial-2026-09-14/cases.json`,
`directed/dispatch-overwritten-handler`).

**Evidence.** `src/ken/kql2/syntax/parser.py` (`body_clause`, the `insert` branch) parses the
count into the clause's `name`. `src/ken/kql2/body.py` `compile_body` registers the introduced
role (keeping the domain the enclosing scope declared) and `match_step` binds a fresh
collection from the derived write targets, then requires
`INDEXED_WRITE_COUNT(<write occurrence>) == n` — the per-owner count
`src/ken/structural/write_inventory.py` publishes.

**Measured.** `dispatch-table#direct` on the 150-method budget fixture: 13 438 states with the
field selected first, **260** with the registration body first (the write binds `$table`, then
`HAS_FIELD` verifies a single candidate) against the 2 000-state ceiling of
`tests/structural/test_dispatch_table.py::test_dispatch_table_avoids_unrelated_method_parameter_cross_product`.

**Verification.** `tests/kql2/test_insert_write_count.py` (bound and fresh collection, count one
and count two), `tests/structural/test_dispatch_table.py`,
`tests/structural/test_catalog_adversarial_matrix.py -k dispatch`,
`tests/structural/test_catalog_kql2_migration.py`, `tests/structural/test_negative_corpus.py`
and the whole `tests/kql2` suite.

### 5.78 `name: /regex/;` — the callee spelling the source qualified

**Need.** `memento#serialized-snapshot` identifies the codec by the spelling of the call that
performs it, and the published spelling is what the *source* wrote, not the identifier the
pattern hopes for:

| language | published spelling | why a literal list cannot claim it |
|---|---|---|
| Rust | `serde_json::to_string` | the path before the last segment is an import choice |
| C# | `Deserialize<string>` | the generic argument is part of the name |

The legacy rule said so with two anchored regular expressions
(`/(dumps|…|to_string)$/` for the encoder, unanchored `/(loads|…|from_str)/` for the
decoder), and the anchoring was *measured*, not stylistic: without `$` the encoder list
would also claim `dumps_extra`, and without dropping the anchor the C# decoder list would
miss `Deserialize<string>`.

**Spelling.**

```
call $encode { name: /to_string$/; argument $state at 0; };
call $decode { name: /(loads|parse|fromJson|Deserialize|decode)/; argument $payload at 0; };
```

`name: "clone";` (one spelling) and `name: ["copy", "deepcopy"];` (§ earlier) are unchanged;
a `/…/` operand is a third form of the same inventory. The expression is searched, not
matched, so `$` is how a pattern asks for "ends with" — exactly as a graph-level `edge`
matcher reads the same literal.

**Semantics.** `src/ken/kql2/body.py`: `name_regex(value)` compiles the literal with the
flags it carries (`i` supported) and refuses a pattern that could not stay regular
(backreferences, lookaround, more than 512 characters) — the same limits
`src/ken/kql2/graph.py:matcher` enforces, and the lexer itself already refuses both
spellings when it scans any regex literal. Where the matcher compares,
`spelled(spelling)` is `search(pattern, spelling) is not None`, applied to the spelling the
clause already reads (entity attribute `name`, then an `ENTITY` fact, then the occurrence's
`name`).

**Authoring trap, measured.** A local variable named `pattern` inside `match_step` shadows the
enclosing `BodyPattern` parameter of `match()`. The shadowing is silent at import time and
breaks *every* call-clause alias (`call … as $x`) with `UnboundLocalError`. The helper is
therefore bound to `spelled_by`.

**The three decode shapes.** The variant states them as three pattern-level arms, because a
`body` cannot carry an `either` (§5.25):

1. the decoder's own value is stored — `$state = $decode;` (Python, JS, TS, Java, C#, C++);
2. the decoder is wrapped by an operation whose value is stored — Rust's
   `serde_json::from_str(payload).unwrap()`;
3. the state is handed to the decoder as the destination argument —
   `argument $state at 1;` (Go's `json.Unmarshal(payload, &e.state)`).

Arm 2 needs the wrapper *named* to be comparable with what the source stored
(`ASSIGNMENT_VALUE` is the wrapping call, not a fresh value), and a `call` clause alias only
becomes a storage-comparable role when its domain is declared:

```
pattern wrapped(out …, out Call $local_unwrapped) {
  type $unit {
    method $load {
      body {
        call $decode { name: /from_str/; argument $payload at 0; };
        call on $decode { } as $local_unwrapped;
        $state = $local_unwrapped;
      }
    }
  }
}
```

Two consequences, both measured here:

- `receiver: $decode;` is refused (`receiver requires a bound storage role`) — a *call* is not
  a place, so the receiver-of-a-call shape is spelled `call on $decode`.
- every declared output must be bound in **every** `either` alternative
  (`src/ken/kql2/graph.py:684`), so the wrapper role cannot be declared on the rule that has
  the alternatives. The wrapped shape is therefore its own `pattern` in the same module, and
  the arm states `use wrapped(…);`.

**Verification.** `tests/kql2/test_body_call_name_regex.py` (qualified Rust spelling, the
parameterised C# spelling, a regex that brackets the last segment with a literal dot, and the
refusal of a lookaround), `tests/structural/test_memento_serialized_snapshot.py` (8 positives
× 1 match, 8 renamed fixtures, and the four negative families),
`tests/structural/test_algorithm_memento.py`, `tests/structural/test_memento_accessors.py`,
`tests/structural/test_behavioral_catalog_join_regressions.py`,
`tests/structural/test_catalog_kql2_migration.py -k memento`,
`tests/structural/test_catalog_adversarial_matrix.py -k memento`,
`tests/structural/test_negative_corpus.py` and the whole `tests/kql2` suite.

### 5.79 The catalogue no longer uses an internal operator

`examples/bench/catalog_authoring_inventory.py` reports **0** queries with `edge`/`walk`/`tally`
across all 33 catalogues, and its "Entradas que todavía usan operadores internos" list is
empty: `memento#serialized-snapshot` was the last entry that still used them. Legacy
`edge`/`walk`/`tally` clauses stay parseable, but no catalogue entry is authored with them.

## 6. Non-goals

- No new grammar for "design pattern" as a first-class declaration: patterns
  remain `pattern detect(...)` plus catalog metadata.
- No change to the public Python API of `src/ken/structural` or `src/ken/kql2`;
  extensions are new accepted surface plus lowering inside the existing
  compiler/body pipeline.
- Legacy `edge`/`walk`/`tally` clauses stay parseable (other catalogs and the
  conformance corpus rely on them) but no migrated entry may use them.
