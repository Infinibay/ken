"""C++ writes a pool entry as ``insert(std::make_pair(key, value))``.

One argument that *is* the pair. Reading the key and the value out of it is what
publishes the indexed write; accepting any single argument would read a property
setter (``obj.set(x)``) as a write, which is why the unpacking asks for a pair
construction by name.
"""
from __future__ import annotations

from ken.structural.frontend import lower_source

PAIR = b'''#include <unordered_map>
#include <string>

class Factory {
    std::unordered_map<std::string, Value> entries_;
public:
    Value Get(const std::string &key) {
        if (this->entries_.find(key) == this->entries_.end()) {
            this->entries_.insert(std::make_pair(key, Value(key)));
        }
        return this->entries_.find(key)->second;
    }
};
'''

SETTER = b'''class Config {
    int value_;

public:
    void Apply(Config other, int incoming) {
        other.set(incoming);
    }
};
'''


def facts(source, name="sample.cpp"):
    graph = lower_source(source, "cpp", name)
    assert not graph.diagnostics, graph.diagnostics
    return graph


def test_a_pair_insert_publishes_an_indexed_write():
    graph = facts(PAIR)
    writes = [fact for fact in graph.facts if fact.relation == "WRITES_ELEMENT"]
    assert any(fact.object.endswith("/STORAGE:entries_") for fact in writes)
    indexed = [fact for fact in graph.facts if fact.relation == "INDEX" and "/CALL:" in fact.subject]
    stored = [fact for fact in graph.facts if fact.relation == "STORES_VALUE" and "/CALL:" in fact.subject]
    assert indexed and stored
    # The value is the construction, not the pair wrapper.
    assert any(fact.object.endswith("/CALL:") or "/CALL:" in fact.object for fact in stored)


def test_a_find_on_the_field_is_a_lookup():
    graph = facts(PAIR)
    lookups = [fact for fact in graph.facts if fact.relation == "LOOKS_UP"]
    assert any(fact.object.endswith("/STORAGE:entries_") for fact in lookups)


def test_a_one_argument_non_pair_call_is_not_an_indexed_write():
    graph = facts(SETTER)
    assert not [fact for fact in graph.facts if fact.relation == "WRITES_ELEMENT"]
