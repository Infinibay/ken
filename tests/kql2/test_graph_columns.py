"""Storage conformance: native columns, source matching and immutable revisions."""

import json
import math
from dataclasses import asdict

import pytest

from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.model import IR, Entity, Fact, Operation
from ken.structural.query import QueryBudget
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.semantic import link_project
from ken.structural_store import Store
from ken.structural_store.graph_index import GraphIndex
from ken.structural_store.graph_projection import publish
from ken.structural_store.migrations import migrate, validate


def stored(store, ir, key="test"):
    snapshot = store.publish([], expected_parent=store.current, profile=key)
    return GraphIndex(store, publish(store, snapshot, key, ir))


def test_native_records_roundtrip_without_json(monkeypatch):
    attrs = {
        "flag": False,
        "number": 1,
        "float": 1.5,
        "empty": None,
        "name": 'á\n"x',
        "nested": {"list": [1, True, "1", None]},
        "tuple": (1, 2),
        "huge": 2**90,
        "negative_zero": -0.0,
    }
    ir = IR(
        "a.py",
        "python",
        view="query",
        diagnostics=["gap"],
        capabilities={"complete:a:R"},
    )
    ir.entities["a"] = Entity("a", "CALLABLE", "f", "a.py", 1, 4, attrs)
    ir.operations = [
        Operation("op", "RETURN", "return", None, "body", 3, 9, 2, "a", attrs)
    ]
    ir.facts = [
        Fact("a", "R", "b", attrs, ["proof", "proof"]),
        Fact("a", "R", "b", attrs, ["other"]),
    ]
    ir.relations = {"R", "EMPTY"}
    with Store(cache_mb=0) as store:
        index = stored(store, ir)
        monkeypatch.setattr(
            json, "loads", lambda *a, **k: pytest.fail("graph access parsed JSON")
        )
        assert asdict(index.ir.entities["a"]) == asdict(ir.entities["a"])
        assert [asdict(o) for o in index.ir.operations] == [
            asdict(o) for o in ir.operations
        ]
        assert [asdict(f) for f in index.ir.facts] == [asdict(f) for f in ir.facts]
        assert math.copysign(1, index.ir.entities["a"].attrs["negative_zero"]) == -1
        assert "complete:a:R" in index.ir.capabilities
        assert index.ir.diagnostics == ["gap"]
        assert len(index.rows("R", "a", "b")) == 2
        assert not index.rows("R", "a", "missing")
        assert [f.evidence for f in index.attr_rows("R", "flag", "false")] == [
            ["proof", "proof"],
            ["other"],
        ]
        first, second = list(index.rows("R"))
        first.attrs["nested"]["list"].append("changed")
        assert second.attrs["nested"]["list"] == [1, True, "1", None]


def test_operation_metadata_does_not_decode_unrequested_attributes(monkeypatch):
    ir = IR("a", "python", view="query")
    attrs = {"tokens": ["large", "body"], "nested": {"values": [1, 2]}}
    ir.operations = [
        Operation("op", "RETURN", "return", None, "body", 0, 10, 1, "f", attrs)
    ]
    with Store(cache_mb=0) as store:
        index = stored(store, ir)
        with monkeypatch.context() as patch:
            patch.setattr(
                index.values,
                "get",
                lambda *args: pytest.fail("unrequested attributes loaded"),
            )
            first = next(index.operations(owner="f"))
            assert (first.kind, first.start, first.end) == ("RETURN", 0, 10)
        assert asdict(first) == asdict(ir.operations[0])
        assert first == ir.operations[0] and ir.operations[0] == first
        second = next(index.operations(local_id="op"))
        first.attrs["nested"]["values"].append(3)
        assert second.attrs["nested"]["values"] == [1, 2]


