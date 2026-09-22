"""Generator suspension in source-authored BODY, without graph vocabulary."""
import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.query import QueryBudget
from ken.structural.rules import builtin_rules,execute_rules,named_rule

SOURCES={
 'python':'def entries(items):\n print("trace")\n yield items\n',
 'javascript':'function* entries(items){console.log("trace");yield items;}',
 'typescript':'function* entries(items:number[]){console.log("trace");yield items;}',
 'csharp':'class C { System.Collections.Generic.IEnumerable<int[]> Entries(int[] items){System.Console.WriteLine("trace");yield return items;} }',
}

def graph(source,language):
 result=link_project([lower_source(source,language,'case.'+language)])
 assert not result.diagnostics,result.diagnostics
 return result


def detect(source,language,variant):
 registry=builtin_rules()
 result=execute_rules(graph(source,language),[named_rule('iterator#'+variant,registry)],registry=registry)
 assert result['complete'],result
 return result


@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('mutation',['positive','return','dead','nested_only'])
def test_yield_source_generator(language,mutation):
 source=SOURCES[language]
 if mutation=='return':source=source.replace('yield return items','return items').replace('yield items','return items')
 if mutation=='dead':source=source.replace('yield return items','yield break;yield return items').replace('yield items','return;yield items' if language!='python' else 'return\n yield items')
 if mutation=='nested_only':
  source={'python':'def entries(items):\n def inner():\n  yield items\n return items\n',
          'javascript':'function entries(items){function* inner(){yield items;}return items;}',
          'typescript':'function entries(items:number[]){function* inner(){yield items;}return items;}',
          'csharp':'class C { int[] Entries(int[] items){System.Collections.Generic.IEnumerable<int[]> Inner(){yield return items;}return items;} }'}[language]
 result=detect(source,language,'generator')
 if mutation=='nested_only':
  assert result['matches'],result
  assert all('Entries' not in m['bindings']['$iterator'].split('/CALLABLE:')[-1] and 'entries' not in m['bindings']['$iterator'].split('/CALLABLE:')[-1] for m in result['matches'])
 else:assert bool(result['matches']) is (mutation=='positive'),result


@pytest.mark.parametrize('language',['python','javascript','typescript'])
@pytest.mark.parametrize('mutation',['positive','ordinary','dead'])
def test_yield_delegation_source(language,mutation):
 source=SOURCES[language].replace('yield items','yield from items' if language=='python' else 'yield* items')
 if mutation=='ordinary':source=SOURCES[language]
 if mutation=='dead':source=source.replace('yield from items','return\n yield from items').replace('yield* items','return;yield* items')
 result=detect(source,language,'delegated-generator')
 assert bool(result['matches']) is (mutation=='positive'),result


@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('operand',['$items','0'])
def test_yield_operand_and_operation_capture(language,operand):
 query='''language "kql/2";module t;
 pattern p(out Callable $producer,out Operation $suspend){
 callable $producer{param $items{name:"items";} body{yield OPERAND as $suspend;}}
 }query q{use p(producer:$producer,suspend:$suspend);select $producer,$suspend;}
 '''.replace('OPERAND',operand)
 result=Executor(query_graph(graph(SOURCES[language],language)),{},QueryBudget()).execute(compile_source(query))
 assert result['complete'],result
 assert bool(result['matches']) is (operand=='$items'),result
 if result['matches']:assert 'yield' in result['matches'][0]['bindings']['$suspend']


def test_bare_python_yield_produces_none():
 query='language "kql/2";module t;pattern p(out Callable $p){callable $p{body{yield null;}}}query q{use p(p:$p);select $p;}'
 result=Executor(query_graph(graph('def entries():\n yield\n','python')),{},QueryBudget()).execute(compile_source(query))
 assert result['matches'],result


def test_python_context_manager_is_not_iterator_variant():
 source='from contextlib import contextmanager\n@contextmanager\n'+SOURCES['python'].replace('yield items','yield from items')
 assert not detect(source,'python','delegated-generator')['matches']


def test_csharp_yield_break_does_not_produce_an_element():
 source=SOURCES['csharp'].replace('yield return items','yield break')
 assert not detect(source,'csharp','generator')['matches']


@pytest.mark.parametrize('language',['python','javascript','typescript','csharp'])
def test_constant_false_branch_does_not_produce_reachable_yield(language):
 source=SOURCES[language]
 if language=='python':source=source.replace(' yield items',' if False:\n  yield items')
 else:source=source.replace('yield return items;','if(false){yield return items;}').replace('yield items;','if(false){yield items;}')
 assert not detect(source,language,'generator')['matches']


@pytest.mark.parametrize('language',['python','javascript','typescript'])
def test_async_suspension_does_not_erase_generator_shape(language):
 source=SOURCES[language]
 if language=='python':source=source.replace('def entries','async def entries').replace(' yield items',' await ready()\n yield items')
 else:source=source.replace('function*','async function*').replace('yield items','await ready();yield items')
 result=detect(source,language,'generator')
 assert result['matches'],result
 assert not result['outcomes']['iterator#generator']['unknown'],result


@pytest.mark.parametrize('language',['python','javascript','typescript'])
def test_iteration_can_consume_a_captured_call_result(language):
 source={'python':'def values(): return [1]\ndef consume():\n for item in values():\n  print(item)\n',
 'javascript':'function values(){return [1];}function consume(){for(const item of values()){console.log(item);}}',
 'typescript':'function values(){return [1];}function consume(){for(const item of values()){console.log(item);}}'}[language]
 query='''language "kql/2";module t;pattern p(out Callable $consumer){
 callable $produce{name:"values";}
 callable $consumer{name:"consume";body{
 let $items=call $produce {};
 iterate $items as $item {async:false;body{}}
 }}
 }query q{use p(consumer:$consumer);select $consumer;}'''
 result=Executor(query_graph(graph(source,language)),{},QueryBudget()).execute(compile_source(query))
 assert result['complete'],result
 assert result['matches'],result
