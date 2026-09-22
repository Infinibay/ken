import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from .test_eager_singleton import source

QUERY='''language "kql/2"; module initial;
pattern P(out TypeDecl $unit,out Call $creation) {
 type $unit {field $slot {initializer {construct $unit {} as $creation;} } }
}
query results {use P(unit:$unit,creation:$creation);select $unit,$creation;}
'''
def run(text,lang,query=QUERY):
 return Executor(query_graph(link_project([lower_source(text,lang,'sample')])),{},None).execute(compile_source(query))

@pytest.mark.parametrize('lang',['java','csharp','typescript','javascript'])
@pytest.mark.parametrize('mode',['positive','parentheses','nested','different-type','null-initializer','later'])
def test_declaration_initializer_root_expression(lang,mode):
 text=source(lang,mode if mode not in ('nested','later') else 'positive')
 if mode=='nested':text=text.replace('new Shared()','wrap(new Shared())')
 if mode=='later':text=text.replace('=new Shared()','=null').replace('return ',('Shared.instance' if lang in ('javascript','typescript') else 'instance')+'=new Shared();return ')
 result=run(text,lang)
 assert result['complete'],result
 assert bool(result['matches']) is (mode in ('positive','parentheses')),result


def test_construct_binding_constraint_does_not_force_relational_routing():
 from ken.kql2.syntax import parse
 from ken.kql2.graph import has_graph
 query='''language "kql/2"; module routing;
 query results {
 type $item {}
 callable $make {var $state {} body {let $made=construct $item {initializer $state;};return $made;} }
 select $make.name;
 }
 '''
 assert not has_graph(parse(query))
