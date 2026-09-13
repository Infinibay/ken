"""Private fields have declaration identity, not an initializer VALUE placeholder."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR


@pytest.mark.parametrize('language',['javascript','typescript'])
@pytest.mark.parametrize('static',[False,True])
@pytest.mark.parametrize('initializer',['=1','=null','=(1)',''])
def test_private_field_declaration_and_read_share_storage(language,static,initializer):
    modifier='static ' if static else '';receiver='C' if static else 'this'
    text='class C{'+modifier+'#value'+initializer+';'+modifier+'read(){return '+receiver+'.#value;}}'
    g=IR.from_dict(link_project([lower_source(text,language,'private')]).to_dict());assert not g.diagnostics
    fields=[e for e in g.entities.values() if e.kind=='STORAGE' and e.name=='#value'];assert len(fields)==1
    field=fields[0];assert field.attrs['declared'] and field.attrs['static']==static
    assert any(f.relation=='RETURN_OPERAND' and f.object==field.id for f in g.facts)
    assert len([f for f in g.facts if f.relation=='ASSIGNMENT_TARGET' and f.object==field.id])==bool(initializer)


@pytest.mark.parametrize('language',['javascript','typescript'])
def test_public_and_private_spellings_remain_distinct(language):
    text='class C{static value=1;static #value=2;static read(){return C.#value;}}'
    g=link_project([lower_source(text,language,'private')]);fields={e.name:e.id for e in g.entities.values() if e.kind=='STORAGE'}
    assert fields['value']!=fields['#value']
    assert any(f.relation=='RETURN_OPERAND' and f.object==fields['#value'] for f in g.facts)


@pytest.mark.parametrize('language',['javascript','typescript'])
def test_nested_classes_have_distinct_private_field_declarations(language):
    text='class Outer{static #value=1;static make(){class Inner{static #value=2;static read(){return Inner.#value;}}return Inner;}}'
    g=link_project([lower_source(text,language,'private')]);assert not g.diagnostics
    fields=[e for e in g.entities.values() if e.kind=='STORAGE' and e.name=='#value'];assert len(fields)==2
