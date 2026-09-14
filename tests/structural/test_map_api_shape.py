"""A dictionary read or written through its API is the same fact as a subscript.

The canonical Java example of a pool is::

    private static Map<String, TreeType> treeTypes = new HashMap<>();
    TreeType getTreeType(String name, ...) {
        TreeType result = treeTypes.get(name);
        if (result == null) {
            result = new TreeType(name, ...);
            treeTypes.put(name, result);          // write
        }
        return result;                            // no subscript anywhere
    }

There is no index expression in that method, so before IR 1.73 the graph held a
map field, a read and a write that nothing connected, and Flyweight read 0/8 on
the RefactoringGuru corpora while the subscript spelling of the same pool was
detected.
"""
from __future__ import annotations

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

JAVA = '''import java.util.HashMap;
import java.util.Map;

class Tree {
    Tree(String name) { }
}

class TreeFactory {
    private static Map<String, Tree> treeTypes = new HashMap<>();

    public static Tree getTreeType(String name) {
        Tree result = treeTypes.get(name);
        if (result == null) {
            result = new Tree(name);
            treeTypes.put(name, result);
        }
        return result;
    }
}
'''

JAVA_LOCAL = '''import java.util.HashMap;
import java.util.Map;

class TreeFactory {
    private Map<String, Tree> treeTypes = new HashMap<>();

    Tree getTreeType(String name) {
        Map<String, Tree> local = new HashMap<>();
        return local.get(name);
    }
}
'''

JAVA_PARAMETER = '''import java.util.HashMap;
import java.util.Map;

class TreeFactory {
    private Map<String, Tree> treeTypes = new HashMap<>();

    Tree getTreeType(Map<String, Tree> incoming, String name) {
        return incoming.get(name);
    }
}
'''

JAVA_SETTER = '''class Config {
    private int value;

    void apply(Config other, int incoming) {
        other.set(incoming);
    }
}
'''

PYTHON = '''class Tree:
    def __init__(self, name): self.name = name

class TreeFactory:
    def __init__(self): self.trees = {}
    def get_tree(self, name):
        result = self.trees.get(name)
        if result is None:
            result = Tree(name)
            self.trees[name] = result
        return result
'''


def facts(language, source, extension):
    graph = link_project([lower_source(source, language, f"sample.{extension}")])
    assert not graph.diagnostics, graph.diagnostics
    return graph


def labels(graph, relation):
    return {fact.subject for fact in graph.facts if fact.relation == relation}


def test_a_map_read_and_write_on_a_field_publish_the_pool_facts():
    graph = facts("java", JAVA, "java")
    lookups = [f for f in graph.facts if f.relation == "LOOKS_UP"]
    writes = [f for f in graph.facts if f.relation == "WRITES_ELEMENT"]
    assert lookups and writes
    assert all(f.object.endswith("/STORAGE:treeTypes") for f in lookups + writes)
    # The read is an access with a container and an index, like any subscript.
    reads = [f for f in graph.facts if f.relation == "CONTAINER"]
    assert any(f.subject.endswith("/CALL:") or "/CALL:" in f.subject for f in reads)
    assert {f.relation for f in graph.facts} >= {"CONTAINER", "INDEX", "STORES_VALUE"}


def test_the_reads_and_writes_are_published_for_the_callable_too():
    graph = facts("java", JAVA, "java")
    for relation in ("LOOKS_UP", "WRITES_ELEMENT"):
        assert any("/CALLABLE:" in subject for subject in labels(graph, relation))


def test_a_map_on_a_local_or_a_parameter_is_not_a_pool():
    for source in (JAVA_LOCAL, JAVA_PARAMETER):
        graph = facts("java", source, "java")
        assert not [f for f in graph.facts if f.relation == "LOOKS_UP"]


def test_a_one_argument_setter_is_not_an_indexed_write():
    graph = facts("java", JAVA_SETTER, "java")
    assert not [f for f in graph.facts if f.relation == "WRITES_ELEMENT"]


def test_the_python_spelling_of_the_same_pool_also_publishes_them():
    graph = facts("python", PYTHON, "py")
    assert labels(graph, "LOOKS_UP")
    assert any(f.object.endswith("/STORAGE:trees") for f in graph.facts if f.relation == "WRITES_ELEMENT")


def test_the_canonical_java_pool_is_detected_end_to_end():
    graph = facts("java", JAVA, "java")
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule("flyweight#explicit-interning", registry)],
                           registry=registry, evidence_mode="strict")
    assert result["complete"], result["outcomes"]
    assert len(result["matches"]) == 1
    assert result["matches"][0]["bindings"]["$unit"].endswith("CLASS:TreeFactory")


def test_the_catalog_still_declares_only_ready_variants_with_queries():
    rule = next(r for r in _load_catalog() if r.id == "flyweight")
    for variant in rule.variants:
        assert variant.get("status") == "ready"
        assert variant.get("query", "").strip()
