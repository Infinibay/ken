"""Explicit argument bindings preserve callsite and parameter identity."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.kenql import query_graph
from ken.structural.model import IR


def analyze(text,language='python'):
    graph=link_project([lower_source(text,language,'bindings')])
    assert not graph.diagnostics
    return graph


def bound_pairs(graph):
    parameters={f.subject:f.object for f in graph.facts if f.relation=='BINDING_PARAMETER'}
    values={f.subject:f.object for f in graph.facts if f.relation=='BINDING_VALUE'}
    return [(f.subject,f.object,graph.entities[parameters[f.object]].name,values[f.object],f.attrs)
            for f in graph.facts if f.relation=='CALL_BINDING']


SOURCES={
 'python':'class Packet:\n def __init__(self,x,y): self.x=x\nPacket(1,2)\nPacket(3,4)\n',
 'javascript':'class Packet{constructor(x,y){this.x=x;}} new Packet(1,2);new Packet(3,4);',
 'typescript':'class Packet{x:number;constructor(x:number,y:number){this.x=x;}} new Packet(1,2);new Packet(3,4);',
 'java':'class Packet{int x;Packet(int x,int y){this.x=x;}} class Main{void run(){new Packet(1,2);new Packet(3,4);}}',
 'csharp':'class Packet{int x;public Packet(int x,int y){this.x=x;}} class Main{void run(){new Packet(1,2);new Packet(3,4);}}',
}


@pytest.mark.parametrize('language',SOURCES)
def test_each_constructor_call_has_its_own_argument_bindings(language):
    graph=analyze(SOURCES[language],language)
    pairs=bound_pairs(graph)
    assert len(pairs)==4 and len({p[1] for p in pairs})==4 and len({p[0] for p in pairs})==2
    assert [p[2] for p in pairs]==['x','y','x','y']
    args={(f.subject,f.attrs['position']):f.object for f in graph.facts if f.relation=='ARGUMENT'}
    assert all(args[call,attrs['position']]==value for call,_,_,value,attrs in pairs)
    assert len([f for f in graph.facts if f.relation=='CONSTRUCTOR_TARGET'])==2


@pytest.mark.parametrize('call,count',[
 ('f(1,2)',2),('f(1,y=2)',2),('f(y=2,x=1)',2),('f(1)',1),
 ('f(x=1)',1),('f(1,2,3)',0),('f(1,x=2)',0),('f(z=1)',0),('f()',0),
 ('f(*items)',0),('f(**items)',0),
])
def test_python_named_default_missing_duplicate_and_expanded_arguments(call,count):
    graph=analyze('def f(x,y=0): return x\n'+call+'\n')
    pairs=bound_pairs(graph)
    assert len(pairs)==count
    statuses=[f.object for f in graph.facts if f.relation=='BINDING_STATUS']
    assert statuses==['supported' if count else 'unsupported']
    if count:
        assert {p[2] for p in pairs}==({'x','y'} if count==2 else {'x'})


@pytest.mark.parametrize('signature,call,expected',[
 ('x, /, *, y','f(1,y=2)',True),('x, /, *, y','f(x=1,y=2)',False),
 ('x, /, *, y','f(1,2)',False),('x, *, y=0','f(1)',True),
 ('*values','f(1,2)',False),('**values','f(x=1)',False),
])
def test_python_parameter_modes_are_not_scalar_positional_guesses(signature,call,expected):
    graph=analyze('def f('+signature+'): pass\n'+call+'\n')
    assert bool(bound_pairs(graph))==expected


@pytest.mark.parametrize('language',['java','csharp'])
def test_overloaded_constructors_remain_ambiguous(language):
    text='class P {public P(int x){} public P(string x){}} class Main{void run(){new P(1);}}'
    if language=='java':text=text.replace('string','String')
    graph=analyze(text,language)
    assert not bound_pairs(graph)
    assert not any(f.relation=='CONSTRUCTOR_TARGET' for f in graph.facts)
    assert len([f for f in graph.facts if f.relation=='MAY_CONSTRUCTOR_TARGET'])==2


@pytest.mark.parametrize('text',[
 'class P: pass\nP()\n',
 'class Base:\n def __init__(self,x): pass\nclass P(Base): pass\nP(1)\n',
 'class P:\n def __new__(cls,x): return object.__new__(cls)\n def __init__(self,x): pass\nP(1)\n',
])
def test_implicit_inherited_and_custom_python_construction_not_guessed(text):
    graph=analyze(text)
    assert not any(f.relation=='CONSTRUCTOR_TARGET' for f in graph.facts)


def test_same_value_used_in_different_calls_does_not_merge_binding_nodes():
    graph=analyze('def f(x,y): pass\nvalue=1\nf(value,value)\nf(value,value)\n')
    pairs=bound_pairs(graph)
    assert len(pairs)==4 and len({p[1] for p in pairs})==4 and len({p[3] for p in pairs})==1
    view=query_graph(graph).ir
    assert {f.object for f in view.facts if f.relation=='CALL_BINDING'}=={p[1] for p in pairs}
    assert query_graph(IR.from_dict(view.to_dict())).ir.to_dict()==view.to_dict()


@pytest.mark.parametrize('call,expected',[
 ('new P(y:2,x:1)',2),('new P(1,y:2)',2),('new P(1)',1),
 ('new P(z:2)',0),('new P(1,x:2)',0),
])
def test_csharp_named_and_default_arguments(call,expected):
    graph=analyze('class P{public P(int x,int y=0){}}class Main{void run(){'+call+';}}','csharp')
    assert len(bound_pairs(graph))==expected


def test_unresolved_named_function_does_not_acquire_bindings():
    graph=analyze('missing(1)\n')
    assert not bound_pairs(graph)


def test_constructor_binding_resolves_across_python_import_alias():
    graph=link_project([lower_source('class Snapshot:\n def __init__(self,value): self.saved=value\n','python','snap.py'),
                        lower_source('from snap import Snapshot as S\ns=S(1)\n','python','main.py')])
    pairs=bound_pairs(graph)
    assert len(pairs)==1 and pairs[0][2]=='value'