def test_fact_attribute_projection_does_not_decode_other_members(monkeypatch):
    attrs = {"modality": "may", "nested": {"values": [1, 2]}, "flag": False}
    ir = IR("sample", "python", facts=[Fact("a", "R", "b", attrs)], view="query")
    with Store(cache_mb=0) as store:
        index = stored(store, ir)
        fact = index.rows("R")[0]
        members = dict(index.values.encoded(fact._attributes)[1])
        original = index.values.get
        def get(value):
            assert value not in {fact._attributes, members["nested"]}
            return original(value)
        with monkeypatch.context() as patch:
            patch.setattr(index.values, "get", get)
            assert fact.attribute("modality") == "may"
            assert fact.attribute("flag") is False
            assert fact.attribute("absent") is None
        first = fact.attribute("nested")
        first["values"].append(3)
        assert fact.attribute("nested") == {"values": [1, 2]}
        fact.attrs["flag"] = True
        assert fact.attribute("flag") is True


def test_indexes_are_used_for_endpoints_and_attribute_candidates():
    from ken.structural.query import Clause

    ir = IR("x", "python", view="query")
    ir.facts = [
        Fact(str(i), "ENTITY", "CLASS", {"name": "needle" if i == 42 else "other"})
        for i in range(1000)
    ]
    with Store(cache_mb=0) as store:
        index = stored(store, ir)
        for rows, expected in (
            (index.rows("ENTITY", "42"), "k2_graph_fact_forward"),
            (index.rows("ENTITY", object="CLASS"), "k2_graph_fact_reverse"),
            (index.attr_rows("ENTITY", "name", "needle"), "k2_graph_member_value"),
        ):
            sql, params = rows.sql()
            plan = "\n".join(
                row[3] for row in store.db.execute("EXPLAIN QUERY PLAN " + sql, params)
            )
            assert expected in plan
        clause = Clause(
            "require", "$x", "ENTITY", "CLASS", [("name", "literal", "needle")]
        )
        assert index.estimate_clause(clause, object="CLASS") == 1
        assert [f.subject for f in index.candidates(clause, object="CLASS")] == ["42"]
        alternatives = Clause("require", "$x", "ENTITY", "CLASS|INTERFACE", [])
        rows = index.candidates(alternatives)
        sql, params = rows.sql()
        plan = "\n".join(
            row[3] for row in store.db.execute("EXPLAIN QUERY PLAN " + sql, params)
        )
        assert "k2_graph_fact_reverse" in plan


def test_dictionary_migration_preserves_populated_graphs_and_integer_storage(
    monkeypatch,
):
    from ken.structural_store.graph_dictionary_schema import FAMILIES

    with Store(cache_mb=0) as store:
        expected = []
        for name in ("first", "second"):
            ir = IR(name, "python", view="query")
            attrs = {"": "", "kind": "CALL", "nested": [True, 1, "1", None]}
            ir.entities["e"] = Entity("e", "CALL", name, "shared.py", 1, 2, attrs)
            ir.operations = [
                Operation("o", "CALL", "call", None, "body", 0, 2, 1, "e", attrs)
            ]
            ir.facts = [Fact("e", "ENTITY", "CALL", attrs, [name])]
            index = stored(store, ir, name)
            expected.append((index.graph, ir))
            index.close()
        migrate(store.db, 10)
        assert validate(store.db) == 10
        assert store.db.execute(
            "SELECT DISTINCT typeof(kind) FROM k2_graph_entities"
        ).fetchall() == [("text",)]
        migrate(store.db)
        validate(store.db)
        monkeypatch.setattr(
            json, "loads", lambda *a, **k: pytest.fail("migration decoded JSON")
        )
        for family, fields in FAMILIES.items():
            for field in fields:
                types = store.db.execute(
                    f'SELECT DISTINCT typeof("{field}") FROM k2_graph_{family} WHERE "{field}" IS NOT NULL'
                ).fetchall()
                assert types == [("integer",)], (family, field, types)
        for graph, ir in expected:
            index = GraphIndex(store, graph)
            assert asdict(index.ir.entities["e"]) == asdict(ir.entities["e"])
            assert [asdict(o) for o in index.ir.operations] == [
                asdict(o) for o in ir.operations
            ]
            assert [asdict(f) for f in index.attr_rows("ENTITY", "", "")] == [
                asdict(f) for f in ir.facts
            ]
            assert (
                store.db.execute(
                    "SELECT count(*) FROM k2_graph_terms WHERE graph_id=? AND text='CALL'",
                    (graph,),
                ).fetchone()[0]
                == 1
            )


