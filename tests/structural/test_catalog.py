from __future__ import annotations

import re

import pytest

from ken.structural.catalog import RULES, detect_patterns as _detect_patterns


def detect_patterns(*args, **kwargs):
    """Explicit compatibility tests for the original signature language."""
    return _detect_patterns(*args, **kwargs, legacy=True)
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from .examples import MULTILINGUAL, PYTHON
from .gof_sources import PYTHON as CURRENT_PYTHON


@pytest.mark.parametrize("name", sorted(PYTHON))
@pytest.mark.parametrize("rename", [False, True])
def test_every_gof_pattern_from_python_source(name, rename):
    # legacy=True falls back to the current query after its legacy definition
    # is retired. Use that query's canonical contract in the fallback case;
    # otherwise this accidentally tests a stricter query with a legacy seed.
    rule = next(rule for rule in RULES if rule.id == name)
    source = (PYTHON if rule.legacy_query else CURRENT_PYTHON)[name]
    if rename:
        # Rename all class identifiers and references, including type annotations.
        for i, identifier in enumerate(re.findall(r"class (\w+)", source)):
            source = re.sub(r"\b" + identifier + r"\b", f"Entity{i}", source)
    unit = lower_source(source, "python", "example.py")
    assert not unit.diagnostics
    graph = link_project([unit])
    result = detect_patterns(graph, [name])
    assert result["complete"]
    assert result["findings"], name
    assert all(f["evidence"] and f["caveat"] for f in result["findings"])


@pytest.mark.parametrize("name", [r.id for r in RULES])
def test_class_named_after_pattern_is_not_evidence(name):
    spelling = name.title().replace("-", "")
    graph = link_project([lower_source(f"class {spelling}:\n pass\n", "python", "empty.py")])
    assert detect_patterns(graph, [name])["findings"] == []


@pytest.mark.parametrize("language", sorted(MULTILINGUAL))
def test_fluent_builder_across_grammar_families(language):
    suffix, source = MULTILINGUAL[language]
    unit = lower_source(source, language, "example" + suffix)
    assert not unit.diagnostics
    result = detect_patterns(link_project([unit]), ["builder"])
    assert result["findings"], language


@pytest.mark.parametrize("language", ["javascript", "typescript", "java", "csharp", "cpp"])
def test_factory_method_across_grammar_families(language):
    suffix, source = MULTILINGUAL[language]
    graph = link_project([lower_source(source, language, "example" + suffix)])
    assert detect_patterns(graph, ["factory-method"])["findings"]


def test_catalog_is_exactly_the_23_gof_patterns():
    assert len(RULES) == 23
    assert {r.id for r in RULES} == set(PYTHON)


@pytest.mark.parametrize("mutation", ["return None", "return self.x"])
def test_builder_requires_returning_same_receiver(mutation):
    graph = link_project([lower_source(PYTHON["builder"].replace("return self", mutation), "python", "a.py")])
    assert not detect_patterns(graph, ["builder"])["findings"]


def test_singleton_requires_actual_storage_guard():
    source = PYTHON["singleton"].replace("if cls.value is None:", "if check_permission():")
    graph = link_project([lower_source(source, "python", "a.py")])
    assert not detect_patterns(graph, ["singleton"])["findings"]


def test_observer_requires_iterated_receiver_not_unrelated_call():
    source = PYTHON["observer"].replace("listener.update()", "unrelated.update()")
    graph = link_project([lower_source(source, "python", "a.py")])
    assert not detect_patterns(graph, ["observer"])["findings"]


def test_classic_builder_is_connected_to_its_director():
    source = '''
class Product: pass
class Parts:
    def size(self, value): self.x = value
    def color(self, value): self.y = value
    def finish(self): return Product()
class Coordinator:
    def run(self, parts: Parts):
        parts.size(1)
        parts.color(2)
        return parts.finish()
'''
    graph = link_project([lower_source(source, "python", "construction.py")])
    matches = detect_patterns(graph, ["builder"])["findings"]
    assert any(m["variant"] == "director" for m in matches)
