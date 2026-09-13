"""Constructor list entries retain source inputs without inventing execution order."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import SavedRule,execute_rules


def lower(source):
    graph=link_project([lower_source(source,'cpp','initializers.cpp')])
    assert not graph.diagnostics
    return IR.from_dict(graph.to_dict())


def inputs(graph):
    return [(graph.entities[f.subject].name,graph.entities[f.object].name)
            for f in graph.facts if f.relation=='CONSTRUCTOR_FIELD_INPUT']


@pytest.mark.parametrize('form', ['({})','{{{}}}'])
@pytest.mark.parametrize('before', [True,False])
@pytest.mark.parametrize('field_type,parameter_type', [('Worker*','Worker*'),('Worker&','Worker&'),('Worker* const','Worker*'),('const Worker&','const Worker&'),('const int','int')])
def test_direct_input_to_declared_slot(form,before,field_type,parameter_type):
    field=field_type+' receiver;'
    constructor='public:A('+parameter_type+' receiver):receiver'+form.format('receiver')+'{}'
    graph=lower('class Worker{};class A{'+(field+constructor if before else constructor+field)+'};')
    assert inputs(graph)==[('receiver','receiver')]
    initializer=next(f.object for f in graph.facts if f.relation=='HAS_INITIALIZER')
    stored=next(f.object for f in graph.facts if f.subject==initializer and f.relation=='STORES_VALUE')
    target=next(f.object for f in graph.facts if f.subject==initializer and f.relation=='INITIALIZES_FIELD')
    assert graph.entities[stored].kind=='PARAMETER' and graph.entities[target].kind=='STORAGE'
    assert any(o.id==initializer and o.kind=='INITIALIZE' for o in graph.operations)
    assert not any(f.subject==initializer and f.relation in {'ARGUMENT','ASSIGNMENT_VALUE','CFG_NEXT'} for f in graph.facts)


@pytest.mark.parametrize('body,expected', [('',[('receiver','first')]),('receiver=second;',[('receiver','second')]),('receiver=nullptr;',[]),('first=nullptr;',[]),('if(flag){receiver=nullptr;}',[]),('while(flag){receiver=nullptr;}',[]),('publish(this);',[]),('return;receiver=nullptr;',[('receiver','first')])])
def test_body_transfers_follow_initializer_and_keep_last_input(body,expected):
    graph=lower('class Worker{};class A{Worker*receiver;bool flag;public:A(Worker*first,Worker*second):receiver(first){'+body+'}};')
    assert inputs(graph)==expected


def test_two_members_use_their_own_arguments_independent_of_textual_order():
    graph=lower('class Worker{};class A{Worker*first;Worker*second;public:A(Worker*p,Worker*q):second(q),first(p){}};')
    assert set(inputs(graph))=={('first','p'),('second','q')}
    for init in [f.object for f in graph.facts if f.relation=='HAS_INITIALIZER']:
        target=next(f.object for f in graph.facts if f.subject==init and f.relation=='INITIALIZES_FIELD')
        value=next(f.object for f in graph.facts if f.subject==init and f.relation=='STORES_VALUE')
        assert (graph.entities[target].name,graph.entities[value].name) in {('first','p'),('second','q')}


@pytest.mark.parametrize('entry', ['Base()','other(make(first))','other(first,second)','other(second)','receiver(first),receiver(second)'])
def test_unmodeled_entries_do_not_certify_final_constructor_capture(entry):
    graph=lower('class Worker{};class Base{};class A:public Base{Worker*receiver;Worker other;public:A(Worker*first,Worker*second):'+entry+',receiver(first){}};')
    assert not inputs(graph)
    assert any(f.relation=='CONSTRUCTOR_INITIALIZER_STATUS' and f.object=='unsupported' for f in graph.facts)
    assert not [e for e in graph.entities.values() if e.kind=='STORAGE' and e.name=='Base']


def test_delegating_constructor_is_not_an_invented_field():
    graph=lower('class A{public:A(int value){}A():A(2){}};')
    assert not [f for f in graph.facts if f.relation=='INITIALIZES_FIELD']
    assert not inputs(graph)


@pytest.mark.parametrize('declaration,init', [('Worker items[2]','items{}'),('Worker object','object(first)'),('void(*callback)(int)','callback(first)'),('static Worker*shared','shared(first)')])
def test_arrays_objects_callbacks_and_static_fields_are_not_scalar_capture(declaration,init):
    graph=lower('class Worker{};class A{'+declaration+';public:A(Worker*first):'+init+'{}};')
    assert not inputs(graph)
    assert not [f for f in graph.facts if f.relation=='CONSTRUCTOR_INITIALIZER_INPUT']


@pytest.mark.parametrize('entry', ['receiver()','receiver{}','receiver(nullptr)'])
def test_null_initialization_is_attached_to_that_occurrence(entry):
    graph=lower('class Worker{};class A{Worker*receiver;public:A():'+entry+'{}A(Worker*p):receiver(p){}};')
    values=[f for f in graph.facts if f.relation=='STORES_VALUE' and f.object=='NULL']
    assert len(values)==1
    assert inputs(graph)==[('receiver','p')]
    assert not [f for f in graph.facts if f.relation=='INITIALIZED_AS']


def test_explicit_list_input_is_not_the_class_default_initializer():
    graph=lower('class Worker{};class A{Worker*receiver=nullptr;public:A(Worker*p):receiver(p){}};')
    assert inputs(graph)==[('receiver','p')]
    initializer=next(f.object for f in graph.facts if f.relation=='HAS_INITIALIZER')
    assert not [f for f in graph.facts if f.subject==initializer and f.relation=='STORES_VALUE' and f.object=='NULL']


@pytest.mark.parametrize('entry', ['number(0)','number{}','number()','number(42)'])
def test_independent_scalar_initialization_does_not_hide_retained_receiver(entry):
    graph=lower('class Worker{};class A{Worker*receiver;int number;public:A(Worker*p):'+entry+',receiver(p){}};')
    assert inputs(graph)==[('receiver','p')]


@pytest.mark.parametrize('relation', ['INITIALIZER_ARGUMENT','INITIALIZER_FORM','CONSTRUCTOR_INITIALIZER_STATUS','CONSTRUCTOR_INITIALIZER_INPUT','METHOD_SIGNATURE_STATUS','VIRTUAL_METHOD'])
def test_relation_is_known_even_in_a_graph_without_cpp_evidence(relation):
    graph=link_project([lower_source('pass','python','empty.py')])
    result=execute_rules(graph,[SavedRule('empty',f'query empty {{ require $a {relation} $b; emit $a,$b; }}')])
    assert result['complete'] and not result['matches']
