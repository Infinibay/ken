"""Contracts between extensible operators, proof storage and result projection."""

from types import MappingProxyType

import pytest

from ken.structural.model import Fact, FactIndex, IR
from ken.structural.query import Clause
from ken.structural.relational import Executor, Node, Query, Row
from ken.structural.relational_evidence import FactEvidence
from ken.structural.relational_operators import OPERATORS, OperatorSpec
from ken.structural.relational_results import project_rows
from ken.structural_store import Store
from ken.structural_store.graph_index import GraphIndex
from ken.structural_store.graph_projection import publish


@pytest.mark.parametrize("preserves_closure", [False, True])
def test_extension_must_declare_closure_before_absence_is_a_proof(monkeypatch, preserves_closure):
    from ken.structural import relational_operators

    def empty(engine, node, row, output, constraint):
        pass

    spec = OperatorSpec(empty, preserves_closure=preserves_closure)
    monkeypatch.setattr(relational_operators, "OPERATORS",
                        MappingProxyType({**OPERATORS, "extension": spec}))
    index = FactIndex(IR("sample", "python", facts=[Fact("owner", "ENTITY", "CLASS")]))
    query = Query("q", [
        Node("fact", Clause("require", "$owner", "ENTITY", "CLASS")),
        Node("not", ("extension", "$owner"), [[Node("extension")]]),
    ], {"owner": "$owner"})
    result = Executor(index, {}, evidence_mode="possible").execute(query)
    match, = result["matches"]
    assert match["unknown"] == ([] if preserves_closure else ["absence:extension:owner"])
    assert match["status"] == ("structural_match" if preserves_closure else "unknown")


def test_fact_proofs_use_the_storage_comparison_contract():
    class ExternalFact(Fact):
        comparisons = 0

        def same_evidence(self, other):
            self.comparisons += 1
            return self.evidence == other.evidence

    a = ExternalFact("a", "R", "b", evidence=["proof"])
    b = Fact("a", "R", "b", evidence=["proof"])
    assert FactEvidence(a) == FactEvidence(b)
    assert a.comparisons == 1
    assert FactEvidence(b) == FactEvidence(a)


def test_native_evidence_identity_respects_mutated_decoded_values():
    ir = IR("sample", "python", view="query",
            facts=[Fact("a", "R", "b", evidence=["proof"])])
    with Store(cache_mb=0) as store:
        snapshot = store.publish([], expected_parent=store.current, profile="interfaces")
        index = GraphIndex(store, publish(store, snapshot, "interfaces", ir))
        a, b = index.rows("R")[0], index.rows("R")[0]
        assert a.same_evidence(b)
        a.evidence.append("local edit")
        assert not a.same_evidence(b)
        assert not b.same_evidence(a)
        assert FactEvidence(a) != FactEvidence(b)
        assert b.evidence == ["proof"]


@pytest.mark.parametrize("mode", ["strict", "possible"])
@pytest.mark.parametrize("limit", [0, 1, 2, None])
def test_projection_keeps_certainty_order_and_bounded_alternative_proofs(mode, limit):
    rows = [
        Row({"$owner": "a", "$hidden": str(i)}, [{"witness": i}], {"gap"})
        for i in range(30)
    ]
    rows += [Row({"$owner": "b"}, ["certain b"]), Row({"$owner": "a"}, ["certain a"])]
    original = list(rows)
    result = project_rows(rows, {"unit": "$owner"}, evidence_mode=mode, max_matches=limit)
    assert rows == original  # Projection does not reorder its caller's batch.
    assert result.complete == (limit is None or limit >= 2)
    if not result.complete:
        assert "budget:max_matches" in result.unknown
    expected = ["a", "b"][:limit]
    assert [match["bindings"]["$unit"] for match in result.matches] == expected
    assert all(match["status"] == "structural_match" for match in result.matches)
    assert all(match["unknown"] == [] for match in result.matches)
    if result.complete:
        if mode == "strict":
            assert result.matches[0]["evidence"] == ["certain a"]
            assert set(result.unknown) == {"gap"}
        else:
            group, = result.matches[0]["evidence"]
            assert len(group["alternatives"]) == 16
            assert group["alternatives"][0] == {"evidence": ["certain a"], "unknown": []}
            assert group["truncated"]


def test_projection_can_merge_duplicates_when_distinct_result_limit_is_full():
    rows = [Row({"$owner": "a"}, [str(i)]) for i in range(3)]
    result = project_rows(rows, {"unit": "$owner"}, evidence_mode="strict", max_matches=1)
    assert result.complete
    assert len(result.matches[0]["evidence"][0]["alternatives"]) == 3


def test_retained_profile_does_not_retain_the_closed_executor():
    import gc
    import weakref

    enabled = gc.isenabled()
    gc.disable()
    try:
        engine = Executor(FactIndex(IR("sample", "python")), {}, profile=True)
        engine.execute(Query("q", [Node("optional", children=[[]])], {}))
        profile = engine.profiler
        reference = weakref.ref(engine)
        engine.close()
        del engine
        assert reference() is None
        assert profile.parent is None
        assert len(profile.operators) == 1
    finally:
        if enabled:
            gc.enable()
