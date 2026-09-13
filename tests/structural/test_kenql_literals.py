"""Quoted graph endpoints must survive joins and query composition literally."""
import json

import pytest

from ken.structural.kenql import Engine, parse
from ken.structural.model import FactIndex, IR
from ken.structural.query import _bind, _resolve


@pytest.mark.parametrize('literal', ['Clone', '$handler', '_', '@unit', 'A|B',
                                     'a b', 'a"b', 'a\\b', 'ñ\n雪', ''])
@pytest.mark.parametrize('subject', [False, True])
def test_literal_endpoints_are_exact_in_named_queries(literal, subject):
    ir = IR('test', 'mixed')
    ir.add(literal if subject else 'hit', 'TYPE_NAME', 'hit' if subject else literal)
    ir.add('noise', 'TYPE_NAME', 'noise')
    endpoint = json.dumps(literal)
    clause = f'{endpoint} TYPE_NAME $result' if subject else f'$result TYPE_NAME {endpoint}'
    child = parse(f'query child {{ require {clause}; emit result=$result; }}')
    root = parse('query root { match "child"(result:$handler); emit $handler; }')
    outcome = Engine(FactIndex(ir), {'child': child}).execute(root)
    assert outcome['complete']
    assert [hit['bindings'] for hit in outcome['matches']] == [{'$handler': 'hit'}]


def test_quoted_kind_constraint_agrees_with_selector():
    ir = IR('test', 'mixed')
    ir.add('A', 'ENTITY', 'CLASS')
    query = parse('query q { type_decl() as $x; require $x ENTITY "CLASS"; emit $x; }')
    assert Engine(FactIndex(ir), {}).execute(query)['matches'][0]['bindings'] == {'$x': 'A'}


def test_literal_path_endpoints_and_proof():
    ir = IR('test', 'mixed')
    ir.add('$start', 'VALUE_FLOW', 'middle')
    ir.add('middle', 'VALUE_FLOW', '_')
    query = parse('query q { path "$start" VALUE_FLOW{2,2} "_" as $proof; emit $proof; }')
    hits = Engine(FactIndex(ir), {}).execute(query)['matches']
    assert len(hits) == 1
    assert json.loads(hits[0]['bindings']['$proof']) == ['$start', 'middle', '_']


@pytest.mark.parametrize('clause', [r'require $x TYPE_NAME "bad\q";',
                                     r'path "bad\q" VALUE_FLOW{1,2} $x as $p;'])
def test_bad_json_escape_rejected_before_execution(clause):
    with pytest.raises(ValueError):
        parse(f'query q {{ {clause} emit $x; }}')


def test_quoted_dollar_does_not_bind_export():
    with pytest.raises(ValueError, match='positively bound'):
        parse('query q { require "root" TYPE_NAME "$handler"; emit $handler; }')


def test_legacy_term_helpers_preserve_wildcards_and_alternatives():
    bindings = {}
    assert _resolve('_', bindings) is None
    assert _bind('_', 'anything', bindings)
    assert _bind('A|B', 'B', bindings)
    assert _bind('$x', 'value', bindings)
    assert _resolve('$x', bindings) == 'value'
