"""Exact counts describe explicit write events per callable, not executions."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import SavedRule,execute_rules


@pytest.mark.parametrize('language',['python','javascript','typescript','java','csharp'])
@pytest.mark.parametrize('count',[0,1,2,3])
def test_explicit_parameter_write_counts(language,count):
    statements=['key=other' for _ in range(count)]
    if language=='python':source='def f(key,other):\n'+''.join(' '+s+'\n' for s in statements)+' return key\n'
    elif language in {'javascript','typescript'}:source='function f(key,other){'+';'.join(statements)+';return key;}'
    else:source='class A{int f(int key,int other){'+';'.join(statements)+';return key;}}'
    graph=link_project([lower_source(source,language,'counts')]);assert not graph.diagnostics
    graph=IR.from_dict(graph.to_dict())
    owner=next(e.id for e in graph.entities.values() if e.kind=='CALLABLE' and e.name=='f')
    key=next(e.id for e in graph.entities.values() if e.kind=='PARAMETER' and e.name=='key')
    facts=[f for f in graph.facts if f.relation=='BINDING_WRITE_COUNT' and f.subject==owner and f.object==key]
    assert len(facts)==1 and facts[0].attrs['count']==count,facts
    query='query q { parameter(name:"key") as $key; require $owner BINDING_WRITE_COUNT $key [count:'+str(count)+']; emit $owner,$key; }'
    out=execute_rules(graph,[SavedRule('count',query)]);assert out['complete'] and len(out['matches'])==1,out


def test_counts_include_mutually_exclusive_and_dead_source_writes():
    source='def f(key,flag):\n if flag:\n  value=key\n else:\n  value=key\n return value\n value=key\n'
    graph=link_project([lower_source(source,'python','branches')]);assert not graph.diagnostics
    result=next(e.id for e in graph.entities.values() if e.name=='value')
    facts=[f for f in graph.facts if f.relation=='BINDING_WRITE_COUNT' and f.object==result]
    assert len(facts)==1 and facts[0].attrs['count']==3


def test_field_counts_do_not_merge_methods():
    source='class A:\n def first(self,value): self.field=value\n def second(self,value):\n  self.field=value\n  self.field=value\n def read(self): return self.field\n'
    graph=link_project([lower_source(source,'python','owners')]);assert not graph.diagnostics
    field=next(e.id for e in graph.entities.values() if e.name=='field')
    counts={graph.entities[f.subject].name:f.attrs['count'] for f in graph.facts if f.relation=='BINDING_WRITE_COUNT' and f.object==field}
    assert counts=={'first':1,'second':2,'read':0}


@pytest.mark.parametrize('body',['key+=other','key,other=other,key','exec(code)','while key: key=other'])
def test_unsupported_body_does_not_publish_exact_zero_or_count(body):
    graph=link_project([lower_source('def f(key,other):\n '+body+'\n return key\n','python','unsupported')]);assert not graph.diagnostics
    assert not [f for f in graph.facts if f.relation=='BINDING_WRITE_COUNT']
