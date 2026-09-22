import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.query_view import query_graph
from ken.structural.semantic import link_project
from ken.structural.relational import Executor

QUERY='''language "kql/2"; module effects;
pattern detect(out Callable $init) {
 class $unit { constructor $init { receiver $self { escapes: false; } } }
}
query results { use detect(init: $init); select $init; }
'''

@pytest.mark.parametrize('body,accepted',[
 ('this.value=value; System.out.println(value);',True),
 ('this.value=value; publish(this);',False),
 ('this.value=value; Object alias=this; publish(alias);',False),
 ('this.value=value; Object[] values={this}; publish(values);',False),
 ('this.value=value; this.opaque();',False),
])
def test_constructor_receiver_escape(body,accepted):
 source='class Item { int value; Item(int value){'+body+'} }'
 result=Executor(query_graph(link_project([lower_source(source,'java','item.java')])),{},None).execute(compile_source(QUERY))
 assert result['complete']
 assert bool(result['matches']) is accepted,result

@pytest.mark.parametrize('language,source',[
 ('python','class Item:\n def __init__(self, value):\n  self.value=value\n  print(value)\n'),
 ('typescript','class Item { value:number; constructor(value:number){this.value=value; console.log(value);} }'),
 ('java','class Item { Item(){} Item(int value){this(); System.out.println(value);} }'),
])
def test_nonreceiver_logging_and_known_constructor_delegation(language,source):
 result=Executor(query_graph(link_project([lower_source(source,language,'sample')])),{},None).execute(compile_source(QUERY))
 assert result['complete'] and result['matches'],result

@pytest.mark.parametrize('body',[
 'Object alias=this;',
 'Runnable callback=()->publish(this);',
 'return;',
])
def test_unproved_capture_or_alias_is_unknown_not_safe(body):
 result=Executor(query_graph(link_project([lower_source('class Item { Item(){'+body+'} }','java','sample')])),{},None).execute(compile_source(QUERY))
 # Bare return transfers no object and remains locally nonescaping.
 if body=='return;':
  assert result['matches']
 else:
  assert not result['matches'] and result['unknown'],result


def test_receiver_effect_scope_survives_query_role_rename():
 query=QUERY.replace('use detect(init: $init); select $init;', 'use detect(init: $renamed); select $renamed;')
 result=Executor(query_graph(link_project([lower_source('class Item { Item(){} }','java','sample')])),{},None).execute(compile_source(query))
 assert result['matches'],result


def test_opaque_base_constructor_is_not_proved_nonescaping():
 source='class Item extends External { Item(){super();} }'
 result=Executor(query_graph(link_project([lower_source(source,'java','sample')])),{},None).execute(compile_source(QUERY))
 assert not result['matches'] and result['unknown'],result

@pytest.mark.parametrize('language,source',[
 ('python',"class Item:\n def __init__(self):\n  exec('publish(self)')\n"),
 ('python',"class Item:\n def __init__(self):\n  eval('publish(self)')\n"),
 ('javascript',"class Item {constructor(){eval('publish(this)');}}"),
])
def test_dynamic_execution_cannot_prove_nonescape(language,source):
 result=Executor(query_graph(link_project([lower_source(source,language,'sample')])),{},None).execute(compile_source(QUERY))
 assert not result['matches'] and result['unknown'],result


def test_implicit_base_initialization_is_not_proved_nonescaping():
 source='class Item extends External { Item(){} }'
 result=Executor(query_graph(link_project([lower_source(source,'java','sample')])),{},None).execute(compile_source(QUERY))
 assert not result['matches'] and result['unknown'],result

@pytest.mark.parametrize('language,source',[
 ('java','interface Prototype {} class Item implements Prototype { Item(){} }'),
 ('csharp','interface Prototype {} class Item: Prototype { Item(){} }'),
 ('java','interface First {} interface Second {} class Item implements First,Second { Item(){} }'),
])
def test_resolved_interface_base_has_no_constructor_effect(language,source):
 result=Executor(query_graph(link_project([lower_source(source,language,'sample')])),{},None).execute(compile_source(QUERY))
 assert result['matches'],result

@pytest.mark.parametrize('language,source',[
 ('java','interface Prototype {} class Item extends External implements Prototype { Item(){} }'),
 ('csharp','interface Prototype {} class Item: External,Prototype { Item(){} }'),
 ('java','class Base {} class Item extends Base { Item(){} }'),
 ('csharp','class Base {} class Item: Base { Item(){} }'),
 ('java','class Item implements External { Item(){} }'),
])
def test_interface_resolution_does_not_hide_class_or_unknown_base(language,source):
 result=Executor(query_graph(link_project([lower_source(source,language,'sample')])),{},None).execute(compile_source(QUERY))
 matches=[m for m in result['matches'] if '/CLASS:Item/' in str(m)]
 assert not matches and result['unknown'],result
