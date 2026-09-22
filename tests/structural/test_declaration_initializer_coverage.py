"""Initializer roots preserve partial evidence and ignore transparent comments."""
from dataclasses import replace
import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor

QUERY='''language "kql/2";module t;
pattern p(out TypeDecl $unit,out Call $creation){
 type $unit{field $slot{initializer{construct $unit {} as $creation;}}}
}query q{use p(unit:$unit,creation:$creation);select $unit,$creation;}'''


def execute(text,language='java',mutation=None,query=QUERY):
 graph=link_project([lower_source(text,language,'sample.'+language)])
 assert not graph.diagnostics,graph.diagnostics
 if mutation in ('SYNTAX_NODE','ALLOCATES_TYPE','ASSIGNMENT_TARGET'):
  graph.facts=[f for f in graph.facts if f.relation!=mutation]
 elif mutation=='root-operation':graph.operations=[o for o in graph.operations if o.native_kind!='object_creation_expression']
 elif mutation=='may':graph.facts=[replace(f,attrs={**f.attrs,'modality':'may'}) if f.relation=='ALLOCATES_TYPE' else f for f in graph.facts]
 elif mutation=='may-target':graph.facts=[replace(f,attrs={**f.attrs,'modality':'may'}) if f.relation=='ASSIGNMENT_TARGET' else f for f in graph.facts]
 return Executor(query_graph(graph),{},None).execute(compile_source(query))


@pytest.mark.parametrize('mutation',['SYNTAX_NODE','ALLOCATES_TYPE','ASSIGNMENT_TARGET','root-operation','may','may-target'])
def test_partial_initializer_proof_is_unknown_not_absence_or_certainty(mutation):
 result=execute('class Shared { static Shared instance = new Shared(); }',mutation=mutation)
 assert result['complete'],result
 assert not result['matches'],result
 assert result['unknown'],result


@pytest.mark.parametrize('language',['java','csharp','typescript','javascript'])
@pytest.mark.parametrize('expression',['(/*before*/ new Shared())','(new Shared() /*after*/)','((/*nested*/ new Shared()))'])
def test_comments_inside_transparent_parentheses(language,expression):
 declaration='static Shared instance' if language in ('java','csharp') else 'static instance'
 result=execute('class Shared { '+declaration+' = '+expression+'; }',language)
 assert result['matches'],result
 assert not result['unknown'],result


@pytest.mark.parametrize('expression',['null','wrap(new Shared())','new Other()'])
def test_known_nonconstruction_or_other_type_is_closed_negative(expression):
 result=execute('class Other {} class Shared { static Shared instance = '+expression+'; }')
 assert not result['matches'],result
 assert not result['unknown'],result


@pytest.mark.parametrize('expression,expected',[('build()',True),('wrap(build())',False),('other()',False)])
def test_call_initializer_alias_captures_only_root_occurrence(expression,expected):
 query='''language "kql/2";module t;
 pattern p(out TypeDecl $unit,out Call $creation){
 call $selected{name:"build";}
 type $unit{field $slot{initializer{call $selected {} as $creation;}}}
 }query q{use p(unit:$unit,creation:$creation);select $unit,$creation;}'''
 source='class Shared { static Shared instance = '+expression+'; static Shared build(){return new Shared();} }'
 result=execute(source,query=query)
 assert bool(result['matches']) is expected,result
 assert not result['unknown'],result


@pytest.mark.parametrize('mutation',[None,'SYNTAX_NODE','ALLOCATES_TYPE','ASSIGNMENT_TARGET','root-operation','may','may-target'])
def test_native_initializer_projection_preserves_partial_evidence(mutation,monkeypatch):
 from ken.structural_store import Store
 from tests.kql2.test_graph_columns import stored
 graph=link_project([lower_source('class Shared { static Shared instance = new Shared(); }','java','sample.java')])
 if mutation in ('SYNTAX_NODE','ALLOCATES_TYPE','ASSIGNMENT_TARGET'):
  graph.facts=[f for f in graph.facts if f.relation!=mutation]
 elif mutation=='root-operation':graph.operations=[o for o in graph.operations if o.native_kind!='object_creation_expression']
 elif mutation in ('may','may-target'):
  relation='ALLOCATES_TYPE' if mutation=='may' else 'ASSIGNMENT_TARGET'
  graph.facts=[replace(f,attrs={**f.attrs,'modality':'may'}) if f.relation==relation else f for f in graph.facts]
 memory=query_graph(graph)
 query=compile_source(QUERY)
 expected=Executor(memory,{}).execute(query)
 with Store() as store:
  index=stored(store,memory.ir)
  native=index.operations
  def restricted(**kwargs):
   assert any(value is not None for value in kwargs.values()),'unbounded project operation scan'
   yield from native(**kwargs)
  monkeypatch.setattr(index,'operations',restricted)
  actual=Executor(index,{}).execute(query)
  assert {k:actual[k] for k in ('matches','complete','unknown')}=={k:expected[k] for k in ('matches','complete','unknown')}


def test_native_initializer_children_cross_callable_owners():
 from ken.structural_store import Store
 from ken.kql2.declaration_initializers import Initializers
 from tests.kql2.test_graph_columns import stored
 memory=query_graph(link_project([lower_source('const callback = () => { return build(); };','typescript','sample.ts')]))
 reference=Initializers(memory)
 with Store() as store:
  index=stored(store,memory.ir)
  native=Initializers(index)
  for operation in memory.ir.operations:
   assert [o.id for o in native.children.get(operation.id,())]==[o.id for o in reference.children.get(operation.id,())]
