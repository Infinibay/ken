"""Defaults are language-specific field evidence, never invented assignment syntax."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import SavedRule,execute_rules


def graph(source,language):return IR.from_dict(link_project([lower_source(source,language,'fields')]).to_dict())

def field(g,name='value'):
    return next(e for e in g.entities.values() if e.kind=='STORAGE' and e.name==name)

def initial(g,name='value'):
    slot=field(g,name);status=next(f for f in g.facts if f.subject==slot.id and f.relation=='FIELD_INITIAL_STATUS')
    value=next((f for f in g.facts if f.subject==slot.id and f.relation=='FIELD_INITIAL_VALUE'),None)
    return status,value


@pytest.mark.parametrize('static',['','static '])
@pytest.mark.parametrize('language,type_,value,type_family',[
 ('java','C','NULL',None),('java','Object','NULL',None),('java','Integer','NULL',None),('java','String[]','NULL',None),('java','int[]','NULL',None),('java','java.util.Map<String,C>','NULL',None),
 ('java','byte',0,'int'),('java','int',0,'int'),('java','long',0,'int'),('java','float',0.0,'float'),('java','double',0.0,'float'),('java','boolean',False,'bool'),('java','char','\x00','char'),
 ('csharp','C','NULL',None),('csharp','string','NULL',None),('csharp','string?','NULL',None),('csharp','object','NULL',None),('csharp','dynamic','NULL',None),('csharp','int[]','NULL',None),('csharp','int[,]','NULL',None),('csharp','int?','NULL',None),('csharp','bool?','NULL',None),
 ('csharp','sbyte',0,'int'),('csharp','int',0,'int'),('csharp','ulong',0,'int'),('csharp','nint',0,'int'),('csharp','float',0.0,'float'),('csharp','decimal',0.0,'float'),('csharp','bool',False,'bool'),('csharp','char','\x00','char')])
def test_language_defaults_for_declared_fields(static,language,type_,value,type_family):
    g=graph('class C{'+static+type_+' value;}',language);assert not g.diagnostics
    status,record=initial(g);assert status.object=='supported' and record.attrs['basis']=='language-field-default'
    if type_family is None:assert record.object==value
    else:
        e=g.entities[record.object];assert e.attrs['type']==type_family and e.attrs['literal_value']==value and e.attrs['synthetic']
        assert not any(op.id==e.id for op in g.operations)
    assert not any(f.relation=='ASSIGNMENT_TARGET' and f.object==field(g).id for f in g.facts)
    out=execute_rules(g,[SavedRule('default','query defaults {require $field FIELD_INITIAL_VALUE $value [basis:language-field-default];emit $field,$value;}')]);assert out['complete'] and len(out['matches'])==1


@pytest.mark.parametrize('language',['python','java','csharp','javascript','typescript'])
@pytest.mark.parametrize('value',['null','creation','number'])
def test_explicit_initializers_take_precedence(language,value):
    rhs=('None' if language=='python' else 'null') if value=='null' else ('C()' if language=='python' else 'new C()') if value=='creation' else '4'
    text='class C:\n value='+rhs+'\n' if language=='python' else 'class C{'+('static C ' if language in {'java','csharp'} else 'static ')+'value='+rhs+';}'
    g=graph(text,language);status,record=initial(g);assert status.object=='supported' and record.attrs['basis']=='explicit-field-initializer'
    if value=='null':assert record.object=='NULL'
    else:assert record.object!='NULL' and g.entities[record.object].kind==('CALL' if value=='creation' else 'VALUE')


@pytest.mark.parametrize('language',['java','csharp'])
def test_multiple_declarators_have_separate_values(language):
    g=graph('class C{static C first,second=null,third=new C();}',language)
    assert initial(g,'first')[1].attrs['basis']=='language-field-default'
    assert initial(g,'second')[1].object=='NULL'
    assert initial(g,'third')[1].object!='NULL'


def test_java_dimensions_on_individual_names_are_not_primitive_defaults():
    g=graph('class C{int first[],second,third[][];}', 'java')
    assert initial(g,'first')[1].object=='NULL' and initial(g,'third')[1].object=='NULL'
    assert g.entities[initial(g,'second')[1].object].attrs['literal_value']==0


@pytest.mark.parametrize('language,source,status,value',[
 ('javascript','class C{static value;}','supported','UNDEFINED'),
 ('javascript','class C{#value;}','supported','UNDEFINED'),
 ('typescript','class C{value!:number;}','unsupported',None),
 ('typescript','class C{declare value:number;}','absent',None),
 ('typescript','abstract class C{abstract value:number;}','absent',None),
 ('python','class C:\n value:int\n','absent',None),
 ('python','class C:\n value:ClassVar[int]\n','absent',None)])
def test_undefined_absent_and_unknown_are_distinct(language,source,status,value):
    g=graph(source,language);name='#value' if '#value' in source else 'value';s,v=initial(g,name);assert s.object==status
    assert (v.object if v else None)==value


@pytest.mark.parametrize('type_',['Missing','T','T?','ValueStruct','ValueStruct?','UnknownAlias'])
def test_csharp_unresolved_value_or_generic_types_do_not_default_to_null(type_):
    g=graph('class T{}struct ValueStruct{}class C<T>{'+type_+' value;}','csharp')
    s,v=initial(g);assert s.object=='unsupported' and v is None


@pytest.mark.parametrize('language,source',[
 ('java','class C{void run(){C value;}}'),('csharp','class C{void Run(){C value;}}'),
 ('javascript','function run(){let value;}'),('typescript','function run(){let value:C;}'),
 ('python','def run():\n value:int\n')])
def test_locals_never_acquire_field_defaults(language,source):
    g=graph(source,language);assert not any(f.relation in {'FIELD_DECLARATION','FIELD_INITIAL_VALUE'} for f in g.facts)


@pytest.mark.parametrize('language',['python','javascript','typescript','java','csharp'])
def test_duplicate_field_declarations_are_not_arbitrarily_selected(language):
    s='class C:\n value=None\n value=1\n' if language=='python' else 'class C{'+('static C ' if language in {'java','csharp'} else 'static ')+'value=null;'+('static C ' if language in {'java','csharp'} else 'static ')+'value=new C();}'
    g=graph(s,language);status,value=initial(g);assert status.object=='unsupported' and value is None


@pytest.mark.parametrize('language',['java','csharp','typescript','javascript'])
def test_parse_errors_do_not_certify_initial_values(language):
    g=graph('class C{'+('C ' if language in {'java','csharp'} else '')+'value; ???}',language);assert g.diagnostics
    assert not any(f.relation=='FIELD_INITIAL_VALUE' for f in g.facts)


def test_csharp_auto_properties_and_events_are_not_field_declarators():
    g=graph('class C{C Value{get;set;}event Handler Changed;}','csharp')
    assert not any(f.relation=='FIELD_INITIAL_VALUE' for f in g.facts)


@pytest.mark.parametrize('annotation',['Missing','int'])
def test_flow_inferred_type_does_not_change_the_declared_default(annotation):
    g=graph('class C{'+annotation+' value;void Run(){value=new C();}}','csharp')
    s,v=initial(g)
    if annotation=='Missing':assert s.object=='unsupported' and v is None
    else:assert g.entities[v.object].attrs['literal_value']==0
