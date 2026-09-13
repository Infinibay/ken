"""Bounded reachability keeps exact first witnesses without enumerating all walks."""
import json
import random

import pytest

from ken.structural.kenql import Engine, Row, parse
from ken.structural.model import FactIndex, IR
from ken.structural.query import QueryBudget


def exhaustive(ir, start, low, high):
    """Small graph oracle: enumerate every walk, then retain first witnesses."""
    frontier = [(start, [start], False)]
    seen = set()
    result = []
    for depth in range(high + 1):
        next_frontier = []
        for target, witness, possible in frontier:
            if depth >= low and (target, possible) not in seen:
                seen.add((target, possible))
                result.append((target, witness, possible))
            if depth < high:
                for fact in ir.facts:
                    if fact.relation == 'VALUE_FLOW' and fact.subject == target:
                        next_frontier.append((fact.object, witness + [fact.object],
                                              possible or fact.attrs.get('modality') == 'may'))
        frontier = next_frontier
    return result


@pytest.mark.parametrize('seed', range(20))
@pytest.mark.parametrize('bounds', [(0, 0), (0, 4), (2, 4), (4, 4)])
def test_reachability_and_first_witness_equal_exhaustive_walks(seed, bounds):
    rng = random.Random(seed)
    ir = IR('', '')
    for _ in range(11):
        ir.add(str(rng.randrange(4)), 'VALUE_FLOW', str(rng.randrange(4)),
               modality=rng.choice(['must', 'may']))
    low, high = bounds
    query = parse(f'query q {{ path "0" VALUE_FLOW{{{low},{high}}} $end as $proof; emit $end, $proof; }}')
    engine = Engine(FactIndex(ir), {}, QueryBudget(timeout_ms=10000))
    rows = engine.run_nodes(query.nodes, [Row()])
    actual = [(r.bindings['$end'], json.loads(r.bindings['$proof']), bool(r.unknown)) for r in rows]
    assert actual == exhaustive(ir, '0', low, high)


def diamond(depth=18):
    ir = IR('', '')
    previous = ['root']
    for level in range(depth):
        current = [f'{level}:a', f'{level}:b']
        for source in previous:
            for target in current:
                ir.add(source, 'VALUE_FLOW', target)
        previous = current
    return ir


def test_convergent_paths_finish_under_small_work_budget():
    ir = diamond()
    query = parse('query q { path "root" VALUE_FLOW{18,18} $end as $proof; emit $end, $proof; }')
    result = Engine(FactIndex(ir), {}, QueryBudget(max_states=100, max_rows=100, timeout_ms=10000)).execute(query)
    assert result['complete'], result['unknown']
    assert {m['bindings']['$end'] for m in result['matches']} == {'17:a', '17:b'}
    assert result['stats']['rows_examined'] == 70
    for match in result['matches']:
        assert len(json.loads(match['bindings']['$proof'])) == 19


@pytest.mark.parametrize('mode,expected', [('strict', 1), ('possible', 2)])
def test_certain_and_possible_witnesses_remain_separate(mode, expected):
    ir = IR('', '')
    ir.add('a', 'VALUE_FLOW', 'b', modality='may')
    ir.add('a', 'VALUE_FLOW', 'c')
    ir.add('c', 'VALUE_FLOW', 'b')
    ir.add('b', 'VALUE_FLOW', 'd')
    query = parse('query q { path "a" VALUE_FLOW{2,3} "d" as $proof; emit $proof; }')
    result = Engine(FactIndex(ir), {}, evidence_mode=mode).execute(query)
    assert result['complete']
    assert len(result['matches']) == expected
    assert any(not m['unknown'] for m in result['matches'])


def test_cycle_can_reach_an_endpoint_again_at_required_minimum_length():
    ir = IR('', '')
    ir.add('a', 'VALUE_FLOW', 'b')
    ir.add('b', 'VALUE_FLOW', 'a')
    query = parse('query q { path "a" VALUE_FLOW{4,4} "a" as $proof; emit $proof; }')
    result = Engine(FactIndex(ir), {}).execute(query)
    assert json.loads(result['matches'][0]['bindings']['$proof']) == ['a', 'b', 'a', 'b', 'a']


@pytest.mark.parametrize('budget', [QueryBudget(max_rows=1), QueryBudget(max_states=1)])
def test_work_limits_still_report_incomplete(budget):
    result = Engine(FactIndex(diamond()), {}, budget).execute(
        parse('query q { path "root" VALUE_FLOW{18,18} $end as $proof; emit $end; }'))
    assert not result['complete']
    assert any(reason.startswith('budget:') for reason in result['unknown'])
