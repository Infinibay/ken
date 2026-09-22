# Review of the catalogue queries: what each claim rests on, and how it breaks

Instead of measuring recall once more, this reviews the 78 variants themselves:
what kind of evidence each query actually uses, and the counterexample each kind
is exposed to. The method is the obvious one -- state the claim, then try to
falsify it against what the query is *written* to accept.

Two parts: a profile of every variant's evidence (mechanical, reproducible), and
counterexamples. Only the counterexamples that are **measured** are marked as
findings; the rest are hypotheses with the variant named, which is what makes
them cheap to turn into tests one at a time.

## Profile

`query_registry` exposes every variant as nodes, so the evidence can be counted
rather than eyeballed. Shares below are over the 84 registered variants (each
appears twice under `gof.<id>#<variant>` and `<id>#<variant>`):

| evidence used | variants | share |
|---|---|---|
| `different` (distinctness of two roles) | 99 | 58% |
| `any{}` union of alternatives | 60 | 35% |
| any data-flow relation (`FLOWS_TO`, `LOADED_FROM`, `RESULT`, ...) | 55 | 32% |
| constructor arity attribute (`callable(constructor:)`) | 46 | 27% |
| `where` on a role or its attribute | 43 | 25% |
| subtype/implementation relation | 40 | 23% |
| bounded `path` | 31 | 18% |
| **resolved** callee (`TARGET`) | 23 | **13%** |
| unresolved callee (`CALLEE_NAME`/`CALLEE_VALUE`) | 20 | 11% |
| container/index facts (`LOOKS_UP`, `WRITES_ELEMENT`, `INDEX`, ...) | 19 | 11% |
| cardinality (`count`) | 17 | 10% |
| protocol identified by an explicit `name` filter | 17 | 10% |
| modality (`MAY_*`, `modality: may`) | 1 | 1% |
| **absence (`not`/`forbid`)** | **0** | **0%** |

Two structural facts stand out.

**No variant claims absence.** Nothing in the catalogue rests on "there is no
other X", which is the failure mode that would be unsound whenever analysis is
incomplete. That is a deliberate-looking property and it holds across all 84.

**102 of 168 entries (61%) use neither a container nor a data-flow relation.**
They claim a pattern from the *shape of calls and types* alone: a method, a call,
a subtype edge, and two roles that differ. That is the class where a
counterexample is cheapest, and the profile says it is the majority of the
catalogue.

## Counterexample 1 (measured): a layered service is reported as a Facade

```python
class OrderService:
    def __init__(self, repository: Repository, mailer: Mailer) -> None:
        self._repository = repository
        self._mailer = mailer

    def place(self, order):
        self._repository.save(order)
        self._mailer.send(order)
        return order
```

```
$ ken structural patterns --path /tmp/counterexample --scope service.py --cache-mb 0 --full
findings: 1
  facade   default   OrderService   service.py:13
```

This is not a Facade by intent; it is the most ordinary class shape in layered
code -- an application service holding two injected collaborators and calling
them. `facade#object-surface` has no way to tell the two apart, and the property
that would distinguish them is not structural: a Facade *hides* a subsystem from
a caller, a service *is* the caller's own layer. The finding carries
`confidence: 1.0`, so the compact payload gives a reader no signal that this is
the weakest kind of evidence in the catalogue.

The same file also contains a two-node expression tree with a shared
`evaluate` shape and an abstract `Repository`/`Mailer` pair; neither was flagged,
so this is not "the engine flags everything" -- it is specifically the
collaborator-orchestration shape that Facade's claim cannot distinguish.

## The failure modes by evidence kind

**Distinctness used as independence (58%).** `different $a $b` proves two
bindings are not the same entity. It never proves the two things are
*independent*, *alternatives*, or *unrelated*. `mediator#direct-colleagues`
requires `different $first $second` and two distinct caller types; a class whose
method delegates to two methods of the *same* collaborator, or to two unrelated
utilities, satisfies it. Already observed in practice: Java's canonical Mediator
collapses both conditional delegations to **one** field, and the variant dies at
precisely this clause while looking satisfiable.

