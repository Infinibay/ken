"""Ruby parses into the shared IR the catalog reads.

Ruby has no annotations, so the frontend must publish the facts a dynamic
language can support: ``initialize`` as the constructor, instance variables as
fields, and the call-name linkage of a retained collaborator. These tests fix
that surface before any detector is written for it; they do not claim that a
GoF detector matches yet.
"""
from __future__ import annotations

import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project

from .gof_sources_ruby import RUBY


@pytest.mark.parametrize('name', sorted(RUBY))
def test_ruby_fixture_parses_into_a_clean_ir(name):
    unit = lower_source(RUBY[name], 'ruby', name + '.rb')
    assert not unit.diagnostics, unit.diagnostics
    assert any(entity.kind == 'CALLABLE' for entity in unit.entities.values())


def test_ruby_initialize_is_the_constructor():
    unit = lower_source('class A\n def initialize(x)\n  @x = x\n end\nend\n', 'ruby', 'a.rb')
    callables = {entity.name: entity for entity in unit.entities.values() if entity.kind == 'CALLABLE'}
    assert callables['initialize'].attrs['constructor'] is True


def test_ruby_retained_collaborator_publishes_call_name_and_receiver():
    unit = lower_source(RUBY['strategy'], 'ruby', 'strategy.rb')
    graph = link_project([unit])
    assert not graph.diagnostics
    relations = {fact.relation for fact in graph.facts}
    assert {'HAS_FIELD', 'HAS_CALL', 'RECEIVER', 'CALLEE_NAME'} <= relations
    assert any(fact.relation == 'MEMBER_FLOW_STATUS' for fact in graph.facts)
