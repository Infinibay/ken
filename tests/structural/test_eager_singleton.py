"""Shared class initialization, direct accessors and their intentionally narrow claim."""
import re
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import IR
from ken.structural.rules import builtin_rules,named_rule,execute_rules,SavedRule
from ken.structural.query import QueryBudget

SOURCES={
 'java':'class Shared{private static final Shared instance=new Shared();private Shared(){}public static Shared get(){return instance;}}',
 'csharp':'class Shared{private static readonly Shared instance=new Shared();private Shared(){}public static Shared get(){return instance;}}',
 'typescript':'class Shared{private static readonly instance=new Shared();private constructor(){}static get(){return Shared.instance;}}',
 'javascript':'class Shared{static instance=new Shared();static get(){return Shared.instance;}}',
}
POSITIVE={'positive','renamed','comments','parentheses','block','extra-field'}
NEGATIVE={'different-type','null-initializer','fresh-return','other-return','no-return','instance-field','instance-accessor','computed-return'}
CHANGES=sorted(POSITIVE|NEGATIVE)


def source(language,change='positive'):
    text=SOURCES[language];binding='Shared.instance' if language in {'javascript','typescript'} else 'instance'
    ret='return '+binding+';'
    if change=='renamed':
        for a,b in [('Shared','Registry'),('instance','current'),('get','acquire')]:text=re.sub(r'\b'+a+r'\b',b,text)
    elif change=='comments':text=text.replace(ret,'/* shared slot */'+ret+'/* end */').replace('new Shared()','new /* allocation */ Shared()')
    elif change=='parentheses':text=text.replace(ret,'return (( '+binding+' ));').replace('=new Shared()','=((new Shared()))')
    elif change=='block':text=text.replace(ret,'{'+ret+'}')
    elif change=='extra-field':text=text.replace('class Shared{','class Shared{'+ ('static Shared other=null;' if language in {'java','csharp'} else 'static other=null;'))
    elif change=='different-type':text=text.replace('new Shared()','new Other()')+'class Other{}'
    elif change=='null-initializer':text=text.replace('new Shared()','null')
    elif change=='fresh-return':text=text.replace(ret,'return new Shared();')
    elif change=='other-return':text=text.replace(ret,'return null;')
    elif change=='no-return':text=text.replace(ret,'')
    elif change=='instance-field':text=text.replace('static ','',1)
    elif change=='instance-accessor':text=text.replace('static Shared get','Shared get') if language in {'java','csharp'} else text.replace('static get','get')
    elif change=='computed-return':text=text.replace(ret,'return '+binding+'.copy();')
    return text


def search(text,language,rule='singleton.shared_instance',budget=None):
    graph=IR.from_dict(link_project([lower_source(text,language,'shared')]).to_dict());assert not graph.diagnostics
    rules=builtin_rules();selected=named_rule(rule,rules) if isinstance(rule,str) else rule
    out=execute_rules(graph,[selected],budget,registry=rules);assert out['complete'];return graph,out


@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('change',CHANGES)
def test_shared_initialization_and_direct_return(language,change):
    _,out=search(source(language,change),language,'singleton')
    assert bool(out['matches'])==(change in POSITIVE and language!='javascript')
    _,broad=search(source(language,change),language,'singleton.shared_instance')
    assert bool(broad['matches'])==(change in POSITIVE)


@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('change',['before','branch','alias','parameter','static-block'])
def test_more_complex_valid_idioms_remain_coverage_gaps(language,change):
    text=source(language);binding='Shared.instance' if language in {'javascript','typescript'} else 'instance';ret='return '+binding+';'
    if change=='before':text=text.replace(ret,'prepare();'+ret)
    elif change=='branch':text=text.replace(ret,'if(flag){'+ret+'}'+ret)
    elif change=='alias':text=text.replace(ret,('Shared' if language in {'java','csharp'} else 'const')+' result='+binding+';return result;')
    elif change=='parameter':text=text.replace('get()','get('+('int key' if language in {'java','csharp'} else 'key:number' if language=='typescript' else 'key')+')')
    elif change=='static-block':
        if language in {'java','csharp'}:
            text=text.replace('=new Shared()','').replace('private Shared(){}',('static Shared()' if language=='csharp' else 'static')+'{instance=new Shared();}private Shared(){}')
        else:text=text.replace('=new Shared()','').replace('static get()','static {Shared.instance=new Shared();}static get()')
    _,out=search(text,language)
    assert not out['matches']


