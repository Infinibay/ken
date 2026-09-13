"""Logical negations preserve null-test polarity without boolean decomposition."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import builtin_rules,named_rule,execute_rules,SavedRule
from .test_cache_aside import SOURCES

LANGUAGES=['python','java','javascript','typescript','csharp']


def expression(language,case):
    py=language=='python';null='None' if py else 'null';eq=' is ' if py else ' == ';ne=' is not ' if py else ' != ';neg='not ' if py else '!'
    a='value'+eq+null;b='value'+ne+null
    return {'eq':a,'ne':b,'not-eq':neg+'('+a+')','not-ne':neg+'('+b+')',
            'double-not':neg+'('+neg+'('+a+'))','reversed':null+eq+'value','parentheses':'(('+a+'))',
            'truth':neg+'value','and':a+(' and flag' if py else ' && flag'),
            'or':a+(' or flag' if py else ' || flag'),'numeric':'-('+a+')',
            'two-values':'value == other'}[case]


def source(language,condition):
    if language=='python':return 'def f(value,other,flag):\n if '+condition+':\n  return 1\n else:\n  return 0\n'
    if language in {'javascript','typescript'}:return 'function f(value,other,flag){if('+condition+'){return 1;}else{return 0;}}'
    return 'class C{int f(Object value,Object other,bool flag){if('+condition+'){return 1;}else{return 0;}}}'


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('case,when,negated',[
 ('eq','true',False),('ne','false',False),('not-eq','false',True),('not-ne','true',True),
 ('double-not','true',False),('reversed','true',False),('parentheses','true',False),
 ('truth',None,None),('and',None,None),('or',None,None),('numeric',None,None),('two-values',None,None)])
def test_null_polarity_and_excluded_expressions(language,case,when,negated):
    text=source(language,expression(language,case));g=IR.from_dict(link_project([lower_source(text,language,'predicate')]).to_dict());assert not g.diagnostics
    facts=[f for f in g.facts if f.relation=='NULL_TEST']
    if when is None:assert not facts
    else:
        assert len(facts)==1 and facts[0].attrs['when']==when and facts[0].attrs['negated']==negated
        assert g.entities[facts[0].object].name=='value'
        arms=[f for f in g.facts if f.subject==facts[0].subject and f.relation in {'BRANCH_TRUE','BRANCH_FALSE'}];assert len(arms)==2
        q=SavedRule('predicate',f'query predicate {{require $branch NULL_TEST $value [when:{when},negated:{str(negated).lower()}];emit $branch,$value;}}')
        out=execute_rules(g,[q]);assert out['complete'] and len(out['matches'])==1


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('depth',[32,33])
def test_negation_normalization_is_bounded(language,depth):
    neg='not ' if language=='python' else '!';condition=expression(language,'eq')
    for _ in range(depth):condition=neg+'('+condition+')'
    g=link_project([lower_source(source(language,condition),language,'bounded')]);facts=[f for f in g.facts if f.relation=='NULL_TEST']
    assert bool(facts)==(depth==32)


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('meaning',['miss','hit'])
def test_cache_aside_uses_the_same_negated_null_evidence(language,meaning):
    text=SOURCES[language];py=language=='python';null='None' if py else 'null'
    old='value is None' if py else 'value === null' if language in {'javascript','typescript'} else 'value == null'
    assert old in text
    comparison='value'+((' is not ' if meaning=='miss' else ' is ') if py else (' != ' if meaning=='miss' else ' == '))+null
    if language in {'javascript','typescript'}:comparison=comparison.replace(' != ',' !== ').replace(' == ',' === ')
    text=text.replace(old,('not ' if py else '!')+'('+comparison+')')
    g=link_project([lower_source(text,language,'cache')]);rs=builtin_rules();out=execute_rules(g,[named_rule('architecture.cache-aside',rs)],registry=rs)
    assert out['complete'] and bool(out['matches'])==(meaning=='miss')
