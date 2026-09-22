"""Saved-rule authoring uses source syntax and the same CFG semantics as KQL 2."""
import pytest

from ken.kql2.catalog import compile_source
from ken.kql2.compiler import CompileError
from ken.structural.frontend import lower_source
from ken.structural.query_view import query_graph
from ken.structural.semantic import link_project
from ken.structural.relational import Executor

QUERY = '''language "kql/2"; module example;
pattern detect(out Callable $method, out Operation $returned) {
 class $subject {
  method $method {
   name: "work";
   body {
    var $value { name: "value"; }
    $value = $value + 1;
    return $value as $returned;
   }
  }
 }
}
query results {
 use detect(method: $method, returned: $returned);
 select $method, $returned;
}'''
SOURCES = {
 'python': 'class Subject:\n def work(self):\n  value=0\n  print(123)\n  value=value+1\n  return value\n',
 'java': 'class Subject { int work() { int value=0; log(); value=value+1; return value; } }',
 'typescript': 'class Subject { work() { let value=0; log(); value=value+1; return value; } }',
 'cpp': 'class Subject { public: int work() { int value=0; log(); value=value+1; return value; } };',
 'csharp': 'class Subject { int work() { int value=0; Log(); value=value+1; return value; } }',
}

def run(source, language, query=QUERY, **budget):
 from ken.structural.query import QueryBudget
 index=query_graph(link_project([lower_source(source,language,'example.'+language)]))
 assert not index.ir.diagnostics
 return Executor(index,{},QueryBudget(**budget)).execute(compile_source(query))

@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('mutation',['positive','wrong_return','wrong_update','noise_adjacent'])
def test_nested_saved_body_preserves_source_contract(language,mutation):
 source=SOURCES[language]
 query=QUERY
 if mutation=='wrong_return':source=source.replace('return value','return 0')
 if mutation=='wrong_update':source=source.replace('value=value+1','value=value-1')
 if mutation=='noise_adjacent':query=query.replace('body {','body adjacent {')
 result=run(source,language,query)
 assert result['complete']
 assert bool(result['matches']) is (mutation=='positive'),result


def test_saved_body_does_not_join_opposite_control_branches():
 source='class Subject:\n def work(self, flag):\n  value=0\n  if flag:\n   value=value+1\n  else:\n   return value\n  return 0\n'
 assert not run(source,'python')['matches']


def test_saved_body_requires_immediate_method_owner():
 source='class Subject:\n def other(self):\n  def work():\n   value=0\n   value=value+1\n   return value\n'
 assert not run(source,'python')['matches']


def test_saved_body_propagates_unsupported_cfg():
 source='class Subject:\n def work(self):\n  value=0\n  try:\n   value=value+1\n  except Exception:\n   pass\n  return value\n'
 result=run(source,'python')
 assert result['complete'] and not result['matches'] and result['unknown']


def test_saved_body_uses_the_executor_budget():
 result=run(SOURCES['python'],'python',max_states=5)
 assert not result['complete']

@pytest.mark.parametrize('source',[
 QUERY.replace('name: "work"','invented: "work"'),
 QUERY.replace('body {','body { adjacent;'),
 QUERY.replace('return $value','return $missing'),
 QUERY.replace('method $method','field $method'),
])
def test_saved_source_schema_fails_before_execution(source):
 with pytest.raises(CompileError):compile_source(source)

@pytest.mark.parametrize('argument,expected',[('$input',True),('42',False)])
def test_saved_body_arguments_retain_normalized_occurrence_metadata(argument,expected):
 query='''language "kql/2"; module example;
 pattern detect(out Callable $owner) {
  callable $target { name: "consume"; }
  callable $owner { name: "work"; param $input { name: "input"; }
   body { call $target { argument '''+argument+''' at 0; }; }
  }
 }
 query results { use detect(owner: $owner); select $owner; }
 '''
 result=run('def consume(value):\n return value\ndef work(input):\n consume(input)\n','python',query)
 assert result['complete'] and bool(result['matches']) is expected,result

CAPTURED = '''language "kql/2"; module example;
pattern detect(out Callable $owner) {
 callable $producer { name: "produce"; }
 callable $owner { name: "work"; body {
  let $value = call $producer {};
  return $value;
 } }
}
query results { use detect(owner: $owner); select $owner; }
'''