@pytest.mark.parametrize('language',SOURCES)
def test_public_construction_and_resets_are_not_uniqueness_proofs(language):
    text=source(language).replace('private Shared()','public Shared()').replace('private constructor','constructor').replace('final ','').replace('readonly ','')
    reset='static void reset(){instance=new Shared();}' if language in {'java','csharp'} else 'static reset(){Shared.instance=new Shared();}'
    text=text[:-1]+reset+'}'
    _,out=search(text,language)
    assert len(out['matches'])==1


@pytest.mark.parametrize('language',SOURCES)
def test_initializer_in_a_method_is_not_class_initialization(language):
    text=source(language).replace('=new Shared()','=null')
    assignment=('instance' if language in {'java','csharp'} else 'Shared.instance')+'=new Shared();'
    method='static void initialize(){'+assignment+'}' if language in {'java','csharp'} else 'static initialize(){'+assignment+'}'
    text=text[:-1]+method+'}'
    _,out=search(text,language)
    assert not out['matches']


@pytest.mark.parametrize('language',SOURCES)
def test_same_name_fields_do_not_cross_type_boundaries(language):
    other=source(language).replace('Shared','Other').replace('get()','unused()').replace('return instance;','return null;').replace('return Other.instance;','return null;')
    g,out=search(source(language)+other,language,'singleton.shared_instance')
    assert len(out['matches'])==1
    roles=out['matches'][0]['bindings'];assert g.entities[roles['$unit']].name=='Shared'
    assert g.entities[roles['$accessor']].name=='get'
    assert any(f.subject==roles['$unit'] and f.relation=='HAS_FIELD' and f.object==roles['$storage'] for f in g.facts)
    assert any(f.subject==roles['$creation'] and f.relation=='ALLOCATES_TYPE' and f.object==roles['$unit'] for f in g.facts)


@pytest.mark.parametrize('language',SOURCES)
def test_return_after_unconditional_return_does_not_change_the_first_operand(language):
    text=source(language);binding='Shared.instance' if language in {'javascript','typescript'} else 'instance'
    _,out=search(text.replace('return '+binding+';','return '+binding+';return new Shared();'),language)
    assert len(out['matches'])==1
    _,out=search(text.replace('return '+binding+';','return new Shared();return '+binding+';'),language)
    assert not out['matches']


@pytest.mark.parametrize('language',['java','csharp'])
def test_multiple_declarators_match_only_the_directly_returned_storage(language):
    text=source(language).replace('instance=new Shared();','instance=new Shared(),other=new Shared();')
    g,out=search(text,language,'singleton.shared_instance');assert len(out['matches'])==1
    assert g.entities[out['matches'][0]['bindings']['$storage']].name=='instance'


@pytest.mark.parametrize('language',['javascript','typescript'])
def test_private_field_and_static_get_accessor(language):
    text=source(language).replace('instance','#instance').replace('private static','static').replace('static get()','static get current()')
    _,out=search(text,language);assert len(out['matches'])==1


def test_named_query_can_correlate_a_shared_accessor_with_its_calls():
    text=source('java')+'class Client{Shared use(){return Shared.get();}}'
    q=SavedRule('use','''query uses_shared {
      match "singleton.shared_instance"(unit:$unit,storage:$storage,accessor:$accessor,creation:$creation);
      require $call TARGET $accessor;
      emit $unit,$storage,$accessor,$creation,$call;
    }''')
    _,out=search(text,'java',q);assert len(out['matches'])==1


def test_shared_accessor_query_has_a_bounded_join_cost():
    text=''.join(source('java').replace('Shared',f'Shared{i}') for i in range(150))
    _,out=search(text,'java','singleton.shared_instance',QueryBudget(max_matches=200,max_states=15000,max_rows=15000,timeout_ms=5000))
    assert len(out['matches'])==150
