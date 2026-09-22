"""Late proof materialization preserves the eager engine's evidence contract."""

import copy
import json
import random

import pytest

from ken.structural.model import Fact, FactIndex, IR
from ken.structural.query import Clause
from ken.structural.relational import Executor, Node, Query, Row, merge_proofs
from ken.structural.relational_evidence import FactEvidence, ProofAccumulator, materialize
from ken.structural_store import Store
from ken.structural_store.graph_index import GraphIndex
from ken.structural_store.graph_projection import publish


def eager_union(first, second):
    """Previous eager implementation, kept as a differential oracle."""
    alternatives = []
    truncated = False
    for row in (first, second):
        if len(row.evidence) == 1 and "alternatives" in row.evidence[0]:
            candidates = row.evidence[0]["alternatives"]
            truncated |= row.evidence[0].get("truncated", False)
        else:
            candidates = [{"evidence": row.evidence, "unknown": sorted(row.unknown)}]
        for candidate in candidates:
            if candidate not in alternatives:
                alternatives.append(candidate)
    alternatives.sort(key=lambda proof: bool(proof["unknown"]))
    truncated |= len(alternatives) > 16
    preferred = second if first.unknown and not second.unknown else first
    return Row(preferred.bindings,
               [{"alternatives": alternatives[:16], "truncated": truncated}],
               preferred.unknown)


@pytest.mark.parametrize("seed", range(16))
def test_incremental_union_matches_eager_union_with_duplicates_and_late_certainty(seed):
    randomizer = random.Random(seed)
    rows = [Row({"$unit": "same", "$hidden": str(i)}, [{"witness": i}], {"gap"})
            for i in range(40)]
    rows += [Row({"$unit": "same", "$hidden": str(i)}, [{"witness": i}], set())
             for i in range(40)]
    rows += randomizer.choices(rows, k=80)
    # Also merge already consolidated groups, including nested/truncated proofs.
    rows += [eager_union(rows[i], rows[i + 1]) for i in range(0, 78, 2)]
    randomizer.shuffle(rows)
    expected = rows[0]
    accumulator = ProofAccumulator(rows[0])
    for row in rows[1:]:
        before = copy.deepcopy(expected)
        actual = merge_proofs(expected, row)
        assert expected == before  # Merging never mutates a previously held proof.
        expected = eager_union(expected, row)
        accumulator.add(row)
        assert actual == expected == accumulator.finish()


def test_saturated_proof_prefix_does_not_compare_discarded_witnesses():
    class Unreadable:
        def __eq__(self, other):
            pytest.fail("discarded proof was inspected")

    proofs = ProofAccumulator(Row({}, [{"witness": 0}], set()))
    for i in range(1, 17):
        proofs.add(Row({}, [{"witness": i}], set()))
    for _ in range(100):
        proofs.add(Row({}, [{"witness": Unreadable()}], {"gap"}))
    assert len(proofs.finish().evidence[0]["alternatives"]) == 16
    assert proofs.finish().evidence[0]["truncated"]


def graph(store, ir):
    snapshot = store.publish([], expected_parent=store.current, profile="proof-test")
    return GraphIndex(store, publish(store, snapshot, "proof-test", ir))


def test_native_proofs_decode_only_surviving_sources_and_detach_before_close(monkeypatch):
    ir = IR("sample", "python", view="query")
    ir.facts = [Fact("owner", "HAS_METHOD", str(i), {}, ["proof-" + str(i)])
                for i in range(200)]
    child = Query("methods", [Node("fact", Clause("require", "$owner", "HAS_METHOD", "$method"))],
                  {"owner": "$owner"})
    query = Query("q", [Node("match", ("methods", {"owner": "$unit"}, None))],
                  {"unit": "$unit"})
    expected = Executor(FactIndex(ir), {"methods": child}).execute(query)
    with Store(cache_mb=0) as store:
        index = graph(store, ir)
        sources = {fact._evidence for fact in index.rows("HAS_METHOD")}
        decoded = set()
        original = index.values.get

        def decode(value):
            if value in sources:
                decoded.add(value)
            return original(value)

        monkeypatch.setattr(index.values, "get", decode)
        actual = Executor(index, {"methods": child}).execute(query)
        assert len(decoded) == 16
    assert json.loads(json.dumps(actual))["matches"] == expected["matches"]


