"""Pattern-owned named queries reuse hygienic matches without extending GoF unions."""
from dataclasses import replace
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import SavedRule, builtin_rules, named_rule, execute_rules, query_registry, save_rule, read_rules


SOURCES={
 'python':'def f(xs):\n for item in xs:\n  use(item)\n',
 'javascript':'function f(xs){for(const item of xs){use(item);}}',
 'typescript':'function f(xs: User[]){for(const item of xs){use(item);}}',
 'java':'class C{void f(User[] xs){for(User item:xs){use(item);}}}',
 'csharp':'class C{void F(User[] xs){foreach(User item in xs){Use(item);}}}',
 'cpp':'void f(Users xs){for(auto item:xs){use(item);}}',
 'rust':'fn f(xs:Vec<User>){for item in xs{use_item(item);}}',
 'go':'package p;func f(xs []User){for _,item:=range xs{use(item)}}',
}


def run(source,language,query=None):
 g=link_project([lower_source(source,language,'sample')])
 assert not g.diagnostics
 registry=builtin_rules()
 rule=SavedRule('custom',query)if query else named_rule('iterator.iterate_over',registry)
 result=execute_rules(g,[rule],registry=registry)
 assert result['complete']
 return g,result['matches']


@pytest.mark.parametrize('language',SOURCES)
def test_foreach_operation_in_source(language):
 g,hits=run(SOURCES[language],language)
 assert len(hits)==1
 bindings=hits[0]['bindings']
 assert g.entities[bindings['$item']].name=='item'
 assert g.entities[bindings['$source']].name=='xs'
 assert any(o.id==bindings['$body']for o in g.operations)


def test_named_operation_is_not_a_gof_detector_variant():
 registry=builtin_rules()
 query=query_registry(registry)['gof.iterator']
 assert 'iterate_over' not in repr(query)
 assert 'iterator.iterate_over' in query_registry(registry)


def test_two_loops_do_not_cross_join_source_and_body():
 source='def f(xs,ys):\n for one in xs:\n  first(one)\n for two in ys:\n  second(two)\n'
 g,hits=run(source,'python')
 assert {(g.entities[h['bindings']['$source']].name,g.entities[h['bindings']['$item']].name)for h in hits}=={('xs','one'),('ys','two')}
 assert len(hits)==2


def test_operation_inside_another_query_can_constrain_each_usage():
 g,hits=run(SOURCES['python'],'python','query q {match "iterator.iterate_over"(source:$s,body:$b); require $s ENTITY "PARAMETER"; emit $s,$b;}')
 assert len(hits)==1


def test_go_index_only_does_not_become_a_value_binding():
 _,hits=run('package p;func f(xs []User){for index:=range xs{use(index)}}','go')
 assert hits==[]


def test_destructuring_needs_a_separate_binding_model():
 _,hits=run('def f(xs):\n for a,b in xs:\n  use(a)\n','python')
 assert hits==[]


@pytest.mark.parametrize('language',['javascript','typescript'])
def test_property_keys_are_not_array_values(language):
 _,hits=run('function f(xs){for(const key in xs){use(key);}}',language)
 assert hits==[]


def test_python_underscore_is_a_real_binding():
 g,hits=run('def f(xs):\n for _ in xs:\n  use(_)\n','python')
 assert len(hits)==1 and g.entities[hits[0]['bindings']['$item']].name=='_'


def test_cpp_reference_binding_is_an_iteration_element():
 _,hits=run('void f(Users& xs){for(auto& item:xs){use(item);}}','cpp')
 assert len(hits)==1


def custom():
 return SavedRule('custom','query q {require $a EDGE $b;emit $a;}',operations=[{'id':'uses','status':'ready','query':'query use {require $x EDGE $y;emit $x,$y;}'}])


def test_operations_roundtrip_in_the_same_toml(tmp_path):
 rule=custom()
 path=save_rule(tmp_path,rule)
 assert '[[operations]]'in path.read_text()
 loaded=read_rules(path)[0]
 assert loaded.operations==rule.operations
 assert 'custom.uses'in query_registry([loaded])


@pytest.mark.parametrize('operation',[
 {'id':'bad.name','status':'ready','query':'query q {require $x EDGE $y;emit $x;}'},
 {'id':'use','status':'ready'},
 {'id':'use','status':'typo'},
 {'id':'use','status':'design','unexpected':'value'},
])
def test_invalid_operation_contract(operation):
 with pytest.raises(ValueError):replace(custom(),operations=[operation]).validate()


def test_operation_does_not_shadow_an_existing_query():
 with pytest.raises(ValueError,match='duplicate named query'):
  query_registry([custom(),SavedRule('custom.uses','query q {require $x EDGE $y;emit $x;}')])


def test_save_checks_operation_collision_before_writing(tmp_path):
 with pytest.raises(ValueError,match='duplicate named query'):
  save_rule(tmp_path,SavedRule('iterator.iterate_over','query q {require $x EDGE $y;emit $x;}'))
 assert not (tmp_path/'.ken/rules/iterator.iterate_over.toml').exists()
