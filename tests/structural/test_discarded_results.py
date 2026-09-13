"""Only the outer call of a call statement has its result discarded."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


TEMPLATES={
 'python':'def f():\n BODY\n',
 'javascript':'function f(){BODY}',
 'typescript':'function f(){BODY}',
 'java':'class C{void f(){BODY}}',
 'csharp':'class C{void f(){BODY}}',
 'cpp':'void f(){BODY}',
 'go':'package p;func f(){BODY}',
 'rust':'fn f(){BODY}',
}


def discarded(language,body):
    graph=link_project([lower_source(TEMPLATES[language].replace('BODY',body),language,'sample')])
    assert not graph.diagnostics
    return [(graph.entities[f.object].attrs['name'],f.attrs['awaited'])
            for f in graph.facts if f.relation=='DISCARDS_RESULT']


@pytest.mark.parametrize('language',TEMPLATES)
def test_outer_call_only(language):
    assert discarded(language,'consume(produce());')==[('consume',False)]


@pytest.mark.parametrize('language',TEMPLATES)
def test_returned_call_is_not_discarded(language):
    assert discarded(language,'return produce();')==[]


@pytest.mark.parametrize('language',['python','javascript','typescript','cpp','csharp'])
def test_parenthesized_outer_call(language):
    assert discarded(language,'(produce());')==[('produce',False)]


@pytest.mark.parametrize('language,body',[
 ('python','x = produce()'),('javascript','let x=produce();'),('typescript','let x=produce();'),
 ('java','Object x=produce();'),('csharp','var x=produce();'),('cpp','auto x=produce();'),
 ('go','x:=produce()'),('rust','let x=produce();'),
])
def test_assigned_call_is_not_discarded(language,body):
    assert discarded(language,body)==[]


def test_rust_tail_call_produces_block_value():
    assert discarded('rust','produce()')==[]


@pytest.mark.parametrize('language,source',[
 ('python','async def f():\n await produce()\n'),
 ('javascript','async function f(){await produce();}'),
 ('typescript','async function f(){await produce();}'),
 ('csharp','class C{async Task f(){await produce();}}'),
 ('rust','async fn f(){produce().await;}'),
])
def test_awaited_statement_preserves_consumption_policy(language,source):
    graph=link_project([lower_source(source,language,'sample')])
    assert not graph.diagnostics
    facts=[f for f in graph.facts if f.relation=='DISCARDS_RESULT']
    assert len(facts)==1 and facts[0].attrs['awaited'] is True
