# Independent recall baseline

The catalogue's claims are only worth what an *external* corpus says about them.
This is the measurement the campaign is steered by: the ground truth is the
repository layout, never ken's own output.

## Method

Each corpus is a canonical pattern collection whose directories are named after
the pattern they implement (RefactoringGuru's `design-patterns-<language>`
repositories, `faif/python-patterns`, and `iluwatar/java-design-patterns` for the
full-tree runs). For every corpus:

1. `ken structural patterns --path <repo> --scope <src> --full` writes every
   finding with `id`, `variant`, `path` and `line`.
2. A pattern is *present* in a corpus when a file's path component names it
   (`normalize(part) in GoF`, so `AbstractFactory.Conceptual/`, `abstract_factory/`
   and `abstract-factory/` all count).
3. A pattern is *detected in its own directory* when at least one finding has
   `id` equal to that pattern **and** a `path` inside that pattern's directory.
4. Recall is (patterns detected in their own directory) / (patterns present).

Detection elsewhere (client code, demos, another pattern's directory) is counted
in the total findings but **not** as recall: a `facade` finding inside the
`ChainOfResponsibility` directory is not evidence that Facade is recognised.

Reproduce with `/tmp/patterns/eval_matrix.py` over the JSON dumps; the corpora
are the eight clones listed above. Findings are compared as the set of
`(pattern, variant, path, line)` tuples -- two spellings of the same detection are
one detection, which is why a "44 findings / 38 distinct" pair is not a change.

## Baseline (IR 1.76, release 0.16.0)

| corpus | language | detected / present | not detected |
|---|---|---|---|
| RefactoringGuru python | python | 13/22 | builder, command, decorator, iterator, memento, prototype, proxy, singleton, state |
| RefactoringGuru typescript | typescript | 17/22 | builder, composite, iterator, prototype, singleton |
| RefactoringGuru java | java | 10/20 | command, decorator, facade, iterator, mediator, memento, observer, prototype, state, strategy |
| RefactoringGuru cpp | cpp | 8/22 | bridge, builder, chain-of-responsibility, command, decorator, flyweight, iterator, memento, observer, prototype, proxy, singleton, state, strategy |
| RefactoringGuru csharp | csharp | 15/22 | builder, decorator, flyweight, iterator, memento, proxy, state |
| RefactoringGuru go | go | 5/21 | adapter, bridge, builder, chain-of-responsibility, command, composite, decorator, factory-method, flyweight, iterator, mediator, memento, prototype, proxy, state, strategy |
| RefactoringGuru rust | rust | 3/22 | abstract-factory, adapter, bridge, builder, chain-of-responsibility, command, composite, decorator, facade, factory-method, flyweight, iterator, mediator, memento, observer, proxy, singleton, state, visitor |
| faif python-patterns | python | 6/18 | adapter, bridge, builder, command, decorator, factory-method, flyweight, mediator, memento, prototype, proxy, visitor |
| **total** | | **77/169 (46%)** | |

Per pattern, over the corpora that implement it:

| pattern | detected | pattern | detected |
|---|---|---|---|
| template-method | 5/5 | prototype | 2/8 |
| interpreter | 1/1 | proxy | 2/8 |
| facade | 6/8 | state | 2/8 |
| visitor | 6/8 | command | 2/8 |
| abstract-factory | 5/6 | builder | 1/8 |
| adapter | 5/8 | decorator | 1/8 |
| composite | 5/8 | iterator | 1/8 |
| factory-method | 5/8 | memento | 1/8 |
| observer | 5/8 | flyweight | 3/8 |
| strategy | 5/8 | mediator | 4/8 |
| bridge | 4/8 | singleton | 3/7 |
| chain-of-responsibility | 3/6 | | |

## What the number does not say

* It is not precision. A finding outside the pattern's own directory may be a
  true positive in client code or a false positive; this table only asks whether
  the pattern is recognised where the corpus author put it.
* It is not per-variant coverage. A pattern counts once per corpus even when four
  variants could have matched.
* The corpora are *conceptual* examples, usually one small file per pattern. A
  query can be correct and still miss a 30-line demo that has no second method.
  The number is a floor for real code, not an estimate of it.

## Known gaps, in payoff order

1. **`decorator` (1/8)** -- the canonical object decorator passes eight clauses of
   `object-wrapper` and dies at the added-behaviour clause: C# adds behaviour with
   an interpolated string, not a second call. The alternative that accepts "the
   returned value flows to the forwarded call" matches in isolation but neither
   under the variant's full prefix nor without firing on interpreter/proxy classes
   in Java. The prefix, not the clause, is what needs bisecting.
2. **Ruby** has a frontend (IR 1.75) and no variant declares it. Missing facts:
   `Glyph.new` is not an `ALLOCATES_TYPE`, `include`/`extend` is not an `IN_TYPE`,
   and there is no export marker to publish.
3. **`flyweight` (3/8)** -- python/typescript/java match; C++ now publishes
   `find` + `insert(make_pair(...))` (IR 1.76) but no variant covers that shape;
   C# uses a list of tuples with LINQ; Go uses comma-ok maps.
4. **Kotlin** -- the parser works and the grammar exposes *no fields*, so it needs
   a positional adapter, not table entries.
5. **C** -- the grammar has not been extracted in this environment
   (`libtree_sitter_c.dylib`), so the language is still unwired.
6. **`iterator` (1/8), `memento` (1/8), `builder` (1/8)** -- each dies at a
   different clause per language; no shared cause was found, so each is separate
   work.
