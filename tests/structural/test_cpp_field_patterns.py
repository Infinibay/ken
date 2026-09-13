"""Typed C++ receivers feed public pattern queries, without class-name hints."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules,named_rule,execute_rules


def matches(source,pattern):
    graph=link_project([lower_source(source,'cpp','sample.cpp')]);assert not graph.diagnostics
    rules=builtin_rules();result=execute_rules(graph,[named_rule(pattern,rules)],registry=rules)
    assert result['complete'];return result['matches']


@pytest.mark.parametrize('declarator',['Backend *field','const Backend *field','Backend &field','Backend * const field'])
@pytest.mark.parametrize('change',['positive','renamed','unused','same-name','unknown-type'])
def test_adapter_field_contract(declarator,change):
    op='.' if '&' in declarator else '->'
    source='class Contract{public:virtual int request(){return 0;}};class Backend{public:int perform() const{return 1;}};class Subject:public Contract{'+declarator+';public:int request(){return field'+op+'perform();}};'
    if change=='renamed':source=source.replace('Backend','Remote').replace('field','provider')
    elif change=='unused':source=source.replace('return field'+op+'perform()','return 1')
    elif change=='same-name':source=source.replace('perform','request')
    elif change=='unknown-type':source=source.replace(declarator,declarator.replace('Backend','External'))
    assert bool(matches(source,'adapter'))==(change in {'positive','renamed'})


@pytest.mark.parametrize('declarator',['Contract *field','Contract*field','Contract * volatile field'])
@pytest.mark.parametrize('change',['positive','renamed','unused','not-injected','one-implementation'])
def test_strategy_retains_field_and_parameter_binding(declarator,change):
    op='.' if '&' in declarator else '->'
    source='class Contract{public:virtual int run(){return 0;}};class First:public Contract{};class Second:public Contract{};class Subject{'+declarator+';public:void configure(Contract *value){field=value;}int execute(){return field'+op+'run();}};'
    if change=='renamed':source=source.replace('Contract','Engine').replace('field','backend')
    elif change=='unused':source=source.replace('return field'+op+'run()','return 0')
    elif change=='not-injected':source=source.replace('field=value','field=nullptr')
    elif change=='one-implementation':source=source.replace('Second:public Contract','Second')
    assert bool(matches(source,'strategy'))==(change in {'positive','renamed'})


@pytest.mark.parametrize('related',[False,True])
def test_runtime_bridge_requires_distinct_nominal_families(related):
    source='class Driver{public:virtual void run(){}};class First:public Driver{};class Second:public Driver{};class Base'+(':public Driver' if related else '')+'{Driver *field;public:void draw(){field->run();}};class Subject:public Base{};'
    assert bool(matches(source,'bridge')) is (not related)
