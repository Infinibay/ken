"""Effective fields preserve the access place and resolve declaration identity."""
import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.query import QueryBudget
from ken.structural.relational import Executor

QUERY='''language "kql/2";module example;
pattern detect(out TypeDecl $unit,out Field $backend) {
 type $contract {name:"Driver";}
 type $unit {name:"Subject";
  field $backend {effective:true;type:nominal($contract);static:false;}
  method $run {name:"render";call $invoke {}
   body {call $invoke {receiver:$backend;};}
  }
 }
}
query results {use detect(unit:$unit,backend:$backend);select $unit,$backend;}
'''
SOURCES={
 'python':'''class Driver:
 def run(self): return 1
class Base:
 backend:Driver
class Subject(Base):
 def render(self):return self.backend.run()
''',
 'typescript':'''class Driver {run(){return 1;}} class Base {backend:Driver;} class Subject extends Base {render(){return this.backend.run();}}''',
 'java':'''class Driver {int run(){return 1;}} class Base {protected Driver backend;} class Subject extends Base {int render(){return this.backend.run();}}''',
}
def run(source,language,query=QUERY):
 index=query_graph(link_project([lower_source(source,language,'sample.'+language)]))
 result=Executor(index,{},QueryBudget()).execute(compile_source(query));assert result['complete'],result
 return result

@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('mutation',['positive','shadow','unrelated','wrong_receiver'])
def test_effective_field_declared_type_and_body_receiver(language,mutation):
 source=SOURCES[language]
 if mutation=='shadow':
  source=source.replace('class Subject(Base):','class Subject(Base):\n backend:int') if language=='python' else source.replace('class Subject extends Base {','class Subject extends Base {backend:number;' if language=='typescript' else 'class Subject extends Base {int backend;')
 if mutation=='unrelated':source=source.replace('class Subject(Base):','class Subject:').replace('class Subject extends Base','class Subject')
 if mutation=='wrong_receiver':source=source.replace('self.backend.run()','other.backend.run()').replace('this.backend.run()','other.backend.run()')
 result=run(source,language)
 certain=[m for m in result['matches'] if not m.get('unknown')]
 assert bool(certain) is (mutation=='positive'),result
 if mutation=='positive':
  assert 'Subject/STORAGE:backend' in certain[0]['bindings']['$backend']

@pytest.mark.parametrize('base',['Missing','Left,Right'])
def test_unresolved_or_multiple_inheritance_is_not_guessed(base):
 source=SOURCES['python'].replace('class Subject(Base):','class Left(Base): pass\nclass Right(Base): pass\nclass Subject('+base+'):')
 result=run(source,'python')
 assert not [m for m in result['matches'] if not m.get('unknown')]
 assert result['unknown'],result


def test_property_shadow_does_not_resolve_to_ancestor_field():
 source=SOURCES['python'].replace('class Subject(Base):','class Subject(Base):\n @property\n def backend(self): return 0')
 result=run(source,'python')
 assert not [m for m in result['matches'] if not m.get('unknown')]
 # A declared property is a known shadow, not an inherited field.


def test_effective_false_preserves_immediate_field_type_lookup():
 assert not run(SOURCES['python'],'python',QUERY.replace('effective:true','effective:false'))['matches']


def test_optional_declaration_capture_is_the_ancestor_identity():
 query=QUERY.replace('out Field $backend','out Field $backend,out Field $declaration').replace('effective:true;','effective:true;declaration:$declaration;').replace('backend:$backend);select $unit,$backend;','backend:$backend,declaration:$declaration);select $unit,$backend,$declaration;')
 result=run(SOURCES['python'],'python',query)
 assert result['matches']
 row=result['matches'][0]['bindings']
 assert row['$declaration'].endswith('/CLASS:Base/STORAGE:backend')
 assert row['$backend'].endswith('/CLASS:Subject/STORAGE:backend')


def test_nearest_shadow_wins_across_multiple_generations():
 source=SOURCES['python'].replace('class Subject(Base):','class Middle(Base):\n backend:int\nclass Subject(Middle):')
 assert not [m for m in run(source,'python')['matches'] if not m.get('unknown')]


def test_declaration_without_effective_is_rejected():
 with pytest.raises(Exception,match='declaration requires effective'):
  compile_source(QUERY.replace('effective:true;','declaration:$decl;'))
