"""A class expression is a class value with its own lexical definition site."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import builtin_rules,named_rule,execute_rules

LANGUAGES=['javascript','typescript']

def graph(source,language='javascript',path='classes'):
    g=IR.from_dict(link_project([lower_source(source,language,path)]).to_dict());assert not g.diagnostics;return g

def expressions(g):return [e for e in g.entities.values() if e.kind=='CLASS' and e.attrs.get('expression')]


@pytest.mark.parametrize('language',LANGUAGES)
@pytest.mark.parametrize('name',['','Local'])
@pytest.mark.parametrize('place',['assignment','return','argument','array','parentheses'])
def test_class_value_identity_is_preserved(language,name,place):
    expression='class '+name+'{render(){return 1;}}'
    text={'assignment':'const Result='+expression+';','return':'function make(){return '+expression+';}','argument':'consume('+expression+');','array':'const choices=['+expression+'];','parentheses':'const Result=(('+expression+'));'}[place]
    g=graph(text,language);units=expressions(g);assert len(units)==1;unit=units[0]
    assert any(f.relation=='CLASS_EXPRESSION' and f.object==unit.id for f in g.facts)
    assert len([f for f in g.facts if f.relation=='HAS_METHOD' and f.subject==unit.id])==1
    if place in {'assignment','parentheses'}:assert any(f.relation=='ASSIGNMENT_VALUE' and f.object==unit.id for f in g.facts)
    if place=='return':assert any(f.relation=='RETURN_OPERAND' and f.object==unit.id for f in g.facts)
    if place=='argument':assert any(f.relation=='ARGUMENT' and f.object==unit.id for f in g.facts)


@pytest.mark.parametrize('language',LANGUAGES)
def test_two_same_named_expressions_are_not_merged(language):
    g=graph('const A=class Local{a(){}};const B=class Local{b(){}};',language)
    units=expressions(g);assert len(units)==2 and len({u.id for u in units})==2
    slots=[{g.entities[f.object].name for f in g.facts if f.relation=='HAS_METHOD' and f.subject==u.id} for u in units]
    assert slots==[{'a'},{'b'}]


@pytest.mark.parametrize('language',LANGUAGES)
def test_internal_name_resolves_only_inside_its_expression(language):
    g=graph('const A=class Hidden{copy(){return new Hidden();}};function outside(){return new Hidden();}',language)
    unit=expressions(g)[0];allocations=[f for f in g.facts if f.relation=='ALLOCATES_TYPE'];assert len(allocations)==1 and allocations[0].object==unit.id
    assert 'copy@' in allocations[0].subject


@pytest.mark.parametrize('language',LANGUAGES)
def test_internal_name_does_not_hide_an_outer_class_from_other_functions(language):
    g=graph('class Shared{}const A=class Shared{copy(){return new Shared();}};function outside(){return new Shared();}',language)
    exp=expressions(g)[0];plain=next(e for e in g.entities.values() if e.kind=='CLASS' and not e.attrs.get('expression'))
    allocations=[f for f in g.facts if f.relation=='ALLOCATES_TYPE'];assert len(allocations)==2
    assert any(f.object==exp.id and 'copy@' in f.subject for f in allocations)
    assert any(f.object==plain.id and 'outside@' in f.subject for f in allocations)


@pytest.mark.parametrize('language',LANGUAGES)
def test_expression_name_does_not_leak_across_files(language):
    g=link_project([lower_source('const A=class Hidden{};',language,'one.js'),lower_source('function make(){return new Hidden();}',language,'two.js')])
    assert not any(f.relation=='ALLOCATES_TYPE' for f in g.facts)


@pytest.mark.parametrize('language',LANGUAGES)
def test_fields_and_methods_of_nested_class_expressions_are_separate(language):
    g=graph('class Outer{static #value=1;static nested=class Inner{static #value=2;static get(){return Inner.#value;}};}',language)
    units=[e for e in g.entities.values() if e.kind=='CLASS'];assert len(units)==2
    slots=[f for f in g.facts if f.relation=='HAS_FIELD' and g.entities[f.object].name=='#value'];assert len(slots)==2 and len({f.object for f in slots})==2
    inner=expressions(g)[0];slot=next(f.object for f in slots if f.subject==inner.id)
    assert any(f.relation=='RETURN_OPERAND' and f.object==slot for f in g.facts)
    assert all(f.subject==inner.id for f in g.facts if f.relation=='HAS_METHOD')


@pytest.mark.parametrize('language',LANGUAGES)
def test_factory_does_not_own_return_or_generator_operations_inside_class(language):
    g=graph('function make(){return class{*values(){yield 1;return 2;}async run(){return await load();}};}',language)
    factory=next(e for e in g.entities.values() if e.kind=='CALLABLE' and e.name=='make');unit=expressions(g)[0]
    assert [f.object for f in g.facts if f.relation=='RETURNS' and f.subject==factory.id]==[unit.id]
    assert not any(f.subject==factory.id and f.relation in {'HAS_YIELD','HAS_AWAIT'} for f in g.facts)


@pytest.mark.parametrize('language',LANGUAGES)
def test_static_shared_pattern_is_attributed_to_inner_class_not_outer(language):
    g=graph('class Outer{static nested=class Outer{static #value=new Outer();static get(){return Outer.#value;}};}',language)
    rules=builtin_rules();out=execute_rules(g,[named_rule('singleton.shared_instance',rules)],registry=rules);assert out['complete'] and len(out['matches'])==1
    assert out['matches'][0]['bindings']['$unit']==expressions(g)[0].id


@pytest.mark.parametrize('language',LANGUAGES)
def test_nominal_base_of_a_class_expression_resolves(language):
    g=graph('class Parent{}const Child=class extends Parent{run(){}};',language);unit=expressions(g)[0]
    assert any(f.subject==unit.id and f.relation=='SUBTYPE_OF' and g.entities[f.object].name=='Parent' for f in g.facts)


@pytest.mark.parametrize('language',LANGUAGES)
def test_self_named_base_does_not_invent_an_inheritance_cycle(language):
    g=graph('class Same{}const Child=class Same extends Same{};',language);unit=expressions(g)[0]
    assert not any(f.subject==unit.id and f.relation=='SUBTYPE_OF' for f in g.facts)


@pytest.mark.parametrize('language',LANGUAGES)
def test_class_alias_allocation_is_not_guessed_from_historical_assignment(language):
    g=graph('const Alias=class Named{};function make(){return new Alias();}',language)
    assert not any(f.relation=='ALLOCATES_TYPE' for f in g.facts)


@pytest.mark.parametrize('language',LANGUAGES)
def test_arrow_class_body_does_not_get_a_callable_cfg(language):
    g=graph('const mix=(base)=>class extends base{run(){return 1;}};',language);unit=expressions(g)[0]
    assert not any(f.subject==unit.id and f.relation in {'CFG_ENTRY','CFG_EXIT','CFG_STATUS'} for f in g.facts)
    assert any(f.relation=='BODY_VALUE' and f.object==unit.id for f in g.facts)


def test_typescript_implements_is_not_a_runtime_base_value():
    g=graph('interface Contract{}class Base{}class C extends Base implements Contract{}','typescript')
    links=[f for f in g.facts if f.relation=='BASE_VALUE'];assert len(links)==1
    assert g.entities[links[0].object].name=='Base'
    assert len([f for f in g.facts if f.relation=='SUBTYPE_OF'])==2


@pytest.mark.parametrize('language',['python','javascript','typescript'])
def test_imported_nominal_base_survives_an_unresolved_reference_value(language):
    if language=='python':texts=[('model.py','class Base: pass'),('child.py','from model import Base\nclass C(Base): pass\nconsume(Base)\n')]
    else:
        ext='.js' if language=='javascript' else '.ts';texts=[('model'+ext,'export class Base{}'),('child'+ext,'import {Base} from "./model";class C extends Base{}consume(Base);')]
    g=link_project([lower_source(s,language,p) for p,s in texts]);assert not g.diagnostics
    assert any(f.relation=='SUBTYPE_OF' and g.entities[f.object].name=='Base' for f in g.facts)
