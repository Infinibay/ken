"""Qualifier layers and indirection survive C++ field type normalization."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.type_refs import parse_type
from ken.structural.rules import SavedRule,execute_rules


@pytest.mark.parametrize('annotation,kinds,qualifiers',[
 ('Driver *',['pointer','nominal'],[]),
 ('const Driver *',['pointer','qualified','nominal'],['const']),
 ('Driver const *',['pointer','qualified','nominal'],['const']),
 ('Driver * const',['qualified','pointer','nominal'],['const']),
 ('Driver *const',['qualified','pointer','nominal'],['const']),
 ('volatile Driver &',['reference','qualified','nominal'],['volatile']),
 ('const volatile Driver * const',['qualified','pointer','qualified','nominal'],['const','const','volatile']),
 ('Driver &&',['rvalue_reference','nominal'],[]),
 ('Driver * const &',['reference','qualified','pointer','nominal'],['const']),
 ('Driver **',['pointer','pointer','nominal'],[]),
 ('Driver *[3]',['array','pointer','nominal'],[]),
 ('Driver (*)[3]',['opaque'],[]),
 ('void (*)(int)',['opaque'],[]),
])
def test_layered_type_descriptors(annotation,kinds,qualifiers):
    ref=parse_type(annotation,'cpp');found=[];quals=[]
    while True:
        found.append(ref.kind);quals.extend(ref.qualifiers)
        if not ref.arguments:break
        ref=ref.arguments[0]
    assert found==kinds and quals==qualifiers


@pytest.mark.parametrize('declaration',['const Driver *field','Driver const *field','Driver *const field','volatile Driver &field'])
def test_qualifier_relations_are_queryable_and_roundtrip(declaration):
    graph=IR.from_dict(link_project([lower_source('class Driver{};class A{'+declaration+';};','cpp','qualified.cpp')]).to_dict())
    assert not graph.diagnostics
    q='query q { variable(name:"field") as $field; require $field TYPE_REF $type; path $type TYPE_ARGUMENT{0,3} $qualified as $layers; require $qualified TYPE_QUALIFIER $qualifier; emit $field,$qualified,$qualifier; }'
    out=execute_rules(graph,[SavedRule('qualifier',q)]);assert out['complete'] and len(out['matches'])==1
    assert out['matches'][0]['bindings']['$qualifier']==('volatile' if 'volatile' in declaration else 'const')


@pytest.mark.parametrize('language',['python','typescript','java','csharp','go','rust'])
def test_cpp_qualification_is_not_applied_to_other_languages(language):
    assert parse_type('Driver *const',language).kind=='opaque'
    assert parse_type('const Driver',language).kind=='opaque'
