"""Erased TypeScript assertions preserve values, not runtime type guarantees."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import builtin_rules,named_rule,execute_rules

FORMS=['value as object','<object>value','value!','value satisfies object','((value as object)!)','value as unknown as object']


@pytest.mark.parametrize('form',FORMS)
@pytest.mark.parametrize('place',['return','assignment','argument'])
def test_erased_assertions_preserve_underlying_parameter(form,place):
    statement={'return':'return '+form+';','assignment':'const saved='+form+';return saved;','argument':'consume('+form+');'}[place]
    g=IR.from_dict(link_project([lower_source('function f(value:unknown){'+statement+'}','typescript','assert.ts')]).to_dict());assert not g.diagnostics
    parameter=next(e.id for e in g.entities.values() if e.kind=='PARAMETER' and e.name=='value')
    facts=[f for f in g.facts if f.relation=='TYPE_ASSERTION_VALUE'];assert facts and all(f.object==parameter for f in facts)
    assert all(f.attrs['basis']=='typescript-erased-assertion' for f in facts)
    assert not any(f.relation=='TYPE_NAME' and f.subject==parameter and f.object=='object' for f in g.facts)
    if place=='return':assert any(f.relation=='RETURN_OPERAND' and f.object==parameter for f in g.facts)
    if place=='assignment':assert any(f.relation=='ASSIGNMENT_VALUE' and f.object==parameter for f in g.facts)
    if place=='argument':assert any(f.relation=='ARGUMENT' and f.object==parameter for f in g.facts)


@pytest.mark.parametrize('form',FORMS)
def test_asserted_local_class_still_matches_subclass_factory(form):
    source='function extend(base:any){class value extends base{}return '+form+';}'
    g=link_project([lower_source(source,'typescript','assert.ts')]);rules=builtin_rules();out=execute_rules(g,[named_rule('architecture.subclass-factory',rules)],registry=rules)
    assert out['complete'] and len(out['matches'])==1


@pytest.mark.parametrize('language,source',[('csharp','class C{object f(object value){return (C)value;}}'),('java','class C{Object f(Object value){return (C)value;}}'),('cpp','class C{};C* f(void* value){return (C*)value;}')])
def test_other_language_casts_are_not_erased(language,source):
    g=link_project([lower_source(source,language,'cast')]);assert not g.diagnostics
    assert not any(f.relation=='TYPE_ASSERTION_VALUE' for f in g.facts)
    parameter=next(e.id for e in g.entities.values() if e.kind=='PARAMETER' and e.name=='value')
    assert not any(f.relation=='RETURN_OPERAND' and f.object==parameter for f in g.facts)


def test_asserted_allocation_is_still_one_call():
    g=link_project([lower_source('class Item{}function make(){return new Item() as Item;}','typescript','assert.ts')])
    calls=[e for e in g.entities.values() if e.kind=='CALL'];assert len(calls)==1
    assert any(f.relation=='TYPE_ASSERTION_VALUE' and f.object==calls[0].id for f in g.facts)
