"""C# field modifiers live above the variable declaration and initializer."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import SavedRule,execute_rules


@pytest.mark.parametrize('modifiers,static',[
 ('',False),('public',False),('private readonly',False),('static',True),
 ('private static readonly',True),('public static',True),('const',True),
 ('public const',True),('/* static */ public',False),('[A("static")] public',False),
])
@pytest.mark.parametrize('initializer',['','="static"'])
def test_modifiers_belong_to_field_declaration(modifiers,static,initializer):
    source=f'class A {{ {modifiers} string value{initializer}; }}'
    graph=link_project([lower_source(source,'csharp','fields.cs')]);assert not graph.diagnostics
    graph=IR.from_dict(graph.to_dict());value=next(e for e in graph.entities.values() if e.kind=='STORAGE' and e.name=='value')
    assert value.attrs['static'] is static
    field=next(f for f in graph.facts if f.relation=='HAS_FIELD' and f.object==value.id)
    declaration=next(f for f in graph.facts if f.relation=='DECLARES' and f.object==value.id)
    assert field.attrs['static'] is static and declaration.attrs['static'] is static
    query='query q { variable(name:"value",static:'+str(static).lower()+') as $field; emit $field; }'
    out=execute_rules(graph,[SavedRule('fields',query)]);assert out['complete'] and len(out['matches'])==1


@pytest.mark.parametrize('modifiers,static',[('static',True),('readonly',False),('const',True)])
def test_multiple_declarators_inherit_the_same_modifiers(modifiers,static):
    graph=link_project([lower_source(f'class A {{ {modifiers} string first="x", second="y"; }}','csharp','multi.cs')]);assert not graph.diagnostics
    fields=[graph.entities[f.object] for f in graph.facts if f.relation=='HAS_FIELD']
    assert {e.name for e in fields}=={'first','second'}
    assert all(e.attrs['static'] is static for e in fields)


def test_local_variable_in_static_method_is_not_static_field():
    graph=link_project([lower_source('class A { static string F(){string value="static";return value;} }','csharp','local.cs')]);assert not graph.diagnostics
    value=next(e for e in graph.entities.values() if e.kind=='STORAGE' and e.name=='value')
    assert value.attrs['static'] is False
    assert not [f for f in graph.facts if f.relation=='HAS_FIELD' and f.object==value.id]
