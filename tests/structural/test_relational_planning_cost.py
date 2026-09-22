"""Join choices account for pushed domains and explain their estimates."""

from ken.structural.model import IR, FactIndex
from ken.structural.query import Clause
from ken.structural.relational import Executor, Node, Query
from ken.structural.relational_planning import choose_next


def scan(subject, relation, object_):
    return Node("fact", Clause("require", subject, relation, object_))


class RestrictedDomain:
    def allows(self, bindings):
        return True

    def domain(self, bindings, role):
        return {"chosen"} if role == "$candidate" else None


def test_pushed_domain_changes_join_order_and_explains_estimate():
    ir = IR("sample", "python")
    for i in range(100):
        ir.add("chosen" if i == 0 else f"noise{i}", "ENTITY", "METHOD")
    ir.add("a", "TARGET", "x")
    ir.add("b", "TARGET", "y")
    engine = Executor(FactIndex(ir), {}, profile=True)
    nodes = [scan("$target", "TARGET", "_"), scan("$candidate", "ENTITY", "METHOD")]
    assert choose_next(engine, nodes, {}) == 0
    assert choose_next(engine, nodes, {}, RestrictedDomain()) == 1
    assert engine.profiler.selection == {
        "reason": "estimated_cardinality",
        "estimated_rows_per_input": 1,
        "alternatives": [
            {"position": 0, "estimated_rows_per_input": 2},
            {"position": 1, "estimated_rows_per_input": 1},
        ],
    }


def test_equal_cardinality_prefers_correlated_join_over_independent_domain():
    ir = IR("sample", "python")
    ir.add("a", "ENTITY", "CLASS")
    ir.add("owner", "HAS_METHOD", "method")
    engine = Executor(FactIndex(ir), {})
    nodes = [
        scan("$unrelated", "ENTITY", "CLASS"),
        scan("$owner", "HAS_METHOD", "$method"),
    ]
    assert choose_next(engine, nodes, {"$owner": "owner"}) == 1


def test_profile_contains_scan_identity_estimate_and_actual_work():
    ir = IR("sample", "python")
    ir.add("a", "ENTITY", "CLASS")
    engine = Executor(FactIndex(ir), {}, profile=True)
    result = engine.execute(
        Query("q", [scan("$class", "ENTITY", "CLASS")], {"class": "$class"})
    )
    assert result["complete"]
    assert result["stats"]["planning_ms"] >= 0
    metric = engine.profile[0]
    assert metric["subject"] == "$class"
    assert metric["selection"]["estimated_rows_per_input"] == 1
    assert metric["rows_examined"] == metric["output_rows"] == 1


def test_empty_required_relation_avoids_body_but_preserves_final_uncertainty(
    monkeypatch,
):
    from types import MappingProxyType

    from ken.structural import relational_operators
    from ken.structural.relational import Row
    from ken.structural.relational_operators import OPERATORS, OperatorSpec

    calls = []

    def uncertain_body(engine, node, row, following, constraints):
        calls.append(node)
        following.append(Row(row.bindings, [], {"source_body:unknown"}))

    monkeypatch.setattr(
        relational_operators,
        "OPERATORS",
        MappingProxyType(
            {
                **OPERATORS,
                "source_body": OperatorSpec(uncertain_body),
            }
        ),
    )
    index = FactIndex(IR("sample", "python"))
    query = Query("q", [Node("source_body"), scan("$method", "WRITES", "$value")], {})
    reference = Executor(index, {}, evidence_mode="possible")
    reference.reference = True
    expected = reference.execute(query)
    assert len(calls) == 1
    calls.clear()
    optimized = Executor(index, {}, evidence_mode="possible", profile=True)
    actual = optimized.execute(query)
    assert not calls
    for field in ("matches", "unknown", "complete"):
        assert actual[field] == expected[field]
    assert optimized.profile[0]["selection"]["reason"] == "empty_relation"


def test_one_empty_alternative_does_not_prune_a_nonempty_union():
    ir = IR("sample", "python")
    ir.add("chosen", "ENTITY", "CLASS")
    query = Query(
        "q",
        [
            Node(
                "any",
                children=[
                    [scan("$class", "ENTITY", "CLASS")],
                    [scan("$class", "WRITES", "_")],
                ],
            )
        ],
        {"class": "$class"},
    )
    actual = Executor(FactIndex(ir), {}).execute(query)
    assert actual["complete"]
    assert actual["matches"][0]["bindings"] == {"$class": "chosen"}


