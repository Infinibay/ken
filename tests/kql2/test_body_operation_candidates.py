"""BODY prerequisites remove impossible owners before relational fan-out."""

from contextlib import ExitStack

import pytest

from ken.kql2.catalog import compile_source
from ken.kql2.exploration.catalog_index import CatalogIndex
from ken.structural.frontend import lower_source
from ken.structural.model import IR, Operation
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor, Node, Row
from ken.structural.semantic import link_project
from ken.structural_store import Store
from tests.kql2.test_graph_columns import stored
from tests.kql2.test_source_candidate_planning import canonical


def run(index, query, mode, *, reference=False):
    engine = Executor(index, {}, evidence_mode=mode, profile=True)
    engine.reference = reference
    try:
        return engine.execute(query), engine.profile
    finally:
        engine.close()


@pytest.mark.parametrize("backend", ["memory", "native", "vector"])
@pytest.mark.parametrize("mode", ["strict", "possible"])
@pytest.mark.parametrize("coverage", ["structured", "partial", "missing_status", "missing_entry", "await"])
@pytest.mark.parametrize("body", [
    "call $target { resolution: any; };",
    "let $value = call $target { resolution: any; }; return $value;",
])
def test_prerequisite_preserves_evidence_and_unknowns(backend, mode, coverage, body):
    ir = link_project([lower_source(
        "def selected(): return target()\ndef noise(): return 0\n", "python", "sample.py"
    )])
    noise = next(e.id for e in ir.entities.values() if e.name == "noise")
    for fact in ir.facts:
        if fact.subject == noise and fact.relation == "CFG_STATUS":
            if coverage in {"partial", "await"}:
                fact.object = "partial"
                fact.attrs["reasons"] = ["await"] if coverage == "await" else ["unsupported"]
    missing = {"missing_status": "CFG_STATUS", "missing_entry": "CFG_ENTRY"}.get(coverage)
    if missing:
        ir.facts = [f for f in ir.facts if not (f.subject == noise and f.relation == missing)]
    memory = query_graph(ir)
    query = compile_source('language "kql/2"; module ops; query q { callable $method { body { '
                           + body + ' } } select $method; }')
    expected, _ = run(memory, query, mode, reference=True)
    with ExitStack() as stack:
        index = memory
        if backend != "memory":
            store = stack.enter_context(Store(cache_mb=0))
            index = stored(store, memory.ir)
            stack.callback(index.close)
            if backend == "vector":
                index = CatalogIndex(index)
                stack.callback(index.close)
        actual, profile = run(index, query, mode)
    for key in ("matches", "complete", "unknown"):
        assert canonical(actual[key]) == canonical(expected[key])
    assert actual["complete"] and actual["matches"]
    assert any(p.get("source_prefilter", {}).get("operation_kinds") == ["CALL"] for p in profile)


def test_body_prerequisite_prevents_cross_product_with_unrelated_declarations():
    source = "def selected(): target()\n" + "\n".join(
        f"def noise{i}(): return {i}\nclass C{i}: pass" for i in range(40)
    )
    index = query_graph(link_project([lower_source(source, "python", "noise.py")]))
    query = compile_source('''language "kql/2"; module fanout; query q {
      class $unrelated {}
      callable $method { body { call $target { resolution: any; }; } }
      select $method, $unrelated;
    }''')
    actual, profile = run(index, query, "possible")
    expected, reference_profile = run(index, query, "possible", reference=True)
    for key in ("matches", "complete", "unknown"):
        assert canonical(actual[key]) == canonical(expected[key])
    assert actual["complete"] and len(actual["matches"]) == 40
    body_inputs = lambda metrics: sum(p["input_rows"] for p in metrics if p["operator"] == "source_body")
    assert body_inputs(profile) == 40
    assert body_inputs(reference_profile) > 40 * 40


def test_operation_owner_inventory_is_columnar_and_snapshot_scoped(monkeypatch):
    operations = [
        Operation("a", "CALL", "call", None, "body", 0, 1, 1, "first", {}),
        Operation("b", "CALL", "call", None, "body", 1, 2, 2, "first", {}),
        Operation("c", "RETURN", "return", None, "body", 2, 3, 3, "second", {}),
    ]
    with Store(cache_mb=0) as store:
        first = stored(store, IR("one", "python", view="query", operations=operations), "one")
        second = stored(store, IR("two", "python", view="query"), "two")
        def no_payload(_):
            raise AssertionError("operation-owner lookup must not decode records")
        monkeypatch.setattr(first.values, "get", no_payload)
        assert first.operation_owners(frozenset({"CALL"})) == {"first"}
        assert first.operation_owners(frozenset({"CALL", "RETURN"})) == {"first", "second"}
        assert first.operation_owners(frozenset({"MISSING"})) == set()
        assert first.operation_owners(frozenset()) == set()
        assert second.operation_owners(frozenset({"CALL"})) == set()


def test_prerequisites_replan_for_an_owner_bound_by_an_earlier_body():
    source = "def selected(): return target()\n" + "\n".join(
        f"def noise{i}(): return {i}" for i in range(40)
    )
    index = query_graph(link_project([lower_source(source, "python", "sample.py")]))
    query = compile_source('''language "kql/2"; module bound; query q {
      callable $method { body { return _; } body { call $target { resolution: any; }; } }
      select $method;
    }''')
    actual, profile = run(index, query, "possible")
    expected, _ = run(index, query, "possible", reference=True)
    for key in ("matches", "complete", "unknown"):
        assert canonical(actual[key]) == canonical(expected[key])
    bodies = [p for p in profile if p["operator"] == "source_body"]
    assert [p["input_rows"] for p in bodies] == [41, 1]


def test_prebound_unknown_owner_is_not_pruned_by_operation_inventory():
    query = compile_source('''language "kql/2"; module unknown_owner; query q {
      callable $method { body { call $target { resolution: any; }; } } select $method;
    }''')
    pattern = next(node.value for node in query.nodes if node.kind == "source_body")
    index = query_graph(IR("empty", "python"))
    engine = Executor(index, {}, evidence_mode="possible")
    try:
        result = engine.run_nodes([Node("source_body", pattern)], [Row({"$method": "@unknown:method"})])
        assert len(result) == 1 and result[0].unknown == {"source_body:unknown"}
        assert engine.run_nodes([Node("source_body", pattern)], []) == []
    finally:
        engine.close()
