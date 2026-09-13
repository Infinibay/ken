"""Parsing reuse belongs to a request, while validation and fresh edits remain visible."""
from collections import Counter

import pytest

from ken.structural import kenql
from ken.structural.model import IR
from ken.structural.rules import SavedRule, builtin_rules, execute_rules, query_registry, select_rules


def test_batch_parses_each_distinct_query_source_once(monkeypatch):
    registry = builtin_rules()
    rules = select_rules(registry, collections=['gof', 'modern'])
    original = kenql.parse
    counts = Counter()

    def counting(source):
        counts[source] += 1
        return original(source)

    monkeypatch.setattr(kenql, 'parse', counting)
    result = execute_rules(IR('', ''), rules, registry=registry)
    assert result['complete']
    assert counts
    assert set(counts.values()) == {1}, counts


def test_compiled_libraries_do_not_share_mutable_asts():
    rule = SavedRule('team.example', 'query example { callable() as $f; emit $f; }')
    first = query_registry([rule])
    first['team.example'].exports.clear()
    first['team.example'].nodes.clear()
    second = query_registry([rule])
    assert second['team.example'].exports == {'f': '$f'}
    assert second['team.example'].nodes


def test_live_rule_edit_is_not_hidden_by_compilation_reuse():
    rule = SavedRule('team.example', 'query example { require "a" ENTITY "CLASS"; emit; }')
    # Use a bound export: an empty graph initially cannot satisfy the selector.
    rule.query = 'query example { class() as $unit; emit $unit; }'
    graph = IR('', '')
    graph.add('f', 'ENTITY', 'CALLABLE')
    assert not execute_rules(graph, [rule])['matches']
    rule.query = 'query example { callable() as $unit; emit $unit; }'
    assert execute_rules(graph, [rule])['matches'][0]['bindings'] == {'$unit': 'f'}
    rule.query = 'query broken {'
    with pytest.raises(ValueError):
        execute_rules(graph, [rule])


def test_validation_still_rejects_invalid_ready_variant():
    rule = SavedRule('team.example', 'query example { callable() as $f; emit $f; }',
                     variants=[{'id': 'invalid', 'status': 'ready', 'query': 'query broken {'}])
    with pytest.raises(ValueError):
        execute_rules(IR('', ''), [rule])


def test_reused_source_does_not_bypass_each_rules_metadata_validation():
    query = 'query example { callable() as $f; emit $f; }'
    with pytest.raises(ValueError, match='rule id'):
        execute_rules(IR('', ''), [SavedRule('valid', query), SavedRule('bad id', query)])
