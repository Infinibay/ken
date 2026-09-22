"""Captured values and consumers are independent of source variable spelling."""
import pytest
from ken.kql2.catalog import compile_source
from ken.kql2.compiler import CompileError
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.query import QueryBudget

QUERY='''language "kql/2"; module usage_examples;
pattern inspect(out Callable $work,out Usage $use) {
 callable $make {name:"make";}
 callable $work {name:"work";body {let $result=call $make {};}}
 usages of $result as $use { FILTER }
}
query results {use inspect(work:$work,use:$use);select $work,$use;}
'''

def execute(source,filters='',language='python',reference=False,alter=None):
    graph=link_project([lower_source(source,language,'example.'+language)])
    assert not graph.diagnostics
    if alter:alter(graph)
    index=query_graph(graph)
    executor=Executor(index,{},QueryBudget())
    executor.reference=reference
    result=executor.execute(compile_source(QUERY.replace('FILTER',filters)))
    assert result['complete']
    return result

def witnesses(result):
    def walk(value):
        if isinstance(value,dict):
            if 'usage' in value and 'kind' in value:yield value
            else:
                for child in value.values():yield from walk(child)
        elif isinstance(value,list):
            for child in value:yield from walk(child)
    return list(walk(result['matches']))

PREFIX='def make(): return 1\ndef consume(a,b=0): pass\ndef work():\n'

@pytest.mark.parametrize('body,count',[
    (' consume(make())\n',1),
    (' x=make()\n consume(x)\n',1),
    (' x=make()\n alias=x\n consume(alias)\n',1),
    (' x=make()\n alias=x\n x=0\n consume(alias)\n',1),
    (' x=make()\n x=0\n consume(x)\n',0),
    (' x=make()\n consume(x,x)\n',2),
    (' x=make()\n y=x*2\n consume(y)\n',0),
    (' x=make()\n consume(0)\n',0),
])
@pytest.mark.parametrize('reference',[False,True])
def test_identity_aliases_reassignment_and_argument_occurrences(body,count,reference):
    result=execute(PREFIX+body,'kind: argument;',reference=reference)
    assert len(result['matches'])==count,result
    assert 'usage_inventory_open' in result['unknown']
    ids=[w['usage'] for w in witnesses(result)]
    assert len(ids)==len(set(ids))

@pytest.mark.parametrize('kind,count',[('assignment',2),('argument',2),('condition',1),('return',1),('operand',1)])
def test_distinct_consumers_without_propagating_derived_identity(kind,count):
    source=PREFIX+' x=make()\n alias=x\n consume(x,alias)\n y=x*2\n if x:\n  return x\n return y\n'
    result=execute(source,'kind: '+kind+';')
    assert len(result['matches'])==count,result
    assert all(w['kind']==kind for w in witnesses(result))

def test_each_position_can_be_selected():
    result=execute(PREFIX+' x=make()\n consume(x,x)\n','kind: argument;position:1;')
    assert len(result['matches'])==1
    assert witnesses(result)[0]['position']==1

def test_possible_origin_is_not_a_certain_match():
    source=PREFIX+' x=make()\n if flag:\n  x=0\n consume(x)\n'
    result=execute(source,'kind: argument;')
    assert not result['matches']
    assert 'usage_origin_may' in result['unknown']

def test_missing_usage_facts_do_not_prove_absence():
    def alter(graph):graph.facts=[f for f in graph.facts if f.relation!='ARGUMENT_VALUE_ORIGIN']
    result=execute(PREFIX+' x=make()\n consume(x)\n','kind: argument;',alter=alter)
    assert not result['matches'] and 'usage_inventory_open' in result['unknown']

@pytest.mark.parametrize('filters',[
    'kind: banana;','position:-1;','kind: argument;kind:return;','position:true;',
    'scope: global;','owner:$unbound;',
])
def test_reject_invalid_filters(filters):
    with pytest.raises((CompileError,ValueError)):
        compile_source(QUERY.replace('FILTER',filters))

def test_usage_requires_captured_value_not_a_callable():
    with pytest.raises(CompileError,match='captured Value'):
        compile_source(QUERY.replace('FILTER','').replace('usages of $result','usages of $make'))

@pytest.mark.parametrize('language,source',[
    ('python',PREFIX+' consume(make())\n'),
    ('javascript','function make(){return 1;} function consume(x){} function work(){consume(make());}'),
    ('typescript','function make():number{return 1;} function consume(x:number){} function work(){consume(make());}'),
    ('java','class A {int make(){return 1;} void consume(int x){} void work(){consume(make());}}'),
    ('csharp','class A {int make(){return 1;} void consume(int x){} void work(){consume(make());}}'),
    ('cpp','int make(){return 1;} void consume(int x){} void work(){consume(make());}'),
    ('go','package a\nfunc make() int{return 1}\nfunc consume(x int){}\nfunc work(){consume(make())}'),
    ('rust','fn make()->i32{1} fn consume(x:i32){} fn work(){consume(make());}'),
])
def test_inline_argument_across_languages(language,source):
    result=execute(source,'kind: argument;position:0;',language)
    assert len(result['matches'])==1,result