@pytest.mark.parametrize('body,expected',[
 ('result=produce()\n return result',True),
 ('result=produce()\n print(7)\n return result',True),
 ('return produce()',True),
 ('result=produce()\n alias=result\n return alias',True),
 ('result=produce()\n result=0\n return result',False),
 ('result=produce()\n alias=result\n alias=0\n return alias',False),
 ('result=produce()\n return 0',False),
 ('result=produce()\n result=other()\n return result',False),
])
def test_captured_results_use_current_origins_not_historical_assignments(body,expected):
 source='def produce():\n return 1\ndef other():\n return 2\ndef work():\n '+body+'\n'
 result=run(source,'python',CAPTURED)
 assert result['complete'] and bool(result['matches']) is expected,result
 assert not result['unknown'],result


def test_produced_value_cannot_be_assigned_as_a_binding():
 with pytest.raises(CompileError):
  compile_source(CAPTURED.replace('return $value;', '$value = 0; return $value;'))

ITERATION = '''language "kql/2"; module example;
pattern detect(out Callable $owner) {
 callable $consume { name: "consume"; }
 callable $owner { name: "work"; param $items { name: "items"; }
  body {
   iterate $items as $element {
    body { call $consume { argument $element at 0; }; }
   }
  }
 }
}
query results { use detect(owner: $owner); select $owner; }
'''
ITERATION_SOURCES = {
 'python': 'def consume(item):\n pass\ndef work(items, other):\n for element in items:\n  print(0)\n  consume(element)\n  print(1)\n',
 'java': 'class A { void consume(int item) {} void work(int[] items,int[] other) { for(int element:items) { log(); consume(element); log(); } } }',
 'typescript': 'function consume(item: number) {} function work(items:number[],other:number[]) { for(const element of items) { log(); consume(element); log(); } }',
}

@pytest.mark.parametrize('language',ITERATION_SOURCES)
@pytest.mark.parametrize('mutation',['positive','other_collection','discarded_element','outside_loop'])
def test_iteration_scopes_the_element_and_calls(language,mutation):
 source=ITERATION_SOURCES[language]
 if mutation=='other_collection':
  source=source.replace('in items:', 'in other:').replace('element:items','element:other').replace('of items','of other')
 if mutation=='discarded_element':source=source.replace('consume(element)','consume(0)')
 if mutation=='outside_loop':
  if language=='python':source=source.replace('  consume(element)\n','').rstrip()+'\n consume(element)\n'
  else:source=source.replace('consume(element);','').replace('log(); } }','log(); } consume(element); }')
 result=run(source,language,ITERATION)
 assert result['complete'] and bool(result['matches']) is (mutation=='positive'),result


def test_iteration_element_is_local_to_its_body():
 with pytest.raises(CompileError):
  compile_source(ITERATION.replace('select $owner;', 'select $owner, $element;'))

@pytest.mark.parametrize('language',ITERATION_SOURCES)
@pytest.mark.parametrize('position',['before','after'])
def test_iteration_value_is_not_a_reassigned_binding(language,position):
 source=ITERATION_SOURCES[language]
 if language=='python':
  original='  consume(element)'
  replacement='  element=0\n'+original if position=='before' else original+'\n  element=0'
 else:
  original='consume(element);'
  replacement='element=0; '+original if position=='before' else original+' element=0;'
  if language=='typescript':source=source.replace('const element','let element')
 result=run(source.replace(original,replacement),language,ITERATION)
 assert result['complete'] and bool(result['matches']) is (position=='after'),result


def test_saved_body_resolves_query_aliases_to_the_same_source_role():
 query = CAPTURED.replace('callable $owner { name: "work"; body {',
     'callable $original { name: "work"; } bind $owner = $original; callable $owner { body {')
 assert run('def produce():\n return 1\ndef work():\n result=produce()\n return result\n','python',query)['matches']


@pytest.mark.parametrize('mutation', ['positive', 'overwrite', 'other_result'])
def test_rust_return_expression_uses_current_origin(mutation):
 statement = {'positive':'log();', 'overwrite':'result=0;', 'other_result':'result=other();'}[mutation]
 source = ('fn produce() -> i32 { return 1; } fn other() -> i32 { return 2; } '
           'fn work() -> i32 { let mut result=produce(); '+statement+' return result; }')
 result = run(source,'rust',CAPTURED)
 assert bool(result['matches']) is (mutation == 'positive'),result


