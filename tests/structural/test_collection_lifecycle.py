"""Collection reset facts preserve syntax kind and same-block iteration order."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.kenql import query_graph
from ken.structural.model import IR
from ken.structural.rules import execute_rules, SavedRule


def analyze(source,language='python'):
    graph=link_project([lower_source(source,language,'lifecycle')]);assert not graph.diagnostics
    return graph


def after(graph):
    return [f for f in graph.facts if f.relation=='AFTER_ITERATION']


@pytest.mark.parametrize('source,expected',[
 ('def f(xs):\n for x in xs: x.run()\n xs=[]\n',True),
 ('def f(xs):\n for x in xs: x.run()\n xs.clear()\n',True),
 ('def f(xs):\n for x in xs: x.run()\n xs += []\n',False),
 ('def f(xs):\n for x in xs: x.run()\n xs.clear(1)\n',False),
 ('def f(xs):\n for x in xs: x.run()\n y=xs.clear()\n',False),
 ('def f(xs):\n xs=[]\n for x in xs: x.run()\n',False),
 ('def f(xs):\n for x in xs: x.run()\n if flag: xs=[]\n',False),
 ('def f(xs):\n for x in xs:\n  x.run()\n  xs=[]\n',False),
 ('def f(xs):\n for x in xs: x.run()\n return\n xs=[]\n',False),
 ('def f(xs):\n for x in xs: x.run()\n raise Error()\n xs=[]\n',False),
 ('def f(xs):\n for x in xs: x.run()\n def callback():\n  xs=[]\n',False),
 ('def f(xs):\n for x in xs: x.run()\ndef g(xs):\n xs=[]\n',False),
 ('def f(xs):\n for x in xs: x.run()\n xs=[1]\n',False),
 ('def f(xs):\n for x in xs: x.run()\n xs=list()\n',False),
 ('def f(xs):\n for x in xs: x.run()\n xs=[*other]\n',False),
 ('async def f(xs):\n for x in xs:\n  await x.run()\n xs=[]\n',True),
 ('def f(xs):\n for x in xs:\n  try: x.run()\n  except Error: pass\n xs=[]\n',True),
])
def test_reset_shapes_and_lexical_order(source,expected):
    graph=analyze(source)
    assert bool(after(graph))==expected


@pytest.mark.parametrize('language',['javascript','typescript','java','csharp'])
@pytest.mark.parametrize('shape',['after','before','branch','return','throw','inside','augmented','nonempty','other-function'])
def test_block_boundaries_in_braced_languages(language,shape):
    js=language in {'javascript','typescript'}
    loop='for (const item of xs) { item.run(); }' if js else ('for(Item item:xs){item.run();}' if language=='java' else 'foreach(Item item in xs){item.run();}')
    reset='xs=[];' if js else ('xs.clear();' if language=='java' else 'xs.Clear();')
    bodies={
      'after':loop+reset,
      'before':reset+loop,
      'branch':loop+'if(flag){'+reset+'}',
      'return':loop+'return;'+reset,
      'throw':loop+'throw new Error();'+reset,
      'inside':loop.replace('item.run();','item.run();'+reset),
      'augmented':loop+'xs += [];',
      'nonempty':loop+'xs=[1];',
      'other-function':loop,
    }
    if not js and shape in {'augmented','nonempty'}:
        bodies[shape]=loop+('xs.clear(1);' if language=='java' else 'xs.Clear(1);')
    body=bodies[shape]
    text='function f(xs){'+body+'}' if js else 'class C{void f(List<Item> xs){'+body+'}}'
    if shape=='other-function':
        text+=('function g(xs){'+reset+'}') if js else 'class D{void g(List<Item> xs){'+reset+'}}'
    graph=analyze(text,language)
    assert bool(after(graph))==(shape=='after')


@pytest.mark.parametrize('language,source,count',[
 ('python','def f():\n x=[]\n y=[1]\n z={}\n',2),
 ('javascript','function f(){let x=[];let y=[1];let z={};}',2),
 ('typescript','function f(){let x=[];let y=[1];let z={};}',2),
 ('python','def f():\n x=[# comment\n ]\n',1),
 ('javascript','let x=[/* comment */];',1),
 ('typescript','let x=[...items];',0),
 ('javascript','let x=[,,];',0),
 ('typescript','let x=[/* hole */,];',0),
 ('python','x=list()\n',0),
])
def test_only_empty_literals_get_empty_collection_fact(language,source,count):
    graph=analyze(source,language)
    assert len([f for f in graph.facts if f.relation=='EMPTY_COLLECTION'])==count


@pytest.mark.parametrize('language,source,counts',[
 ('python','f()\nf(1)\nf(*xs)\nf(**xs)\nf(a=1)\n',[0,1,1,1,1]),
 ('javascript','f();f(1);f(...xs);',[0,1,1]),
 ('typescript','f();f(1);f(...xs);',[0,1,1]),
 ('java','class C{void m(){f();f(1);f(1,2);}}',[0,1,2]),
 ('csharp','class C{void m(){f();f(1);f(a:1);}}',[0,1,1]),
])
def test_explicit_argument_count_is_not_callee_arity(language,source,counts):
    graph=analyze(source,language)
    calls=[e for e in graph.entities.values() if e.kind=='CALL']
    assert [e.attrs['explicit_arguments'] for e in calls]==counts
    out=execute_rules(graph,[SavedRule('zero','query q {call(explicit_arguments:0) as $call;emit $call;}')])
    assert out['complete'] and len(out['matches'])==1


def test_reset_facts_survive_serialization_and_do_not_change_source_cfg():
    graph=analyze('def f(xs):\n for x in xs: x.run()\n xs=[]\n')
    assert len(after(graph))==1
    edge=after(graph)[0]
    assert edge.attrs['basis']=='same-block-order'
    result=execute_rules(graph,[SavedRule('reset','query q { require $reset CLEARS_COLLECTION $xs; require $reset AFTER_ITERATION $loop; emit $reset,$xs,$loop;}')])
    assert result['complete'] and len(result['matches'])==1
    view=query_graph(graph).ir
    assert query_graph(IR.from_dict(view.to_dict())).ir.to_dict()==view.to_dict()
