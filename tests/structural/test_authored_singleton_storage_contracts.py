import pytest
from ken.kql2.catalog import compile_source
from ken.kql2.compiler import CompileError
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor

QUERY='''language "kql/2"; module storage;
pattern detect(out Callable $accessor) {
 class $unit { field $state { initial:null; }
 method $accessor { name:"get"; writes: exactly($state,1); }
 }
}
query results { use detect(accessor:$accessor); select $accessor; }
'''

def run(source,query=QUERY):
 return Executor(query_graph(link_project([lower_source(source,'java','sample')])),{},None).execute(compile_source(query))

@pytest.mark.parametrize('initial,body,expected',[
 ('null','state=new A();',True),
 ('new A()','state=new A();',False),
 ('null','',False),
 ('null','state=new A(); state=null;',False),
])
def test_initial_value_and_callable_local_write_count(initial,body,expected):
 result=run('class A { static A state='+initial+'; static A get(){'+body+'return state;} void other(){state=null;} }')
 assert bool(result['matches']) is expected,result


def test_write_count_requires_bound_binding():
 with pytest.raises(CompileError,match='already bound'):
  compile_source(QUERY.replace('exactly($state,1)','exactly($missing,1)'))

@pytest.mark.parametrize('matcher',['exactly($state,-1)','exactly($state,true)','unknown($state,1)'])
def test_bad_write_matcher_is_rejected(matcher):
 with pytest.raises(CompileError):compile_source(QUERY.replace('exactly($state,1)',matcher))

LINEAR='''language "kql/2"; module lazy;
pattern detect(out TypeDecl $unit) {
 class $unit { field $state { static:true; initial:null; }
 method $accessor { writes: exactly($state,1); body linear {
 if ($state == null) { let $made=construct $unit {}; $state=$made; }
 return $state;
 } } }
}
query results { use detect(unit:$unit); select $unit; }
'''

@pytest.mark.parametrize('mutation',['positive','noise','nested_guard','before_guard','before_return'])
def test_linear_body_preserves_described_decisions(mutation):
 assign='state=new A();'
 if mutation=='noise':assign='System.out.println(1);'+assign+'System.out.println(2);'
 if mutation=='nested_guard':assign='if(flag){'+assign+'}'
 algorithm='if(state==null){'+assign+'} return state;'
 if mutation=='before_guard':algorithm='if(flag){'+algorithm+'} return null;'
 if mutation=='before_return':algorithm=algorithm.replace('return state;','if(flag){return state;} return null;')
 result=run('class A {static A state=null; static A get(){'+algorithm+'}}',LINEAR)
 assert bool(result['matches']) is (mutation in ('positive','noise')),result


def test_default_body_remains_subsequence_through_an_unspecified_decision():
 text='class A {static A state=null; static A get(){if(state==null){if(flag){state=new A();}} return state;}}'
 assert run(text,LINEAR.replace('body linear','body'))['matches']

@pytest.mark.parametrize('domain,kind',[('Call','CALL'),('Operation','OPERATION')])
def test_construction_evidence_retains_declared_source_domain(domain,kind):
 query='''language "kql/2"; module evidence;
 pattern Build(out '''+domain+''' $creation) {
 class $unit { method $make { body { let $made=construct $unit {} as $creation; return $made; } } }
 }
 query results { use Build(creation:$site); select $site; }
 '''
 ir=link_project([lower_source('class Item { Item make(){return new Item();} }','java','sample')])
 result=Executor(query_graph(ir),{},None).execute(compile_source(query))
 assert result['matches'],result
 identity=result['matches'][0]['bindings']['$site']
 if kind=='CALL':assert ir.entities[identity].kind=='CALL'
 else:assert any(op.id==identity and op.kind=='CALL' for op in ir.operations)


def test_public_compiler_routes_typed_call_evidence_to_source_plan():
 from ken.kql2.compiler import compile
 from ken.kql2.syntax import parse
 query='''language "kql/2"; module typed;
 pattern P(out Call $site) {
 class $unit { method $make { body { let $value=construct $unit {} as $site; return $value; } } }
 }
 query results { use P(site:$found); select $found; }
 '''
 program=compile(parse(query))
 assert program.graph