def test_alternative_source_domains_do_not_leak_into_each_other():
 query='''language "kql/2"; module example;
 pattern detect(out Entity $subject) {
  either { class $subject {} } or { callable $subject {} }
 }
 query results { use detect(subject: $subject); select $subject; }
 '''
 result=run('class A:\n pass\ndef f():\n pass\n','python',query)
 assert len(result['matches']) == 2,result


@pytest.mark.parametrize('language,source',[
 ('python','def produce():\n return 1\ndef work():\n value=produce()\n print(2)\n return value\n'),
 ('java','class A { int produce() { return 1; } int work() { int value=produce(); log(); return value; } }'),
 ('typescript','function produce() { return 1; } function work() { const value=produce(); log(); return value; }'),
])
def test_call_can_capture_its_resolved_target_without_a_global_scan(language,source):
 query='''language "kql/2"; module fresh;
 pattern detect(out Callable $owner, out Callable $producer) {
  callable $owner { name: "work"; body {
   let $value = call $producer {};
   return $value;
  } }
 }
 query results { use detect(owner: $owner,producer: $producer); select $owner,$producer; }'''
 result=run(source,language,query)
 assert len(result['matches']) == 1,result
 assert '/CALLABLE:produce' in result['matches'][0]['bindings']['$producer']


@pytest.mark.parametrize('language,source',[
 ('python','def yes():\n pass\ndef no():\n pass\ndef work(flag):\n if flag:\n  yes()\n else:\n  no()\n'),
 ('java','class A { void yes() {} void no() {} void work(boolean flag) { if (flag) { yes(); } else { no(); } } }'),
 ('typescript','function yes() {} function no() {} function work(flag:boolean) { if(flag) { yes(); } else { no(); } }'),
])
@pytest.mark.parametrize('mutation',['positive','swapped','wrong_condition'])
def test_if_pattern_inspects_correlated_arms(language,source,mutation):
 query='''language "kql/2"; module branches;
 pattern detect(out Callable $owner) {
  callable $yes { name: "yes"; } callable $no { name: "no"; }
  callable $owner { name: "work"; param $flag { name: "flag"; } body {
   if ($flag) { call $yes {}; } else { call $no {}; }
  } }
 }
 query results { use detect(owner: $owner); select $owner; }'''
 if mutation=='swapped':query=query.replace('call $yes','call $temp').replace('call $no','call $yes').replace('call $temp','call $no')
 if mutation=='wrong_condition':query=query.replace('if ($flag)','if (false)')
 result=run(source,language,query)
 assert bool(result['matches']) is (mutation=='positive'),result


@pytest.mark.parametrize('returned_inside',[False,True])
def test_statement_after_iteration_cannot_match_inside_the_iteration(returned_inside):
 query='''language "kql/2"; module traversal;
 pattern detect(out Callable $owner) {
  callable $consume { name: "consume"; }
  callable $owner { name: "work"; param $items {} body {
   iterate $items as $element { body { call $consume { argument $element at 0; }; } }
   return 0;
  } }
 }
 query results { use detect(owner: $owner); select $owner; }'''
 source='def consume(item):\n pass\ndef work(items):\n for item in items:\n  consume(item)\n'+('  return 0\n' if returned_inside else ' return 0\n')
 result=run(source,'python',query)
 assert bool(result['matches']) is not returned_inside,result


@pytest.mark.parametrize('assignment,expected',[('',True),(' input=0\n',False),(' input=input\n',False)])
def test_parameter_reassignment_property_is_closed_explicit_write_inventory(assignment,expected):
 query='''language "kql/2"; module stable;
 pattern detect(out Callable $owner) { callable $owner { param $input { reassigned: false; } } }
 query results { use detect(owner: $owner); select $owner; }'''
 result=run('def work(input):\n'+assignment+' return input\n','python',query)
 assert bool(result['matches']) is expected,result


