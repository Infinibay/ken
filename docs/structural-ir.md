> **Operational reference: IR 1.71.0.** This document describes available behavior
> and its limits. The [design specification](design/structural/README.md) also
> contains future contracts; proposal text is not evidence of implementation.

# Structural IR and queries

Read [Representation contract](#representation-contract) for the serialized graph
and the difference between source operands and query values;
[Queryable types, operators and control](#queryable-types-operators-and-control)
for executable examples; and [Precision and uncertainty](#precision-and-uncertainty)
before interpreting an absent match. The [KenQL guide](structural-queries.md)
documents the current query language and named dependencies. Versioned sections
below explain when a contract appeared; their exclusions still apply unless a
later section explicitly extends them.

## A comparison branch publishes the value it discriminates (IR 1.71)

``if kind == Num`` now publishes which slot the branch tests:

```
<if operation> --TRUTH_TEST--> kind
<if operation> --TRUTH_TEST--> Num
```

``TRUTH_TEST`` existed for a bare test (``if value``), where the tested value is the
condition itself. A *comparison* has a different shape: the condition is not the value
being discriminated, so nothing was published and a query asking "this branch dispatches
on that tag field" could only ask "this callable contains a branch". Both sides are
offered and only the ones that denote a slot (``STORAGE`` or ``MEMBER``) are published;
no polarity is claimed, because which arm a comparison selects is not the truthiness of
the value. A comparison against a null literal is **excluded**: that shape already
publishes ``NULL_TEST`` with its own polarity, and emitting both made the branch carry
two pairs of arms.

Rust's ``if`` is an ``if_expression``, so the branch handling now covers both spellings
-- without that, Rust published no ``TRUTH_TEST`` at all and the dispatch evidence was
missing in exactly one of the six languages.

## Rust ownership wrappers denote their payload (IR 1.70)

A Rust slot annotated ``Box<Expr>``, ``Rc<Expr>`` or ``Arc<Expr>`` is typed by
``Expr``:

```
left --TYPE--> Expr          (native_type stays "Box<Expr>")
```

``normalized_type`` already strips ``&``/``*``/``mut``, and ``TYPE_HEAD`` keeps the
*head* of a generic annotation -- that is what resolves ``OnceLock<Service>`` to
``OnceLock``. For a smart pointer the head is the wrapper (``Box``), which declares
nothing, so the slot had no ``TYPE`` at all and a query asking "this field is of my
own type" could not see the recursive operand. The unwrapped spelling therefore wins
over the head **only** when the annotation was actually unwrapped, which leaves
``Vec<Expr>`` on its existing element-type path and keeps the cell reading of
``OnceLock<T>``.

The unwrap is guarded on the entity's language: another language's own ``Box<T>`` is
a user type and is untouched.

## Shared member signatures (IR 1.69)

Two nominal types that declare the same member name with the same arity point at one
``SIGNATURE`` entity:

```
<callable> --MATCHES_SIGNATURE--> signature:<name>/<arity>
```

A query that relates two providers by their creation-slot set cannot join on ``name``
without pairing every method of one type with every method of the other, which is the
recorded ``budget:max_states`` blocker for ``abstract-factory#structural-families`` on a
corpus of 30 types. Grouping the slot under one entity turns that into a join by
identity:

```
require $first_slot MATCHES_SIGNATURE $slot;
require $second_slot MATCHES_SIGNATURE $slot;
```

A ``SIGNATURE`` entity is created only for a ``(name, arity)`` pair that **two or more**
nominal types declare, so a member only one type has is not a slot. Constructors are
excluded: every class has one, so they would group unrelated types, and a constructor is
a declaration rather than a creation slot. Arity counts parameters that are not the
receiver; parameter *types* are not part of the key, so ``f(int)`` and ``f(string)`` are
the same slot. The entity is language-agnostic and shared across files, which is what
lets a provider in one file pair with a provider in another.

## Rust compound assignment is an assignment (IR 1.68)

``total += child.count(ctx)`` now carries the two facts every other language's
compound assignment already carried:

```
<op> --ASSIGNMENT_TARGET--> total
<op> --ASSIGNMENT_VALUE-->  <the call producing the added value>
```

Rust spells it ``compound_assignment_expr``; the augmented-assignment branch that
Python (``augmented_assignment``) and JS/TS (``augmented_assignment_expression``)
already used did not include it, so the operation appeared in the graph with no
target and no value. Java, C# and C++ reach the same branch through
``assignment_expression`` and were unaffected.

The consequence is the one that matters for accumulation: a query asking "the
element's result feeds the total this callable returns" could not see the edge at
all, and returned zero matches without failing.

## Go ``var`` inside a callable binds a new name (IR 1.67)

A declaration inside a Go callable is a new binding, even when the file declares the
same spelling. Two entities now exist where one did before:

```
package-level:   <module> --DECLARES--> <module>/STORAGE:guard
function-local:  <module>/CALLABLE:current --DECLARES--> <module>/CALLABLE:current/STORAGE:guard
```

IR 1.57 lowered a file-scope Go ``var`` so that reads inside a callable could resolve
it, and function-local ``var`` declarations rode along on the same lookup: the spelling
resolved outward to the module slot, so the declaration never created a binding. Go is
the one analysed language whose declaration node *is* the assignment (the name lives on
a ``var_spec`` child), so it was never covered by the block-declaration handling that
JS/TS ``let``, Java ``local_variable_declaration`` and C# ``variable_declaration`` use.

The defect is silent in the direction that matters least and loud in the other: a
function-local slot that shadows a file one merges its write set with the file slot, so
a guard created fresh on every invocation is indistinguishable from a shared one. A
``var`` inside a nested Go block keeps the block-scoped entity it already had through
that path.

## Address-of denotes its slot (IR 1.66)

``&slot`` and ``*pointer`` resolve to the storage they name, so an argument that
addresses a slot is evidence about that slot:

```
Editor/Restore --ARGUMENT--> <argument/0>      the payload
              --ARGUMENT--> Editor/STORAGE:state   &e.state
```

Before this a Go ``unary_expression`` such as ``&e.state`` fell through to the primitive
fallback and produced an anonymous ``VALUE`` with ``native_kind: unary_expression``,
which made the destination slot unrecoverable. An array of languages pass a destination
by address instead of assigning to it — Go's ``json.Unmarshal(payload, &e.state)`` is the
canonical one — so a query asking "this call stores into that slot" had no way to see it.

``pointer_expression`` and ``reference_expression`` were already unwrapped; only the
operator spelling had to be checked for ``unary_expression``, so ``-x`` and ``!x`` keep
their own values.

## Return type arguments (IR 1.65)

A method whose return type applies **its own declaring type** publishes the argument it
is applied to:

```
<method> --RETURN_TYPE_ARGUMENT--> <argument>
```

``Builder<Pending>`` becomes ``Builder<Ready>`` across a typestate step, and the bare type
name cannot say so: the generic spelling survives in ``native_return_type``, but a query
cannot match a prefix against a bound name, and no other fact recovers which state a step
moved to. The fact is emitted only when the applied base equals the declaring type's
name, so a method returning someone else's generic type is untouched.

The argument is a **name**, not a resolved type: nothing here links it to a declaration
of ``Ready``, and no instantiation is resolved. A step returning the declaring type
applied to its *own* parameter (``Builder<State>``) is recorded too, and it is the query
that has to exclude it.

## Type parameters in every generic grammar (IR 1.64)

Type-parameter binding was Rust-only until IR 1.62 added C++, and four of the six
grammars that spell a type-parameter group still bound nothing. They do now:

| Language | Group | Members |
|---|---|---|
| Rust | `type_parameters` field | `type_parameter` |
| TypeScript, Java | `type_parameters` field | `type_parameter` |
| Go | `type_parameters` field | `type_parameter_declaration` |
| C++ | `template_declaration`'s `parameters` field | `type_parameter_declaration` |
| C# | **unfielded** `type_parameter_list` child | `type_parameter` |

C# is the odd one: it leaves the group as an ordinary child with no field name, so it
is found by node type among the declaration's own children. Java's `type_parameter`
carries no `name` field either, so the name falls back to the identifier child.

Go needed a second fix, in the same commit and for the same reason. A generic receiver
spells its type arguments — `func (a *Abstraction[I]) Operation()` — while the
declaration is named without them, so the method resolved to no type at all and was
owned by the **module** instead of by `Abstraction`. Trailing type arguments are
stripped from the receiver before the lookup.

Both are additive: no existing fact is reinterpreted, and a declaration with no group
binds nothing.

## Parameters typed by a type parameter (IR 1.63)

A parameter whose declared type **is** one of its callable's own type parameters
publishes that identity:

```
<parameter> --TYPE_PARAMETER--> <parameter name>
```

The declared type keeps its decoration, so the bare name has to be recovered:

| Language | Declared | `TYPE_NAME` | `TYPE_PARAMETER` |
|---|---|---|---|
| C++ | `Visitor& visitor` | `Visitor &` | `Visitor` |
| Rust | `visitor: &V` | `&V` | `V` |

Without the undecorated fact there is nothing to join: the method says it binds
`Visitor` (or `V`) and the parameter says its type is `Visitor &` (or `&V`), and a query
asking which parameter stands for the bound type silently matches nothing. Reference,
pointer, `const` and `mut` decoration is stripped for the comparison only; a parameter
whose type is anything else keeps its own name and publishes no such fact.

This is what makes a visitor **generic** rather than named: the element's method
selects its visitor by type parameter, so no visitor type has to resolve at the call.

## Bound type parameters (IR 1.62)

A declaration that binds type parameters publishes them, and C++ now binds them at all:

| Language | Spelling | Group |
|---|---|---|
| Rust | `struct Context<P: Policy>` | the `type_parameters` field, members `type_parameter` |
| C++ | `template <typename Policy> class Context` | the `template_declaration`'s `parameters` field, members `type_parameter_declaration` |

C++ was the gap. `bound_type_parameters` walked ancestors looking for a
`type_parameters` field, which C++ does not have: its `template_declaration` puts the
group in the `parameters` field — the same name a function uses for its ordinary
parameter list. Only the `type_parameter_declaration` node type is read from that field,
and only when the ancestor is a `template_declaration`, so a function's arguments are
never mistaken for a type-parameter group.

Each binding is published as a **fact**, not only as an attribute:

```
<declaration> --BINDS_TYPE_PARAMETER--> <parameter name>
```

An attribute list is not reachable from KenQL, and the question a query asks is which
parameter a *field's* `TYPE_NAME` stands for. With the fact, the two join directly:

```
require $unit BINDS_TYPE_PARAMETER $parameter;
require $policy TYPE_NAME $parameter;
```

That reads "this field is typed by a parameter of this declaration", which is what
makes a policy static instead of a runtime object. It resolves **no** instantiation: a
use site's `Context<FastPolicy>` is not connected to the declaration, and partial
specialisation is not modelled.

## Call completeness and exact cardinality (IR 1.61)

A callable publishes `complete:<callable>:HAS_CALL`: its own calls are **enumerated,
not sampled**. Two query forms depend on that and were previously unusable in strict
evidence mode:

```kenql
query documented_call_cardinality {
 require $unit HAS_METHOD $build;
 callable(constructor: false) as $build;
 count distinct $call = 1 {
  require $build HAS_CALL $call;
 };
 emit unit=$unit, $build;
}
```

The same capability backs `not exists { … } within callable($x)`, which answers "this
callable makes no call of this shape" rather than "exactly one".

Both are "closed-world" forms. `Engine.closed` (`kenql.py`) walks the block and
requires a `complete:<subject>:<relation>` capability for every fact, resolving each
subject against the **outer** row — so a fact whose subject is bound *inside* the block
can never be closed, and a count block should keep its extra conditions in a `where`
rather than in a second `require`. Without closure, `=`/`<=`/`<` counts and absence
carry `cardinality:open_world` and `strict` mode drops them; `>=` works either way
because a lower bound can be witnessed.

Two Java and C# node types were missing from the call set and had to be added first,
because a completeness claim is only as good as the classification under it:

| Language | Node | Why it is a call |
|---|---|---|
| Java | `explicit_constructor_invocation` | `super(...)`/`this(...)` invokes another constructor |
| C# | `constructor_initializer` | `: base(...)`/`: this(...)`, same, spelled with an unnamed callee token |

Before them a Java or C# constructor body could contain a call the graph never
recorded, which would have made the claim **unsound** rather than merely incomplete.

`tests/structural/test_call_cardinality_closure.py` enumerates one call form per
language with its expected syntactic callee name, and asserts both that the form is
classified and that the owning callable publishes completeness. A grammar rename fails
there before the claim becomes a lie. Rust macro invocations are not calls and are
deliberately not counted. Completeness is withheld when the source carries diagnostics.

## C++ parameter reference kind (IR 1.60)

A C++ parameter bound through a `reference_declarator` records how it is bound:
`reference_kind` is `lvalue` for `&` and `rvalue` for `&&`. Parameters taken by value
carry no `reference_kind` at all, so the attribute distinguishes three bindings rather
than two.

It exists because `X(const X&)` and `X(X&&)` differ in nothing else. Both are
constructors of `X`, both have arity 1, and the parameter's `TYPE` resolves to `X`
either way — the declarator spelling is the only place the distinction lives. Copy
and move are different protocols, so a rule asking for the copy constructor has to be
able to say so.

## Suspending loops (IR 1.59)

A loop that advances through the async protocol — Python `async for`, JavaScript and
TypeScript `for await`, C# `await foreach` — carries `async: True` on the loop
operation, so `operation(kind: loop, async: true)` selects it.

Nothing else in the graph distinguishes it. The iteration facts are the same ones a
synchronous loop over the same source produces:

| Fact | `for (const item of produce())` | `for await (const item of produce())` |
|---|---|---|
| `LOOP` operation | yes | yes |
| `ITERATION_SOURCE` | the call | the call |
| `ITERATION_BODY` | the block | the block |
| `TARGET` on the source | to `produce` | to `produce` |
| loop `async` | absent | `True` |

Before this the only trace was the unnamed token list on the operation, which no
query can reach, so "this loop suspends to advance" was not expressible at all.

The flag is set from the loop's own tokens, so it is a property of the loop rather
than of the enclosing callable: the plain count loop inside an `async def` stays
unflagged.

## Enum declarations and named-constant identity (IR 1.58)

An enum declaration is a nominal type. `enum_specifier` (C++), `enum_item` (Rust)
and `enum_declaration` (Java, C#, TypeScript) now lower through the same path as a
class, so the declaration binds a name that a reference can resolve. A body-less
C++ `enum_specifier` is an elaborated *reference* (`enum State` inside a
declaration), not a definition, and declares nothing.

The load-bearing part is **reference identity**. A reference to a named constant
has one identity per declaration, not one per occurrence:

| Language | Reference | Entity |
|---|---|---|
| C++ | `State::Idle` | `…/CLASS:State/MEMBER:Idle` |
| Rust | `State::Idle` | `…/CLASS:State/MEMBER:Idle` |
| Java | `State.IDLE` | `…/CLASS:State/MEMBER:IDLE` |
| C# | `State.Idle` | `…/CLASS:State/MEMBER:Idle` |
| TypeScript | `State.Idle` | `…/CLASS:State/MEMBER:Idle` |
| Python | `State.IDLE` | `…/CLASS:State/MEMBER:IDLE` |
| Go | `Idle` | `…/module/STORAGE:Idle` |
| JavaScript | `State.IDLE` | `…/module/STORAGE:State/MEMBER:IDLE` |

Python reaches this through `class_definition`, Go through a module-level `const`
block, and JavaScript through an object literal of constants; those three already
keyed by name. Before this version C++ and Rust lowered `State::Idle` as an
anonymous `VALUE` keyed by byte offset, so two occurrences of **one** constant were
two entities.

That difference is observable, which is why it is a contract rather than an
implementation detail: a check of the form "at least two distinct values are
written here" is satisfied by writing the same constant twice as soon as identity
is per occurrence. A query that needs to distinguish states must be able to say so,
and it can only do that if the graph agrees on what a constant is.

Qualified references are only resolved to a constant when the qualifier resolves to
a declared type **and** that type's declaration lists the name. `Config::new` and
module paths keep their previous treatment.

## File-scope declarations and function-local statics (IR 1.57)

A declaration at file scope binds a **module-scope** slot:

| Language | Source | Slot owner |
|---|---|---|
| Go | `var instance = Config{value: 1}` | the module |
| Go | `const limit = 3` | the module |
| Rust | `static INSTANCE: Config = Config { value: 1 };` | the module |
| Rust | `const LIMIT: i32 = 3;` | the module |

Before this the declaration node was not lowered at all. The read inside an
accessor (`return instance`) therefore could not resolve the name and created a
**callable-local** `STORAGE` of the same spelling: the module declared nothing, and
the initialization and the read pointed at two different entities sharing one name.
The binding is now created while declaring, so its identity does not depend on
whether the file reads or declares the name first.

A Go grouped declaration (`var ( a = 1; b = 2 )`) and a multi-target
`var a, b = 1, 2` stay unresolved. One declaration node cannot carry two
independent assignment occurrences without inventing which operand reached which
target.

A C++ declaration carrying the `static` storage class marks its slot
`static: True`. That is what separates a function-local static —

```cpp
Config& get_config() { static Config instance = Config(); return instance; }
```

— from the per-call local with the same syntax minus the specifier. Once the slot
exists the two are indistinguishable downstream, so the fact has to be recorded at
the declaration.

## C++ condition clauses (IR 1.56)

C++ wraps an `if`/`while` condition in a `condition_clause`. It is a pure wrapper
and is now unwrapped like `parenthesized_expression`, so a test written
`if (subject == nullptr)` reaches `NULL_TEST` on the member instead of stopping at
the clause.

## Go `append` and C++ range-for bindings (IR 1.55)

`append` is a free function rather than a method, so
`d.pending = append(d.pending, action)` emitted no `INSERTS_INTO`. The two-argument
free form is recognised now; it is the canonical way to add to a Go slice.

A C++ range-for writes its binding through a `declarator` wrapping a
`reference_declarator`, which the loop-binding lookup did not try. `for (auto
&action : pending)` now yields its loop binding and `ITERATES_CALLS`.

## Closures as callables (IR 1.54)

A Rust closure is a `closure_expression`, which is now treated as a callable like
`lambda`, `arrow_function`, `function_expression` and `func_literal` in the other
languages. Before this the closure body was flattened into the enclosing function:
there was no nested `CALLABLE`, so `CAPTURES` and the returned-wrapper identity
were lost. After it, ``move |value| inner(value)`` yields a nested callable with
`CAPTURES` to the captured parameter and `RETURNS` from the factory, in the same
shape as the other seven languages.

Invoking a captured callable has two recorded shapes and both mean the same thing:

| Shape | Example | Fact |
|---|---|---|
| Direct call | ``inner(value)`` | `CALLEE_VALUE` to the parameter |
| Method on the callable | ``inner.applyAsInt(value)`` (Java functional interface) | `RECEIVER` to the parameter |

A query that needs "the captured callable is invoked" must accept both; neither is
a synonym for the other.

## Nominal member resolution and structural satisfaction (IR 1.53)

`MEMBER_DECLARATION` links a member access to the **field** its receiver's type
declares. It is emitted only when the receiver's recorded type is a single simple
nominal name resolving to exactly one class or interface declaring that member; a
structural, generic or ambiguous receiver yields no fact. Method members are
**not** linked here: the nominal call resolution already separates
`DECLARED_TARGET` (the declared slot), `MAY_TARGET` (several possible concrete
targets) and `TARGET` (exactly one), and collapsing them would present an
ambiguous dispatch as resolved.

Type spellings are normalised before lookup: `&dyn Trait`, `dyn Trait` and
`impl Trait` name the same declaration as `Trait`. That is what lets
``creator.create()`` on a ``&dyn Creator`` parameter reach the trait slot.

Go satisfies an interface by method set rather than by an ``implements`` keyword.
That is `IMPLEMENTS` with `basis='method-set'`, plus an `OVERRIDES` per satisfied
operation, and it is deliberately **not** `SUBTYPE_OF`: the ficha for the affected
variants forbids synthesising a nominal subtype for a structural contract. The
link requires exact coverage of the required operations (name and arity); a type
covering only part of an interface produces no fact. Go's interface method
specifications are declared as `method_elem`, which the frontend now treats as a
method signature like the Java, TypeScript and C# forms.

## C++ constructor resolution (IR 1.52)

In C++ a constructor is a `CALLABLE` named exactly like its class. The nominal
resolver refuses to read a call as a construction when its name matches a local
binding, so that a function shadowing a type name is not mistaken for a type;
that guard was also discarding every C++ constructor, and with it `ALLOCATES_TYPE`
and `RETURNS_NEW`.

The guard now exempts a matching `CALLABLE` marked `constructor`. No other
language names a constructor after its own class, so the change is confined to
C++. It is what lets ``return Builder(name, this->size);`` register the successor
as a new instance of `Builder`.

## C# events (IR 1.51)

An ``event`` is a field-like member with add/remove accessors, not a plain
delegate field. Four relations model it:

| Relation | Meaning |
|---|---|
| `class DECLARES_EVENT storage` | The type declares the event; `name` carries the spelling |
| `callable ADDS_HANDLER storage` | A method registers a handler (`+=`); `handler` carries the operand |
| `callable REMOVES_HANDLER storage` | A method unregisters one (`-=`) |
| `call RAISES_EVENT storage` | The call invokes the event |

A custom accessor (``event_declaration`` with an ``accessor_list``) is **not**
marked and produces no registration fact: its semantics are unknown.

`MEMBER_DECLARATION` links a member access to the field its receiver's type
declares. It is emitted only when the receiver's recorded type is a single simple
nominal name resolving to exactly one class or interface that declares that
member; a structural, generic or ambiguous receiver yields no fact. The relation
is general, not event-specific.

The null-conditional invocation ``receiver?.Member(args)`` is lowered as a member
call: the receiver and the member name come from the
``conditional_access_expression``, so it carries `RECEIVER` like
``receiver.Member(args)``.

## Module exports (IR 1.50)

`EXPORT` links a module to a symbol it exposes: `module EXPORT <callable-or-type>`
with `name` and `basis`. It is what lets a query require a public entry point
without depending on a class or a field. Visibility uses each language's own
rule, never a project convention:

| Language | Rule | `basis` |
|---|---|---|
| JavaScript / TypeScript | enclosing `export function` / `export class` | `explicit-export` |
| JavaScript / TypeScript | `export { a, b }`, `export default a` | `export-clause` |
| Rust | `pub` modifier | `visibility-modifier` |
| Go | leading upper-case letter | `public-name` |
| Python | module-level name without a leading underscore | `public-name` |

Only module-level declarations are considered. `__all__` is **not** interpreted:
a module-level public name stays importable whether or not it is re-listed there.
`EXPORT_SYNTAX` (JS/TS) remains the raw text of the export statement and is a
separate, coarser fact. The module entity itself now carries `IS MODULE`; it is
built outside `entity()`, so it previously had no kind fact.

## Block-scoped locals (IR 1.49)

A local declaration inside a lexical block is a **different binding** from a
same-spelled declaration in an enclosing block. The frontend now allocates a
separate `STORAGE` for the shadowing declaration, keyed by the declaring block:
the entity id carries the block's start byte (`<owner>/STORAGE:name@<byte>`) and
the `block_scope` attribute records the block. `Entity.name` keeps the source
spelling, so consumers that compare by name are unaffected.

Reads resolve to the innermost declaration: a name declared in a nearer block
wins over the callable-level binding, and the inner binding no longer applies
once the read leaves its block. Before this change both declarations collapsed
into one `STORAGE`, so the branch walk merged their write sets and could report
an origin that is not reachable at the read.

This applies to block-scoped declarations only: JS/TS `let`/`const`
(`lexical_declaration`), Java `local_variable_declaration` and C#
`variable_declaration`. JS/TS `var` (`variable_declaration`) is function-scoped,
so two `var` declarations of one name remain a single binding. Python has no
block scope and is unchanged. A callable whose declaration order prevents the
frontend from separating the bindings (a nested declaration processed before the
outer one, when no callable-level binding exists yet) is reported by
`structured-locals/3` as `unsupported` with `reason='shadowed-binding'` instead
of publishing an invented union.

## Argument read-site provenance (IR 1.48)

`ARGUMENT_ORIGIN` links the source CALL to its raw argument operand, with
`position`, `origins` (source value/entity IDs), `unknown`, and `modality`.
It describes the binding value at that call occurrence, not object immutability.
A must origin requires exactly one known value ID across the reaching paths.
Two calls to the same callee are **different values**, even with identical text.
`ARGUMENT_REACHES` links that call to reaching write operations and carries
`position` and `operand` so different argument slots remain distinguishable.
Origin/definition correlation is retained in the `cases` attribute of the origin
fact; these attributes are serializable evidence, not new KenQL syntax.

The query projection uses these read-site origins to connect call RESULT values
to an argument's loaded VALUE. Aliases retain their snapshot's origin; later
writes to the original variable cannot change it. Coarse ASSIGNED_FROM edges
remain may for possible-mode discovery. UNIQUE_BINDING_WRITE never upgrades an
edge by itself: one syntactic write does not prove order or reachability.

Supported calls are standalone, nested calls, and calls in assignment/return
operands within the existing loop-free structured-local analysis in Python,
JavaScript, TypeScript, Java, C#, Go and Rust. Calls are sampled before the
enclosing store or return. Call mapping uses owner and byte span, including file
identity through the owner. Functions without an explicit return can also have
argument evidence. Unmodeled expression regions, indirect writes and existing
unsupported constructs remain conservative; this does not implement arbitrary
callee/receiver resolution, heap preservation, short-circuit evaluation, or
interprocedural effects.

Go and Rust were admitted by measuring their ownership constructs first: Go
multiple assignment (``a, b := f()``), Rust tuple destructuring
(``let (a, b) = f()``), Rust reference writes and ``if let`` all surface as
``unsupported`` instead of invented origins. Rust ``let b = a`` keeps the value's
provenance, which is what a move preserves; no claim is made about ``a`` being
usable afterwards. C++ is not admitted.

## Current capabilities

This table describes IR 1.54.0, checked against the implementation on 2026-09-13.
Preserving syntax, deriving a relationship and proving runtime behavior are
different levels of support.

| Area | Available evidence | Remaining limits |
|---|---|---|
| Types | Structured primitive/container descriptors, generic positions, native spelling, distinct `any` and `unknown` | Annotation/literal models, not complete type inference or runtime API identity |
| Expressions | Operators, ordered operands, simple/compound assignment syntax, comparisons and updates | No general overload resolution or expression-level execution graph |
| Control | Statement CFG for `if/else/elif`, loops, break/continue and explicit returns | Inspect `CFG_STATUS`; exception cleanup, suspension and expression evaluation are outside the structured guarantee |
| Return origins | Sequential locals, conditional joins and returned allocation/field-write states in Python/JS/TS/Java/C# | Inspect `RETURN_FLOW_STATUS`; bounded branch states for field writes, no loop fixed point or general heap analysis |
| Explicit call bindings | Per-call, per-argument bindings to resolved ordinary targets and unique explicit constructors in Python/JS/TS/Java/C# | No expanded arguments, variadic signatures, implicit/inherited constructors or overload selection; inspect binding/constructor status |
| Called expression bindings | CALLEE_VALUE survives parentheses around identifiers, members and indexes in tested grammars | No cast reinterpretation or general runtime callable identity; C# syntax and parser exclusions apply |
| C++ virtual slots | Member prototypes and inline definitions, parameter types, cv/ref qualifiers and bounded virtual override correspondence | Inspect METHOD_SIGNATURE_STATUS; no general template substitution, aliases, out-of-class definition merging or call overload selection |
| Direct field transfers | Linear parameter-to-field assignments and getters in Python/JS/TS/Java/C#/C++; supported C++ constructor list inputs precede body writes | `basis=linear-syntax`; no hidden-effect, deep-copy or heap guarantee; inspect FIELD_FLOW_STATUS and initializer statuses |
| Last binding inputs | Last explicit direct parameter write to a binding in eight grammars; separate from instance member retention | BINDING_FLOW_STATUS; no general aliases, descriptor/setter storage model or implicit initialization |
| Generators and async | Yield/delegation/await syntax and modeled iterator variants | No complete suspension/resumption or asynchronous lifecycle analysis |
| Threads and resources | Import-sensitive Python threading/asyncio API models; native constructs preserved | No race detection, complete lock analysis or general happens-before graph |
| Composed searches | Named `match` dependencies and pattern-owned public operations in TOML | `%… do … %end`, `%map` and `%filter` remain proposals |
| Construction access | Explicit constructor declarations and source access in Java/C#/TS; counts of resolved allocation sites | No runtime uniqueness or complete alias/reflection model; partial/primary/record C# surfaces unsupported |
| Field initial values | Explicit declaration operands and bounded language defaults, with supported/absent/unsupported states | Declaration phase only; no final constructor/heap state or unknown TS emit policy |
| Class values | JS/TS class expressions have occurrence identity and internal lexical names; simple Python/JS/TS base references are distinct from nominal inheritance | No runtime class identity across calls, general constructor aliases or substitution of a supplied base |
| Pattern catalogue | 23 GoF concepts with 44 executable variants; ten modern/web rules | 33 GoF variants remain `design`; a working query does not establish all-language or all-idiom coverage |
| Instruction core | Functions, places, result type descriptors, explicit loads/stores, addresses, calls, structured regions and effects; JSON/text export | Migration adapter; partial/native forms are explicit. Existing KenQL still consumes the fact graph |

See [GoF coverage](gof-coverage.md) and [modern/web patterns](modern-patterns.md)
for tests and external evidence. Prototype now includes a bounded
[field-copy variant](design/structural/field-copy.md) for construction followed
by explicit field assignments and return of the new object.

## Instruction core and algorithm contracts

The [algorithm-first design](design/structural/algorithms-to-ir.md) starts with
Builder, Memento, Observer and Cache-Aside described in words, then derives their
required instructions, identities, effects and invariants. The
[instruction contract](design/structural/instruction-ir.md) separates code from
declaration requirements such as HAS_FIELD.

The [23-GoF algorithm review](design/structural/gof-algorithm-contracts.md) extends
that exercise to every GoF, including implementation variants and properties
that the current queries do not yet establish. Individual reviews and regression
tests distinguish pattern definitions from stronger client/algorithm contracts.

The initial `ken-instructions/1` export is available from source IR:

```sh
ken structural ir --scope src/example.py --view instructions --format text
ken structural ir --scope src/example.py --view instructions --symbol rename
```

`lower_instructions(link_project([...]))` is the Python API. JSON is the
interchange format; `Program.from_dict` verifies its schema and references.
The text renderer is an inspection view, not an accepted input language or VM.

The existing graph search also exposes `operation(role: ...)` in IR 1.47. `role`
is the preserved Tree-sitter field name (or an empty string), not a derived control
dependency. For an if, selecting a direct consequence/alternative child and then
its descendants excludes calls evaluated in the condition. Proxy uses this to
correlate its branch body with the same forwarding call. Source roles vary by
grammar and must not be treated as universal semantic labels.

Each function contains declared parameter places, other encountered places and
an entry region. `slot.declare` records supported explicit declarations without
inventing initialization. `slot.load` creates a distinct value occurrence;
`slot.store` writes a binding. `field.addr`/`index.addr` derive an address from
the receiver value; `memory.load`/`memory.store` access that address. Therefore
`item.name = value` does not become a reassignment of the local binding item.
Calls preserve their callee, receiver where modeled, and positional arguments.
Results carry type descriptors, often unknown; parameter descriptors reuse the
structured type parser, preserving any, unknown and container arguments.

`if` owns separate arm regions; Python elif nests later conditions in the prior
alternative. A supported `while` owns repeated test/body regions; `do` orders
body/test; a C-style `for` owns init/test/body/update. Init runs once; continue
reaches update for a counted for and test for while/do. Missing for conditions
are synthetic true constants; missing init/update remain empty. These forms are
covered in JS/TS/Java/C#/C++; Python while retains its supported subset.

IR 1.47 adds `choose` with one condition and two single-result expression regions.
Only the selected arm executes; its output becomes the choose result. Python
conditional expressions and JS/TS/Java/C# ternaries are tested. `short_circuit`
has one evaluated left operand and a conditional RHS region. It preserves
selected-operand results in Python/JS/TS and boolean results in Java/Go/Rust;
JS/TS nullish coalescing has a distinct test. C++ binary/comparison expressions
remain opaque until native sequencing and operator dispatch are resolved;
overloaded C# logical operators also remain opaque. The adapter must not invent
left-to-right evaluation of side-effecting C++ operands.

`iterate` evaluates its iterable once and contains a repeated body beginning with
`iteration.value`, the element produced on that turn. An explicit slot.store binds
that value; subsequent rebinding remains another store. Python simple for,
JS/TS for-of, Java enhanced-for, C# foreach and Rust for are supported structurally.
The native protocol carries unknown effects; this does not prove termination,
element identity, borrowing or iterator cleanup. JS for-in, for-await, Python
for-else/destructuring and Go range are not silently normalized to this protocol.

Java constructor_body is traversed as statements instead of an opaque implicit
return. C# explicit this receivers preserved only as tokens by Tree-sitter are
retained on supported member loads/stores/calls. Source-level blocks/scopes and
implicit receivers still require fuller binding resolution.

Suspension operations carry suspend/unknown effects. Unsupported constructs become
native instructions with source spans and reasons for a partial function. Chained
comparisons, expanded arguments, unsupported loops/exception bodies and C++ calls
with multiple arguments are examples of current opaque forms.
The adapter does not imply complete block-scope resolution, overload resolution,
argument evaluation semantics, alias analysis or heap effects. `lowered` means
the body used available lowering rules; it is not a proof of runtime behavior.

The structural verifier checks unique definitions, operand/place references,
region visibility, selected opcode signatures and result presence. It checks
choose/short-circuit outputs, loop layouts and iteration-element placement;
branch-local temporaries cannot escape in place of a choose result. It does not
prove type correctness of the source program or runtime reachability. Existing
GoF queries still execute against KenQL's graph view; the new export does not
silently strengthen their claims or change their matching implementation.

`preservation.preserve_binding(function, place, after=..., through=...)` checks
the interval `(after, through]` within one ordered region. It returns preserved,
violated or unknown with witnesses. Strict mode treats unknown effects and
suspension as unknown. `mode="explicit-writes"` only inventories direct binding
writes and declares that weaker basis; it does not prove safety against hidden
effects. Regions/native operations and unsupported interval boundaries remain
unknown. General object/field preservation and the proposed preserve syntax in
KenQL are not implemented yet.

## Normal completion and handler fallthrough

IR 1.46.0 normalizes do_statement as LOOP, including lexical loop context and
continue targets. NORMAL_COMPLETION reports possible, abrupt or unsupported
with basis=statement-normal/1 for supported statement regions in six grammars.
It describes structural normal paths, not feasible runtime execution. Conditions
are not evaluated and calls can still throw or fail to return.

LOOP_BODY_TAIL connects a loop to the last direct statement of its body, before
update/test/exhaustion. HANDLER_FALLTHROUGH connects a handler to its try when
the handler has a supported normal path and the try has no finally, resources
or else. Nested ordinary try/catch and if/else/elif are supported; other control,
suspension and parse errors remain conservative. Exception CFG status stays
partial. Retry adds a handler-fallthrough variant using these public facts;
its existing explicit-continue variant keeps its lexical contract. See
[design and limits](design/structural/normal-completion.md).

## Field declarations and initial values

IR 1.45.0 connects direct class field slots to their real declarator through
FIELD_DECLARATION. Attributes retain `native_type`, initialization mode and syntax
status, plus sorted enclosing `type_parameters`. These parameters are lexical
names used to avoid confusing a generic parameter with a nominal class; they are
not resolved generic arguments or constraints. Locals, member references, method writes, properties and events do not
become field declarators. Java dimensions attached to an individual name belong
to that declarator; `int a[], b` gives a reference default for a and numeric zero
for b.

FIELD_INITIAL_STATUS is supported, absent or unsupported. FIELD_INITIAL_VALUE
carries either the explicit source operand (`basis=explicit-field-initializer`)
or a language default (`basis=language-field-default`), with `phase=declaration`
and a link to the declarator in its attributes. It describes completion of that
declaration, not final state after other initialization, constructor execution,
setters or later method calls. Repeated declarations of the same slot and parse
errors prevent a known initial value. Method writes do not replace the declaration
fact, nor does a historical null assignment imply a null field initializer.

| Language | No explicit initializer |
|---|---|
| Java | Reference types/arrays: NULL; primitive numbers: zero; boolean: false; char: U+0000. |
| C# | Built-in primitive defaults; string/object/dynamic and arrays: NULL. Built-in nullable value types: NULL. Other nominal types require a resolved reference class/interface; unresolved value types/type parameters stay unsupported. |
| JavaScript | Native fields: UNDEFINED, distinct from NULL. |
| TypeScript | Unsupported without a known field emit policy; declare/abstract fields have absent runtime initialization. |
| Python | A bare annotation is absent initialization, not NULL. |

Explicit initializer operands are preserved in these five languages. This pass
does not invent defaults for C++/Go/Rust or uninitialized locals. C# generic type
parameters shadowing a class name cannot inherit that class's reference default.
Implicit primitive defaults are synthetic VALUE entities with `type`,
`literal_value`, `synthetic=true` and `basis=language-field-default`; they have
no assignment operation. NULL and UNDEFINED remain separate literal endpoints.

### Relation contract

| Relation | Subject → object | Attributes |
|---|---|---|
| `FIELD_DECLARATION` | Field storage → real declarator operation | `initialization`: `explicit`, `implicit` or `absent`; `native_type`; `type_parameters`; `syntax_status`: `supported` or `unsupported` |
| `FIELD_INITIAL_STATUS` | Field storage → `supported`, `absent` or `unsupported` | `initialization`; `reason` (empty when supported) |
| `FIELD_INITIAL_VALUE` | Field storage → source operand, `NULL`, `UNDEFINED` or synthetic default value | `basis`; `declaration` (declarator ID); `phase: declaration` |

The mode and status answer different questions. A TypeScript field can have mode
`implicit` but status `unsupported`; a Python annotation has mode and status
`absent`. `unsupported` is never an initialization mode. A field with no
FIELD_DECLARATION fact is outside this pass's declaration model, not automatically
absent or unsupported.

For example, these fragments produce different evidence for the field `value`:

| Source fragment | Mode / status | Initial value |
|---|---|---|
| Java: `class C { static C value; }` | implicit / supported | `NULL` |
| Java: `class C { int value; }` | implicit / supported | Synthetic integer VALUE with `literal_value=0` |
| C#: `class C { Missing value; }` | implicit / unsupported | No value fact; `reason=unresolved-field-default` |
| JavaScript: `class C { value; }` | implicit / supported | `UNDEFINED` |
| TypeScript: `class C { value: C; }` | implicit / unsupported | No value fact; `reason=typescript-field-emit-policy` |
| TypeScript: `class C { declare value: C; }` | absent / absent | No value fact; `reason=no-runtime-initializer` |
| Python class body: `value: int` | absent / absent | No value fact; `reason=no-runtime-initializer` |
| Python class body: `value = None` | explicit / supported | `NULL` |

Here, `supported` means that declaration's operand or default is represented.
It does not mean an explicit initializer was evaluated: `value = make()` points
to a source call operand, not the object returned at runtime. The query view
retains this raw FIELD_INITIAL_VALUE endpoint; use `RESULT` separately when
following a call's query value. For nominal C# defaults, the pass uses the
declared annotation link, not a TYPE inferred from a later assignment.

```kenql
query defaulted_fields {
  require $field FIELD_INITIAL_STATUS supported;
  require $field FIELD_INITIAL_VALUE $value [basis:language-field-default];
  emit $field,$value;
}
```

`singleton.lazy_instance` now uses the supported declaration value instead of
requiring explicit `=null` syntax. Its branch/write/return restrictions remain.

```kenql
query implicit_lazy_initialization {
  match "singleton.lazy_instance"(unit:$unit,storage:$storage,accessor:$accessor,creation:$creation);
  require $storage FIELD_INITIAL_VALUE NULL [basis:language-field-default];
  emit $unit,$storage,$accessor,$creation;
}
```

See [design](design/structural/field-initial-values.md) and
[audit](structural-validation/multilanguage/field-initial-values.md).

## Lazy initialization and negated null tests

IR 1.44.0 extends NULL_TEST to explicitly negated comparisons. `when` is the
condition result that corresponds to the null case; `operator` retains the inner
comparison and `negated` is the parity of up to 32 logical negations. For example,
`!(value != null)` has `when=true`, while `!(value == null)` has `when=false`.
Python `not` follows the same rule. Conjunctions, disjunctions, truthiness and
arithmetic negation are not decomposed into null tests. This is source comparison
evidence, not a proof of overloaded equality behavior; JS loose comparisons also
admit undefined. Original syntax remains available.

```kenql
query negated_null_miss {
  require $branch NULL_TEST $storage [when:true,negated:true];
  emit $branch,$storage;
}
```

The new public `singleton.lazy_instance` operation correlates class, storage,
accessor and creation. In 1.44 it required a static field explicitly assigned NULL in the class body;
1.45 also accepts a supported implicit NULL declaration value. It requires
a supported explicit write inventory with exactly one write to that field inside
the accessor, and structured statement CFG. The CFG starts with the null test:
the non-null arm immediately returns the field and exits; the null arm starts
with a direct assignment constructing that class, immediately followed by a return
of the same field and exit. Assignment and its immediate statement wrapper are
correlated by identity or one SYNTAX_PARENT edge. Structural blocks are normalized
by CFG; arbitrary nested expressions are not accepted as direct writes.

```kenql
query lazy_accessors {
  match "singleton.lazy_instance"(unit:$unit,storage:$storage,accessor:$accessor,creation:$creation);
  emit $unit,$storage,$accessor,$creation;
}
```

The canonical `singleton#lazy-guarded` now delegates to this operation, with tests
in Python/Java/JS/TS/C#. Both branch polarities, separate returns and early non-null
returns are supported. GUARDS_WRITE remains historical syntax evidence and is no
longer sufficient for this variant. RETURN_FLOW_STATUS may be unsupported because
the field write is nonlocal; this query uses direct CFG and RETURN_OPERAND evidence
and does not invent local return origins for shared memory.

Logging between test/write/return, temporary return aliases, extra branches,
double-checked locks and other synchronization forms need additional models.
There is no guarantee of private construction, thread safety, reentrancy, stable
heap storage, descriptors/setters or global uniqueness. Null assignments elsewhere
in a method do not establish the required class-body null initialization.
See [design](design/structural/lazy-null-flow.md) and
[audit](structural-validation/multilanguage/lazy-null-flow.md).

## Construction access and resolved allocation sites

IR 1.43.0 exposes `visibility`, `visibility_basis`, `visibility_status` and
`instance_constructor` on Java/C#/TS member callables. Modifier grammar tokens
supply explicit access; words in annotations, comments and parameter properties
do not. Explicit constructors without an access modifier default to package in
Java, private in C#, and public in TypeScript. Interface members without a modifier
have public access. C# combined access is stored as sorted token text
(`internal protected` or `private protected`), distinct from plain `private`.
A C# static constructor is not an instance constructor.

CONSTRUCTOR_INVENTORY connects each modeled class to supported/unsupported, with
`explicit`, `private` and `other` counts of instance constructor declarations and
`basis=declared-instance-constructors`. TypeScript overload signatures are counted
separately. An implicit constructor does not acquire a synthetic declaration;
`explicit=0` cannot establish private construction. File parse errors, C# partial
classes, primary constructors and records prevent a supported inventory.

```kenql
query private_construction {
  require $unit CONSTRUCTOR_INVENTORY supported [other:0];
  require $unit HAS_METHOD $constructor;
  callable(instance_constructor:true,visibility:private,visibility_status:supported) as $constructor;
  emit $unit,$constructor;
}
```

RESOLVED_ALLOCATION_COUNT records the number of distinct CALL sites already
linked by ALLOCATES_TYPE to a class in the analyzed graph. Its `count` attribute
and string object carry that number, with `basis=explicit-resolved-sites`.
It includes linked sites in other methods, nested classes and files. It does
not close ALLOCATES_TYPE globally: opaque constructor aliases, reflection,
serialization, cloning and excluded source can create instances without a
resolved site. Counts are definition sites, not execution frequencies.

```kenql
query single_resolved_site {
  match "singleton.shared_instance"(unit:$unit,creation:$creation);
  require $unit RESOLVED_ALLOCATION_COUNT _ [count:1];
  emit $unit,$creation;
}
```

The canonical `singleton#eager-shared` now combines the shared-instance operation,
a supported inventory with at least one explicit instance constructor and all
such declarations private, and exactly one resolved allocation site. Java/C#/TS
have tested forms. JavaScript's ordinary publicly constructible class remains
queryable through `singleton.shared_instance`, but no longer satisfies this eager
variant. Explicit calls to the variant now use this stronger contract too.

In IR 1.43, `singleton.shared_instance` and `singleton#lazy-guarded` retained
their prior contracts; the lazy contract is strengthened in IR 1.44 above. The root Singleton query still includes lazy-guarded; it
is not a global uniqueness theorem. TypeScript private is a type-checking
restriction, not a runtime barrier. Storage resets, hidden effects and separate
class loaders remain outside the eager guarantee. See
[design](design/structural/restricted-eager-singleton.md) and
[validation](structural-validation/multilanguage/restricted-eager-singleton.md).

## Class expressions, base values and erased assertions

IR 1.42.0 models JS/TS `class` expressions as CLASS entities, with occurrence-based
IDs even for repeated internal names. Named expressions bind their names only
inside their own class; anonymous expressions keep synthetic names. The syntax
operation points to the class through CLASS_EXPRESSION. DECLARES from the enclosing
scope uses `kind=type-expression` for syntactic ownership, not an outer name binding.
Class fields and methods have their own owner, including private fields and nested
expressions; their returns/yields are not attributed to the enclosing factory.

ASSIGNMENT_VALUE, RETURN_OPERAND and argument values can refer to the class entity.
This represents a definition site, not one runtime class shared across executions,
and it does not assert construction of an instance. General `new Alias()` and
construction from a factory result still require further value-flow models.

BASE_VALUE preserves a simple lexical base reference in Python/JS/TS, with
`name` and `basis=lexical-base-syntax`. A parameter or declared value binding is
not promoted to a nominal type by a same-spelled class outside its scope. BASE_NAME
is retained. SUBTYPE_OF remains a nominal relationship; no subtype edge to an
unresolved parameter is invented. TypeScript implements clauses are not runtime
BASE_VALUE relations. Complex bases, MRO and temporal dead zones are not resolved.

```kenql
query expression_bases {
  require $syntax CLASS_EXPRESSION $class;
  require $class BASE_VALUE $base;
  emit $syntax,$class,$base;
}
```

TypeScript `as`, angle assertions, non-null assertions and `satisfies` preserve
their operand through TYPE_ASSERTION_VALUE, with `basis=typescript-erased-assertion`.
Original syntax remains queryable. The asserted type is not a runtime conversion,
validation or new inferred type of the value. This normalization does not erase
C#/C++/Java casts or change CALLEE_VALUE's rules for asserted callees.

```kenql
query asserted_values {
  require $assertion TYPE_ASSERTION_VALUE $value;
  emit $assertion,$value;
}
```

The modern rule `architecture.subclass-factory` combines a locally defined class,
its supplied base parameter and supported return flow with no explicit parameter
writes. It also handles a concise arrow whose BODY_VALUE is directly the class.
BODY_VALUE is now published for expression-bodied JS/TS arrows as well as the
existing Java/C# lambda projection; each language retains its own return contract.
A class occupying an arrow's body does not receive a callable CFG.

```kenql
query subclass_factory_uses {
  match "architecture.subclass-factory"(factory:$factory,derived:$class,base:$base);
  require $call TARGET $factory;
  emit $factory,$class,$base,$call;
}
```

The rule describes a building block of mixins/class decorators, not their runtime
application, argument forwarding, API compatibility or GoF Decorator intent.
Read [design](design/structural/class-expression-factories.md) and
[validation](structural-validation/multilanguage/class-expression-factories.md).

## Shared class storage and static calls

IR 1.41.0 gives JS/TS private field declarations the same storage identity as
their reads and writes, preserving the `#` spelling. A field creates its own slot
even beside a same-named method or inside a nested class declaration; it does not
reuse a lexical outer field. This does not add general support for class expressions.

For receivers already resolved to a Java/C#/JS/TS class entity, the linker now
selects that class's own static methods. TARGET/CALLS use
`basis=direct-class-static`; multiple declarations remain MAY_TARGET/MAY_CALLS.
No DELEGATES_TYPE is inferred from a class call. In JS/TS, a same-named field blocks
method selection, and getters/setters are excluded from direct invocation targets.

```kenql
query direct_static_invocations {
  require $call TARGET $method [basis:direct-class-static];
  emit $call,$method;
}
```

This does not validate accessibility, select overloads, resolve inherited statics,
track monkey patching or resolve every imported receiver to a class. A getter that
returns a function is not the target implementation of the subsequent invocation.
Existing call-binding status must still be checked before assuming argument mapping.

Singleton gains `eager-shared` and the public operation `singleton.shared_instance`.
It joins a static field declaration initialized with its own class to a static,
zero-argument accessor whose CFG starts at a direct return of that field. It uses
existing assignment operands, allocation, ownership, CFG and return-operand facts;
no Singleton-specific IR relation was introduced.

```kenql
query shared_instance_usage {
  match "singleton.shared_instance"(
    unit:$unit, storage:$storage, accessor:$accessor, creation:$creation
  );
  require $use TARGET $accessor;
  emit $unit,$storage,$accessor,$creation,$use;
}
```

The signature proves class initialization and direct shared-slot access, not a
private constructor, immutable binding, unique lifetime allocation or thread safety.
Resets and shared-default intent remain possible. Branching accessors, aliases,
module singletons, C++ local statics and once primitives need separate models.
See [design](design/structural/eager-singleton.md) and
[validation](structural-validation/multilanguage/eager-singleton.md).

## Parenthesized callee bindings and callable dependencies

IR 1.40.0 preserves CALLEE_VALUE for a called identifier, member or index wrapped
only in parenthesized_expression nodes, including comments inside the parentheses.
The original operations remain in the graph. In Rust, `(self.callback)(value)`
is the callable-field form covered by this change. It also handles nested
parentheses around a parameter or indexed callable in the tested grammars.

```kenql
query called_parameter_bindings {
  require $call CALLEE_VALUE $binding;
  parameter() as $binding;
  emit $call,$binding;
}
```

The projection does not strip casts, pointer/address operators, tuples, sequences,
conditionals or suspension to invent a single binding. INVOKES_RESULT_OF still
describes invocation of another call's result. CALLEE_NAME and receiver/nominal
dispatch are not universally normalized by this change: CALLEE_VALUE preserves
the lexical expression, not a runtime target or a complete callable type proof.

C# parses `(callback)(value)` as a cast when callback is an identifier;
`((callback))(value)` has the tested invocation form. The grammar also currently
parses `(callbacks[0])(value)` as cast/array-type syntax, so that shape remains a
coverage gap; double-parenthesized indexing is tested. Cast nodes are not
reinterpreted as calls. See the [language distinction and parser limit](design/structural/callable-dependency-injection.md#binding-invocado-entre-paréntesis).

`architecture.dependency-injection#callable-input` reuses strategy.supplied_policy
and requires another method to invoke that same field through CALLEE_VALUE.
Its public roles match the existing object variant: unit, dependency, inject and
operation. It covers supplied factories, converters and callbacks without requiring
framework names. The canonical dependency-injection query now combines both forms.

```kenql
query injected_callable_uses {
  match "architecture.dependency-injection#callable-input"(
    unit:$unit, dependency:$callable, inject:$configure, operation:$consumer
  );
  emit $unit,$callable,$configure,$consumer;
}
```

The callable form requires a last supported source write or constructor input;
the object-assignment variant keeps its historical-write contract, including
nonlinear configuration candidates. Do not attribute final retention to that
older variant. Neither proves a DI container, lifetime safety, descriptor storage
behavior or temporal order between configuration and use. Go/Rust returned struct
factory injection and nonlinear callable configuration need further models.
See [design](design/structural/callable-dependency-injection.md) and
[audit](structural-validation/multilanguage/callable-dependency-injection.md).

## Last binding inputs and supplied policies

IR 1.39.0 distinguishes the last explicit source write to a binding from a
retained instance member. This supports locals and class/static storage names,
including Python writes to an attribute with a class descriptor. The descriptor
may reject or transform the value; a source write is not a heap-value identity.

| Relation | Source → destination | Contract |
|---|---|---|
| BINDING_FLOW_STATUS | callable → supported/unsupported | `analysis=linear-bindings/1`, reason; availability of the bounded explicit-write pass. Absence means the pass did not publish a result. |
| FINAL_BINDING_INPUT | assignment operation → explicit parameter | Last direct write to that binding before the first explicit return in a supported linear body; the parameter has no explicit reassignment anywhere in the body. `basis=linear-syntax`, `analysis=linear-bindings/1`. Read its target with ASSIGNMENT_TARGET. |

The pass covers Python, JS, TS, Java, C#, C++, Go and Rust. Targets must be
resolved STORAGE/PARAMETER entities or MEMBER_OF accesses. It does not propagate
arbitrary alias chains. Branches, loops, exception handling, suspension, dynamic
scope and unmodeled indirect writes make the pass unsupported. These restrictions
apply to the writing callable; a separate consumer can still branch or iterate.
Calls and aliases may have hidden effects: supported does not mean pure or safe.
FINAL_MEMBER_INPUT keeps its previous, narrower instance-member contract.
Unlike BINDING_WRITE_STATUS/COUNT (the inventory of explicit writes, including
branches), BINDING_FLOW_STATUS describes this linear last-input pass. Their
availability and language coverage must be checked independently.

```kenql
query last_binding_inputs {
  require $owner HAS_OPERATION $write;
  require $write FINAL_BINDING_INPUT $input [basis:linear-syntax];
  require $write ASSIGNMENT_TARGET $binding;
  emit $owner,$write,$binding,$input;
}
```

Variable declarators without a value in JS/TS/Java/C#, Python annotations without
assignment and Rust let declarations without initializers are DECLARATION
operations, not operand-less ASSIGN operations. Their names/types remain
queryable. Written assignment tokens protect C# initializers whose values have
no grammar field name. This does not model implicit initialization (including
undefined), temporal dead zones or source validity. Explicit initializers remain ASSIGN.

`strategy.supplied_policy` exposes unit, configure, supplied and policy. It
correlates a class field with a parameter of its configuring method, using the
last supported source binding write or a supported CONSTRUCTOR_FIELD_INPUT.
It does not require invocation or algorithm intent by itself.

```kenql
query supplied_policies {
  match "strategy.supplied_policy"(
    unit:$context, configure:$configure, supplied:$input, policy:$policy
  );
  emit $context,$configure,$input,$policy;
}
```

Strategy's object variant adds an invocation of that field from another method,
a slot on its nominal contract through DECLARED_TARGET or TARGET, and two observed
subtypes. Multiple MAY_TARGET implementations do not erase a known declared slot.
The callable variant adds CALLEE_VALUE of the same field from another method.
Neither variant equates arbitrary historical ASSIGNED_FROM with a retained input.
State, Command, Bridge, Decorator and Interpreter can still share these structural
roles. The queries do not establish exclusive intent or temporal order between
configuration and invocation. External-only implementations and nonlinear
configuration remain coverage gaps. See [design](design/structural/strategy-binding-inputs.md)
and [validation](structural-validation/multilanguage/strategy-binding-inputs.md).

## C++ field declarators and qualified types

IR 1.36.0 associates each class/struct field declarator with its storage slot.
Pointer/reference wrappers no longer receive the type instead of the field used
by calls. Fields are declared before method bodies are resolved; declaration order
does not change their identity. Multiple declarators retain separate abstract type
spellings and default initializers. Method declarators are excluded from field
normalization, while callback fields preserve opaque function-pointer spelling
without resolving a fake contract. Inline method definitions have callable entities;
C++ method declarations without a body were missing as callables in 1.36.0;
the [1.37.0 contract below](#c-method-declarations-and-virtual-signatures)
adds those slots and bounded signature correspondence.

`CPP_FIELD_DECL_STATUS` maps the declaration operation to supported, unsupported
or not-storage, with its field count. Supported means the field identities and
spellings were normalized, not that their full types or initial values are known.
`TYPE_HEAD_STATUS` on C++ fields marks whether a simple nominal receiver head was
available. A simple local nominal type with zero/one indirection can produce
TYPE_HEAD; arrays, callbacks, qualified names and multiple indirections do not
silently resolve to a local basename. The linker respects unsupported head status.

`TYPE_REF` retains pointer/reference/array layers. C++ adds qualified layers with
`TYPE_QUALIFIER` const/volatile and distinguishes rvalue_reference from reference.
Native type spelling retains qualifier order, with separator whitespace normalized;
the original syntax/span remains available. A qualifier is source type evidence,
not immutability, pointer validity, ownership or thread-safety evidence.

```kenql
query cpp_const_pointees {
  variable(language:cpp) as $field;
  require $field TYPE_REF $pointer;
  require $pointer TYPE_KIND "pointer";
  require $pointer TYPE_ARGUMENT $pointee [position:0];
  require $pointee TYPE_QUALIFIER "const";
  emit $field,$pointer,$pointee;
}
```

Default field initializers are attached to their individual declarator operation
with basis=field-initializer. Constructor member-initializer lists were outside
1.36.0; the [1.38.0 contract](#c-constructor-initializers-and-retained-command-dispatch)
below models a bounded subset. NOMINAL_ROOT also covers explicit C++ base graphs, using the same bounds
and exclusions. For C++ receivers, Bridge runtime-composition requires distinct resolved roots,
preventing connected decorator hierarchies from posing as independent families.
The earlier runtime-composition behavior in other languages is retained: applying
this root restriction there lost a reviewed Python Bridge with unresolved abc.ABC.
See [design](design/structural/cpp-field-declarators.md) and
[validation](structural-validation/multilanguage/cpp-field-declarators.md).

## C++ method declarations and virtual signatures

IR 1.37.0 gives ordinary class/struct method prototypes callable identities,
HAS_METHOD, OWNED_BY and HAS_PARAMETER facts. This includes pure virtual slots,
multiple declarators, pointer/reference returns and parenthesized method names.
Function-pointer/reference fields remain storage. Overloads keep separate IDs;
no out-of-class definition is merged into a declaration yet.

Callable attributes retain `declaration_only` (no written body),
`explicit_virtual`, `pure_virtual`, `override_specifier`, `final_specifier`,
`cv_qualifiers`, `ref_qualifier` and `native_return_type`. Defaulted/deleted
definitions also have no written body. Anonymous parameters use synthetic names
and do not declare a binding with the type's name. A sole `(void)` means no
parameters; defaults and names do not distinguish override signatures.
TYPE_HEAD/TYPE_HEAD_STATUS also distinguish simple C++ parameter receiver heads
from complex annotations, while native_type/TYPE_REF retain all written layers.
This avoids losing a local nominal receiver merely because its pointer is const,
or treating a double pointer or array as a scalar receiver of its element type.
Pure-specifier `= 0` is declaration syntax, not a runtime assignment. Prototypes
have no synthetic CFG, return origin or member-write body.

The C++ linker now requires compatible parameter signatures and receiver cv/ref
qualifiers, and a resolved ancestor slot whose virtuality is written or inherited.
Static methods and constructors do not participate. Parameter signatures support
modeled primitive types and resolved local nominal types through pointer/reference
and cv layers. Top-level parameter cv is ignored; pointee cv is preserved. Array
parameters adjust to pointers. Unknown types, aliases, function-pointer types,
member templates and destructors do not acquire a signature-based override.

| Relation | Source → destination | Contract |
|---|---|---|
| METHOD_SIGNATURE_STATUS | callable → supported/unsupported | `analysis=cpp-virtual-signatures/1`, with a reason. Describes availability of the bounded comparison, not whether an override exists or the source compiles. |
| VIRTUAL_METHOD | callable → declaring class/struct | Virtual slot established by a written virtual seed and compatible resolved overrides. Not proof that dispatch at any call is virtual or resolved. |
| OVERRIDES | implementation → ancestor slot | C++ uses `basis=cpp-resolved-virtual-signature`; inherited virtuality does not require repeating virtual/override. Other languages retain their previous linking behavior. |

```kenql
query cpp_virtual_implementations {
  require $implementation OVERRIDES $slot [basis:"cpp-resolved-virtual-signature"];
  require $slot METHOD_SIGNATURE_STATUS "supported";
  require $slot VIRTUAL_METHOD $contract;
  emit $implementation,$slot,$contract;
}
```

The relation assumes otherwise valid C++ and does not validate return covariance,
exception specifications, final/deleted restrictions, accessibility or complete
type correctness. An `override` word alone cannot create a missing base relation.
Missing signature evidence is unknown, not proof of non-overriding. The search
engine still exposes ambiguous calls; signatures do not select call overloads.
See [design](design/structural/cpp-method-contracts.md) and
[external audit](structural-validation/multilanguage/cpp-method-contracts.md).

## C++ constructor initializers and retained Command dispatch

IR 1.38.0 preserves each explicit class/struct member-initializer as an INITIALIZE
operation. The member name resolves in the class scope; arguments resolve in the
constructor scope. Thus `receiver(receiver)` links the declared field to its
parameter even when the names coincide or the field is declared after the method.
Base/delegating initializers do not invent instance fields. Overloaded constructors
retain separate initializer occurrences and parameter identities.

| Relation | Source → destination | Contract |
|---|---|---|
| HAS_INITIALIZER | constructor → initializer operation | `basis=cpp-constructor-syntax`; syntax occurrence, not a resolved constructor call. |
| INITIALIZES_FIELD | initializer → declared instance field | Own class fields only; no inherited/base-name guessing. |
| INITIALIZER_FORM | initializer → argument_list/initializer_list | Written parentheses/braces, with a pack-expansion marker. |
| INITIALIZER_ARGUMENT | initializer → raw source operand | Zero-based position and native_kind; separate from normalized call ARGUMENT occurrences. |
| CONSTRUCTOR_INITIALIZER_STATUS | initializer → supported/unsupported | `analysis=cpp-initializers/1` and reason; describes this bounded input model, not complete initialization or valid C++. |
| STORES_VALUE | initializer → supported source value | Single direct same-type parameter for scalar/pointer/reference fields, supported scalar literal, or NULL for explicit null/empty pointer initialization. A class constructor argument is not automatically its stored value. |
| CONSTRUCTOR_INITIALIZER_INPUT | initializer → parameter | Direct compatible written parameter input; final retention after the body requires CONSTRUCTOR_FIELD_INPUT. |

```kenql
query explicit_constructor_inputs {
  require $constructor HAS_INITIALIZER $initialization [basis:"cpp-constructor-syntax"];
  require $initialization INITIALIZES_FIELD $field;
  require $initialization CONSTRUCTOR_INITIALIZER_INPUT $input;
  emit $constructor,$initialization,$field,$input;
}
```

Empty scalar initialization is supported as an independent initializer but does
not synthesize a numeric STORES_VALUE node. Pointer `field()` and `field{}` have
STORES_VALUE NULL on their occurrence; this is not a global INITIALIZED_AS claim
about every instance or constructor. Class defaults remain distinct source facts.

The linear field pass now also handles C++ bodies. Supported initializer inputs
seed its state before body writes; a later field overwrite kills that input.
Reassigned parameters and non-linear/escaped bodies retain the conservative
exclusions of the pass. An unsupported explicit initializer disables final
constructor retention, including bases, delegation, duplicates, packs and unmodeled
conversions. Initializer syntax inputs can still be inspected separately. No CFG
edges impose list order: C++ member initialization uses declaration order.

`command.retained_dispatch` exposes an invoker retaining a nominal input in a
field, then referencing that field from a different method to call a zero-argument
slot. Retention needs FINAL_FIELD_INPUT or CONSTRUCTOR_FIELD_INPUT, not merely
a historical ASSIGNED_FROM. The public operation does not require Command intent:
ordinary injected services can also have this usage shape.

```kenql
query retained_dispatches {
  match "command.retained_dispatch"(
    invoker:$invoker, storage:$field, dispatch:$dispatch, contract:$contract
  );
  emit $invoker,$field,$dispatch,$contract;
}
```

The catalogue's `command#retained-contract` adds a concrete subtype overriding
that slot, a constructor-retained receiver and a discarded receiver call in its
zero-argument action. It supports tested shapes in Python/TS/Java/C#/C++. It does
not prove that a particular runtime dispatch selects that subtype, that callers
configure before invoking, or exclusive intent relative to other patterns.
The previous direct-object/closure variants keep their earlier guarantees.
See [design](design/structural/cpp-constructor-initializers.md) and
[validation](structural-validation/multilanguage/cpp-constructor-initializers.md).

## Refined Bridge and field storage modifiers

IR 1.35.0 corrects C# field storage classification: `static` and `const` modifiers
belong to the enclosing field declaration, including all of its declarators.
`readonly` alone does not make a field static. Modifier words in comments,
attributes or initializer strings do not set this flag. Entity attributes and
HAS_FIELD/DECLARES metadata agree; a local inside a static method remains local.
The version changes to invalidate previously cached field classifications.

The catalogue adds `bridge#refined-composition`. It combines HAS_METHOD,
OVERRIDES, DELEGATES_TO, TYPE and INSTANCE_SLOT facts with the new NOMINAL_ROOT to find an overriding
operation in a refined abstraction that delegates to a nonstatic implementation
field. That implementation contract must differ from the abstraction contract
and have two distinct nominal subtypes. A second abstraction subtype must also
be present; this is a restricted observed-family signature, not every Bridge idiom.
A bounded INSTANCE_SLOT path allows a
local field (zero steps) or a resolved inherited slot (one step).

```kenql
query refined_bridges {
  match "bridge#refined-composition"(
    unit:$refined, abstraction:$base, operation:$operation,
    field:$field, implementation:$implementation
  );
  emit $refined,$base,$operation,$field,$implementation;
}
```

`NOMINAL_ROOT` relates a type to the unique root of its explicitly declared,
resolved base graph, with `basis=explicit-resolved-bases` and
`analysis=explicit-nominal-roots/1`. `NOMINAL_ROOT_STATUS` is supported/unsupported
with a reason. The current pass supports Python/JS/TS/Java/C#/C++ (C++ was added
in 1.36.0). If the graph has parsing diagnostics the pass emits neither roots nor
statuses; otherwise unresolved bases, cycles, multiple roots and paths deeper than
32 types produce an unsupported status. Diamond
paths sharing one root are memoized with the remaining depth budget. No implicit
Object/object base, structural conformance or runtime inheritance is inferred.
Distinct roots separate the two families in this explicit graph; missing roots
are unknown, not independent. A shared marker root can conservatively exclude a
valid Bridge. Configuration consumers can still satisfy the structural signature;
intent requires review.

Local-field fixtures cover Python, TypeScript, Java and C#; inherited-slot fixtures
cover Python and TypeScript. Existing single-inheritance exclusions still apply.
No constructor injection, runtime field value, generated constructor or generic
composition is inferred. See [design](design/structural/patterns/bridge.md) and
[external validation](structural-validation/multilanguage/refined-bridge.md).

## Scoped write counts and null-miss cache flow

IR 1.34.0 adds `BINDING_WRITE_COUNT`: callable → binding, with an integer `count`,
`basis=explicit-writes` and `analysis=binding-writes/1`. It reports source assignment
events within a supported callable inventory. Zero is emitted for used bindings
without an explicit reassignment. Unsupported scopes have no exact count facts.

```kenql
query bindings_written_twice {
  require $owner BINDING_WRITE_COUNT $binding [count: 2];
  emit $owner, $binding;
}
```

Counts include mutually exclusive branches and source statements after return;
they are not dynamic execution counts. They exclude implicit argument binding and
parameter-property initialization. Method scope remains explicit when several
methods write the same field. `BINDING_WRITE_STATUS` describes the inventory's
availability; the absence of a count is not zero.

`architecture.cache-aside#null-miss` now correlates exactly two writes to the
tested binding: lookup initialization and loading in the null arm. Stable key/cache
bindings, bounded CFG paths and RETURN_ORIGIN connect lookup → test → load →
write-back → return. The hit and miss may reach one return with different possible
origins or distinct returns; the query explicitly accepts `modality=may` at joins.
It establishes compatible paths, not one origin that must hold on every execution.

Relevant key/value arguments must be positional, without spread. Extra options
such as a third TTL argument are retained. Java Optional's separate variant keeps
its earlier assignment model; these new guarantees do not apply to its closures.
See [design and examples](design/structural/cache-aside-flow.md) and
[validation](structural-validation/multilanguage/cache-aside-flow.md).

## Presence tests and explicit binding inventories

IR 1.33.0 adds `architecture.read-through-cache` and its public `read_fill`
operation. The operation connects a presence test, a lookup returned on hit,
and a false CFG path through loading, write-back and returning the loaded origin.
The canonical rule additionally requires a cache field constructed by a method of
that class. This is observed local construction, not runtime ownership or a
resolved cache library contract.

```kenql
query cache_read_fill {
  match "architecture.read-through-cache.read_fill"(
    read: $read, cache: $cache, key: $key, load: $load, write: $write
  );
  emit $read, $cache, $key, $load, $write;
}
```

| Relation | Source → destination | Contract |
|---|---|---|
| `TRUTH_TEST` | if statement → tested source operand | Simple call, member or identifier through parentheses and explicit `not`/`!`; `when=true/false`, `basis=condition-syntax`. Does not flatten conjunctions/disjunctions/comparisons or prove truthiness semantics. |
| `UNREASSIGNED_BINDING` | callable → binding | No explicit assignment target for this used binding in the supported callable inventory; `basis=explicit-writes`. Not absence of alias mutation or callee side effects. |
| `UNIQUE_BINDING_WRITE` | assignment operation → binding | Exactly one syntactic write event to this binding in that callable, not proof it executes exactly once or on every path. |
| `BINDING_WRITE_STATUS` | callable → supported/unsupported | Inventory availability with `analysis=binding-writes/1` and reason. Requires structured CFG; excludes loops, indirect/unmodeled writes, nested callables and known dynamic-scope operations. |

```kenql
query stable_presence_inputs {
  require $read HAS_OPERATION $branch;
  require $branch TRUTH_TEST $presence [when: true];
  require $presence RECEIVER $cache;
  require $read UNREASSIGNED_BINDING $cache [basis: explicit-writes];
  emit $read, $presence, $cache;
}
```

The inventory is implemented for Python/JS/TS/Java/C#. It counts source writes
across branches, with operation identity preserving method scope. A member access
may have a VALUE identity while remaining a known assignment target. Diagnostics
suppress derived inventory facts; absent status does not mean supported.

The cache operation requires unchanged key/cache bindings, a uniquely assigned
loaded variable and RETURN_ORIGIN evidence in a supported return-flow scope.
Contains/get accept one written positional argument and put/set two; expanded
arguments are not scalar keys. CFG paths are bounded and existential: this does
not prove every miss fills the cache, atomic contains/get, TTL, invalidation,
single-flight or thread safety. See [design and examples](design/structural/read-through-cache.md)
and [external audit](structural-validation/multilanguage/read-through-cache.md).

## Final configuration writes

IR 1.32.0 makes `builder#mutable-product` require a final direct parameter input,
using `FINAL_MEMBER_INPUT` and the assignment operation's `ASSIGNMENT_TARGET`.
A historical assignment is insufficient: `state = input; state = 0` does not
establish configuration by that input. Explicit parameter reassignment also
suppresses the fact, including reassignment after the member write.

The restricted linear member pass now covers direct instance fields (including
implicit receivers), as well as nested member accesses, in Python/JS/TS/Java/C#,
Rust, C++ and Go. Go statement-list wrappers preserve direct body ordering.
C++ pointer/reference return declarators retain callable names and formal
parameters; this change does not implement complete C++ return-type reconstruction.

```kenql
query final_configuration_inputs {
  require $builder HAS_FIELD $state;
  require $builder HAS_METHOD $step;
  callable(constructor: false) as $step;
  require $step HAS_OPERATION $write;
  require $write FINAL_MEMBER_INPUT $input [basis: linear-syntax];
  require $write ASSIGNMENT_TARGET $state;
  emit $builder, $step, $state, $input, $write;
}
```

Unsupported bodies do not fall back to old assignments in the Builder variant.
The relation does not prove absence of hidden calls/alias effects, later writes
by other methods, or the intent of snapshot creation. Direct-field and nested-member
facts retain the `linear-members/1` contract; IR versioning invalidates older caches.
See [design, examples and limits](design/structural/builder-input-writes.md).

## Stored products and nominal Rust annotations

IR 1.31.0 adds Builder's `stored-product` variant in Python, JavaScript,
TypeScript, Java, C# and Rust. It connects construction of an internal product,
a parameter-driven member write and a distinct finalization method returning
that field or its modeled derived Rust clone. It does not require fluent setters.

```kenql
query stored_builders {
  match "builder#stored-product"(builder: $builder, finish: $finish, product: $product);
  emit $builder, $finish, $product;
}
```

| Relation | Source → destination | Contract |
|---|---|---|
| `TYPE_HEAD` | annotated storage/parameter → nominal spelling | Rust AST root through references, pointers and generic application; `basis=annotation-syntax`. Qualified paths and container components are not collapsed to a basename. |
| `FINAL_MEMBER_INPUT` | assignment operation → explicit parameter | Last direct write to that member before the first explicit return in a supported linear body; the parameter has no explicit reassignment anywhere in the body. `basis=linear-syntax`, `analysis=linear-members/1`. |
| `MEMBER_FLOW_STATUS` | callable → supported/unsupported | Availability of that restricted member pass, with reason. Emitted for candidate callables with member assignments, absent when the graph has diagnostics. Not a claim about all effects in the method. |

`TYPE` can now link `Record<'a>` or `&Record<'a>` to the nominal `Record`
declaration. `TYPE_NAME`, `native_type` and `TYPE_REF` retain the written type,
including lifetime and generic arguments. Bound Rust type parameters suppress
lookup of homonymous global declarations. A nominal link does not assert equal
generic instantiations or identical value/reference semantics.

```kenql
query annotated_products {
  require $parameter TYPE_HEAD "Product" [basis: annotation-syntax];
  require $parameter TYPE $product;
  parameter() as $parameter;
  emit $parameter, $product;
}
```

Rust struct literals now expose `HAS_INITIALIZER`, `FIELD_NAME`, `STORES_VALUE`
and resolved `INITIALIZES_FIELD` for explicit and shorthand fields. Attributed
fields carry `modality=may`, including through comments. Struct updates (`..other`)
are preserved as source syntax; their omitted fields are not synthesized.

`prototype.derived_copy` exposes the existing derive(Clone) model as a public
operation. Bind the receiver and call to avoid combining copies of different
stored objects:

```kenql
query derived_copy_uses {
  match "prototype.derived_copy"(unit: $product, receiver: $receiver, copy: $copy);
  emit $product, $receiver, $copy;
}
```

The member pass rejects branches, loops, exception handling, suspension, nested
callables, known dynamic-scope access, compound writes and unmodeled assignment
events. The facts do not establish hidden-effect purity, alias stability,
initialization order across calls, deep copying or ownership/typestate validity.
See the [complete contract and examples](design/structural/stored-product-builder.md)
and [validation report](structural-validation/multilanguage/stored-product-builder.md).

## Stored work and explicit collection resets

IR 1.30.0 adds Command's `queued-object` variant and the modern
`architecture.batch-work-queue` rule. Both use a public named operation that
connects registration, stored collection, iteration, item activation and reset:

```kenql
query batch_usage {
  match "architecture.batch-work-queue.drain"(
    queue: $queue, item: $item, dispatch: $dispatch, reset: $reset
  );
  emit $queue, $item, $dispatch, $reset;
}
```

`EMPTY_COLLECTION` identifies an empty literal and its category. `CLEARS_COLLECTION`
connects a plain assignment of that literal, or a modeled zero-argument clear/Clear
call, to its target. `+= []` is not a reset. Clear APIs are recognized by shape in
Python/Java/C#; user methods with those names are not certified library operations.
`AFTER_ITERATION` relates reset events to earlier iteration statements in the same
block and callable, excluding intervening direct return/throw/break/continue.
Its `basis=same-block-order` is lexical evidence, not termination or reachability.

The call selector `explicit_arguments` counts written argument occurrences. Zero
excludes spreads even if their runtime expansion might be empty; this is different
from a callable's formal `arity`. It is unavailable when the graph has diagnostics.

The public operation requires an unchanged input parameter to be inserted into
the same field that is iterated, an unchanged item receiver activated with no
explicit arguments, a discarded result (await allowed), and a later reset.
Command additionally correlates a concrete operation through the registration
contract or an observed caller for untyped registration, and a retained receiver.
See the [design and limitations](design/structural/queued-command.md) and
[external audit](structural-validation/multilanguage/queued-command.md).
Neither query proves FIFO, exactly-once execution, atomic draining, successful
completion or exclusivity versus one-shot observers.

## Context-owned state and constructor properties

IR 1.29.0 adds State's `context-transition` variant for Python/JS/TS/Java/C#.
It follows an initially stored state that receives the context, retains it, and
calls the context's state setter from a dispatched action with a new successor.
The same context field must govern dispatch and receive the setter parameter.

Four public relations support this analysis:

| Relation | Source → destination | Contract |
|---|---|---|
| `INSTANCE_RECEIVER` | type → source receiver value | `basis=instance-relative`; observed `this/self` use in an instance callable. Not a runtime object ID. |
| `PARAMETER_INITIALIZES_FIELD` | parameter → field | TypeScript constructor property syntax, preserving two identities and their annotation; `basis=typescript-parameter-property`. |
| `CONSTRUCTOR_FIELD_INPUT` | field → constructor parameter | Final direct parameter input in the restricted linear constructor model, including implicit TypeScript parameter-property initialization and supported explicit C++ member initializers before body assignments; `basis=linear-syntax`. |
| `DECLARED_TARGET` | call → declared method slot | Unique method lookup from the receiver's resolved nominal annotation; `basis=nominal-annotation`. Does not replace `TARGET` or remove `MAY_TARGET`. |

```kenql
query constructor_captured_input {
  require $field CONSTRUCTOR_FIELD_INPUT $parameter [basis: linear-syntax];
  require $constructor HAS_PARAMETER $parameter;
  emit $constructor, $field, $parameter;
}
```

TypeScript `constructor(public context: Context) {}` declares both a parameter
and a field. Plain parameters and modifier-like text in comments/defaults do not.
The IR preserves the implicit initialization without inventing assignment statements
in the source AST/CFG. Explicit overwrites or unsupported bodies suppress the final
constructor input fact while retaining the source property declaration.

A receiver annotated as an interface can also hold a concrete implementation.
`DECLARED_TARGET` exposes the nominal slot while existing possible dispatch targets
remain ambiguous. It does not prove the concrete method that executes. Overloaded
slots do not receive a unique declaration target.

See the [State design and limitations](design/structural/state-context-transitions.md)
and [external audit](structural-validation/multilanguage/state-context-transitions.md).
The initial state assignment is syntactic evidence, not proof that no later write
or hidden effect replaces it before dispatch. State/Strategy and Adapter overlap
remain classification issues requiring review.

## Callsite-correlated bindings and Memento accessors

IR 1.28.0 adds explicit constructor targets and argument bindings. Each binding
belongs to one call and one argument occurrence, even when the operand repeats.
This prevents evidence from different calls from being combined accidentally:

```kenql
query constructor_input {
  require $creation CONSTRUCTOR_TARGET $constructor;
  require $creation CALL_BINDING $binding [mode: direct];
  require $binding BINDING_TARGET $constructor;
  require $binding BINDING_PARAMETER $parameter;
  require $binding BINDING_VALUE $operand;
  emit $creation, $constructor, $parameter, $operand;
}
```

`CALL_BINDING.position` is the source argument position; `HAS_PARAMETER.position`
is the formal parameter position. Named arguments can make them differ.
`BINDING_VALUE` retains a **raw source operand**, unlike the query view's
`ARGUMENT → VALUE` projection. It does not establish general reaching definitions.
Omitted defaults produce no synthetic argument binding. Consult `BINDING_STATUS`
and `CONSTRUCTOR_STATUS`; unsupported or missing evidence is not a compiler error.

`FINAL_FIELD_INPUT`, `FINAL_FIELD_VALUE`, `RETURNS_FIELD` and `CALL_RECEIVER_INPUT`
model direct transfers in restricted linear bodies. They carry
`basis=linear-syntax`, not a purity or heap guarantee. Memento's new
`accessor-snapshot` variant uses them to connect saved state, a snapshot constructor,
its getter and restoration to the original field, including nominal contracts.
See the [complete relation contracts](design/structural/call-bindings.md),
[language variants and limits](design/structural/memento-accessors.md) and
[external audit](structural-validation/multilanguage/memento-accessors.md).

## Queryable types, operators and control

Find parameters annotated as maps with string keys and lists of integers:

```kenql
query integer_lists_by_name {
  parameter() as $parameter;
  require $parameter TYPE_REF $map;
  require $map TYPE_KIND "map";
  require $map TYPE_ARGUMENT $key [position: 0];
  require $key TYPE_KIND "str";
  require $map TYPE_ARGUMENT $list [position: 1];
  require $list TYPE_KIND "list";
  require $list TYPE_ARGUMENT $element [position: 0];
  require $element TYPE_KIND "int";
  emit $parameter;
}
```

These are annotation categories, not a claim that a user-defined `Map` or `list`
implements a standard collection API. Use `TYPE_NATIVE` for exact spelling.
`TYPE_KIND "any"` and `TYPE_KIND "unknown"` remain distinct. The older flat
`type` selector is a compatibility summary and does not preserve all distinctions
of these descriptors, including its historical any/unknown normalization.
An explicit TypeScript `unknown` annotation and an absent annotation can both
have a descriptor of kind unknown. Use the selector's `type_state` and
`native_type`, or the TYPE_REF edge's `basis=annotation-syntax` versus
`basis=missing-annotation`, to distinguish them. `any` is a represented type,
not a wildcard; `*` is the query wildcard. TYPE_BITS is emitted only when the
annotation model knows a width; a missing width is not an assumed machine size.

Inspect a comparison and the operation occurrences that are its operands:

```kenql
query less_or_equal {
  operation(kind: compare) as $comparison;
  require $comparison OPERATOR "<=";
  require $comparison OPERAND $left [position: 0];
  require $comparison OPERAND $right [position: 1];
  emit $comparison, $left, $right;
}
```

Operators can be overloaded; finding `+` does not prove numeric addition.
The serialized operation kind is uppercase (`COMPARE`); KenQL's query view
normalizes selector attributes to lowercase (`operation(kind: compare)`).
For chained comparisons use the operator position as well as operand positions.
Short-circuit flags preserve evaluation policy without proving expression-level
reachability. Assignment operands are not the same as reaching definitions.

Inspect the actual control target of an unlabelled continue:

```kenql
query continue_targets {
  require $jump CFG_NEXT $target [kind: continue];
  emit $jump, $target;
}
```

The target may be a loop test or the update of a C-style for. These are
statement-level structured edges. Check `CFG_STATUS` for unsupported constructs;
even a `structured` CFG excludes exceptions, expression evaluation and suspension.

Use a pattern's public operation without copying its query:

```kenql
query iteration_usage {
  match "iterator.iterate_over"(
    source: $source, item: $item, body: $body, iteration: $iteration
  );
  emit $source, $item, $body, $iteration;
}
```

IR 1.21.0 exposes foreach syntax through `ITERATION_SOURCE`, `ITERATION_BINDING`
and `ITERATION_BODY`. Binding facts carry position and role; Go's first binding
is `first`, not universally an element (range over a map, slice, channel and
iterator function differ). The operation currently uses value bindings, including
Go's second slot. Single-slot Go ranges, destructuring, explicit cursors and callback
pipelines need additional models. JS/TS for-in keys are distinct from for-of values;
the current operation uses values. Python `_` remains a real binding, and C++
reference declarators retain their iteration binding. A same-spelled block-local binding can still be
coalesced by the current frontend; full block-scope resolution remains pending.
Bind iteration and body alongside item when correlating usage.

The operation is stored in `[[operations]]` in Iterator's TOML. It does not add a
new variant to the GoF detector. The proposed percent block syntax and map/filter
operations are described in [pattern operations](design/structural/pattern-operations.md)
and are not implemented yet.

## Collection snapshots and notification

Find calls on elements of a copied collection:

```kenql
query copied_iteration_calls {
  require $iteration ITERATION_SNAPSHOT $copy;
  require $copy COLLECTION_SNAPSHOT_OF $collection;
  require $iteration ITERATION_INVOKES_VALUE $invocation;
  emit $iteration, $copy, $collection, $invocation;
}
```

IR 1.22.0 models unshadowed Python `list(xs)`/`tuple(xs)` and JS/TS
`Array.from(xs)` without a mapper. These API models assume standard builtins;
they do not prove runtime API identity or rule out external monkey-patching.
The copy retains element provenance, not container identity: clearing the source
after copying does not clear the copy. The new Observer `snapshot-registry`
variant uses this relationship and can recognize registration in a callback
passed by a method to another call. Passing a callback does not prove execution.

Local aliases require one simple write before the use in a containing statement
sequence. Multiple writes, non-dominating branches, loop-binding reuse, dynamic
execution and aliases passed to unknown calls or used as method receivers are
excluded. Those exclusions propagate through aliases. This deliberately limited
analysis may miss valid uses; it is not a general heap or loop value-flow analysis.
Element calls must belong to that loop's callable and binding; explicit writes
and reused loop bindings are excluded. Full block-scope resolution, subscription
lifecycle, thread safety and execution reachability remain outside the guarantee.
See the [snapshot contract](design/structural/collection-snapshots.md) and
[RxJS validation](structural-validation/multilanguage/observer-snapshots.md).

## Inherited members and input access paths

IR 1.23.0 adds `EFFECTIVE_METHOD` and `INSTANCE_SLOT` for resolved single
inheritance in Python/JS/TS. Overrides and declared fields that replace methods
hide inherited methods. Static fields, lexically private names and descriptors
are excluded from public slot correspondence. A slot is relative to an instance;
it does not merge all objects of a class. Multiple or unresolved bases remain
unsupported by this projection.

Find member access paths rooted in a parameter, including supported local aliases:

```kenql
query input_member_access {
  require $access ACCESS_INPUT $input;
  parameter(receiver: false) as $input;
  emit $access, $input;
}
```

`ACCESS_INPUT` retains ordered `members` and assignment operation IDs in its
attributes. Aliases require a unique simple write before the use in a containing
statement sequence. Reassigned parameters, ambiguous aliases, loop bindings and
dynamic execution are excluded. This is syntactic provenance: getters, mutations,
concurrency and runtime value equality are not resolved.

The `architecture.dispatch-table#adapted` query joins registration and lookup
through the same instance-relative slot and requires invocation of a resolved
adapter's result. `RETURN_ORIGIN` provides evidence of a possible return of the
input or a wrapper call receiving it. This does not prove preservation on every
branch or by the wrapper API. The [web dispatch contract](design/structural/web-dispatch.md)
and [Flask audit](structural-validation/web-frameworks/flask-adapted-dispatch.md)
describe the exact scope.

Argument lowering now preserves Python indexed expressions instead of replacing
them with their containers. Single-index projections cover the C++ index-list
wrapper, C# argument-list wrapper and Rust's unfielded index grammar. Named and
expanded arguments retain their wrappers' metadata. Multi-index forms remain
in the syntax layer and are not silently reduced to one key. JavaScript field
definitions now expose declarations and assignments, including method shadowing.

## Iteration producers and deferred changes

IR 1.24.0 generalizes the bounded iteration-origin projection beyond copies:
`ITERATION_ORIGIN` links a loop to the call producing its iterable, directly or
through an eligible local alias. Java and C# statement wrappers are supported.
`ITERATION_SNAPSHOT` still requires an explicit collection-copy API model;
an arbitrary producer call is never labelled as a snapshot.

`ITERATION_PASSES_VALUE` links a loop to a call receiving its element, with the
exact positional argument index. The call must belong to the same loop/callable;
explicitly written or reused element bindings and modeled dynamic/ref/out hazards
are excluded. `INSERTED_INPUT` links an insertion to a parameter of its owner
when no explicit binding writes or modeled hazards invalidate that provenance.
These are positive syntax-model facts, not claims of runtime immutability,
reachability, complete alias analysis or hidden-effect freedom.

The declarative `persistence.unit-of-work` rule uses these facts to find keyed
deferred changes followed by at least two persistence API actions on one store.
Its public `persistence.unit-of-work.keyed_flush` operation exposes individual
workers and actions. Transaction atomicity and rollback remain unmodeled.
See [Unit of Work](design/structural/unit-of-work.md) and the
[external audit](structural-validation/multilanguage/unit-of-work.md).

An upper cardinality check such as “exactly one assignment” or “zero writes”
requires coverage sufficient to prove absence. The new rule does not bypass
KenQL's `cardinality:open_world` behavior: its positive relationships are derived
by a constrained IR pass, and its count of persistence actions is a lower bound.

## Discarded call results and command roles

IR 1.25.0 adds `DISCARDS_RESULT`: an expression statement points to the outer
call whose result is discarded. Parentheses are transparent; an await wrapper
sets `awaited=true`. Arguments, assignments, return operands, compound expressions
and Rust block tails are not treated as discarded call results. Unsupported
wrappers do not acquire this relationship by an arbitrary ancestor search.

For example, `require $statement DISCARDS_RESULT $call [awaited: false];` finds
call statements without an intervening await. This is a use of the result,
not proof that the callee has effects or that a returned coroutine executes.

Command's action variant now requires a discarded receiver call or an explicit
return origin linked to a resolved receiver method writing receiver state.
The separate `retained-object` variant admits pure calculations when an invoker
stores a supplied command object and dispatches it from another method.
Neither signature proves runtime ordering or intent; stored query objects and
stateful getters can share those structures. Existing captured-closure commands
remain a separate variant. See [Command design](design/structural/patterns/command.md)
and the [precision audit](structural-validation/multilanguage/command-actions.md).

## Implementation history and semantic limits

IR 1.27.0 connects the return-origin analysis to KenQL's `RETURNS_VALUE` view.
In supported callables, returning a local that currently holds a call result
now points to that call's `RESULT` value. Overwritten origins and statements
after an unconditional return no longer contribute returned query values.

```kenql
query actual_returned_construction {
  require $method RETURNS_VALUE $value [basis: flow];
  require $construction RESULT $value;
  require $construction ALLOCATES_TYPE $type;
  emit $method, $construction, $type;
}
```

These facts retain `analysis`, `modality` and the `return_operation` ID, so
alternative returns carry their own evidence. Possible origins remain `may`;
strict queries do not silently promote them. Returning a parameter through
an alias yields a value `LOADED_FROM` the original parameter. This is not a
general reaching-definition analysis for every argument or storage load.

Callables without a supported return pass retain the earlier syntax projection
with `basis=syntax`, including unsupported control and implicit-return forms.
Use `[basis: flow]` or inspect `RETURN_FLOW_STATUS` when the search needs that
guarantee. Source `RETURNS` facts and assignment/argument projection are unchanged.
The view remains serializable and idempotent. Existing Prototype and Builder
queries benefit from the generic relationship; the matcher has no pattern-specific
return logic. See the [return-value contract](design/structural/returned-values.md).

IR 1.26.0 extends the return pass to simple member writes on local bindings.
These writes do not rebind the local. In bodies containing them, branch states
remain separate so that a returned allocation cannot borrow field evidence
from another branch's object. Last writes replace earlier writes, including
writes through a supported local alias. Returning branches stop contributing
state to subsequent statements.

```kenql
query returned_field_writes {
  require $return RETURN_FIELD_STATE $state;
  require $state FIELD_STATE_ORIGIN $allocation;
  require $state FIELD_STATE_WRITE $write;
  require $write ASSIGNMENT_TARGET $member;
  require $write ASSIGNMENT_VALUE $operand;
  emit $return, $allocation, $write, $member, $operand;
}
```

The intermediate state ID correlates **one return, allocation, field and last
explicit write**. It is a graph node, not an executable operation or a full heap
snapshot. `RETURN_FIELD_STATE` carries the field name and `modality=must` when
that tuple occurs in every modeled state reaching this return, otherwise `may`.
Use `--evidence-mode possible` to include the latter. Neither mode proves branch
feasibility, successful execution, setter behavior or deep/complete copying.

Opaque uses suppress field evidence for that allocation and its aliases: calls,
container publication, storing the object in another object's field, and other
uses outside bare alias assignments, bare returns and supported member-write
receivers. The exclusion is intentionally independent of source order, so even
a harmless or unreachable use can suppress evidence. Return origins may remain
known. Field RHS expressions can stay opaque; a ternary inside such an RHS no
longer rejects the entire method, but is not interpreted as a direct field copy.
Copies through a temporary holding a field value still need another model.

The pass limits branch depth to 32, continuing states to 256 and modeled work to
100,000 units; a limit yields `unsupported` and publishes no partial return/field
facts for that callable. These are analysis budgets, not a process memory limit.
Bodies without member writes retain the less expensive merged local domain.
Their separate `RETURN_REACHES` and `RETURN_ORIGIN` edges do not preserve pair
correlation when joined, unlike the new field-state node.

Python bare class annotations no longer imply initialized static storage. An
explicit class value remains static even if followed by a bare annotation;
explicit `ClassVar[...]` spelling is retained as a class-level hint. This is
syntax classification, without alias resolution for the typing API. Explicit
local declarations in JS/TS/Java/C# and Python assignments now create their own
callable-local bindings instead of resolving to a same-named class field.
Full block scoping and Python global/nonlocal handling remain incomplete.

IR 1.20.0 extends local return origins to structured `if`/`else` and Python
`elif` chains. Joining branches unions possible binding origins; an overwritten
origin disappears when every continuing branch replaces it. Returning branches
do not contribute to the environment after the conditional. Multiple origins
carry `modality=may`; a single origin is `must` conditional on reaching that return.
This is a nonrelational analysis: correlations between different variables and
feasibility of conditions are not proven. Loops still need a value-flow fixed point.

The separate statement-level CFG now represents branches, `while`, `for`, Rust
loop/for/while forms, do-while, `break`, `continue` and explicit returns through
`CFG_ENTRY`, `CFG_EXIT` and `CFG_NEXT` (`kind`: true, false, iterate, exhausted,
break, continue, return, next). A C-style for's continue targets its update;
Python loop break bypasses its else. `CONTROL_CONDITION`, `CONTROL_BODY` and
`CONTROL_ITERABLE` retain syntax anchors. `CFG_STATUS` distinguishes structured
normal control from partial handling; expression evaluation, exceptions and
suspension are excluded, not silently certified. Loops existing in this graph
do not imply that the return-value pass has analyzed their reaching definitions.

Operators are queryable as `OPERATOR` edges with their spelling, position and
short-circuit flag. `OPERAND` edges retain ordered operation occurrences;
normalized kinds include `BINARY`, `UNARY`, `COMPARE`, `ASSIGN` and `UPDATE`.
Chained comparisons retain all operators and operands. These facts preserve
syntax without proving numeric arithmetic, overload resolution or eager evaluation.

Structured type descriptors are linked by `TYPE_REF` and `RETURN_TYPE_REF`.
`TYPE_KIND` separates int, float, char, str, bool, number, any, unknown, never,
void, null, arrays/slices/lists, maps, sets, tuples, unions, optionals and references.
`TYPE_ARGUMENT` preserves generic argument positions; `TYPE_BITS`, `TYPE_SIGNED`,
`TYPE_EXTENT` and `TYPE_RANK` preserve represented distinctions. Descriptor IDs
are structural hashes; `TYPE_NATIVE` retains spelling. Dynamic `any` is distinct
from an unannotated `unknown`; neither is the same as a nominal `object`.

Annotation categories are syntactic, including library spellings such as Map,
String or Optional; they do not establish runtime API identity or defeat local
shadowing. Unmodeled type expressions stay opaque. Literal descriptors use
`basis=literal-syntax`, annotations use `annotation-syntax`, missing annotations
use `missing-annotation`. JavaScript object literals are records, not Map values.
No scalar widths are inferred for implementation-dependent C++ int/double types.

IR 1.19.0 computes local binding origins for explicit returns in supported
sequential Python, JavaScript, TypeScript, Java and C# callable bodies.
`RETURN_ORIGIN` connects a return operation to the operand value captured by
the reaching assignments; `RETURN_REACHES` identifies the final write to the
returned local binding. Alias assignments capture their current origin, so
`y = x; x = null; return y` retains the earlier value of x.

The initial 1.19.0 pass used `sequential-locals/1`. The current
`RETURN_FLOW_STATUS` identifies `analysis=structured-locals/3`, with
`supported` or `unsupported` and a reason. It does not certify the whole IR.
Structured `if/else/elif` statements are supported since 1.20.0. Unsupported
constructs include loops, conditional expressions outside supported field RHSs,
try/cleanup, suspension, nested callables, indirect writes beyond the member-write
model above, compound writes, destructuring, unrecognized nested blocks, unknown
bindings and dynamic execution APIs. C++/Go/Rust need separate semantics and do
not currently receive this analysis. It models local binding origins conditional
on reaching a return, not successful execution, object immutability or a full CFG.

Supported origin summaries replace the flow-insensitive traversal used to derive
`RETURNS_NEW`/`RETURNS_NEW_SELF`; overwritten allocations and returns after an
unconditional return no longer contribute. Other scopes retain the older
structural summaries and their documented imprecision. Consumers needing precise
origins should query the new relations and inspect `RETURN_FLOW_STATUS`.

IR 1.18.0 adds occurrence-level `ASSIGNMENT_TARGET` and `ASSIGNMENT_VALUE` from
assignment operations to their target and RHS operand. `RETURN_OPERAND` connects
explicit nonempty return operations to their operand. Operation IDs preserve
source spans and execution owners; successive writes no longer need to be
reconstructed from method-level `WRITES` facts. C++ `init_declarator` now participates
in assignment lowering, including local variable initialization.

These are syntax operands, not reaching definitions or runtime stored values.
In particular, the RHS of compound assignment is not its computed result;
destructuring targets need further decomposition. Implicit expression-body returns
and bare returns do not acquire `RETURN_OPERAND` in this version. The existing
flow-insensitive `RETURNS_NEW` summary was not corrected in 1.18.0 by these facts alone;
see the [precision review](design/structural/ir-review-2026-09-13.md).

IR 1.17.0 adds Go keyed struct initializer occurrences (`HAS_INITIALIZER`,
`FIELD_NAME`, `STORES_VALUE`, then resolved `INITIALIZES_FIELD`). Map keys and
unresolved construction types do not become struct fields. Unqualified Go nominal
types resolve across files only within the same directory and declared package;
ambiguous external references are left unresolved. This is not full module/import,
build-tag, alias or cross-file receiver-method resolution.

`CAPTURES` records reads of explicitly declared local bindings or parameters from
an enclosing callable. Referenced package/global names are excluded. It does not
claim capture-by-copy, escaping lifetime, immutability, reaching definitions or
complete capture sets (implicit this, nonlocal/global directives and capture lists
need language-specific handling).

IR 1.16.0 links local Go slice element declarations `[]T` and `[]*T` through
`ELEMENT_TYPE`. Qualified types, aliases and fixed arrays need separate handling.
`ITERATED_CALL` identifies the specific call whose receiver is the iterated value;
for Go range this is the second binding, not the first (index/key). The existing
`ITERATES_KEYS_CALLS` remains distinct. Other supported loop grammar families also
emit `ITERATED_CALL` alongside their method-level iteration evidence.

IR 1.15.0 declares Java/C#/C++ `lambda_expression` as a callable with a separate
execution owner. Single inferred, parenthesized and typed Java/C# parameters retain
identity. Lambdas in fields are not class methods. Java/C# expression bodies expose
`BODY_VALUE`, not an unconditional `RETURNS`: the target functional interface or
delegate may be void. Explicit return statements remain owned by the lambda.

The Java Optional model starts only at an unshadowed `Optional.ofNullable` with
an unambiguous explicit `import java.util.Optional`. It emits `OPTIONAL_VALUE`,
`OPTIONAL_OR`, `OPTIONAL_PRESENT` and `OPTIONAL_FALLBACK` for known receiver chains
and single-assignment aliases. It does not model wildcard/static imports, fully
qualified receivers, arbitrary Optional-valued method returns or all classpath
resolution. Declaration collisions in the file conservatively suppress the seed.
The immutable container API does not establish immutability of stored values or
absence of reference mutation through other code.

IR 1.14.0 adds `NULL_TEST` from an if-operation to the compared value, with
`when` (`true` or `false`) and `operator` attributes. Only a binary equality or
inequality against a literal null/None is recognized; compound boolean conditions
are not collapsed to a null test. `BRANCH_TRUE` and `BRANCH_FALSE` identify the
corresponding syntax arms. `SYNTAX_NODE` links a call entity to its exact operation,
including both byte offsets and grammar kind. These relationships support
source-based predicates and do not resolve overloaded equality or runtime reachability.
C# variable initializers without a tree-sitter field name are now recorded after
their explicit '=' token, including comments between '=' and the expression.

IR 1.13.0 exposes lexical operation contexts for structural queries:
`SYNTAX_PARENT` (within the same execution owner), `ENCLOSING_LOOP` (nearest),
`IN_HANDLER` (nearest catch/except), `HANDLER_OF` (handler to its try),
`IN_TRY_BODY` (nearest try's protected body) and `CONTINUE_TARGET` (unlabelled
continue to its nearest loop). These are syntax relationships, not control-flow
reachability or proof that cleanup/finally cannot override an exit. Contexts stop
at callable boundaries. Labelled continue targets are deliberately unresolved.
The projection memoizes parent contexts and accepts operations in arbitrary order.

Ken can analyze live source code without running it, downloading a model, or requiring
an existing vector index. The same engine powers custom searches, the 23 GoF pattern
signatures, bug rules, and summaries of the patterns found in each directory.

```sh
ken structural patterns --path .
ken structural patterns --path . --scope src/factories --pattern factory-method
ken structural bugs --path .
ken structural search --path . --query-file search.kenq
ken structural ir --path . --scope src/factory.py --symbol Factory
ken structural catalog
```

The existing MCP surface exposes these through `ken_find` with `scope="structure"`,
`"patterns"`, or `"bugs"`. For structural searches, `query` is the query language
below. For patterns, it is a comma-separated list of catalogue ids, or an empty
string for all 23. The `path` parameter scopes the scan; `cache_mb=0` disables caching.
The original semantic/text scopes retain their behavior.

## Representation contract

The serialized IR has a schema version, source path, language, entities, operations,
facts, capabilities, and diagnostics. There are two related representations:

* **Ordered operations:** every named tree-sitter node retains its native grammar
  kind, parent, grammar field, byte range, line, execution owner, and unnamed
  operators/modifiers. Normalized kinds include CALL, ASSIGN, YIELD, AWAIT, LOOP,
  BRANCH, IMPORT, EXPORT, MATCH and RESOURCE_SCOPE. Unmodeled syntax stays NATIVE.
* **Evidence graph:** triples connect types, methods, parameters, storage locations,
  calls and values. Facts carry attributes and source locations. Examples include
  HAS_METHOD, HAS_PARAMETER, ARGUMENT, ASSIGNED_FROM, FLOWS_TO, SUBTYPE_OF, CALLS,
  ALLOCATES_TYPE, RETURNS_NEW, DELEGATES_TO, and ITERATES_CALLS.

An identifier's identity includes its source unit and lexical scope. Methods retain
separate identities for overloads. Receiver storage is class-scoped; local storage
is callable-scoped; distinct block-local declarations can still be coalesced.
Lexical names are available for explicit filters, but GoF rules
mostly bind structural roles. A class named `Factory` is not evidence of a factory.

Project linking resolves local declarations and explicit Python/JS/TS named imports,
including aliases and relative modules. A same-spelled class in an unrelated file
does not resolve a reference. Nominal annotations and possible runtime types remain
separate. Ambiguous dispatch produces MAY_TARGET/MAY_CALLS. Linked calls connect
arguments to parameters and returned values to call results; spreads use MAY_BIND_TO.

This is a conservative structural analysis, not a full compiler or a proof system.
It does not implement complete alias analysis, path-sensitive control-flow proofs,
macro expansion, framework dependency injection resolution, or exhaustive runtime
polymorphism. Ordered operations preserve syntax that the semantic pass cannot resolve.

### Serialized source graph and KenQL view

The current serialized fields are `version`, `path`, `language`, `entities`,
`operations`, `facts`, `capabilities`, `diagnostics`, `relations` and `view`.
Entities form an ID-keyed object; each fact has `subject`, `relation`, `object`,
`attrs` and `evidence`. Operations retain their native kind and source byte range.
The proposed `Snapshot` envelope, separate schema/semantics versions and per-fact
dependency records in the design document are not the current serialization.

`ken structural ir --scope src/example.py --view query` exposes the normalized
KenQL view. In the source graph, `ARGUMENT` points directly to its operand and
carries argument metadata. In the query view, it points to an argument occurrence;
`VALUE` connects that occurrence to the supplied value. A storage load has a
`LOADED_FROM` edge to the binding, and a call has a separate `RESULT` value.
Argument position/keyword/spread metadata belong to the argument occurrence's
`ENTITY` fact, not the query view's `ARGUMENT` edge.

This projection preserves compatibility with older queries; it is not SSA.
Historical assignments may contribute `VALUE_FLOW` with `modality=may`.
Since IR 1.27.0, `RETURNS_VALUE` uses captured origins where the return pass is
supported; its `basis` distinguishes that projection from the syntax fallback.
Use occurrence-level assignment facts and the scoped return-origin analysis
when a search needs evidence about overwrites. Graph endpoints also include
literals and descriptor IDs; not every endpoint has an entry in `entities`.

## Compatibility query syntax

The examples in this section use the earlier selector/line-based query formats
retained for compatibility. For the current `query { ... }`, `match` and `emit`
syntax use the examples above and the [KenQL operational guide](structural-queries.md).
In particular, closure shorthand and triple-attribute spelling below describe
the compatibility parser, not the KenQL parser.

Selectors compile into the same indexed joins used by the catalogue:

```text
var_declaration(name: /^user.*/i, type: [str, unknown]) as $user;

method(name: *, return_type: [str, unknown]) as $method {
    has_parameter(pos: 0, type: int) as $position;
    has_parameter(pos: *, type: str, name: /^filter.*$/i) as $filter;
}

require $method READS $user;
```

`method` and `function` select callable entities. `class`, `interface`, `variable`,
`var_declaration`, `parameter`, `call`, `value`, `collection` and generic `entity`
select other entities. `var_declaration` requires a declaration/assignment;
`variable` can also match a referenced storage location. `operation(kind: YIELD)`
queries normalized operations, with `native_kind` available for grammar-specific cases.

`has_parameter` inspects a signature and excludes the implicit Python receiver by
default; explicit parameters start at position 0. Use `receiver: true` to inspect
that receiver. `has_argument` inspects values supplied at a call site. They are
separate because keyword arguments, defaults, destructuring and spreads do not
always have a one-to-one positional binding.

```text
call(name: /^load/) as $call {
    has_argument(pos: 0, type: str) as $path;
}

operation(kind: YIELD, delegated: true) as $delegated_generator;
```

Predicates accept literal values, `*`, alternatives `[str, unknown]`, and regex
literals `/pattern/ims`. `unknown` means unavailable type information; `*` accepts
any value. Primitive type spellings are normalized where the language provides
evidence; JavaScript `number` is not claimed to be Python `int`.

Aliases bind identities. Reusing `$x` means the same entity. Nested relations include
has_method, has_parameter, has_argument, has_call, has_field, reads, writes, calls,
returns and used_by. Arbitrary graph relations remain available as triple clauses.

```text
pattern fluent-construction
require $class IS CLASS
count >=2 $class HAS_METHOD $step distinct=$step where $step WRITES _ and $step RETURNS_SELF $class

pattern product-consumer
require $factory RETURNS_NEW $product
require $call TARGET $factory
require $call FLOWS_TO{1,4} $consumer
```

Graph clauses support:

* `require`: all required constraints must hold; repeated variables form joins.
* `optional`: add evidence and rank candidates, without relaxing required clauses.
* `forbid`: exclude a known fact; missing semantic evidence is unknown unless the
  required completeness capability is available.
* `different $a $b`: require different bound entities.
* `count >=2 … distinct=$role where … and …`: correlated cardinality constraints.
* `variant NAME` / `end`: alternative implementations sharing common constraints.
* `RELATION{2,4}`: bounded paths. `RELATION+` and `RELATION*` both mean a positive,
  bounded closure of 1–16 edges; zero-length identity is deliberately not implicit.
* Triple attributes use `=`, `!=`, `<`, `>`, `<=`, `>=`, and `~=` for shell-style
  glob matching. Selectors use `/…/` for regex. Constant terms can use `A|B`.

Regex patterns are limited to 512 characters and each match has a 10 ms timeout.
No query uses `eval` or executes the analyzed code. Graph searches budget rows,
solver states, elapsed time and result count; relation and endpoint indexes choose
the most selective available join. Bounds and optional evidence are returned in JSON.

## Precision and uncertainty

`complete` describes whether the search exhausted the available graph within its
budgets. It does **not** assert exhaustive understanding of runtime behavior.
`analysis.coverage_complete` reports source parsing/scan coverage; the `skipped`,
`diagnostics` and `resolution` fields explain unsupported files, parse errors and
unresolved calls. These are separate from query completion.

Each match reports bindings, supporting facts, source evidence, its variant, and
missing capabilities. `evidence_score` measures required/optional rule coverage;
it is not a calibrated probability. All GoF detections include an intent caveat.
State/Strategy and Decorator/Proxy/Chain can legitimately overlap structurally.
An empty result is a statement about the extracted graph, not proof that the code
has no bugs or patterns. Directory shares count distinct matching files over parsed
files in that directory; they do not claim every class in the directory is a factory.

For bug-like absence checks, require the capability that would prove absence:

```text
require $call CREATES_CONTEXT $thread
forbid _ WAITS_FOR $thread when_capability=complete_concurrency_flow
```

Ken currently does not advertise complete concurrency flow, so the absence remains
unknown. A fire-and-forget thread may be intentional; a timeout join does not prove
completion. Conversely, a mutable literal default has direct syntactic evidence.

## Language-specific features

The first frontend set covers Python, JavaScript/JSX, TypeScript/TSX, Java, C#, C++,
Go and Rust. Frontends reuse Ken's existing tree-sitter grammars, each with a separate
mutable parser instance. Tests cover common shapes in all eight families. Go/Rust
implementations are not rewritten into inheritance-based languages.

Python positional-only, keyword-only, `*args`, `**kwargs`, defaults, async scopes,
decorators and generator delegation are explicit. JS/TS rest/spread, exports,
async/generators and type parameters remain queryable. Java/C#/C++ parameter and
member relationships, Go receivers/goroutine launches, and Rust impl ownership and
implicit tail returns are modeled. Native syntax remains available for templates,
interfaces, generics, matches, resource scopes and features without a semantic model.

API effects are separate from the neutral graph. Explicit Python `threading` and
`asyncio` imports can identify context creation, entry callable, start, join, lock
acquire/release, and task scheduling. Rebound/shadowed aliases disable those models.
A timed join is MAY_WAITS_FOR, and an unrelated `.start()` is not a thread start.
Other threading libraries, inherited members beyond the bounded projection above, virtual dispatch,
lock-protected shared memory, race detection and framework APIs need more models;
the IR preserves their underlying calls and operations.

## Catalogues and extension

`ken structural catalog` prints each GoF rule's query, category and caveat. The
catalogue includes all 23 GoF names, with one or more structural signatures per name;
it is not a claim to recognize every idiomatic implementation of all 23 patterns.
All 23 canonical GoF concepts have positive, renamed and contrasting negative
fixtures in Python, Java and TypeScript. Additional tests exercise individual
variants and language-specific features; they do not cover all 23 concepts in
every supported language. See the [coverage matrix](gof-coverage.md).

Eight initial bug signatures cover mutable literal defaults, bare except handlers,
empty exception handlers, returns in finally, unreachable statements after a local
terminator, local self-assignment, JavaScript NaN equality, and tuple assertions.
They emit source locations and warnings for review. Closely resembling safe cases
are tested. New signatures can use the public query engine and the existing graph;
new semantics should add tested facts in the language/API layer rather than special
logic inside the matcher. Distribute custom `.kenq` files and use `--query-file`.

## Cache and installation

The disposable SQLite LRU cache lives at `.ken/structural-cache.sqlite`. It stores
compressed per-file IR and linked project graphs. Keys include content hashes,
paths, frontend grammar package versions and the IR implementation/schema version.
Modification timestamps are not trusted; deletion and rename change the manifest.
Any lowering/linking semantic change must bump `IR_VERSION` to invalidate old entries.

The default is **500 MB (500,000,000 bytes)**. Set `.ken/structural.json`:

```json
{"cache": {"enabled": true, "max_mb": 500}}
```

Overrides, in increasing precedence: project config, `KEN_STRUCTURAL_CACHE_MB`,
CLI `--cache-mb` / MCP `cache_mb`. Zero disables cache reads and writes. SQLite page limits
bound the database including indexes; transient transaction journals and process
memory are outside this disk-cache budget. Oversized entries bypass the cache;
unavailable/corrupt caches fall back to analysis. Concurrent processes use SQLite
transactions. Scans honor Git ignores and report file/size limits and path escapes.

The engine is Python and tree-sitter; timed regex uses the `regex` package. It ships
through the existing wheel/sdist build and `uv tool install` flow. A native Rust
backend remains a possible optimization behind this graph/query contract if larger
benchmarks justify it. It would use PyO3/Maturin and prebuilt Linux/macOS wheels;
converting Rust source to C is unnecessary.

Run `uv run python examples/bench/structural.py --files 300` for cold/warm scans,
index construction and dynamic/catalogue query timings. This benchmark validates
result counts before reporting performance. Run `uv run pytest tests/structural`
for the regression suite and `uv run mypy` for the repository typing gate.

References: [GoF publisher catalogue](https://www.informit.com/store/design-patterns-elements-of-reusable-object-oriented-9780321770462),
[PyO3 distribution](https://pyo3.rs/main/building-and-distribution).
