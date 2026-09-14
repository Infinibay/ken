"""Mediator ``tag-dispatch``: the centre branches on the tag it was handed.

The sibling variant ``message-coordination`` requires the tag to be *forwarded*
as an argument of each delegated call, and its ``no-tag-argument`` negative pins
exactly that. The canonical RefactoringGuru example does the opposite -- it
*branches* on the tag and the delegated calls take no arguments::

    def notify(self, sender, event):
        if event == "A":
            self._component2.do_c()
        elif event == "D":
            self._component1.do_b()

so the same fixture that is a negative for the sibling is the positive here. The
fixtures are shared with that module on purpose: the two variants partition the
shape, and a change that moves one into the other should fail a test on both
sides.
"""
from __future__ import annotations

import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

from .test_mediator_message_coordination import EXTENSIONS, LANGUAGES, NAMES, RENAMED, source

RULE = "mediator#tag-dispatch"
ROOT = "mediator"
# Modes of the shared fixture that must NOT be read as a tag dispatch.
NEGATIVES = ["no-branch", "same-target", "no-self", "one-colleague"]


def detect(language, text):
    graph = link_project([lower_source(text, language, f"mediator.{EXTENSIONS[language]}")])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry, evidence_mode="strict")
    assert result["complete"], result["outcomes"]
    return result["matches"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_branch_that_tests_the_tag_is_detected(language):
    """``no-tag-argument`` is the sibling's negative and this variant's positive."""
    matches = detect(language, source(language, "no-tag-argument"))
    assert matches, language
    # The registry projects the roles every ready variant shares, so the centre
    # arrives as ``$unit`` even though this query names it ``$coordinator``.
    assert "/CLASS:" in matches[0]["bindings"]["$unit"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_renaming_the_centre_and_its_colleagues_preserves_detection(language):
    assert detect(language, source(language, "no-tag-argument", names=RENAMED)), language


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("mode", NEGATIVES)
def test_the_shape_without_a_tag_dispatched_branch_is_rejected(language, mode):
    assert not detect(language, source(language, mode)), f"{language}/{mode}"


def test_the_variant_is_registered_and_its_sibling_keeps_its_own_negative():
    rule = next(r for r in _load_catalog() if r.id == ROOT)
    ids = {v["id"]: v for v in rule.variants}
    assert ids["tag-dispatch"]["status"] == "ready"
    assert "tag-dispatch" in rule.query
    # The sibling must not have absorbed the tag-dispatch shape: its own negative
    # fixture is the positive of this variant.
    sibling = ids["message-coordination"]["query"]
    assert "PARAMETER_TEST" not in sibling
    assert "PARAMETER_TEST" in ids["tag-dispatch"]["query"]
