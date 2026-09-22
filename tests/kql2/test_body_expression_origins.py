"""Source arithmetic must consume the captured result at this occurrence."""
import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.query import QueryBudget

QUERY = '''language "kql/2"; module expressions;
pattern detect(out Callable $work) {
 callable $produce { name:"produce"; }
 callable $work { name:"work"; body {
  let $result = call $produce {};
  return $result + _;
 } }
}
query results { use detect(work:$work); select $work; }
'''

@pytest.mark.parametrize('language', ['python','java','javascript','typescript','csharp','cpp','go'])
@pytest.mark.parametrize('mode', ['positive','alias','overwrite','other_operand'])
def test_return_expression_preserves_operand_origin(language,mode):
    operand='alias' if mode == 'alias' else 'value'
    expression = f'{operand} + 2' if mode != 'other_operand' else f'2 + {operand}'
    middle={'positive':'','alias':'alias = value','overwrite':'value = 7','other_operand':''}[mode]
    if language == 'python':
        source=f'def produce(): return 1\ndef work():\n value=produce()\n'+(' '+middle+'\n' if middle else '')+f' return {expression}\n'
    else:
        decl='let' if language in ('javascript','typescript') else 'int'
        if mode=='alias': middle=decl+' '+middle
        body=f'{decl} value=produce(); {middle+";" if middle else ""} return {expression};'
        if language in ('javascript','typescript'): source=f'function produce(){{return 1;}} function work(){{{body}}}'
        elif language=='cpp': source=f'int produce(){{return 1;}} int work(){{{body}}}'
        elif language=='go':
            body=body.replace('int value=','value:=').replace('int alias =','alias :=')
            source=f'package a\nfunc produce() int {{return 1}}\nfunc work() int {{{body}}}'
        else: source=f'class A {{int produce(){{return 1;}} int work(){{{body}}}}}'
    graph=link_project([lower_source(source,language,'expression.'+language)])
    assert not graph.diagnostics,graph.diagnostics
    result=Executor(query_graph(graph),{},QueryBudget()).execute(compile_source(QUERY))
    assert bool(result['matches']) is (mode in ('positive','alias')),result
    assert result['complete'],result

@pytest.mark.parametrize('matcher,expected', [
 ('binary(left:$result, operator:_, right:_)',True),
 ('binary(left:$result, operator:["+","-"], right:_)',True),
 ('binary(left:$result, operator:"*", right:_)',False),
 ('binary(left:_, operator:_, right:$result)',False),
])
def test_generic_binary_expression_pattern(matcher,expected):
    source='def produce(): return 1\ndef work():\n value=produce()\n return value+2\n'
    graph=link_project([lower_source(source,'python','binary.py')])
    result=Executor(query_graph(graph),{},QueryBudget()).execute(compile_source(QUERY.replace('$result + _',matcher)))
    assert result['complete'] and bool(result['matches']) is expected,result

@pytest.mark.parametrize('matcher', [
 'binary(left:$result, right:_)',
 'binary(left:$result, operator:1, right:_)',
 'binary(left:$result, operator:undefined, right:_)',
 'binary(left:$result, operator:[], right:_)',
 'binary(left:$result, operator:_, left:_, right:_)',
 'binary(left:$result, operator:$result, right:_)',
])
def test_invalid_expression_matcher_is_rejected(matcher):
    from ken.kql2.syntax import ParseError
    with pytest.raises(ParseError):
        compile_source(QUERY.replace('$result + _',matcher))
