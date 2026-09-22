import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from .test_strategy_binding_inputs import source

QUERY='''language "kql/2"; module retained;
pattern detect(out TypeDecl $unit, out Parameter $supplied) {
 type $unit {field $policy {} method $configure {param $supplied {reassigned:false;} body linear {
 $policy=$supplied;
 gap until exit {forbid assign(binding($policy));}
 } } }
}
query results {use detect(unit:$unit,supplied:$supplied);select $unit,$supplied;}
'''

def run(text,language,query=QUERY):
 result=Executor(query_graph(link_project([lower_source(text,language,'sample')])),{},None).execute(compile_source(query))
 assert result['complete'],result
 return result

@pytest.mark.parametrize('language',['python','java','typescript','cpp','csharp'])
@pytest.mark.parametrize('change',['positive','overwrite-before','overwrite-after','rebind-before','rebind-after','return-before','return-after','other-parameter-final','branch','loop'])
def test_terminal_binding_assignment_contract(language,change):
 result=run(source(language,'object',change),language)
 assert bool(result['matches']) is (change in ('positive','overwrite-before','return-after','other-parameter-final')),result

@pytest.mark.parametrize('language,text',[
 ('typescript','class A {constructor(public field: object){} }'),
 ('cpp','class A {void*field; public:A(void*input):field{input}{} };'),
])
def test_constructor_initializer_precedes_body(language,text):
 query='''language "kql/2"; module init;
 pattern P(out Callable $constructor) {
 class $unit {field $field {} constructor $constructor {param $input {reassigned:false;} body linear {
 initializer {$field=$input;}
 gap until exit {forbid assign(binding($field));}
 } } }
 }
 query results {use P(constructor:$constructor);select $constructor;}
 '''
 assert run(text,language,query)['matches']

@pytest.mark.parametrize('suffix,expected',[
 ('log(1);',True),
 ('return; field=null;',True),
 ('field=null;',False),
 ('if(flag){field=null;}',False),
 ('field++;',False),
 ('eval("field=null");',False),
])
def test_terminal_suffix_explicit_write_and_unknown_inventory(suffix,expected):
 text='class A {field:object; configure(input:object){this.field=input;'+suffix.replace('field','this.field')+'}}'
 assert bool(run(text,'typescript')['matches']) is expected


def test_anchor_statement_does_not_hide_an_outer_assignment():
 text='class A {Object field;void configure(Object input){field=(field=input);}}'
 assert not run(text,'java')['matches']


@pytest.mark.parametrize('change',['log','overwrite','publish','alias','container','dynamic'])
def test_constructor_initializer_retention_requires_no_publication(change):
 from ken.structural.rules import builtin_rules,named_rule,execute_rules
 suffix={'log':'console.log(1);','overwrite':'this.field=null;',
         'publish':'publish(this);','alias':'let alias=this;publish(alias);',
         'container':'publish([this]);','dynamic':'eval("publish(this)");'}[change]
 text='class A {constructor(public field:object){'+suffix+'} run(){this.field.execute();}}'
 rules=builtin_rules()
 graph=link_project([lower_source(text,'typescript','sample')])
 result=execute_rules(graph,[named_rule('architecture.dependency-injection#retained-object',rules)],registry=rules)
 assert result['complete'],result
 assert bool(result['matches']) is (change=='log'),result


def test_terminal_gap_and_initializer_route_public_compiler():
 from ken.kql2.compiler import compile as compile_query
 # Routing is necessary without any other graph-backed selector property.
 source=QUERY.replace('reassigned:false;','')
 from ken.kql2.syntax import parse
 program=compile_query(parse(source))
 assert program is not None
 from ken.kql2.graph import has_graph
 from ken.kql2.syntax import parse
 assert has_graph(parse(source))


@pytest.mark.parametrize('clause',[
 'gap until exit {forbid assign(binding($policy));} $policy=$supplied;',
 '$policy=$supplied; gap until exit {forbid write(binding($policy));}',
 '$policy=$supplied; gap until exit {}',
 '$policy=$supplied; initializer {$policy=$supplied;}',
])
def test_invalid_terminal_and_initializer_placement_is_rejected(clause):
 from ken.kql2.compiler import CompileError
 query=QUERY.replace('$policy=$supplied;\n gap until exit {forbid assign(binding($policy));}',clause)
 with pytest.raises(CompileError):compile_source(query)
