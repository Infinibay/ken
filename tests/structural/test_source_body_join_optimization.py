"""Pure declaration joins prune BODY candidates independently of authoring order."""
import json
from types import SimpleNamespace
import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.query import Clause,QueryBudget
from ken.structural.relational import Executor,Node

QUERY='''language "kql/2"; module example;
pattern detect(out TypeDecl $unit,out Callable $factory,out TypeDecl $product) {
 type $base {method $slot {constructor:false;static:false;}}
 type $unit {method $factory {constructor:false;static:false;
  body {let $created=construct $product {};return $created;}
 }}
 where subtype($unit,$base);
 where overrides($factory,$slot);
}
query results {use detect(unit:$unit,factory:$factory,product:$product);select $unit,$factory,$product;}
'''
def execute(source,query=QUERY,reference=False):
 index=query_graph(link_project([lower_source(source,'python','sample.py')]))
 engine=Executor(index,{},QueryBudget(max_states=2000000,timeout_ms=30000))
 engine.reference=reference
 return engine.execute(compile_source(query))

def normalized(result):
 def atoms(item):
  if isinstance(item,dict):
   if 'relation' in item:return [json.dumps(item,sort_keys=True)]
   return [atom for k,v in item.items() if k not in ('elapsed_ms','stats') for atom in atoms(v)]
  if isinstance(item,list):return [atom for v in item for atom in atoms(v)]
  return []
 return sorted((json.dumps(m.get('bindings',{}),sort_keys=True),tuple(sorted(atoms(m)))) for m in result['matches']),result['unknown']

@pytest.mark.parametrize('body',['return Product()','x=Product()\n  print(1)\n  return x','x=Product()\n  x=0\n  return x','try:\n   return Product()\n  finally:\n   print(1)'])
def test_pure_join_motion_preserves_results_and_evidence(body):
 source='class Product: pass\nclass Base:\n def create(self): pass\nclass Child(Base):\n def create(self):\n  '+body+'\n'
 optimized=execute(source);reference=execute(source,reference=True)
 assert optimized['complete'] and reference['complete']
 assert normalized(optimized)==normalized(reference)


def test_selective_override_runs_before_unrelated_body_cartesian_product():
 source='class Product: pass\nclass Base:\n def create(self): pass\nclass Child(Base):\n def create(self): return Product()\n'
 source+=''.join(f'class Noise{i}:\n def one(self): return 1\n def two(self): return 2\n def three(self): return 3\n' for i in range(18))
 optimized=execute(source);reference=execute(source,reference=True)
 assert optimized['complete'] and reference['complete']
 assert normalized(optimized)==normalized(reference)
 assert optimized['matches']
 assert optimized['stats']['states'] * 5 < reference['stats']['states'],(optimized['stats'],reference['stats'])


def fact(a,b):return Node('fact',Clause('require',a,'TYPE',b))
def engine():return Executor(query_graph(link_project([])),{})

@pytest.mark.parametrize('kind',['any','match','not','count','optional','path'])
def test_scope_boundaries_remain_immovable(kind):
 body=Node('source_body',SimpleNamespace(outputs=('value',)))
 boundary=Node(kind,('dependency',{'unit':'$unit'},'') if kind=='match' else None)
 join=fact('$type','$base')
 nodes=[body,boundary,join]
 assert engine().source_pruned_plan(nodes,{'$type'})==nodes


def test_body_capture_dependency_cannot_be_hoisted():
 body=Node('source_body',SimpleNamespace(outputs=('value',)))
 join=fact('$value','$type')
 assert engine().source_pruned_plan([body,join],{'$owner'})==[body,join]


def test_unbound_filter_cannot_cross_body_even_if_not_an_output():
 body=Node('source_body',SimpleNamespace(outputs=('value',)))
 constraint=Node('where',('$missing.name','==','"X"'))
 assert engine().source_pruned_plan([body,constraint],{'$owner'})==[body,constraint]


