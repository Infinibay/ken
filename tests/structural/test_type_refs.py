"""Type syntax retains scalar distinctions and nested type arguments."""
import pytest
from ken.structural.type_refs import parse_type
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import FactIndex, IR
from ken.structural.kenql import Engine, parse


@pytest.mark.parametrize('annotation,language,kind,bits,signed',[
 ('int','python','int',None,None), ('int','java','int',32,True),
 ('int','cpp','int',None,True), ('uint64','go','int',64,False),
 ('u32','rust','int',32,False), ('i8','rust','int',8,True),
 ('char','java','char',16,None), ('char','rust','char',32,None),
 ('str','python','str',None,None), ('string','csharp','str',None,None),
 ('float','java','float',32,None), ('double','csharp','float',64,None),
 ('double','cpp','float',None,None), ('float64','go','float',64,None),
 ('number','typescript','number',None,None), ('bool','rust','bool',None,None),
 ('any','typescript','any',None,None), ('unknown','typescript','unknown',None,None),
 ('Any','python','any',None,None), ('dynamic','csharp','any',None,None),
 ('never','typescript','never',None,None), ('object','python','nominal',None,None),
 ('','python','unknown',None,None), ('User','java','nominal',None,None),
])
def test_scalar_types(annotation,language,kind,bits,signed):
    ref=parse_type(annotation,language)
    assert (ref.kind,ref.bits,ref.signed)==(kind,bits,signed)
    assert ref.native==annotation


@pytest.mark.parametrize('annotation,language,kind,arguments,extent',[
 ('int[]','java','array',['int'],None),
 ('char[8]','cpp','array',['char'],'8'),
 ('[]int','go','slice',['int'],None),
 ('[8]int','go','array',['int'],'8'),
 ('[u8; 32]','rust','array',['int'],'32'),
 ('[u8]','rust','slice',['int'],None),
 ('list[str]','python','list',['str'],None),
 ('dict[str, int]','python','map',['str','int'],None),
 ('map[string]int','go','map',['str','int'],None),
 ('HashMap<String, i32>','rust','map',['str','int'],None),
 ('Dictionary<string, int>','csharp','map',['str','int'],None),
 ('std::unordered_map<std::string, User>','cpp','map',['str','nominal'],None),
 ('Set<User>','typescript','set',['nominal'],None),
 ('tuple[str, int]','python','tuple',['str','int'],None),
 ('Optional[int]','python','optional',['int'],None),
 ('User?','csharp','optional',['nominal'],None),
 ('int | None','python','union',['int','null'],None),
 ('&mut str','rust','reference',['str'],None),
 ('User*','cpp','pointer',['nominal'],None),
])
def test_composite_types(annotation,language,kind,arguments,extent):
    ref=parse_type(annotation,language)
    assert (ref.kind,[a.kind for a in ref.arguments],ref.extent)==(kind,arguments,extent)


def test_nested_map_and_array_arguments():
    ref=parse_type('map[string][]map[int]*User','go')
    assert ref.kind=='map'
    nested=ref.arguments[1].arguments[0]
    assert nested.kind=='map' and nested.arguments[0].kind=='int'
    assert nested.arguments[1].kind=='pointer'


def test_type_facts_are_queryable_and_roundtrip():
    g=link_project([lower_source('def f(values: dict[str, list[int]], value: Any):\n return values\n','python','sample')])
    g=IR.from_dict(g.to_dict())
    query='query q { require $p TYPE_REF $map; require $map TYPE_KIND "map"; require $map TYPE_ARGUMENT $key [position: 0]; require $key TYPE_KIND "str"; emit $p; }'
    result=Engine(FactIndex(g),{}).execute(parse(query))
    assert len(result['matches'])==1
    assert g.entities[result['matches'][0]['bindings']['$p']].name=='values'


def test_unannotated_dynamic_parameter_is_unknown_not_any():
    g=link_project([lower_source('def f(value):\n return value\n','python','sample')])
    parameter=next(e.id for e in g.entities.values()if e.kind=='PARAMETER')
    ref=next(f.object for f in g.facts if f.subject==parameter and f.relation=='TYPE_REF')
    assert any(f.subject==ref and f.relation=='TYPE_KIND' and f.object=='unknown'for f in g.facts)


def test_deep_types_stop_with_an_opaque_remainder():
    ref=parse_type('list['*40+'int'+']'*40,'python')
    for _ in range(33):ref=ref.arguments[0]
    assert ref.kind=='opaque'


def test_rectangular_array_rank_is_not_an_extent():
    ref=parse_type('int[,,]','csharp')
    assert ref.rank==3 and ref.extent is None


def test_cpp_fixed_array_and_rust_tuple():
    assert parse_type('std::array<int, 8>','cpp').extent=='8'
    assert [a.kind for a in parse_type('(i32, bool)','rust').arguments]==['int','bool']


@pytest.mark.parametrize('language,source,expected',[
 ('python','def f():\n return {"a":1}\n','map'),
 ('python','def f():\n return [1,2]\n','list'),
 ('javascript','function f(){return [1,2];}','array'),
 ('javascript','function f(){return {a:1};}','record'),
 ('java',"class C{char f(){return 'a';}}",'char'),
])
def test_literal_categories(language,source,expected):
    g=link_project([lower_source(source,language,'sample')])
    refs={f.object for f in g.facts if f.relation=='TYPE_REF' and f.attrs.get('basis')=='literal-syntax'}
    assert any(f.subject in refs and f.relation=='TYPE_KIND' and f.object==expected for f in g.facts)
