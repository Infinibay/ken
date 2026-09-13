"""C++ declaration syntax and field-use identity remain correlated."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import execute_rules,SavedRule

DECLARATORS=['Driver slot','Driver *slot','Driver &slot','Driver &&slot',
 'const Driver *slot','Driver const *slot','Driver * const slot','Driver *const slot',
 'volatile Driver &slot','Driver * volatile slot','Driver **slot','Driver slots[3]',
 'Driver *slots[3]','Driver (*matrix)[3]','void (*callback)(int)']


def lower(source):
    graph=link_project([lower_source(source,'cpp','fields.cpp')]);assert not graph.diagnostics
    return IR.from_dict(graph.to_dict())


@pytest.mark.parametrize('declaration',DECLARATORS)
@pytest.mark.parametrize('before',[False,True])
def test_declarator_identity_and_contract(declaration,before):
    name='slots' if 'slots' in declaration else 'matrix' if 'matrix' in declaration else 'callback' if 'callback' in declaration else 'slot'
    use=f'void inspect(){{consume({name});}}'
    field=declaration+';';body=field+use if before else use+field
    graph=lower('class Driver {};class Subject{'+body+'};')
    slots=[graph.entities[f.object] for f in graph.facts if f.relation=='HAS_FIELD']
    assert len(slots)==1 and slots[0].name==name
    slot=slots[0];assert slot.attrs['declared'] is True
    assert slot.attrs['native_type']==declaration.replace(name,'').strip()
    assert all(f.subject==slot.id for f in graph.facts if f.relation=='TYPE_NAME' and f.object==slot.attrs['native_type'])
    assert any(f.relation=='ARGUMENT' and f.object==slot.id for f in graph.facts)
    driver=next(e.id for e in graph.entities.values() if e.name=='Driver')
    expected='**' not in declaration and name=='slot'
    assert any(f.relation=='TYPE' and f.subject==slot.id and f.object==driver for f in graph.facts)==expected
    assert all(f.object=='supported' for f in graph.facts if f.relation=='CPP_FIELD_DECL_STATUS')


@pytest.mark.parametrize('declaration',['Driver *slot','Driver &slot','const Driver *slot','Driver * const slot'])
@pytest.mark.parametrize('rename',[False,True])
def test_receiver_is_the_declared_typed_field(declaration,rename):
    arrow='.' if '&' in declaration else '->'
    source='class Driver{public:void run(){}};class A{'+declaration+';void use(){slot'+arrow+'run();}};'
    if rename:source=source.replace('Driver','Backend').replace('slot','worker')
    graph=lower(source)
    query='query q { require $class HAS_FIELD $field; require $field TYPE $type; require $class HAS_METHOD $method; require $method DELEGATES_TO $field; emit $class,$field,$type,$method; }'
    out=execute_rules(graph,[SavedRule('typed-field',query)]);assert out['complete'] and len(out['matches'])==1


def test_multiple_declarators_have_independent_types_and_initializers():
    graph=lower('class Driver{};class A{Driver *first=nullptr, second, **third=nullptr;};')
    fields={e.name:e for e in graph.entities.values() if e.kind=='STORAGE'}
    assert {n:e.attrs['native_type'] for n,e in fields.items()}=={'first':'Driver *','second':'Driver','third':'Driver **'}
    initialized={f.subject for f in graph.facts if f.relation=='INITIALIZED_AS'}
    assert initialized=={fields['first'].id,fields['third'].id}
    targets=[f for f in graph.facts if f.relation=='ASSIGNMENT_TARGET']
    assert len(targets)==2 and len({f.subject for f in targets})==2
    assert {f.subject for f in targets}<={o.id for o in graph.operations}


@pytest.mark.parametrize('prefix,static',[('',False),('static ',True),('/* static */ ',False),('const ',False),('mutable ',False)])
def test_field_modifiers_are_syntax(prefix,static):
    graph=lower('class Driver{};class A{'+prefix+'Driver *first, *second;};')
    fields=[graph.entities[f.object] for f in graph.facts if f.relation=='HAS_FIELD']
    assert len(fields)==2 and all(e.attrs['static'] is static for e in fields)
    assert all(f.attrs['static'] is static for f in graph.facts if f.relation=='HAS_FIELD')


def test_methods_and_callback_parameters_do_not_become_fields():
    graph=lower('class Driver{};class A{Driver *get(int value); void method(); int (plain)(int ignored); void (*callback)(int argument);};')
    assert [graph.entities[f.object].name for f in graph.facts if f.relation=='HAS_FIELD']==['callback']
    assert not any(e.kind=='STORAGE' and e.name in {'value','argument','get','method'} for e in graph.entities.values())


def test_qualified_type_does_not_bind_to_local_basename():
    graph=lower('class Driver{};class A{external::Driver *slot;};')
    slot=next(e for e in graph.entities.values() if e.name=='slot')
    assert slot.attrs['native_type']=='external::Driver *'
    assert not [f for f in graph.facts if f.relation=='TYPE' and f.subject==slot.id]
