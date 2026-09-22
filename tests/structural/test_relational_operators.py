"""Operator extension and diagnostics contracts shared by KQL1/KQL2."""

from types import MappingProxyType

import pytest

from ken.structural.model import IR, Fact, FactIndex
from ken.structural.query import Clause, QueryBudget
from ken.structural.relational import Executor, Node, Query, Row
from ken.structural.relational_operators import OPERATORS, OperatorSpec


def test_new_operator_has_execution_and_barrier_in_one_registration(monkeypatch):
    from ken.structural import relational_operators

    def bind_constant(engine, node, row, output, hint):
        output.append(Row({**row.bindings, "$value": node.value}))

    spec = OperatorSpec(bind_constant)
    monkeypatch.setattr(
        relational_operators,
        "OPERATORS",
        MappingProxyType({**OPERATORS, "constant": spec}),
    )
    # The planner and executor consult the same operator specification.
    index = FactIndex(IR("sample", "python"))
    engine = Executor(index, {})
    nodes = [Node("constant", "extension")]
    assert engine.pool_boundary(nodes, set()) == 0
    result = engine.execute(Query("q", nodes, {"value": "$value"}))
    assert result["complete"]
    assert result["matches"][0]["bindings"] == {"$value": "extension"}


@pytest.mark.parametrize("max_states", [None, 2])
def test_graph_profile_retains_nested_relationships_and_stop_costs(max_states):
    index = FactIndex(IR("sample", "python", facts=[Fact("c", "ENTITY", "CLASS")]))
    fact = Node(
        "fact", Clause(mode="fact", subject="$c", relation="ENTITY", object="CLASS")
    )
    query = Query("q", [Node("any", children=[[fact], [fact]])], {"c": "$c"})
    plain = Executor(index, {}, QueryBudget(max_states=max_states))
    traced = Executor(index, {}, QueryBudget(max_states=max_states), profile=True)
    first, second = plain.execute(query), traced.execute(query)
    for field in ("matches", "complete", "unknown"):
        assert first[field] == second[field]
    assert first["stats"]["states"] == second["stats"]["states"]
    assert traced.profile[0]["operator"] == "any"
    assert traced.profile[0]["parent"] is None
    assert traced.profile[1]["parent"] == 0
    assert all(metric["inclusive_ms"] >= 0 for metric in traced.profile)
    assert traced.profiler.parent is None
    if max_states is None:
        assert len(traced.profile) == 2
        assert traced.profile[1]["calls"] == 2
        assert traced.profile[1]["output_rows"] == 2


def test_unknown_operators_fail_closed():
    engine = Executor(FactIndex(IR("sample", "python")), {})
    with pytest.raises(ValueError, match="unsupported node future"):
        engine.execute(Query("q", [Node("future")], {}))