def test_source_receiver_dependency_stays_but_independent_join_moves():
 receiver=Node('source_receiver',('$method','$self'))
 dependent=fact('$self','$type')
 independent=fact('$method','$contract')
 assert engine().source_pruned_plan([receiver,independent],{'$method','$contract'})==[independent,receiver]
 assert engine().source_pruned_plan([receiver,dependent],{'$method'})==[receiver,dependent]


def test_compiled_fresh_construction_type_filters_stay_after_producer():
 query=QUERY.replace('where overrides($factory,$slot);',
                     'where overrides($factory,$slot); type $product { name: "Product"; }')
 compiled=compile_source(query)
 planner=engine()
 planned=planner.source_pruned_plan(compiled.nodes,set())
 body=next(n for n in planned if n.kind=='source_body')
 assert 'product' in body.value.outputs
 producer=planned.index(body)
 dependent=[i for i,n in enumerate(planned) if n.kind=='fact'
            and '$product' in (n.value.subject,n.value.object)]
 assert dependent and all(i>producer for i in dependent)
 source='class Product: pass\nclass Other: pass\nclass Base:\n def create(self): pass\nclass Child(Base):\n def create(self): return Other()\n'
 optimized=execute(source,query); reference=execute(source,query,reference=True)
 assert optimized['complete'] and reference['complete']
 assert normalized(optimized)==normalized(reference)
 assert not optimized['matches']


def test_fresh_domain_scan_stays_after_body_but_later_bound_filter_moves():
 body=Node('source_body',SimpleNamespace(outputs=('product',)))
 expansion=fact('$newtype','$newbase')
 restriction=fact('$type','$base')
 planned=engine().source_pruned_plan([body,expansion,restriction],{'$type','$base'})
 assert planned==[restriction,body,expansion]


def test_bound_restriction_can_cross_multiple_independent_bodies():
 first=Node('source_body',SimpleNamespace(outputs=('product',)))
 second=Node('source_body',SimpleNamespace(outputs=('other',)))
 restriction=fact('$type','$base')
 assert engine().source_pruned_plan([first,second,restriction],{'$type','$base'})==[restriction,first,second]


def test_abstract_factory_filters_creators_before_expanding_other_providers():
 import tomllib
 from pathlib import Path
 catalog=tomllib.loads((Path(__file__).parents[2]/'src/ken/structural/patterns/abstract-factory.toml').read_text())
 query=next(v['query'] for v in catalog['variants'] if v['id']=='structural-families')
 source='class A: pass\nclass B: pass\nclass C: pass\nclass D: pass\n'
 source+='class First:\n def make_a(self): return A()\n def make_b(self): return B()\n'
 source+='class Second:\n def make_a(self): return C()\n def make_b(self): return D()\n'
 source+=''.join(f'class Noise{i}:\n def make_a(self): return 1\n def make_b(self): return 2\n def other(self): return 3\n' for i in range(45))
 optimized=execute(source,query);reference=execute(source,query,reference=True)
 assert optimized['complete'] and reference['complete']
 assert optimized['matches']
 assert normalized(optimized)==normalized(reference)
 assert optimized['stats']['states'] < 100000,optimized['stats']


def test_later_body_capture_prevents_crossing_multiple_matchers():
 first=Node('source_body',SimpleNamespace(outputs=('product',)))
 second=Node('source_body',SimpleNamespace(outputs=('other',)))
 restriction=fact('$other','$base')
 assert engine().source_pruned_plan([first,second,restriction],{'$base'})==[first,second,restriction]

@pytest.mark.parametrize('subject,object_,expected',[
 ('$item','CLASS|INTERFACE|CLASS',{'A','B'}),
 ('A|B','CLASS|INTERFACE',{'A','B'}),
 ('$item','VALUE',{'V'}),
])
def test_finite_endpoint_alternatives_use_union_without_duplicate_rows(subject,object_,expected):
 from ken.structural.model import IR,FactIndex
 from ken.structural.relational import Row
 ir=IR('example','python')
 for name,kind in [('A','CLASS'),('B','INTERFACE'),('V','VALUE')]:ir.add(name,'ENTITY',kind)
 for i in range(1000):ir.add('noise'+str(i),'ENTITY','OPERATION')
 planner=Executor(FactIndex(ir),{})
 hits=planner.facts(Clause('require',subject,'ENTITY',object_),Row())
 assert {h.evidence[-1]['subject'] for h in hits}==expected
 assert len(hits)==len(expected)
 assert planner.rows==len(expected)


