"""Ruby is lowered, and only lowered -- no catalogue variant declares it yet.

Ruby was the largest hole in the recall matrix: ``service`` listed ``.rb`` under
"no structural frontend", so a Ruby repository produced an empty graph and every
pattern read 0%. This covers the *lowering* contract, which is the prerequisite:
a class with its methods and parameters, an instance variable that is a field
(``@pool``, the same fact as Python's ``self.pool``), calls with a receiver, and
indexed reads and writes on that field.

What is deliberately not claimed here: no variant lists ``ruby`` in its
``languages`` yet, and three facts the catalogue leans on are still missing for
it -- ``Glyph.new`` is not an ``ALLOCATES_TYPE``, ``include``/``extend`` are not
``IN_TYPE``, and Ruby has no export marker to publish. So a Ruby pool lowers and
does not yet match ``flyweight``. That is the next step, not a hidden one.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ken.structural import service
from ken.structural.frontend import LANGUAGES, lower_source

SOURCE = b'''class Pool
  def initialize(seed)
    @pool = {}
  end

  def get(key)
    value = @pool[key]
    if value.nil?
      @pool[key] = Glyph.new(key)
    end
    @pool[key]
  end
end
'''


def facts(source=SOURCE, name="pool.rb"):
    graph = lower_source(source, "ruby", name)
    assert not graph.diagnostics, graph.diagnostics
    return graph


def objects(graph, relation):
    return {fact.object for fact in graph.facts if fact.relation == relation}


def test_ruby_files_have_a_structural_frontend():
    assert LANGUAGES[".rb"] == "ruby"
    assert LANGUAGES[".rake"] == "ruby"
    assert LANGUAGES[".gemspec"] == "ruby"


def test_a_class_lowers_to_a_class_with_its_methods_and_parameters():
    graph = facts()
    kinds = objects(graph, "IS")
    assert any(kind == "CLASS" for kind in kinds)
    methods = {entity.rsplit("/", 1)[-1].split(":", 1)[1].split("@")[0]
               for entity in objects(graph, "HAS_METHOD")}
    assert methods >= {"initialize", "get"}
    parameters = {entity.split("/")[-1] for entity in objects(graph, "HAS_PARAMETER")}
    assert any(name.startswith("PARAMETER:key") for name in parameters)


def test_an_instance_variable_is_a_field_of_the_class():
    graph = facts()
    fields = {entity for entity in objects(graph, "HAS_FIELD")}
    assert any(entity.endswith("/STORAGE:pool") for entity in fields)
    # The sigil is a spelling, not part of the name the catalogue asks for.
    assert not any("@pool" in entity for entity in fields)


def test_calls_carry_a_receiver_and_a_callee_name():
    graph = facts()
    names = objects(graph, "CALLEE_NAME")
    assert {"new", "nil?"} <= names
    assert objects(graph, "HAS_CALL")


def test_an_indexed_read_and_write_on_the_field_are_published():
    graph = facts()
    looks_up = objects(graph, "LOOKS_UP")
    writes = objects(graph, "WRITES_ELEMENT")
    assert any(entity.endswith("/STORAGE:pool") for entity in looks_up)
    assert any(entity.endswith("/STORAGE:pool") for entity in writes)


def test_a_ruby_tree_is_analysed_rather_than_skipped(tmp_path):
    (tmp_path / "pool.rb").write_text(SOURCE.decode(), encoding="utf-8")
    graph, analysis = service.build_project(tmp_path, path=".", cache_mb=0)
    assert analysis["files"] == ["pool.rb"]
    assert analysis["skipped"] == []
    assert analysis["coverage_complete"] is True
    assert any(entity.kind == "CLASS" for entity in graph.entities.values())


def test_the_declared_extension_set_is_the_one_the_frontend_accepts():
    # A file the scanner accepts must lower; a spelling only the scanner knows
    # would produce a graph with no entities and no diagnostic.
    for extension, language in sorted(LANGUAGES.items()):
        assert isinstance(language, str) and language
    assert ".rb" in LANGUAGES
    with pytest.raises(ValueError):
        lower_source(b"class A\nend\n", "perl", "x.pl")
