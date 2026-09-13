"""Simple truth predicates retain polarity and do not absorb boolean combinations."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import SavedRule,execute_rules

LANGUAGES=['python','javascript','typescript','java','csharp']


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('form,polarity',[
 ('binding','true'),('call','true'),('member','true'),('parentheses','true'),
 ('negative','false'),('double-negative','true'),('conjunction',None),
 ('disjunction',None),('comparison',None),('numeric-negation',None),
])
def test_truth_predicates(language,form,polarity):
    yes='flag';no='not ' if language=='python' else '!'
    expressions={'binding':yes,'call':'probe(flag)','member':'object.flag',
                 'parentheses':'((probe(flag)))','negative':no+'(probe(flag))',
                 'double-negative':no+'('+no+'probe(flag))',
                 'conjunction':'probe(flag)'+(' and other' if language=='python' else ' && other'),
                 'disjunction':'probe(flag)'+(' or other' if language=='python' else ' || other'),
                 'comparison':'probe(flag) == other','numeric-negation':'-probe(flag)'}
    expression=expressions[form]
    if language=='python':source='def f(flag,other,object):\n if '+expression+':\n  return 1\n else:\n  return 0\n'
    elif language in {'javascript','typescript'}:source='function f(flag,other,object){if('+expression+'){return 1;}else{return 0;}}'
    else:source='class A{int f(bool flag,bool other,A object){if('+expression+'){return 1;}else{return 0;}}}'
    graph=link_project([lower_source(source,language,'truth')]);assert not graph.diagnostics
    graph=IR.from_dict(graph.to_dict())
    facts=[f for f in graph.facts if f.relation=='TRUTH_TEST']
    if polarity is None:assert not facts
    else:
        assert len(facts)==1 and facts[0].attrs['when']==polarity,facts
        assert facts[0].attrs['basis']=='condition-syntax'
        arms=[f for f in graph.facts if f.subject==facts[0].subject and f.relation in {'BRANCH_TRUE','BRANCH_FALSE'}]
        assert {f.relation for f in arms}=={'BRANCH_TRUE','BRANCH_FALSE'}
        if form in {'call','parentheses','negative','double-negative'}:assert graph.entities[facts[0].object].kind=='CALL'
        q='query q { require $branch TRUTH_TEST $predicate [when: '+polarity+']; emit $branch,$predicate; }'
        out=execute_rules(graph,[SavedRule('truth',q)]);assert out['complete'] and len(out['matches'])==1