def test_public_search_compilation_and_result_cache(tmp_path):
    from ken.kql2.service import search
    (tmp_path/'a.py').write_text(PREFIX+' x=make()\n consume(x,x)\n')
    query=QUERY.replace('FILTER','kind: argument;')
    first=search(tmp_path,query)
    second=search(tmp_path,query)
    assert len(first['rows'])==2
    assert first['rows']==second['rows']
    assert first['complete'] and second['complete']
    assert all(row[1]['kind']=='argument' and row[1]['path']=='a.py' for row in first['rows'])


@pytest.mark.parametrize('body,kind,count',[
    (' if make():\n  return 0\n','condition',1),
    (' x=make()\n if consume(x):\n  return 0\n','argument',1),
    (' x=make()\n if consume(x):\n  return 0\n','condition',0),
    (' x=make()\n if x*2:\n  return 0\n','operand',1),
    (' x=make()\n if x*2:\n  return 0\n','condition',0),
    (' x=make()\n if False:\n  y=x*2\n return 0\n','operand',0),
    (' x=make()\n if True:\n  return 0\n else:\n  consume(x)\n','argument',0),
    (' return make()\n','return',1),
])
def test_exact_consumer_and_unreachable_branches(body,kind,count):
    result=execute(PREFIX+body,'kind: '+kind+';')
    assert len(result['matches'])==count,result


def test_operand_owner_is_resolved_from_expression_operation():
    result=execute(PREFIX+' x=make()\n y=x*2\n','kind: operand;owner:$work;')
    assert len(result['matches'])==1,result
    assert witnesses(result)[0]['owner']==result['matches'][0]['bindings']['$work']


def test_missing_consumer_does_not_manufacture_a_known_usage():
    def alter(graph):
        call=next(e.id for e in graph.entities.values() if e.kind=='CALL' and e.name=='make')
        graph.add('missing-operation','RETURN_ORIGIN',call,modality='must')
    result=execute(PREFIX+' x=make()\n','kind: return;',alter=alter)
    assert not result['matches'] and 'usage_inventory_open' in result['unknown']


def test_named_queries_can_export_and_consume_captured_values():
    query='''language "kql/2";module composed;
    pattern producer(out Value $result) {
      callable $make {name:"make";}
      callable $work {name:"work";body{let $result=call $make{};}}
    }
    query results {
      use producer(result:$value);
      usages of $value as $use {kind:argument;}
      select $use;
    }'''
    index=query_graph(link_project([lower_source(PREFIX+' consume(make())\n','python','composed.py')]))
    result=Executor(index,{},QueryBudget()).execute(compile_source(query))
    assert len(result['matches'])==1,result


def test_usage_properties_remain_available_to_where():
    query=QUERY.replace('FILTER','').replace('usages of $result as $use {  }',
        'usages of $result as $use {} where $use.kind == "argument" and $use.position == 1;')
    index=query_graph(link_project([lower_source(PREFIX+' x=make()\n consume(x,x)\n','python','where.py')]))
    result=Executor(index,{},QueryBudget()).execute(compile_source(query))
    assert len(result['matches'])==1,result


def test_query_does_not_mutate_the_shared_graph():
    import json
    index=query_graph(link_project([lower_source(PREFIX+' x=make()\n consume(x)\n','python','shared.py')]))
    before=json.dumps(index.ir.to_dict(),sort_keys=True)
    Executor(index,{},QueryBudget()).execute(compile_source(QUERY.replace('FILTER','')))
    assert json.dumps(index.ir.to_dict(),sort_keys=True)==before


@pytest.mark.parametrize('body',[
    ' x=make()\n consume(*x)\n',
    ' x=make()\n consume(*other,x)\n',
    ' consume(*make())\n',
])
def test_spread_packs_are_not_certain_scalar_argument_positions(body):
    result=execute(PREFIX.replace('return 1','return [1]')+body,'kind:argument;')
    assert not result['matches'],result
    assert result['unknown']


@pytest.mark.parametrize('body,lines', [
    (' x=make()\n x.close()\n', [5]),
    (' x=make()\n alias=x\n x=0\n alias.close()\n', [7]),
    (' x=make()\n x=0\n x.close()\n', []),
    (' x=make()\n other=consume()\n other.close()\n', []),
    (' make().close()\n', [4]),
    (' x=make()\n if flag:\n  x=0\n x.close()\n', []),
])
@pytest.mark.parametrize('reference', [False, True])
def test_receiver_is_the_current_result_not_an_unrelated_close(body, lines, reference):
    result = execute(PREFIX + body, 'kind: receiver;', reference=reference)
    evidence = witnesses(result)
    assert [item['line'] for item in evidence] == lines
    assert all(item['consumer_name'] == 'close' for item in evidence)
    assert 'usage_inventory_open' in result['unknown']