**Protocol identified by callee name (11% unresolved + 10% name filters).**
`adapter#functional-adapter`, `decorator#callable-wrapper`,
`strategy#strategy-callable`, `iterator#callback-iterator` and
`command#stored-closure` match a call by its spelling, so a project that names
its abstraction `apply_fn` instead of `apply` is invisible, and any unrelated
method with the right spelling matches. `flyweight#entry-api`,
`memento#serialized-snapshot` and the iterator cursors go further and filter on
an explicit `name` (`computeIfAbsent`, `/^next$/`), which the `caveat` admits for
`entry-api` but not as a *capability* the result carries.

**Shape without any value evidence (61%).** `strategy#strategy-object`,
`observer#listener-registry`, `proxy#lazy-subject`, `decorator#object-wrapper`
and `state#state-enum` are all satisfied by "a field of an interface type is
called". That is also plain dependency injection -- the same counterexample class
as the measured Facade one, and the reason `strategy` (5/8 recall) and `observer`
(5/8) look good on conceptual corpora while being the most FP-prone on real code.

**Uncertainty is nearly unused (1 of 168).** The engine has modality, `unknown`
and `possible:`, and the caveats say things like "no prueba orden temporal", but
almost nothing in the queries *carries* that into the answer. The prose is
honest and the payload is binary; a caller reading `confidence: 1.0` cannot tell
which claim is the load-bearing one.

## What this suggests, in order

1. **Make the evidence kind visible in the result.** A finding whose only
   support is call shape should not be presented with the same `confidence` as
   one that correlates keys, values and containers. Cheapest useful change: label
   each variant with its evidence class (`shape`, `protocol-by-name`,
   `value-flow`, `container`) and surface it in the compact finding.
2. **Where the claim is about identity, require the resolved target.** `TARGET`
   is used by 13% of variants and `CALLEE_NAME`/`CALLEE_VALUE` by 11%; the second
   should be the documented fallback with its uncertainty attached, not an
   invisible substitution.
3. **Turn each hypothesis above into one negative test.** Every named variant is
   a candidate: write the plain design that satisfies its clauses without the
   intent and assert it is rejected. The catalogue already works this way
   (`test_mediator_message_coordination.py` has five negatives per language); the
   gaps are the variants with no such file.
4. **Keep not claiming absence.** It is the property that makes an incomplete
   analysis safe, and it currently holds everywhere.

## Scope of this review

The profile is mechanical and reproducible from the registry. Counterexample 1 is
measured; the failure modes are argued from the written clauses with the variants
named, and each needs its own test before it is a finding. This is deliberately
not a recall measurement -- `docs/structural-validation/independent-recall.md`
holds that, at 77/169.

## Part 2: the negative corpus (all 78 variants, eight non-patterns)

Reviewing variants one at a time does not scale, so the catalogue is run over a
**negative corpus**: eight ordinary designs that are structurally close to a
pattern but are not one. Every hit is a candidate counterexample, and the whole
catalogue is covered in one measurement. The corpus lives in
`tests/structural/negative_corpus/` and `test_negative_corpus.py` runs it.

Eight files, 78 ready variants, **three hits**:

| hit | design | adjudication |
|---|---|---|
| `state#state-enum` | `Ticket.advance`: `if self.status == "open": self.status = "closed"` | **Working as documented.** Its `query_claim` says it "no exige una clase State ni un objeto por estado", so a guarded field written from several branches is the claimed shape. |
| `observer#listener-registry` | `Emitter.on(fn)` appending to `self.listeners`, `emit` looping over them | **Not adjudicable.** The variant has no `query_claim`, so whether a bare callback registry is the pattern has no answer in the repository. |
| `facade#object-surface` | `OrderService` with two injected collaborators, two calls | **Not adjudicable.** No `query_claim`. This is the ordinary shape of a layered service. |

The corpus ruled out as many hypotheses as it confirmed: the callback wrapper, the
function pipeline, the leaf/node tree, the Protocol-based decorator and the plain
data holder were all rejected by every variant.

## The finding the exercise actually produced

**21 of the 78 ready variants have no written `query_claim`** -- a third of the
catalogue states no claim, so for those the question "does this query make sense?"
cannot be answered from the repository, let alone falsified. The list is pinned in
`CLAIM_DEBT` (test_negative_corpus.py): writing a claim must remove its entry, and
adding a ready variant must state one. It is a ratchet in the same spirit as the
mypy baseline, and it replaces hand-waving about false positives with a countable
debt.

That also corrects this document's Part 1: the evidence profile classified all 84
variants mechanically, but "reviewed every query" would be an overstatement while
21 have nothing written to review.