def test_v6_migration_preserves_units_and_new_graph_is_atomic():
    with Store(cache_mb=0) as store:
        migrate(store.db, 6)
        assert validate(store.db) == 6
        migrate(store.db)
        from ken.structural_store.schema import VERSION

        assert validate(store.db) == VERSION
        ir = IR("x", "python", view="query", facts=[Fact("a", "R", "b")])
        first = stored(store, ir, "first")
        snapshot = store.publish([], expected_parent=store.current, profile="second")

        def interrupted():
            raise RuntimeError("cancelled")

        with pytest.raises(RuntimeError, match="cancelled"):
            publish(store, snapshot, "second", ir, check=interrupted)
        assert (
            store.db.execute(
                "SELECT 1 FROM k2_graphs WHERE fingerprint='second'"
            ).fetchone()
            is None
        )
        assert len(first.rows("R")) == 1
        second = stored(store, IR("x", "python", view="query"), "third")
        assert not second.rows("R") and len(first.rows("R")) == 1


@pytest.mark.parametrize("evidence_mode", ["strict", "possible"])
@pytest.mark.parametrize(
    "body",
    [
        'call $c { name: "log"; };',
        'let $v = call $c { name: "log"; };',
        "return _;",
    ],
)
def test_body_matches_memory_reference(body, evidence_mode):
    source = b"def f(x):\n v = log(x)\n return v\ndef g():\n return 1\n"
    memory = query_graph(link_project([lower_source(source, "python", "a.py")]))
    query = compile_source(
        'language "kql/2"; module t; query q { callable $f { body { '
        + body
        + " } } select $f; }"
    )

    def run(index):
        engine = Executor(index, {}, QueryBudget(), evidence_mode)
        try:
            outcome = engine.execute(query)
            return {key: outcome[key] for key in ("complete", "matches", "unknown")}
        finally:
            engine.close()

    with Store(cache_mb=0) as store:
        assert run(stored(store, memory.ir)) == run(memory)


def test_warm_project_queries_do_not_load_ir_payloads(tmp_path, monkeypatch):
    from ken.structural import service
    from ken.structural.index_service import project_index

    (tmp_path / "a.py").write_text("class A:\n pass\n")
    with project_index(tmp_path) as (first, analysis):
        assert not analysis["query_index"]["hit"]
        cold_phases = analysis["query_index"]["phase_ms"]
        assert {"source_build", "normalization", "index_write"} <= cold_phases.keys()
        assert [e.name for e in first.entities(kind="CLASS")] == ["A"]
    with monkeypatch.context() as patch:
        patch.setattr(
            service,
            "build_project",
            lambda *a, **k: pytest.fail("warm query rebuilt IR"),
        )
        patch.setattr(
            json, "loads", lambda *a, **k: pytest.fail("warm index parsed JSON")
        )
        with project_index(tmp_path) as (warm, analysis):
            assert analysis["query_index"]["hit"]
            assert set(analysis["query_index"]["phase_ms"]) == {
                "manifest",
                "store_open",
                "index_open",
            }
            assert [e.name for e in warm.entities(kind="CLASS")] == ["A"]
    (tmp_path / "a.py").write_text("class B:\n pass\n")
    with project_index(tmp_path) as (changed, analysis):
        assert not analysis["query_index"]["hit"]
        assert [e.name for e in changed.entities(kind="CLASS")] == ["B"]


