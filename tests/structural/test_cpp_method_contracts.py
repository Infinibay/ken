"""Source-level virtual slots, signature correspondence and pattern witnesses."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import builtin_rules, execute_rules, named_rule, SavedRule


def graph(source):
    result = link_project([lower_source(source, 'cpp', 'contract.cpp')])
    assert not result.diagnostics
    return IR.from_dict(result.to_dict())


def overrides(result):
    return [(result.entities[f.subject], result.entities[f.object])
            for f in result.facts if f.relation == 'OVERRIDES']


@pytest.mark.parametrize('base_body', ['= 0;', ';', '{}'])
@pytest.mark.parametrize('suffix', ['', ' const', ' volatile', ' const volatile', ' &', ' const &', ' &&'])
@pytest.mark.parametrize('parameter', ['int value', 'const P &value', 'P *value', ''])
def test_virtual_signature_does_not_require_override_keyword(base_body, suffix, parameter):
    result = graph(f'class P{{}};class Base{{virtual void run({parameter}){suffix}{base_body}}};'
                   f'class Child:public Base{{void run({parameter.replace("value", "renamed")}){suffix}{{}}}};')
    pairs = overrides(result)
    assert len(pairs) == 1 and all(e.name == 'run' for e in pairs[0])
    assert all(f.attrs['basis'] == 'cpp-resolved-virtual-signature' for f in result.facts if f.relation == 'OVERRIDES')
    assert len([f for f in result.facts if f.relation == 'VIRTUAL_METHOD']) == 2


@pytest.mark.parametrize('base,child', [
    ('void run(int);', 'void run(int) {}'),  # Ordinary name hiding.
    ('static void run(int);', 'void run(int) {}'),
    ('virtual void run(int);', 'void run(long) {}'),
    ('virtual void run();', 'void run(int) {}'),
    ('virtual void run() const;', 'void run() {}'),
    ('virtual void run() &;', 'void run() && {}'),
    ('virtual void run(const P*);', 'void run(P*) {}'),
    ('virtual void run(P&);', 'void run(P&&) {}'),
    ('virtual void run(P*, ...);', 'void run(P*) {}'),
])
def test_same_name_is_not_sufficient(base, child):
    result = graph(f'class P{{}};class Base{{{base}}};class Child:public Base{{{child}}};')
    assert not overrides(result)


@pytest.mark.parametrize('base,child', [
    ('const int value=1', 'int renamed'),
    ('P* const value', 'P* renamed'),
    ('int values[3]', 'int* renamed'),
    ('void', ''),
    ('int', 'int renamed=3'),
    ('const P* value', 'P const* renamed'),
])
def test_parameter_adjustments_and_defaults(base, child):
    result = graph(f'class P{{}};class Base{{virtual void run({base});}};'
                   f'class Child:public Base{{void run({child}){{}}}};')
    assert len(overrides(result)) == 1


def test_virtuality_propagates_independent_of_class_order():
    result = graph('class Last:public Middle{void run(int){}};'
                   'class Middle:public First{void run(int){}};'
                   'class First{virtual void run(int)=0;};')
    assert len(overrides(result)) == 3
    assert len([f for f in result.facts if f.relation == 'VIRTUAL_METHOD']) == 3


def test_overloads_keep_distinct_identities_and_only_corresponding_edges():
    result = graph('class Base{virtual void run(int)=0;virtual void run(long)=0;};'
                   'class Child:public Base{void run(int){}void run(long){}};')
    pairs = overrides(result)
    assert len(pairs) == 2
    parameters = {f.subject:result.entities[f.object].attrs['native_type']
                  for f in result.facts if f.relation == 'HAS_PARAMETER'}
    assert all(parameters[a.id] == parameters[b.id] for a,b in pairs)
    assert len({e.id for p in pairs for e in p}) == 4


def test_prototypes_have_metadata_and_no_fake_execution():
    result = graph('class P{};class A{virtual const P *make(int value=3) const & = 0;'
                   'void run() override final;static void shared();A();virtual ~A()=default;};')
    methods = {e.name:e for e in result.entities.values() if e.kind == 'CALLABLE'}
    assert set(methods) == {'make','run','shared','A','~A'}
    assert methods['make'].attrs['native_return_type'] == 'const P *'
    assert methods['make'].attrs['pure_virtual']
    assert methods['make'].attrs['cv_qualifiers'] == ['const']
    assert methods['make'].attrs['ref_qualifier'] == '&'
    assert methods['run'].attrs['override_specifier'] and methods['run'].attrs['final_specifier']
    assert methods['shared'].attrs['static']
    assert methods['A'].attrs['constructor']
    assert all(e.attrs['declaration_only'] for e in methods.values())
    assert not [f for f in result.facts if f.relation in {'CFG_STATUS','RETURNS_NEW','ASSIGNMENT_VALUE'}]
    assert next(f.attrs['default'] for f in result.facts if f.relation=='HAS_PARAMETER') == '3'
    assert not [f for f in result.facts if f.relation=='OPERATOR' and f.object=='=']


def test_multiple_declarations_callback_fields_and_anonymous_parameters():
    result = graph('class P{};class A{virtual P *first(int), **second();'
                   'int (plain)(int);void (*callback)(int named);void (&reference)(int);};')
    methods = {e.name:e for e in result.entities.values() if e.kind == 'CALLABLE'}
    assert set(methods) == {'first','second','plain'}
    assert methods['first'].attrs['native_return_type'] == 'P *'
    assert methods['second'].attrs['native_return_type'] == 'P **'
    assert {result.entities[f.object].name for f in result.facts if f.relation=='HAS_FIELD'} == {'callback','reference'}
    assert all(e.name.startswith('anonymous@') for e in result.entities.values() if e.kind=='PARAMETER')


@pytest.mark.parametrize('parameter', ['External value', 'void (*callback)(int)', 'T value'])
def test_unavailable_signature_does_not_get_false_override(parameter):
    result = graph(f'class Base{{virtual void run({parameter});}};class Child:public Base{{void run({parameter}){{}}}};')
    assert not overrides(result)
    assert all(f.object=='unsupported' for f in result.facts if f.relation=='METHOD_SIGNATURE_STATUS')


def test_homonymous_nested_parameter_types_are_not_equal():
    result = graph('class Base{class P{};virtual void run(P);};'
                   'class Child:public Base{class P{};void run(P){}};')
    assert not overrides(result)


def test_class_template_parameter_does_not_bind_to_homonymous_global_type():
    result=graph('class T{};template<class T>class Base{virtual void run(T)=0;};')
    statuses=[f for f in result.facts if f.relation=='METHOD_SIGNATURE_STATUS']
    assert len(statuses)==1 and statuses[0].object=='unsupported'
    assert not [f for f in result.facts if f.relation=='VIRTUAL_METHOD']


@pytest.mark.parametrize('native,nominal', [('P* const',True),('const P&',True),('P&&',True),('P**',False),('P[3]',False),('external::P*',False)])
def test_parameter_annotation_and_nominal_receiver_head_stay_separate(native, nominal):
    declaration=native.replace('[3]',' value[3]') if '[' in native else native+' value'
    result=graph(f'class P{{}};class A{{void use({declaration}){{consume(value);}}}};')
    parameter=next(e for e in result.entities.values() if e.kind=='PARAMETER')
    assert parameter.name=='value'
    product=next(e.id for e in result.entities.values() if e.name=='P' and e.kind=='CLASS')
    assert bool([f for f in result.facts if f.relation=='TYPE' and f.subject==parameter.id and f.object==product]) is nominal
    assert any(f.relation=='ARGUMENT' and f.object==parameter.id for f in result.facts)


def test_method_template_and_free_prototype_are_not_promoted_to_virtual_slots():
    result = graph('void free_function();class Base{template<class T>void run(T);};')
    assert not overrides(result)
    assert not [f for f in result.facts if f.relation=='VIRTUAL_METHOD']
    assert all(e.name!='free_function' for e in result.entities.values() if e.kind=='CALLABLE')


@pytest.mark.parametrize('prefix,static', [('',False),('static ',True),('/* static */ ',False)])
def test_method_storage_modifier_is_consistent(prefix, static):
    result=graph(f'class Base{{{prefix}void run();}};')
    method=next(e for e in result.entities.values() if e.kind=='CALLABLE')
    assert method.attrs['static'] is static
    facts=[f for f in result.facts if (f.relation=='IS' and f.subject==method.id)
           or (f.relation in {'DECLARES','HAS_METHOD'} and f.object==method.id)]
    assert len(facts)==3 and all(f.attrs['static'] is static for f in facts)


@pytest.mark.parametrize('pattern', ['adapter','factory-method'])
@pytest.mark.parametrize('base_body', ['=0;', ';', '{}'])
@pytest.mark.parametrize('change', ['positive','renamed','nonvirtual','overload','qualifier','no-behavior'])
def test_public_patterns_with_declaration_contracts(pattern, base_body, change):
    if pattern=='adapter':
        source = f'class Target{{virtual int request(){base_body}}};class Backend{{public:int perform(){{return 1;}}}};class Subject:public Target{{Backend *backend;int request(){{return backend->perform();}}}};'
    else:
        source = f'class Product{{}};class Target{{virtual Product *request(){base_body}}};class Subject:public Target{{Product *request(){{return new Product();}}}};'
    if change=='renamed':source=source.replace('Subject','Refinement').replace('request','obtain').replace('Target','Contract')
    elif change=='nonvirtual':source=source.replace('virtual ','').replace('=0;',';')
    elif change=='overload':source=source.replace('request(){return','request(int mode){return')
    elif change=='qualifier':source=source.replace('request(){return','request() const{return')
    elif change=='no-behavior':source=source.replace('return backend->perform();','return 0;').replace('return new Product();','return nullptr;')
    result = graph(source)
    rules = builtin_rules()
    outcome = execute_rules(result,[named_rule(pattern,rules)],registry=rules)
    assert outcome['complete']
    assert bool(outcome['matches']) == (change in {'positive','renamed'})


def test_signature_metadata_is_available_in_kenql():
    result = graph('class A{virtual void run(int)=0;};class B:public A{void run(int){}};')
    outcome = execute_rules(result,[SavedRule('overrides', '''query overrides {
      require $method OVERRIDES $slot [basis:"cpp-resolved-virtual-signature"];
      require $slot METHOD_SIGNATURE_STATUS "supported";
      emit $method,$slot;
    }''')])
    assert outcome['complete'] and len(outcome['matches'])==1


@pytest.mark.parametrize('pattern', ['abstract-factory','interpreter','template-method'])
@pytest.mark.parametrize('change', ['positive','renamed','nonvirtual','overload','no-behavior'])
def test_additional_patterns_recovered_in_external_cpp_examples(pattern, change):
    if pattern=='abstract-factory':
        source='class P{};class Q{};class X:public P{};class Y:public Q{};class Base{virtual P *make(int)=0;virtual Q *other()=0;};class Derived:public Base{P *make(int){return new X();}Q *other(){return new Y();}};'
    elif pattern=='interpreter':
        source='class Context{};class Base{virtual int run(Context* const)=0;};class Derived:public Base{Base *child;int run(Context* const value){return child->run(value);}};'
    else:
        source='class Base{void execute(){step();}virtual void step()=0;};class Derived:public Base{void step(){}};'
    if change=='renamed':source=source.replace('Base','Contract').replace('Derived','Extension').replace('step','hook').replace('run','evaluate').replace('make','create')
    elif change=='nonvirtual':source=source.replace('virtual ','').replace('=0;',';')
    elif change=='overload':source=source.replace('make(int){','make(long){').replace('run(Context* const value){','run(Context& value){').replace('void step(){}','void step(int){}')
    elif change=='no-behavior':source=source.replace('return new X();','return nullptr;').replace('return child->run(value);','return 0;').replace('void execute(){step();}','void execute(){}')
    result=graph(source);rules=builtin_rules()
    outcome=execute_rules(result,[named_rule(pattern,rules)],registry=rules)
    assert outcome['complete']
    assert bool(outcome['matches'])==(change in {'positive','renamed'})


@pytest.mark.parametrize('named', [True,False])
@pytest.mark.parametrize('change', ['positive','renamed','no-self','wrong-type','no-dispatch','overloaded'])
def test_named_visitor_with_const_pointer_prototype_and_reference_input(named, change):
    source='class Element;class Other{};class Visitor{public:virtual void handle(Element* const'+(' value' if named else '')+')=0;};class Element{public:void accept(Visitor& visitor){visitor.handle(this);}};'
    if change=='renamed':source=source.replace('Visitor','Walker').replace('Element','Entry').replace('handle','inspect')
    elif change=='no-self':source=source.replace('handle(this)','handle(nullptr)')
    elif change=='wrong-type':source=source.replace('Element* const','Other* const')
    elif change=='no-dispatch':source=source.replace('visitor.handle(this);','')
    elif change=='overloaded':source=source.replace(')=0;};',')=0;virtual void handle(Other*)=0;};')
    result=graph(source);rules=builtin_rules()
    outcome=execute_rules(result,[named_rule('visitor',rules)],registry=rules)
    assert outcome['complete']
    # ``overloaded`` adds a second ``handle`` overload to the visitor. Until IR 1.61
    # the root query covered only named-dispatch, which needs a resolved TARGET, so
    # the overload set was rejected; visitor#overloaded-dispatch is now ready and
    # admits it, which is precisely the case it exists for.
    assert bool(outcome['matches'])==(change in {'positive','renamed','overloaded'})
