"""Conditions consume an evaluated value, not the history of its variable."""
import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.query import QueryBudget

QUERY = '''language "kql/2"; module condition_values;
pattern detect(out Callable $work) {
 callable $produce { name: "produce"; }
 callable $work { name: "work"; body {
   let $value = call $produce {};
   if ($value == 0) { return 1; } else { return 2; }
 } }
}
query results { use detect(work:$work); select $work; }
'''

@pytest.mark.parametrize('language', ['python','java','javascript','typescript','csharp','cpp','go'])
@pytest.mark.parametrize('mode', ['positive','logging','alias','overwrite','other','merged'])
def test_condition_uses_current_call_result(language, mode):
    target = 'alias' if mode == 'alias' else 'other' if mode == 'other' else 'value'
    if language == 'python':
        middle = {'positive':'','logging':' print(123)\n','alias':' alias = value\n',
                  'overwrite':' value = 7\n','other':' other = 7\n',
                  'merged':' if flag:\n  value = 7\n'}[mode]
        source = 'def produce():\n return 0\ndef work(flag):\n value = produce()\n'+middle+f' if {target} == 0:\n  return 1\n else:\n  return 2\n'
    else:
        declaration = 'let' if language in ('javascript','typescript') else 'int'
        middle = {'positive':'','logging':'log();','alias':f'{declaration} alias = value;',
                  'overwrite':'value = 7;','other':f'{declaration} other = 7;',
                  'merged':'if (flag) { value = 7; }'}[mode]
        body = f'{declaration} value = produce(); {middle} if ({target} == 0) {{ return 1; }} else {{ return 2; }}'
        if language in ('javascript','typescript'):
            source = f'function produce() {{ return 0; }} function work(flag) {{ {body} }}'
        elif language == 'go':
            body = body.replace('} if', '}; if').replace('int value =','value :=').replace('int alias =','alias :=').replace('int other =','other :=')
            source = f'package a\nfunc produce() int {{ return 0 }}\nfunc work(flag bool) int {{ {body} }}'
        elif language == 'cpp':
            source = f'int produce() {{ return 0; }} int work(bool flag) {{ {body} }}'
        else:
            boolean = 'boolean' if language == 'java' else 'bool'
            source = f'class A {{ int produce() {{ return 0; }} int work({boolean} flag) {{ {body} }} }}'
    graph = link_project([lower_source(source,language,'condition.'+language)])
    assert not graph.diagnostics
    result = Executor(query_graph(graph),{},QueryBudget()).execute(compile_source(QUERY))
    assert bool(result['matches']) is (mode in ('positive','logging','alias')),result
    if mode != 'merged':
        assert result['complete'],result

@pytest.mark.parametrize('language, source', [
 ('python', 'def produce():\n return None\ndef work():\n value = produce()\n if value is None:\n  return 1\n else:\n  return 2\n'),
 ('javascript', 'function produce(){return null;} function work(){let value=produce(); if(value === null){return 1;}else{return 2;}}'),
 ('typescript', 'function produce(){return null;} function work(){let value=produce(); if(value === null){return 1;}else{return 2;}}'),
])
def test_null_identity_test_consumes_captured_value(language,source):
    graph=link_project([lower_source(source,language,'null.'+language)])
    result=Executor(query_graph(graph),{},QueryBudget()).execute(compile_source(QUERY.replace('$value == 0','$value == null')))
    assert result['complete'] and len(result['matches']) == 1,result


def test_origin_is_not_reused_from_a_different_condition():
    source='''def produce(): return 0
def work():
 value=produce()
 if value==0:
  print(1)
 value=7
 if value==0:
  return 1
 else:
  return 2
'''
    graph=link_project([lower_source(source,'python','conditions.py')])
    result=Executor(query_graph(graph),{},QueryBudget()).execute(compile_source(QUERY))
    assert result['complete'] and not result['matches'],result


def test_exported_call_target_selectors_use_public_search(tmp_path):
    from ken.kql2.service import search
    (tmp_path/'a.ts').write_text('function build(){return 1;} export function work(){return build();} function hidden(){return build();}')
    query='''language "kql/2"; module exports;
    query q {
      callable $target {name:"build";}
      module_decl $module {
        callable $entry {
          exported:true;
          call $invocation {target:$target;}
        }
      }
      select $entry;
    }'''
    result=search(tmp_path,query,cache_mb=0)
    assert len(result['rows'])==1 and 'CALLABLE:work' in str(result['rows'][0]),result


def test_condition_origin_does_not_require_explicit_return_or_call_arguments():
    source='''def produce(): return 0
def hit(): pass
def miss(): pass
def work():
 value=produce()
 if value==0:
  hit()
 else:
  miss()
'''
    query=QUERY.replace('callable $produce', 'callable $hit {name:"hit";} callable $miss {name:"miss";} callable $produce').replace('return 1;', 'call $hit {};').replace('return 2;', 'call $miss {};')
    graph=link_project([lower_source(source,'python','void.py')])
    result=Executor(query_graph(graph),{},QueryBudget()).execute(compile_source(query))
    assert result['complete'] and len(result['matches'])==1,result