def test_fact_proof_identity_uses_snapshot_value_ids_without_decoding(monkeypatch):
    ir = IR("sample", "python", facts=[Fact("a", "R", "b", {}, ["proof"])], view="query")
    with Store(cache_mb=0) as store:
        index = graph(store, ir)
        a = index.rows("R")[0]
        b = index.rows("R")[0]
        assert a is not b
        with monkeypatch.context() as patch:
            patch.setattr(index.values, "get", lambda _: pytest.fail("source decoded for equality"))
            assert FactEvidence(a) == FactEvidence(b)
        assert materialize([FactEvidence(a)]) == [{
            "subject": "a", "relation": "R", "object": "b", "source": ["proof"]}]


def test_cancellation_during_deferred_source_read_returns_no_handles(monkeypatch):
    from ken.structural.query import _Exhausted

    ir = IR("sample", "python", facts=[Fact("a", "R", "b", {}, ["proof"])], view="query")
    query = Query("q", [Node("fact", Clause("require", "$a", "R", "$b"))], {"a": "$a"})
    with Store(cache_mb=0) as store:
        index = graph(store, ir)
        source = index.rows("R")[0]._evidence
        original = index.values.get
        def decode(value):
            if value == source:
                raise _Exhausted("timeout_ms")
            return original(value)
        monkeypatch.setattr(index.values, "get", decode)
        result = Executor(index, {}).execute(query)
        assert not result["complete"]
        assert result["matches"] == []
        assert result["unknown"] == ["budget:timeout_ms"]
    json.dumps(result)


def test_closure_plan_proves_source_inventory_open_without_reading_capabilities():
    class Unreadable:
        def __contains__(self, key):
            pytest.fail("an open source inventory asked for per-row closure")

    ir = IR("sample", "python")
    ir.capabilities = Unreadable()
    engine = Executor(FactIndex(ir), {})
    nodes = [Node("fact", Clause("require", "$unit", "ENTITY", "CLASS")),
             Node("any", children=[[Node("source_body")]])]
    for unit in ("a", "b", "c"):
        assert not engine.closed(nodes, Row({"$unit": unit}))
    assert len(engine._closure_plans) == 1
    engine.close()
    assert not engine._closure_plans


def test_closure_of_pure_named_queries_still_uses_current_seed_and_scope():
    ir = IR("sample", "python", capabilities={"complete:a:R", "complete:scope:R"})
    child = Query("child", [Node("fact", Clause("require", "$owner", "R", "$item"))],
                  {"first": "$owner", "second": "$owner"})
    nodes = [Node("match", ("child", {"first": "$x", "second": "$y"}, None))]
    engine = Executor(FactIndex(ir), {"child": child})
    assert engine.closed(nodes, Row({"$x": "a"}))
    assert not engine.closed(nodes, Row({"$x": "a", "$y": "b"}))
    assert not engine.closed(nodes, Row())
    assert engine.closed(nodes, Row(), "scope")


def test_closure_compilation_does_not_retain_the_executor_through_recursive_callbacks():
    import gc
    import weakref

    collecting = gc.isenabled()
    gc.disable()
    try:
        engine = Executor(FactIndex(IR("sample", "python")), {})
        nodes = [Node("any", children=[[Node("source_body")]])]
        assert not engine.closed(nodes, Row())
        reference = weakref.ref(engine)
        engine.close()
        del engine
        assert reference() is None
    finally:
        if collecting:
            gc.enable()


def test_named_proof_capture_materializes_json():
    ir = IR("sample", "python", facts=[Fact("a", "R", "b", {}, ["proof"])])
    child = Query("child", [Node("fact", Clause("require", "$a", "R", "$b"))], {"a": "$a"})
    query = Query("q", [Node("match", ("child", {"a": "$a"}, "$proof"))], {"proof": "$proof"})
    result = Executor(FactIndex(ir), {"child": child}).execute(query)
    assert json.loads(result["matches"][0]["bindings"]["$proof"])[0]["source"] == ["proof"]
