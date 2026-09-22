"""Project derivations use indexes instead of repeated repository scans."""

from ken.structural.effects import concurrency_effects
from ken.structural.model import IR, Entity, Fact, Operation
from ken.structural.syntax_graph import syntax_contexts


class CountedFacts(list):
    scans = 0

    def __iter__(self):
        self.scans += 1
        return super().__iter__()


class CountedEntities(dict):
    lookups = 0

    def __getitem__(self, key):
        self.lookups += 1
        return super().__getitem__(key)


def test_context_creation_lookup_does_not_scan_the_graph_per_start():
    graph = IR("sample.py", "python")
    graph.entities["threading"] = Entity("threading", "STORAGE", "threading", graph.path, 1, 1)
    graph.entities["create"] = Entity("create", "CALL", "Thread", graph.path, 2, 2)
    graph.add("sample.py::module", "IMPORT_SYNTAX", "import threading", language="python")
    graph.add("create", "CALLEE_NAME", "Thread")
    graph.add("create", "RECEIVER", "threading")
    for i in range(100):
        graph.entities[f"start{i}"] = Entity(f"start{i}", "CALL", "start", graph.path, 3, 3)
        graph.add(f"slot{i}", "ASSIGNED_FROM", "create")
        graph.add(f"start{i}", "RECEIVER", f"slot{i}")
        graph.add(f"start{i}", "CALLEE_NAME", "start")
    graph.facts.extend(Fact(str(i), "NOISE", "value") for i in range(1000))
    graph.facts = CountedFacts(graph.facts)
    concurrency_effects(graph)
    assert graph.facts.scans <= 4
    starts = [fact for fact in graph.facts if fact.relation == "STARTS_CONTEXT"]
    assert len(starts) == 100
    assert {fact.object for fact in starts} == {"create"}


def test_call_location_index_excludes_unrelated_syntax_nodes():
    graph = IR("sample.py", "python")
    graph.entities = CountedEntities({
        "f": Entity("f", "CALLABLE", "f", graph.path, 1, 5),
        "call": Entity("call", "CALL", "work", graph.path, 2, 2,
                       {"start_byte": 10, "end_byte": 20, "native_kind": "call_expression", "language": "python"}),
    })
    graph.operations = [
        Operation("body", "BLOCK", "block", None, "body", 0, 100, 1, "f"),
        Operation("statement", "EXPRESSION", "expression_statement", "body", "", 10, 21, 2, "f"),
        Operation("call_op", "CALL", "call_expression", "statement", "", 10, 20, 2, "f"),
    ]
    graph.operations += [Operation(f"noise{i}", "VALUE", "identifier", "body", "", 30, 31, 3, "f") for i in range(1000)]
    syntax_contexts(graph)
    assert graph.entities.lookups == 1
    assert any(fact.subject == "statement" and fact.relation == "DISCARDS_RESULT" and fact.object == "call" for fact in graph.facts)
    assert sum(fact.relation == "SYNTAX_PARENT" for fact in graph.facts) == 1002