@pytest.mark.parametrize('language,source',[
 ('python','class A:\n state: object\n def work(self):\n  if self.state == None:\n   self.state = 1\n  return self.state\n'),
 ('java','class A { Object state; Object work() { if (this.state == null) { this.state=1; } return this.state; } }'),
 ('typescript','class A { state: unknown; work() { if (this.state == null) { this.state=1; } return this.state; } }'),
])
@pytest.mark.parametrize('mutation',['positive','wrong_field','wrong_polarity'])
def test_if_body_resolves_member_bindings_without_matching_attribute_text(language,source,mutation):
 query='''language "kql/2"; module fields;
 pattern detect(out TypeDecl $unit) { class $unit { field $state { name: "state"; }
  method $work { name: "work"; body { if ($state == null) { $state = 1; } return $state; } }
 } }
 query results { use detect(unit: $unit); select $unit; }'''
 if mutation=='wrong_polarity':query=query.replace('== null','!= null')
 if mutation=='wrong_field':source=source.replace('if self.state','if other.state').replace('if (this.state','if (other.state')
 result=run(source,language,query)
 assert bool(result['matches']) is (mutation=='positive'),result


@pytest.mark.parametrize('mutation', ['positive', 'overwrite', 'other_value'])
@pytest.mark.parametrize('language,source', [
 ('python', 'def produce():\n return 1\ndef consume(value):\n pass\ndef work(flag):\n value=produce()\n if flag:\n  consume(value)\n'),
 ('java', 'class A { int produce() { return 1; } void consume(int value) {} void work(boolean flag) { int value=produce(); if(flag) { consume(value); } } }'),
 ('typescript', 'function produce() { return 1; } function consume(value:number) {} function work(flag:boolean) { let value=produce(); if(flag) { consume(value); } }'),
])
def test_value_captured_before_branch_is_correlated_inside_it(language,source,mutation):
 query='''language "kql/2"; module nested_values;
 pattern detect(out Callable $owner) {
  callable $producer { name: "produce"; } callable $consumer { name: "consume"; }
  callable $owner { name: "work"; param $flag { name: "flag"; } body {
   let $result = call $producer {};
   if ($flag) { call $consumer { argument $result at 0; }; }
  } }
 }
 query results { use detect(owner: $owner); select $owner; }'''
 if mutation == 'overwrite':
  head, _, tail = source.rpartition('consume(value)')
  source=head+'value=0; consume(value)'+tail
 if mutation == 'other_value':
  head, _, tail = source.rpartition('consume(value)')
  source=head+'consume(0)'+tail
 result=run(source,language,query)
 assert bool(result['matches']) is (mutation=='positive'),result


@pytest.mark.parametrize('tail,expected', [('Product { n: 1 }',True), ('Product { n: 1 } /* tail comment */',True), ('return other; Product { n: 1 }',False), ('Product { n: 1 };',False), ('let p=Product { n: 1 }; p',True), ('let mut p=Product { n: 1 }; p=other; p',False)])
def test_rust_tail_return_is_normalized_and_preserves_current_value(tail,expected):
 query='''language "kql/2"; module tail;
 pattern detect(out Callable $owner) {
  class $product { name: "Product"; }
  callable $owner { name: "make"; body { let $result = construct $product {}; return $result; } }
 }
 query results { use detect(owner: $owner); select $owner; }'''
 result=run('struct Product { n:i32 } fn make(other: Product) -> Product { '+tail+' }','rust',query)
 assert bool(result['matches']) is expected,result


@pytest.mark.parametrize('language,source', [
 ('python','def work(service, other):\n result=service.fetch()\n print(1)\n return result\n'),
 ('typescript','function work(service:any,other:any) { const result=service.fetch(); console.log(1); return result; }'),
 ('java','class A { Object work(Service service, Service other) { Object result=service.fetch(); log(); return result; } }'),
])
@pytest.mark.parametrize('mutation',['positive','other_receiver','discarded_result'])
def test_selected_call_occurrence_can_be_matched_without_resolved_callee(language,source,mutation):
 query='''language "kql/2"; module occurrences;
 pattern detect(out Callable $owner, out Call $invocation) {
  callable $owner { name: "work";
   param $service { name: "service"; }
   call $invocation { name: "fetch"; }
   body { let $result = call $invocation { receiver: $service; }; return $result; }
  }
 }
 query results { use detect(owner: $owner,invocation: $invocation); select $owner,$invocation; }'''
 if mutation == 'other_receiver':source=source.replace('service.fetch()', 'other.fetch()')
 if mutation == 'discarded_result':source=source.replace('return result', 'return null' if language!='python' else 'return None')
 result=run(source,language,query)
 assert bool(result['matches']) is (mutation=='positive'),result
