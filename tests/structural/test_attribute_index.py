"""Exact attribute filters use their own bucket instead of scanning a relation.

``call(name: "computeIfAbsent")`` names one call the way SQL names one row with an
indexed predicate; before the attribute index existed the engine walked every
entity in the project and compared ``name`` per fact. The bucket is a candidate
list, not an intersection, so the answer must not change -- only the work.
"""
from __future__ import annotations

from ken.structural.kenql import Engine, query_graph
from ken.structural.model import FactIndex, IR
from ken.structural.rules import _parsed_query

CALLS = 4000


def graph() -> IR:
    ir = IR("p", "python", capabilities={"syntax"})
    for i in range(CALLS):
        ir.add(f"c{i}", "ENTITY", "CALL", name=f"helper{i}")
        ir.add(f"c{i}", "IS", "CALL")
    ir.add("needle", "ENTITY", "CALL", name="computeIfAbsent")
    ir.add("needle", "IS", "CALL")
    for i in range(40):
        ir.add(f"m{i}", "ENTITY", "CALLABLE", name=f"m{i}", receiver=False)
        ir.add(f"m{i}", "IS", "CALLABLE")
        ir.add(f"m{i}", "HAS_CALL", "needle")
        ir.add(f"m{i}", "HAS_CALL", f"c{i}")
    return ir


def test_the_attribute_bucket_matches_a_full_scan():
    index = FactIndex(graph())
    assert len(index.attr_rows("ENTITY", "name", "computeIfAbsent")) == 1
    assert len(index.attr_rows("ENTITY", "name", "helper7")) == 1
    assert index.attr_rows("ENTITY", "name", "absent") == []
    # Boolean attributes bucket the way the comparison sees them.
    assert len(index.attr_rows("ENTITY", "receiver", "false")) == 40
    assert index.attr_rows("ENTITY", "receiver", "False") == []


def test_a_name_filtered_join_examines_the_bucket_not_the_relation():
    result = Engine(query_graph(graph()), {}, None).execute(
        _parsed_query('query q { require $m HAS_CALL $c; call(name: "computeIfAbsent") as $c; emit $m, $c; }', {}))
    assert len(result["matches"]) == 40
    assert result["stats"]["rows_examined"] < CALLS
