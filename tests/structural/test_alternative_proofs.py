"""Projection deduplication keeps alternative proofs without mixing witnesses."""
import pytest
from ken.structural.kenql import Engine, parse
from ken.structural.model import IR, FactIndex


def run(query, edges, library=None, mode='possible'):
    graph = IR('sample', 'mixed')
    for a,r,b,attrs in edges: graph.add(a,r,b,**attrs)
    return Engine(FactIndex(graph), {k:parse(q) for k,q in (library or {}).items()}, evidence_mode=mode).execute(parse(query))


def query_ids(value):
    if isinstance(value, dict):
        return ({value['query']} if 'query' in value else set()) | set().union(*(query_ids(v) for v in value.values()))
    if isinstance(value, list): return set().union(*(query_ids(v) for v in value))
    return set()


def test_named_variants_remain_visible_in_one_match():
    library = {'a':'query a { require $x A $w; emit unit=$x; }',
               'b':'query b { require $x B $w; emit unit=$x; }'}
    result = run('query q { any {match "a"(unit:$u);} or {match "b"(unit:$u);} emit $u; }',
                 [('same','A','one',{}),('same','B','two',{})], library)
    assert len(result['matches']) == 1
    assert query_ids(result['matches'][0]['evidence']) == {'a','b'}


def test_named_projection_keeps_alternatives_and_following_fact():
    library={'pair':'query p { require $x A $y; emit x=$x, y=$y; }'}
    result = run('query q { match "pair"(x:$x); require $x B $z; emit $x,$z; }',
                 [('a','A','b',{}),('a','A','c',{}),('a','B','z',{})],library)
    evidence = result['matches'][0]['evidence']
    assert len(evidence[0]['alternatives']) == 2
    assert evidence[-1]['relation'] == 'B'


@pytest.mark.parametrize('mode', ['strict','possible'])
def test_possible_proof_does_not_taint_certain_proof(mode):
    result=run('query q { require $x A $y; emit $x; }',
               [('a','A','b',{'modality':'may'}),('a','A','c',{})], mode=mode)
    hit=result['matches'][0]
    assert hit['status']=='structural_match' and hit['unknown']==[]
    if mode=='possible':
        assert {tuple(p['unknown']) for p in hit['evidence'][0]['alternatives']} == {(),('possible:A',)}


def test_projected_witnesses_are_not_cross_joined():
    library={'pair':'query p { require $x A $y; emit x=$x,y=$y; }'}
    result=run('query q {match "pair"(x:$x,y:$y); require $x B $y; emit $x,$y;}',
               [('a','A','b',{}),('c','A','d',{}),('a','B','d',{})],library)
    assert result['matches']==[]


def test_evidence_cap_is_explicit_and_not_result_truncation():
    result=run('query q { require $x A $y; emit $x; }', [('a','A',str(n),{}) for n in range(40)])
    assert result['complete'] and len(result['matches'])==1
    group=result['matches'][0]['evidence'][0]
    assert group['truncated'] is True and len(group['alternatives'])==16


def test_certain_named_proof_is_retained_after_many_possible_ones():
    library={'a':'query a {require $x A $y; emit x=$x;}'}
    edges=[('a','A',str(n),{'modality':'may'})for n in range(20)]+[('a','A','certain',{})]
    result=run('query q {match "a"(x:$x); emit $x;}',edges,library)
    assert result['matches'][0]['status']=='structural_match'
    group=result['matches'][0]['evidence'][0]
    assert group['truncated'] and group['alternatives'][0]['unknown']==[]
