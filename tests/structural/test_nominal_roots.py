"""Explicit nominal roots preserve missing-base and graph-shape uncertainty."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import SavedRule,execute_rules

LANGUAGES=['python','javascript','typescript','java','csharp']

def classes(language,definitions):
    text=''
    for name,bases in definitions:
        if language=='python':text+='class '+name+('('+','.join(bases)+')' if bases else '')+': pass\n'
        else:text+='class '+name+(' '+(':' if language=='csharp' else 'extends')+' '+','.join(bases) if bases else '')+' {}\n'
    return text


def graph_of(language,definitions):
    graph=link_project([lower_source(classes(language,definitions),language,'roots')]);assert not graph.diagnostics
    return IR.from_dict(graph.to_dict())


def facts(graph,relation):
    return {graph.entities[f.subject].name:(graph.entities[f.object].name if f.object in graph.entities else f.object) for f in graph.facts if f.relation==relation}


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('case',['single','chain','independent','missing','cycle'])
def test_root_and_unavailable_cases(language,case):
    definitions={'single':[('A',[])], 'chain':[('A',[]),('B',['A']),('C',['B'])],
      'independent':[('A',[]),('B',[])], 'missing':[('A',['External']),('B',['A'])],
      'cycle':[('A',['B']),('B',['A'])]}[case]
    graph=graph_of(language,definitions);roots=facts(graph,'NOMINAL_ROOT');status=facts(graph,'NOMINAL_ROOT_STATUS')
    expected={'single':{'A':'A'},'chain':{'A':'A','B':'A','C':'A'},'independent':{'A':'A','B':'B'},'missing':{},'cycle':{}}[case]
    assert roots==expected
    assert set(status.values())==({'supported'} if expected else {'unsupported'})
    out=execute_rules(graph,[SavedRule('roots','query q { require $type NOMINAL_ROOT $root; emit $type,$root; }')]);assert out['complete'] and len(out['matches'])==len(expected)


@pytest.mark.parametrize('definition',[ [('A',[]),('B',[]),('C',['A','B'])], [('A',[]),('B',['A']),('C',['A']),('D',['B','C'])]])
def test_multiple_roots_and_shared_diamond(definition):
    graph=graph_of('python',definition);roots=facts(graph,'NOMINAL_ROOT');status=facts(graph,'NOMINAL_ROOT_STATUS')
    if definition[-1][0]=='C':assert status['C']=='unsupported' and 'C' not in roots
    else:assert roots['D']=='A' and status['D']=='supported'


def test_deep_chain_does_not_poison_shorter_root_queries():
    definitions=[('N00',[])]+[(f'N{i:02d}',[f'N{i-1:02d}']) for i in range(1,35)]
    graph=graph_of('python',definitions);roots=facts(graph,'NOMINAL_ROOT');status=facts(graph,'NOMINAL_ROOT_STATUS')
    assert roots['N31']=='N00' and status['N32']=='unsupported'
    assert status['N34']=='unsupported' and roots['N01']=='N00'


def test_shared_diamond_paths_are_bounded_without_enumeration():
    definitions=[('Root',[])];parents=['Root']
    for i in range(20):
        current=[f'L{i:02d}',f'R{i:02d}'];definitions.extend((name,parents) for name in current);parents=current
    graph=graph_of('python',definitions)
    assert len(facts(graph,'NOMINAL_ROOT'))==41
    assert set(facts(graph,'NOMINAL_ROOT').values())=={'Root'}


def test_parsing_diagnostics_do_not_publish_exact_roots():
    graph=link_project([lower_source('class A( :','python','broken')]);assert graph.diagnostics
    assert not facts(graph,'NOMINAL_ROOT')