def test_quoted_pipe_endpoint_is_literal_not_alternatives():
 from ken.structural.model import IR,FactIndex
 from ken.structural.query import QuotedTerm
 from ken.structural.relational import Row
 ir=IR('example','python')
 ir.add('literal','ENTITY','A|B');ir.add('alternative','ENTITY','A')
 planner=Executor(FactIndex(ir),{})
 hits=planner.facts(Clause('require','$subject','ENTITY',QuotedTerm('"A|B"')),Row())
 assert [h.bindings['$subject'] for h in hits]==['literal']


def test_endpoint_union_buckets_still_filter_both_endpoints():
 from ken.structural.model import IR,FactIndex
 from ken.structural.relational import Row
 ir=IR('example','python')
 for subject,obj in [('A','X'),('A','Z'),('B','Y'),('C','X'),('C','Y')]:ir.add(subject,'TYPE',obj)
 planner=Executor(FactIndex(ir),{})
 hits=planner.facts(Clause('require','A|B','TYPE','X|Y'),Row())
 assert {(h.evidence[-1]['subject'],h.evidence[-1]['object']) for h in hits}=={('A','X'),('B','Y')}


def test_named_query_outputs_enable_later_body_pruning_without_crossing_scope():
 dependency=Node('match',('factory',{'unit':'$unit','configure':'$configure'},''))
 owner=fact('$unit','$algorithm')
 body=Node('source_body',SimpleNamespace(outputs=()))
 constraint=Node('where',('$configure','!=','$algorithm'))
 nodes=[dependency,owner,body,constraint]
 assert engine().source_pruned_plan(nodes,set()) == [dependency,owner,constraint,body]


def test_named_query_output_pruning_preserves_reference_evidence():
 query='''language "kql/2"; module example;
 pattern supplied(out TypeDecl $unit,out Callable $configure) {
   type $unit {method $configure {name:"configure";}}
 }
 pattern detect(out TypeDecl $unit,out Callable $algorithm) {
   use supplied(unit:$unit,configure:$configure);
   type $unit {method $algorithm {body {return _;}}}
   where $configure != $algorithm;
 }
 query results {use detect(unit:$unit,algorithm:$algorithm);select $unit,$algorithm;}
 '''
 source='class Context:\n def configure(self): return 1\n def apply(self): return 2\n'
 optimized=execute(source,query); reference=execute(source,query,reference=True)
 assert normalized(optimized)==normalized(reference)
 assert len(optimized['matches'])==1
 assert optimized['stats']['states'] < reference['stats']['states']


@pytest.mark.parametrize('removed',[None,'ASSIGNMENT_VALUE','CFG_STATUS'])
@pytest.mark.parametrize('statement',[
 'self.field=p',
 'self.field=p\n  print(p)',
 'self.field=1',
 'if p:\n   self.field=p',
])
def test_assignment_candidate_pruning_preserves_partial_graph_and_evidence(removed,statement):
 query='''language "kql/2"; module example;
 pattern detect(out TypeDecl $unit) {
  type $unit {field $field {} method $method {param $p {} body {$field=$p;}}}
 }
 query results {use detect(unit:$unit);select $unit;}
 '''
 graph=link_project([lower_source('class C:\n def configure(self,p):\n  '+statement+'\n','python','sample.py')])
 if removed:
  graph.facts=[fact for fact in graph.facts if fact.relation!=removed]
 results=[]
 for reference in (False,True):
  executor=Executor(query_graph(graph),{},QueryBudget(max_states=100000))
  executor.reference=reference
  results.append(executor.execute(compile_source(query)))
 assert all(result['complete'] for result in results)
 assert normalized(results[0])==normalized(results[1])
 if statement=='self.field=p' and removed!='CFG_STATUS':
  assert results[0]['matches']