def test_independent_domain_is_delayed_without_losing_union_evidence():
    import json

    ir = IR("sample", "python")
    for i in range(30):
        ir.add(f"factor{i}", "ENTITY", "OPERATION")
    for i in range(40):
        ir.add(f"method{i}", "ENTITY", "METHOD")
    ir.add("method0", "TARGET", "wanted")
    query = Query("q", [
        scan("$factor", "ENTITY", "OPERATION"),
        Node("any", children=[[
            scan("$method", "ENTITY", "METHOD"),
            scan("$method", "TARGET", "wanted"),
        ], [scan("$method", "DECLARES", "absent")]]),
    ], {"factor": "$factor", "method": "$method"})
    reference = Executor(FactIndex(ir), {})
    reference.reference = True
    expected = reference.execute(query)
    actual = Executor(FactIndex(ir), {}).execute(query)

    def normalized(result):
        return sorted((tuple(sorted(m["bindings"].items())),
                       sorted(json.dumps(e, sort_keys=True) for e in m["evidence"]))
                      for m in result["matches"])

    assert expected["complete"] and actual["complete"]
    assert normalized(actual) == normalized(expected)
    assert len(actual["matches"]) == 30
    assert actual["stats"]["states"] < expected["stats"]["states"] / 3


def test_dependent_or_scoped_unions_do_not_move_across_their_domain():
    from ken.structural.relational_planning import source_pruned_plan

    factor = scan("$factor", "ENTITY", "OPERATION")
    unions = [
        Node("any", children=[[scan("$factor", "TARGET", "$method")]]),
        Node("any", children=[[Node("optional", children=[[scan("$method", "TARGET", "x")]])]]),
    ]
    for union in unions:
        nodes = [factor, union]
        assert source_pruned_plan(Executor(FactIndex(IR("", "")), {}), nodes, set()) == nodes


def test_fact_union_can_join_from_the_target_without_losing_alternative_proofs():
    import json

    ir = IR("sample", "python")
    for i in range(100):
        ir.add(f"call{i}", "ENTITY", "CALL")
        ir.add(f"call{i}", "TARGET", "wanted" if i == 3 else "noise")
    ir.add("call3", "DECLARED_TARGET", "wanted")
    ir.add("call5", "DECLARED_TARGET", "wanted", modality="may")
    union = Node("any", children=[
        [scan("$call", "TARGET", "$target")],
        [scan("$call", "DECLARED_TARGET", "$target")],
    ])
    query = Query("q", [scan("$call", "ENTITY", "CALL"), union,
                        scan("$target", "ENTITY", "CALLABLE")],
                  {"call": "$call", "target": "$target"})
    ir.add("wanted", "ENTITY", "CALLABLE")
    reference = Executor(FactIndex(ir), {}, evidence_mode="possible")
    reference.reference = True
    expected = reference.execute(query)
    engine = Executor(FactIndex(ir), {}, evidence_mode="possible", profile=True)
    actual = engine.execute(query)
    def canonical(value):
        if isinstance(value, dict):
            return {k: canonical(v) for k, v in value.items()}
        if isinstance(value, list):
            return sorted((canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
        return value
    def normalized(result):
        return [(m["bindings"], m["status"], m["unknown"],
                 canonical(m["evidence"]))
                for m in result["matches"]]
    assert actual["complete"] and expected["complete"]
    assert normalized(actual) == normalized(expected)
    assert any(m["operator"] == "fact_union" for m in engine.profile)
    assert actual["stats"]["rows_examined"] < expected["stats"]["rows_examined"] / 5


def test_positive_named_relation_uses_caller_bindings_before_expanding_pairs():
    from tests.structural.test_relational_property_joins import comparable

    ir = IR("sample", "python")
    for i in range(60):
        ir.add(f"service{i}", "HAS_METHOD", f"method{i}", evidence=f"proof{i}")
    ir.add("call", "TARGET", "method2")
    ir.add("call", "DECLARED_TARGET", "method3", modality="may")
    dependency = Query("subsystems", [
        scan("$first_service", "HAS_METHOD", "$first"),
        scan("$second_service", "HAS_METHOD", "$second"),
        Node("different", ("$first_service", "$second_service")),
    ], {"first": "$first", "second": "$second"})
    query = Query("q", [
        Node("match", ("subsystems", {"first": "$first", "second": "$second"}, "")),
        scan("call", "TARGET", "$first"),
        scan("call", "DECLARED_TARGET", "$second"),
    ], {"first": "$first", "second": "$second"})
    index = FactIndex(ir)
    for mode in ("possible", "strict"):
        reference = Executor(index, {"subsystems": dependency}, evidence_mode=mode)
        reference.reference = True
        expected = reference.execute(query)
        actual = Executor(index, {"subsystems": dependency}, evidence_mode=mode).execute(query)
        assert comparable(actual) == comparable(expected)
        assert actual["stats"]["rows_examined"] < expected["stats"]["rows_examined"] / 100


def test_named_relation_with_body_or_proof_capture_remains_a_barrier():
    from types import SimpleNamespace

    for proof, child_nodes in [
        ("$proof", [scan("$first", "ENTITY", "CALLABLE")]),
        ("", [Node("source_body", SimpleNamespace(outputs=("first",)))]),
        ("", [Node("count", ("$first", ">=", 1), [[]])]),
    ]:
        child = Query("child", child_nodes, {"first": "$first"})
        match = Node("match", ("child", {"first": "$first"}, proof))
        nodes = [match, scan("call", "TARGET", "$first")]
        engine = Executor(FactIndex(IR("", "")), {"child": child})
        assert engine.source_pruned_plan(nodes, set()) == nodes