@pytest.mark.parametrize("source", [
    "class Item { Item(){} Item(int value){this(); System.out.println(value);} }",
    "class Item { Item(){publish(this);} }",
    "class Item { Item(){Runnable r=()->publish(this);} }",
    "class Item extends External { Item(){} }",
])
def test_receiver_effects_read_only_selected_owners_and_keep_reference_result(source, monkeypatch):
    from tests.structural.test_authored_receiver_escape import QUERY

    memory = query_graph(link_project([lower_source(source, "java", "sample.java")]))
    query = compile_source(QUERY)
    reference = Executor(memory, {}).execute(query)
    with Store() as store:
        index = stored(store, memory.ir)
        native = index.operations
        reads = []
        def selected(**kwargs):
            assert kwargs.get("owner") is not None or kwargs.get("local_id") is not None
            reads.append(kwargs)
            yield from native(**kwargs)
        monkeypatch.setattr(index, "operations", selected)
        executor = Executor(index, {})
        result = executor.execute(query)
        assert {k: result[k] for k in ("matches", "complete", "unknown")} == {
            k: reference[k] for k in ("matches", "complete", "unknown")}
        assert reads
        assert executor._receiver_effects.operations.get(None) is None
        executor.close()


def test_sql_vm_cancellation_is_reported_and_handler_is_released():
    from ken.structural.query import _Exhausted

    ir = IR(
        "x", "python", view="query", facts=[Fact(str(i), "R", "x") for i in range(2000)]
    )
    with Store(cache_mb=0) as store:
        index = stored(store, ir)
        calls = 0

        def check():
            nonlocal calls
            calls += 1
            if calls > 1:
                raise _Exhausted("cancelled")

        with pytest.raises(_Exhausted, match="cancelled"), index.execution(check):
            index.db.execute(
                "SELECT count(*) FROM k2_graph_facts a CROSS JOIN k2_graph_facts b"
            ).fetchone()
        assert (
            store.db.execute("SELECT count(*) FROM k2_graph_facts").fetchone()[0]
            == 2000
        )


def test_failed_frontend_is_not_retained_as_a_complete_index(tmp_path, monkeypatch):
    from ken.structural import service
    from ken.structural.index_service import project_index

    (tmp_path / "a.py").write_text("class A: pass\n")
    with monkeypatch.context() as patch:

        def fail(*args):
            raise ValueError("frontend failed")

        patch.setattr(service, "lower_source", fail)
        with project_index(tmp_path) as (_, analysis):
            assert not analysis["coverage_complete"]
            assert not analysis["query_index"]["persistent"]
            assert not analysis["graph_key"]
    with project_index(tmp_path) as (index, analysis):
        assert not analysis["query_index"]["hit"]
        assert analysis["coverage_complete"]
        assert [e.name for e in index.entities(kind="CLASS")] == ["A"]


def test_native_syntax_ranges_use_parentage_and_keep_nested_owners():
    source = b"class A:\n def f(self,x):\n  if x:\n   log(x)\n  else:\n   other(x)\n  def nested():\n   log(2)\n  return x\n"
    memory = query_graph(link_project([lower_source(source, "python", "a.py")]))
    with Store(cache_mb=0) as store:
        index = stored(store, memory.ir)
        view = index.source_view()
        for operation in memory.ir.operations:
            start, end, final = index.syntax_bounds(operation.id)
            children = {operation.id}
            pending = [operation.id]
            while pending:
                parent = pending.pop()
                for child in memory.ir.operations:
                    if child.parent == parent:
                        children.add(child.id)
                        pending.append(child.id)
            assert end - start == len(children)
            assert final in children
            expected = [
                op
                for op in memory.ir.operations
                if op.id in children and op.owner == operation.owner
            ]
            assert list(view.region_operations(operation.owner, operation)) == expected
            assert view.operation(operation.id) == operation
        root = memory.ir.operations[0]
        start, end, _ = index.syntax_bounds(root.id)
        plan = store.db.execute(
            "EXPLAIN QUERY PLAN SELECT local_id FROM k2_graph_syntax WHERE graph_id=? AND position>=? AND position<?",
            (index.graph, start, end),
        ).fetchall()
        assert any("position>" in row[3] and "INDEX" in row[3] for row in plan)
