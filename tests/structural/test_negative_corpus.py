"""A negative corpus: designs that are *not* the patterns, and what the catalogue says.

Recall tells you what ken misses. This tells you what it claims without warrant.
The corpus is eight small designs that are ordinary code but structurally close to
a pattern (a layered service, a callback wrapper, a leaf/node tree, an event
emitter, an if/elif state machine, a function pipeline, a plain data holder, a
protocol-based decorator). Running all ready variants over them is the cheapest
way to look for counterexamples across the whole catalogue at once instead of one
variant at a time.

Two reviewed shape hits plus one intent-ambiguous Strategy candidate; the
adjudication matters more than the count:

* ``state#state-enum`` **no longer hits**: its KQL 2 contract requires a closed
  two-transition cycle (compare ``$observed`` -> write ``$next``, else compare
  ``$next`` -> write ``$observed``), and ``state_chain.py`` walks three states, so
  the query now refuses a machine it used to accept on a write count.
* ``observer#listener-registry`` and ``facade#object-surface`` **cannot be
  adjudicated from the repository**: neither variant states a ``query_claim``. A
  listener list invoked in a loop, and a service delegating to two injected
  collaborators, are accepted; whether that is the pattern is a question only the
  claim can answer, and there is none.

So this fixture is both a change detector for the current shape-only hits and the
evidence for the second test. The original audit found 21 of 78 ready variants
without a written claim; the explicit debt below shrinks as claims are added.
"""
from __future__ import annotations

from pathlib import Path

from ken.structural import service
from ken.structural.catalog import RULES

CORPUS = Path(__file__).parent / "negative_corpus"

# Known shape-only hits. Fixing a variant or adding a corpus file must update this
# list deliberately -- that is the point of pinning it.
KNOWN_HITS = [("facade", "object-surface", "service.py"),
              ("observer", "listener-registry", "emitter.py")]

# These are neither automatically confirmed Strategy nor automatically detector
# bugs. The revised contract permits one observed implementation. Both designs
# supply and consume a nominal dependency, but the code alone does not establish
# whether its domain role is an interchangeable algorithm. Keep them separate from
# the older reviewed shape hits so a query change cannot silently rewrite labels.
AMBIGUOUS_HITS = {
    ("strategy", "service.py"): "Repository/Mailer dependencies are injected and used; orchestration intent does not establish or exclude Strategy policy selection.",
    ("strategy", "wrapper.py"): "A retained Client is invoked under its contract while a wrapper adds output; Decorator-like intent can coexist with policy substitution, but is not proven.",
}

# Variants that are ready without a written claim. The list is a ratchet: writing a
# claim must remove its entry, and adding a ready variant must state one.
CLAIM_DEBT = {
    "adapter#object-adapter", "bridge#runtime-composition",
    "builder#director", "chain-of-responsibility#linked-handlers", "command#command-object",
    "composite#recursive-contract", "composite#recursive-nominal", "decorator#object-wrapper",
    "facade#object-surface",
    "interpreter#expression-objects", "iterator#delegated-generator",
    "proxy#guarded-access", "state#state-object",
    "strategy#strategy-object", "template-method#virtual-skeleton", "visitor#named-dispatch",
}


def test_the_negative_corpus_keeps_reviewed_and_ambiguous_hits_distinct():
    result = service.patterns(CORPUS, None, path=".", cache_mb=0)
    assert len(result["analysis"]["files"]) == 8
    hits = sorted((finding["id"], finding["variant"], finding["path"]) for finding in result["findings"])
    # ``variant`` is ``default`` for a union root; the catalogue label comes from the
    # evidence, so compare on the pattern and the file only.
    expected_reviewed = {(pattern, path) for pattern, _, path in KNOWN_HITS}
    assert expected_reviewed.isdisjoint(AMBIGUOUS_HITS)
    assert all(reason.strip() for reason in AMBIGUOUS_HITS.values())
    assert [(pattern, path) for pattern, _, path in hits] == sorted(expected_reviewed | AMBIGUOUS_HITS.keys())


def test_every_ready_variant_states_its_claim_up_to_the_recorded_debt():
    missing = {f"{rule.id}#{variant['id']}"
               for rule in RULES for variant in rule.variants
               if variant.get("status") == "ready" and not (variant.get("query_claim") or "").strip()}
    assert missing == CLAIM_DEBT, (
        "a variant gained or lost a claim: write the claim and remove it from CLAIM_DEBT, "
        "or state the claim for a new variant")
    assert len(missing) <= 18


def test_the_corpus_files_are_the_non_patterns_they_claim_to_be():
    """Guard against the fixture drifting into an actual pattern implementation."""
    names = sorted(path.name for path in CORPUS.glob("*.py"))
    assert names == ["callback.py", "dataclass_holder.py", "emitter.py", "pipeline.py",
                     "service.py", "state_chain.py", "tree_node.py", "wrapper.py"]
    for name in names:
        assert (CORPUS / name).read_text(encoding="utf-8").strip(), name
