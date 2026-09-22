"""Contracts for streaming, profiling, scheduling and snapshot isolation."""

from dataclasses import replace

import pytest

from ken.kql2.compiler import Action, compile
from ken.kql2.execution import execute
from ken.kql2.execution_control import ExecutionBudget, ExecutionControl
from ken.kql2.operators import Frame
from ken.kql2.outcome import Outcome
from ken.kql2.pipeline import OperatorStats, run
from ken.kql2.planning import explain, prepare, schedule
from ken.kql2.runtime import QueryRuntime
from ken.kql2.service import search
from ken.kql2.syntax import Expr, parse
from ken.structural.model import IR, Entity, Fact
from ken.structural_store import Store

HEADER = 'language "kql/2"; module architecture; '


def program(body):
    return compile(parse(HEADER + "query q { " + body + " }"))


def publish(store, count=4, name="C", static=False):
    ir = IR("fixture.py", "python")
    for i in range(count):
        c, m = f"c{i}", f"m{i}"
        ir.entities[c] = Entity(c, "CLASS", name + str(i), ir.path, 1, 3)
        ir.entities[m] = Entity(
            m, "CALLABLE", "work", ir.path, 2, 3, {"static": static}
        )
        ir.facts.append(Fact(c, "HAS_METHOD", m))
    unit = store.put_unit(name, ir, "hash", "version")
    return store.publish([unit], expected_parent=None)


@pytest.mark.parametrize(
    "options", [{}, {"max_states": 8}, {"max_rows": 2}, {"cancelled": lambda: True}]
)
def test_profiling_preserves_results_and_budgets(options):
    p = program('class $c { method $m {} } where $m.name == "work"; select $c;')
    with Store() as store:
        snapshot = publish(store)
        plain = execute(p, store, snapshot, **options)
        profiled = execute(p, store, snapshot, profile=True, **options)
    for field in (
        "rows",
        "order_keys",
        "complete",
        "reason",
        "states",
        "scanned_nodes",
        "unknown_candidates",
    ):
        assert getattr(plain, field) == getattr(profiled, field)
    assert plain.profile == []
    assert len(profiled.profile) == len(profiled.plan)
    assert all(item["elapsed_ms"] >= 0 for item in profiled.profile)
    if plain.complete:
        assert [
            (item["input_rows"], item["output_rows"]) for item in profiled.profile
        ] == [(1, 4), (4, 4), (4, 4)]


def test_plan_keeps_actions_and_body_boundaries_without_store():
    p = program(
        'class $c {} bind $name = $c.name; class $d { name: "C1"; } select $name;'
    )
    steps = schedule(p, prepare(p))
    assert isinstance(steps[1], Action)
    assert [entry["operator"] for entry in explain(p)] == ["scan", "bind", "scan"]
    assert explain(p)[1]["barrier"] is True
    assert explain(p)[1]["source"] == "<query>"


def test_node_metadata_does_not_fetch_property_inventories(monkeypatch):
    p = program('class $c { method $m { name: "work"; } } select $c.name,$m.path;')
    with Store() as store:
        snapshot = publish(store)

        def forbidden(node):
            pytest.fail("metadata is already available on the scanned node")

        monkeypatch.setattr(store, "properties", forbidden)
        result = execute(p, store, snapshot)
        assert result.complete and len(result.rows) == 4


def test_property_cache_reuses_same_node_and_is_snapshot_local(monkeypatch):
    p = program(
        "class $c { method $m { static: false; } } where $m.static == false; select $m.static;"
    )
    with Store() as first, Store() as second:
        first_snapshot = publish(first, static=False)
        second_snapshot = publish(second, static=True)
        original = first.properties
        reads = []

        def counted(node):
            reads.append(node.id)
            return original(node)

        monkeypatch.setattr(first, "properties", counted)
        assert execute(p, first, first_snapshot).rows == [(False,)]
        assert len(reads) == len(set(reads)) == 4
        assert execute(p, second, second_snapshot).rows == []


def test_property_cache_is_bounded():
    import time

    with Store() as store:
        snapshot = publish(store, count=1030)
        runtime = QueryRuntime(
            program("select 1;"),
            store,
            snapshot,
            ExecutionControl(
                store, Outcome(), ExecutionBudget(), time.monotonic(), None
            ),
            reference=False,
        )
        for node in store.scan(snapshot, kind="CLASS"):
            runtime.properties(node)
        assert runtime.properties.cache_info().currsize == 1024


def test_join_depth_does_not_use_python_recursion():
    p = program("select 1;")
    span = p.projection[0].span
    p = replace(
        p, steps=tuple(Action("", Expr("literal", span, "true")) for _ in range(1500))
    )
    with Store() as store:
        result = execute(p, store, publish(store, count=0))
        assert result.complete and result.rows == [(1,)]


@pytest.mark.parametrize("profile", [False, True])
def test_closing_a_pipeline_closes_suspended_operators(profile):
    closed = []

    class OpenScan:
        def apply(self, frame):
            try:
                yield frame
                yield frame
            finally:
                closed.append(True)

    stats = (OperatorStats(), OperatorStats()) if profile else ()
    frames = run((OpenScan(), OpenScan()), lambda: None, stats)
    assert next(frames) == Frame({})
    frames.close()
    assert closed == [True, True]


def test_union_profile_identifies_each_branch():
    p = program(
        'either { class $c { name: "C0"; } } or { class $c { name: "C1"; } } select $c;'
    )
    with Store() as store:
        result = execute(p, store, publish(store), profile=True)
    assert len(result.rows) == 2
    assert {entry["branch_index"] for entry in result.profile} == {0, 1}


@pytest.mark.parametrize("graph", [False, True])
def test_service_profile_bypasses_result_cache(tmp_path, graph):
    (tmp_path / "sample.py").write_text("class C: pass\n")
    body = 'edge ENTITY($c, "CLASS"); select $c;' if graph else "class $c {} select $c;"
    text = HEADER + "query q { " + body + " }"
    normal = search(tmp_path, text, cache_mb=20)
    cached = search(tmp_path, text, cache_mb=20)
    profiled = search(tmp_path, text, cache_mb=20, profile=True)
    assert normal["rows"] == cached["rows"] == profiled["rows"]
    assert cached["analysis"]["result_cache"] == "disk_hit"
    assert profiled["analysis"]["result_cache"] == "miss"
    assert profiled["analysis"]["operator_profile"][0]["output_rows"] == 1
    assert "operator_profile" not in search(tmp_path, text, cache_mb=20)["analysis"]
