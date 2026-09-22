"""Batch resources share snapshot projections without sharing query state."""

import pytest

from ken.kql2 import source_execution
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.model import IR, FactIndex
from ken.structural.query import QueryBudget
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.relational_resources import ExecutionResources
from ken.structural.rules import SavedRule, execute_rules
from ken.structural.semantic import link_project

QUERY = """language "kql/2"; module example;
pattern detect(out Callable $owner) {
  callable $owner { body { return 1; } }
}
query results { use detect(owner: $owner); select $owner; }
"""


def graph():
    return link_project(
        [lower_source("def work():\n return 1\n", "python", "sample.py")]
    )


def test_batch_constructs_one_source_view_and_preserves_each_result(monkeypatch):
    views = []
    original = source_execution.SourceView

    def create(index):
        view = original(index)
        views.append(view)
        return view

    monkeypatch.setattr(source_execution, "SourceView", create)
    rules = [SavedRule("first", QUERY), SavedRule("second", QUERY)]
    result = execute_rules(graph(), rules)
    assert result["complete"]
    assert {match["id"] for match in result["matches"]} == {"first", "second"}
    assert len(views) == 1
    first, second = result["matches"]
    assert first["bindings"] == second["bindings"]
    assert first["evidence"] == second["evidence"]


def test_exhausted_query_does_not_poison_the_next_query():
    index = query_graph(graph())
    resources = ExecutionResources(index)
    query = compile_source(QUERY)
    first = Executor(index, {}, QueryBudget(max_states=1), resources=resources)
    assert not first.execute(query)["complete"]
    second = Executor(index, {}, resources=resources)
    result = second.execute(query)
    assert result["complete"] and len(result["matches"]) == 1
    assert first.cache is not second.cache
    assert second._source_executor.engine.check.__self__ is second


def test_body_context_is_shared_but_pattern_results_and_callbacks_are_not(monkeypatch):
    from ken.kql2.body import BodyEngine

    calls = []
    original = BodyEngine.match_context
    def build(self, owner, region):
        calls.append(owner.local_id)
        return original(self, owner, region)
    monkeypatch.setattr(BodyEngine, "match_context", build)
    index = query_graph(graph())
    resources = ExecutionResources(index)
    first = Executor(index, {}, resources=resources)
    assert len(first.execute(compile_source(QUERY))["matches"]) == 1
    first.close()
    second = Executor(index, {}, resources=resources)
    result = second.execute(compile_source(QUERY.replace("return 1", "return 2")))
    assert result["complete"] and result["matches"] == []
    assert len(calls) == 1
    assert resources.body_contexts.stats()["hits"] == 1
    assert second._source_executor.engine.check.__self__ is second
    second.close()


def test_resources_reject_another_snapshot_and_remain_lazy():
    index = FactIndex(IR("sample", "python"))
    resources = ExecutionResources(index)
    Executor(index, {}, resources=resources)
    assert "source_view" not in vars(resources)
    with pytest.raises(ValueError, match="different FactIndex"):
        Executor(FactIndex(index.ir), {}, resources=resources)


def test_closed_query_releases_callback_cycles_without_collecting_the_graph():
    import gc
    import weakref

    index = query_graph(graph())
    resources = ExecutionResources(index)
    collecting = gc.isenabled()
    gc.disable()
    try:
        engine = Executor(index, {}, resources=resources)
        result = engine.execute(compile_source(QUERY))
        assert result["complete"]
        retained = weakref.ref(engine)
        view = resources.source_view
        engine.close()
        engine.close()
        del engine
        assert retained() is None
        assert resources.source_view is view
    finally:
        if collecting:
            gc.enable()


def test_closed_native_initializer_releases_callback_cycle():
    import gc
    import weakref

    from ken.structural_store import Store
    from tests.kql2.test_graph_columns import stored
    from tests.structural.test_declaration_initializer_coverage import QUERY as INITIALIZER

    memory = query_graph(link_project([lower_source(
        "class Shared { static Shared instance = new Shared(); }", "java", "a.java"
    )]))
    with Store() as store:
        index = stored(store, memory.ir)
        collecting = gc.isenabled()
        gc.disable()
        try:
            engine = Executor(index, {})
            assert engine.execute(compile_source(INITIALIZER))["matches"]
            retained = weakref.ref(engine)
            engine.close()
            del engine
            assert retained() is None
        finally:
            if collecting:
                gc.enable()
